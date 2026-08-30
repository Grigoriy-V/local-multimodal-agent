"""What bounds one turn of the loop: its budget, and the person.

The loop's only ordinary exit is the model answering without asking for a tool.
These are the other two, and they are the reason the loop is allowed to run
without a second lifecycle beside it: a turn that will not stop by itself is
stopped by its budget, and a turn the person no longer wants is stopped by
them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.graph import TurnBudget, build_agent
from app.agent.stop import NO_STOPS, MemoryStopRequests
from app.memory import LOCAL_USER_ID, SqliteStore
from app.models import Completion, ContentPart, Message
from app.tools import Tool, Toolbox
from tests.fakes import ScriptedBackend, calls, says

OWNER = LOCAL_USER_ID


@pytest.fixture
def store() -> SqliteStore:
    with SqliteStore() as store:
        yield store


def ping(recorded: list[str] | None = None) -> Tool:
    def run() -> str:
        if recorded is not None:
            recorded.append("ran")
        return "pong"

    return Tool(
        name="ping",
        description="answer",
        parameters={"type": "object", "properties": {}},
        run=run,
    )


def loop(
    backend: ScriptedBackend,
    store: SqliteStore,
    tools: list[Tool] | None = None,
    budget: TurnBudget | None = None,
    stops=NO_STOPS,
):
    return build_agent(
        backend,
        Toolbox(tools if tools is not None else [ping()]),
        store,
        OWNER,
        budget=budget,
        stops=stops,
    )


def ask(text: str = "go", sequence: int = 10) -> dict[str, object]:
    return {
        "messages": [Message(role="user", content=[ContentPart(kind="text", text=text)])],
        "sequence": sequence,
    }


def spoken(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content)


# --- the budget --------------------------------------------------------------


async def test_a_model_that_never_stops_calling_tools_is_stopped(
    store: SqliteStore,
) -> None:
    """Without this the only ceiling is LangGraph's recursion limit.

    Which is a guard against a graph that cannot terminate, not a statement
    about what a person's question is allowed to cost.
    """

    ran: list[str] = []
    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(backend, store, [ping(ran)], TurnBudget(max_steps=3))

    result = await agent.ainvoke(ask())

    assert result.get("stopping", "") == "budget"
    assert len(ran) == 2, "the third step was the one that was refused"
    # Four model calls for a ceiling of three steps: the ceiling bounds the
    # work, and the answer the person is owed is always allowed after it.
    assert result["steps"] == 4


async def test_the_turn_still_answers_after_its_budget_is_spent(
    store: SqliteStore,
) -> None:
    """A turn that hit its ceiling owes the person a sentence, not silence."""

    backend = ScriptedBackend(
        calls("ping"), calls("ping"), says("I ran out of room, but here it is.")
    )
    agent = loop(backend, store, budget=TurnBudget(max_steps=2))

    result = await agent.ainvoke(ask())

    last = result["messages"][-1]
    assert last.role == "assistant"
    assert spoken(last) == "I ran out of room, but here it is."
    # The refused call came back as a tool result, so the model could see why.
    refused = [message for message in result["messages"] if message.role == "tool"]
    assert "answer now" in spoken(refused[-1])


async def test_the_last_request_of_a_spent_turn_is_offered_no_tools(
    store: SqliteStore,
) -> None:
    """Otherwise the answer is another tool call, and the ceiling is a loop."""

    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(backend, store, budget=TurnBudget(max_steps=2))

    result = await agent.ainvoke(ask())

    assert backend.tools_seen[-1] is None
    # A model offered no tools may still ask for one; what must never be stored
    # is an assistant message whose calls have no results.
    assert not result["messages"][-1].tool_calls


async def test_the_tool_ceiling_counts_calls_and_not_steps(store: SqliteStore) -> None:
    ran: list[str] = []
    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(
        backend, store, [ping(ran)], TurnBudget(max_steps=99, max_tool_calls=2)
    )

    result = await agent.ainvoke(ask())

    assert result.get("stopping", "") == "budget"
    assert len(ran) == 2


async def test_a_turn_that_spent_its_seconds_stops(store: SqliteStore) -> None:
    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(
        backend, store, budget=TurnBudget(max_steps=99, max_seconds=0.000_001)
    )

    result = await agent.ainvoke(ask())

    assert result.get("stopping", "") == "budget"


async def test_an_ordinary_turn_spends_none_of_its_budget_on_the_next_one(
    store: SqliteStore,
) -> None:
    """The counters are reset per turn, or the second one starts exhausted."""

    backend = ScriptedBackend(default=says("done"))
    agent = loop(backend, store, budget=TurnBudget(max_steps=2))

    first = await agent.ainvoke(ask("one"))
    second = await agent.ainvoke(ask("two"))

    assert first["steps"] == second["steps"] == 1
    assert second.get("stopping", "") == ""


# --- the stop ----------------------------------------------------------------


async def test_a_stop_between_steps_ends_the_turn(store: SqliteStore) -> None:
    ran: list[str] = []
    stops = MemoryStopRequests()
    await stops.request(OWNER, 11)  # after the turn's own sequence of 10
    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(backend, store, [ping(ran)], stops=stops)

    result = await agent.ainvoke(ask(sequence=10))

    assert result.get("stopping", "") == "stopped"
    assert ran == [], "nothing may run after the person has said stop"
    assert spoken(result["messages"][-1]) == "Stopped at your request."


async def test_a_stopped_turn_does_not_pay_for_another_model_call(
    store: SqliteStore,
) -> None:
    """Someone who asked for the work to end is not asking for one more request."""

    stops = MemoryStopRequests()
    await stops.request(OWNER, 11)
    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(backend, store, stops=stops)

    await agent.ainvoke(ask(sequence=10))

    assert len(backend.requests) == 1


async def test_a_stop_from_before_this_turn_does_not_stop_it(
    store: SqliteStore,
) -> None:
    """The trap a plain flag has: an unconsumed stop cancelling the next turn.

    The number a stop arrives with is what tells the two apart, and every
    interface has one — Telegram's update id, a session's own counter.
    """

    ran: list[str] = []
    stops = MemoryStopRequests()
    await stops.request(OWNER, 9)
    backend = ScriptedBackend(calls("ping"), says("done"))
    agent = loop(backend, store, [ping(ran)], stops=stops)

    result = await agent.ainvoke(ask(sequence=10))

    assert result.get("stopping", "") == ""
    assert ran == ["ran"]


async def test_one_person_s_stop_does_not_end_another_person_s_turn(
    store: SqliteStore,
) -> None:
    stops = MemoryStopRequests()
    await stops.request("somebody-else", 99)
    backend = ScriptedBackend(calls("ping"), says("done"))
    agent = loop(backend, store, stops=stops)

    result = await agent.ainvoke(ask(sequence=10))

    assert result.get("stopping", "") == ""


async def test_a_stop_channel_that_fails_does_not_fail_the_turn(
    store: SqliteStore,
) -> None:
    """The turn this protects is the expensive half of the product."""

    class Broken:
        async def request(self, key: str, sequence: int) -> None:
            raise RuntimeError("the control plane is down")

        async def requested(self, key: str, since: int) -> bool:
            raise RuntimeError("the control plane is down")

    backend = ScriptedBackend(calls("ping"), says("done"))
    agent = loop(backend, store, stops=Broken())

    result = await agent.ainvoke(ask())

    assert spoken(result["messages"][-1]) == "done"


async def test_a_stopped_turn_is_a_history_the_next_request_can_be_built_from(
    store: SqliteStore,
) -> None:
    """Every call the model made has a result, including the ones never run."""

    stops = MemoryStopRequests()
    await stops.request(OWNER, 11)
    backend = ScriptedBackend(default=calls("ping"))
    agent = loop(backend, store, stops=stops)

    result = await agent.ainvoke(ask(sequence=10))

    asked = [call.id for message in result["messages"] for call in message.tool_calls]
    answered = [
        message.tool_call_id for message in result["messages"] if message.role == "tool"
    ]
    assert asked and asked == answered


# --- where a stop is recorded ------------------------------------------------


async def test_a_stop_applies_to_everything_that_began_before_it() -> None:
    stops = MemoryStopRequests()

    await stops.request("owner", 5)

    assert await stops.requested("owner", 4) is True
    assert await stops.requested("owner", 5) is False
    assert await stops.requested("owner", 6) is False


async def test_a_second_stop_never_moves_the_mark_backwards() -> None:
    """Two stops in quick succession are one intention, not an undo."""

    stops = MemoryStopRequests()

    await stops.request("owner", 5)
    await stops.request("owner", 3)

    assert await stops.requested("owner", 4) is True


async def test_nothing_is_stopped_when_there_is_no_way_to_ask() -> None:
    assert await NO_STOPS.requested("owner", 0) is False
    assert await NO_STOPS.request("owner", 1) is None
