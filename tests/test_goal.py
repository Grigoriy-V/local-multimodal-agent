"""The request as the turn's goal (2026-09-05, report §14).

A turn that ran a tool is asked once, without tools, whether what it did gives
the person what they asked for; `not yet` gives the tools back for a round,
`blocked` asks for the reason, `done` ends the turn. A turn without a tool is
never asked. No model, no network: the model's answers are scripted.
"""

from __future__ import annotations

import pytest

from app.agent.goal import BLOCKED, CHECK, DONE, NOT_YET, MeetsTheRequest, verdict
from app.agent.graph import TurnBudget, build_agent
from app.agent.stopping import STOP_ON_ANSWER, FirstObjection, Steering
from app.memory import SqliteStore
from app.models import ContentPart, Message
from app.tools import Tool, Toolbox
from tests.fakes import ScriptedBackend, calls, prompt_text, says

OWNER = "goal-owner"


@pytest.fixture
def store(tmp_path):
    return SqliteStore(str(tmp_path / "conversations.db"))


def ping(recorded: list[str] | None = None) -> Tool:
    def run() -> str:
        if recorded is not None:
            recorded.append("ran")
        return "pong"

    return Tool(name="ping", description="answer", parameters={"type": "object", "properties": {}}, run=run)


def loop(backend, store, stopping, budget=None):
    return build_agent(backend, Toolbox([ping()]), store, OWNER, budget=budget, stopping=stopping)


def ask(text: str) -> dict[str, object]:
    return {
        "messages": [Message(role="user", content=[ContentPart(kind="text", text=text)])],
        "sequence": 1,
    }


def spoken(messages) -> list[str]:
    return [
        " ".join(part.text or "" for part in message.content)
        for message in messages
        if message.role == "assistant" and message.content
    ]


# --- reading the answer -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("done", (DONE, "")),
        ("`done`\nThe PDF is there.", (DONE, "")),
        ("Not yet", (NOT_YET, "")),
        ("not_yet — the file is in English", (NOT_YET, "")),
        ("blocked: no Cyrillic font is installed", (BLOCKED, "no Cyrillic font is installed")),
        ("Blocked — the site needs a login", (BLOCKED, "the site needs a login")),
        ("blocked", (BLOCKED, "no reason given")),
        ("I think it is fine", (DONE, "")),
        ("", (DONE, "")),
    ],
)
def test_the_first_line_is_the_verdict(text, expected) -> None:
    assert verdict(text) == expected


# --- when the question is asked ---------------------------------------------


async def test_a_turn_without_a_tool_is_never_asked(store) -> None:
    backend = ScriptedBackend(says("42"))
    agent = loop(backend, store, MeetsTheRequest(backend))

    result = await agent.ainvoke(ask("what is it"))

    assert len(backend.requests) == 1
    assert spoken(result["messages"]) == ["42"]


async def test_a_turn_that_worked_is_asked_over_its_own_turn_with_the_request_verbatim(
    store,
) -> None:
    backend = ScriptedBackend(calls("ping"), says("pinged"), says("done"))
    check = MeetsTheRequest(backend)
    agent = loop(backend, store, check)

    result = await agent.ainvoke(ask("ping it, по-русски"))

    assert len(backend.requests) == 3
    question = backend.requests[2]
    assert backend.tools_seen[2] is None
    assert question[0].role == "system"
    assert "по-русски" in prompt_text(question)
    assert CHECK.format(request="ping it, по-русски") in prompt_text(question)
    assert any(message.role == "tool" for message in question)
    assert check.verdicts == [DONE]
    assert spoken(result["messages"]) == ["pinged"]


# --- what each verdict does ---------------------------------------------------


async def test_not_yet_gives_the_tools_back_and_the_draft_is_not_delivered(store) -> None:
    ran: list[str] = []
    backend = ScriptedBackend(
        calls("ping"),
        says("half done"),
        says("not yet"),
        calls("ping"),
        says("all done"),
        says("done"),
    )
    check = MeetsTheRequest(backend)
    agent = build_agent(backend, Toolbox([ping(ran)]), store, OWNER, stopping=check)

    result = await agent.ainvoke(ask("ping twice"))

    assert ran == ["ran", "ran"]
    # The round after `not yet` is offered the tools again.
    assert backend.tools_seen[3] is not None
    assert "not yet done" in prompt_text(backend.requests[3])
    assert check.verdicts == [NOT_YET, DONE]
    assert spoken(result["messages"]) == ["all done"]
    assert "half done" not in prompt_text(result["messages"])


async def test_blocked_keeps_the_answer_and_asks_only_for_the_reason(store) -> None:
    backend = ScriptedBackend(
        calls("ping"),
        says("I could not, the site needs a login."),
        says("blocked: the site needs a login"),
        says(""),  # the answer already says why: nothing to add
    )
    check = MeetsTheRequest(backend)
    agent = loop(backend, store, check)

    result = await agent.ainvoke(ask("fetch it"))

    assert check.verdicts == [BLOCKED]
    assert "the site needs a login" in prompt_text(backend.requests[3])
    assert backend.tools_seen[3] is not None  # blocked is not a budget ending
    assert spoken(result["messages"]) == ["I could not, the site needs a login."]


async def test_the_rounds_are_capped(store) -> None:
    backend = ScriptedBackend(
        calls("ping"),
        says("v1"),
        says("not yet"),
        says("v2"),
        says("not yet"),
        says("v3"),
        # No third question: the cap is reached before it would be asked.
    )
    check = MeetsTheRequest(backend, rounds=2)
    agent = loop(backend, store, check)

    result = await agent.ainvoke(ask("go"))

    assert check.verdicts == [NOT_YET, NOT_YET]
    assert len(backend.requests) == 6
    assert spoken(result["messages"]) == ["v3"]


async def test_the_turn_budget_still_bounds_the_rounds(store) -> None:
    backend = ScriptedBackend(calls("ping"), says("v1"), default=says("not yet"))
    check = MeetsTheRequest(backend)
    agent = loop(backend, store, check, budget=TurnBudget(max_steps=2))

    result = await agent.ainvoke(ask("go"))

    # Two steps used: the call and the answer. Nothing is left to steer into.
    assert check.verdicts == []
    assert spoken(result["messages"]) == ["v1"]


async def test_a_check_that_fails_does_not_fail_the_turn(store) -> None:
    backend = ScriptedBackend(calls("ping"), says("fine"), RuntimeError("boom"))
    agent = loop(backend, store, MeetsTheRequest(backend))

    result = await agent.ainvoke(ask("go"))

    assert spoken(result["messages"]) == ["fine"]


# --- composition ----------------------------------------------------------------


class Objects:
    async def stopping(self, candidate):
        return Steering("finish your list", source="todo")


async def test_the_first_objection_decides_and_the_next_is_not_asked(store) -> None:
    backend = ScriptedBackend(calls("ping"), says("v1"), says(""))
    check = MeetsTheRequest(backend)
    agent = loop(backend, store, FirstObjection(Objects(), check))

    await agent.ainvoke(ask("go"))

    assert check.verdicts == []
    assert "finish your list" in prompt_text(backend.requests[2])


async def test_no_objection_falls_through_to_the_next(store) -> None:
    backend = ScriptedBackend(calls("ping"), says("v1"), says("done"))
    check = MeetsTheRequest(backend)
    agent = loop(backend, store, FirstObjection(STOP_ON_ANSWER, check))

    await agent.ainvoke(ask("go"))

    assert check.verdicts == [DONE]


# --- the question is in the trace ---------------------------------------------


async def test_the_check_is_a_traced_model_call_with_its_verdict(store, tmp_path) -> None:
    from app.agent.graph import RUN_ID
    from app.telemetry import Telemetry, TurnRun
    from app.telemetry.sqlite import SqliteTelemetry

    telemetry = Telemetry(SqliteTelemetry(str(tmp_path / "telemetry.db")))
    backend = ScriptedBackend(calls("ping"), says("v1"), says("not yet"), says("v2"), says("done"))
    agent = build_agent(
        backend, Toolbox([ping()]), store, OWNER, stopping=MeetsTheRequest(backend), telemetry=telemetry
    )
    trace = telemetry.start(TurnRun(run_id="goal-run", user_id=OWNER, thread_id="t", source="test"))
    await agent.ainvoke(ask("go"), config={"configurable": {RUN_ID: "goal-run"}})
    trace.flush()

    events = telemetry.store.events("goal-run")
    purposes = [e.data.get("purpose") for e in events if e.type == "model_finished"]
    assert purposes.count("goal") == 2
    verdicts = [e.data["verdict"] for e in events if e.type == "goal_checked"]
    assert verdicts == [NOT_YET, DONE]
    assert not any("v1" in str(e.data) for e in events)
    telemetry.close()
