"""One model-owned route fronts conversation and bounded task work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.harness import GeneralHarness, HarnessDecision, parse_decision
from app.agent.runtime import Agent
from app.agent.task_graph import ImplementationResult, TaskOutcome
from app.agent.task_runtime import TaskView
from app.memory import MemoryStore
from app.models import BackendError, ContentPart, Message
from tests.fakes import ScriptedBackend, says, user


class StubAgent:
    def __init__(self, backend: ScriptedBackend) -> None:
        self.backend = backend
        self.recorded: list[tuple[str, list[Message]]] = []
        self.closed = False

    def record(self, thread_id: str, messages: list[Message]) -> None:
        self.recorded.append((thread_id, messages))

    def context_prompt(
        self, thread_id: str, messages: list[Message], system_prompt: str
    ) -> list[Message]:
        assert thread_id
        return [
            Message(role="system", content=[ContentPart(kind="text", text=system_prompt)]),
            *messages,
        ]

    async def aclose(self) -> None:
        self.closed = True


class StubTasks:
    def __init__(self, backend: ScriptedBackend) -> None:
        self.backend = backend
        self.started: tuple[str, str, str | None] | None = None
        self.closed = False
        self.view = TaskView(".", None, None, None, None, None)

    async def start(
        self, thread_id: str, task: str, subdirectory: str | None = None
    ) -> TaskView:
        self.started = (thread_id, task, subdirectory)
        return self.view

    async def aclose(self) -> None:
        self.closed = True


def harness(backend: ScriptedBackend) -> tuple[GeneralHarness, StubAgent, StubTasks]:
    agent = StubAgent(backend)
    tasks = StubTasks(backend)
    return GeneralHarness(agent, tasks), agent, tasks  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"route": "answer", "task": ""}, HarnessDecision("answer")),
        (
            {"route": "act", "task": "Create snake.html in the supplied workspace."},
            HarnessDecision("act", "Create snake.html in the supplied workspace."),
        ),
    ],
)
def test_router_accepts_only_the_two_internal_outcomes(
    payload: dict[str, str], expected: HarnessDecision
) -> None:
    assert parse_decision(json.dumps(payload)) == expected


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"route": "conversation", "task": ""},
        {"route": "answer", "task": "secret extra work"},
        {"route": "act", "task": ""},
        {"route": "answer", "task": "", "reason": "hidden prose"},
    ],
)
def test_router_rejects_ambiguous_or_extra_output(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse_decision(json.dumps(payload))


async def test_model_routes_a_normal_request_without_a_user_mode() -> None:
    backend = ScriptedBackend(says('{"route":"answer","task":""}'))
    runtime, _agent, _tasks = harness(backend)

    decision = await runtime.decide("thread", user("Explain what this graph does"))

    assert decision == HarnessDecision("answer")
    assert backend.tools_seen == [None]
    assert backend.formats_seen[0]["json_schema"]["name"] == "request_route"


async def test_model_routes_implementation_and_preserves_the_exact_path() -> None:
    task = r'Edit "D:\ML\local-multimodal-agent\workspace\snake.html".'
    backend = ScriptedBackend(
        says(json.dumps({"route": "act", "task": task}, ensure_ascii=False))
    )
    runtime, _agent, _tasks = harness(backend)

    decision = await runtime.decide(
        "thread", user("Change the title in that absolute path")
    )

    assert decision == HarnessDecision("act", task)


async def test_routing_receives_multimodal_parts_without_a_separate_mode() -> None:
    backend = ScriptedBackend(says('{"route":"answer","task":""}'))
    runtime, _agent, _tasks = harness(backend)
    message = Message(
        role="user",
        content=[
            ContentPart(kind="text", text="What is wrong here?"),
            ContentPart(kind="image", data=b"image", media_type="image/png"),
        ],
    )

    await runtime.decide("thread", message)

    assert backend.requests[0][-1] == message


async def test_routing_sees_bounded_conversation_context(tmp_path: Path) -> None:
    backend = ScriptedBackend(says('{"route":"answer","task":""}'))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = Agent(backend, MemoryStore(tmp_path / "memory.sqlite3"), workspace)
    agent.record(
        "thread",
        [
            user("The artifact is result.html"),
            Message(
                role="assistant",
                content=[ContentPart(kind="text", text="Understood")],
            ),
        ],
    )
    runtime = GeneralHarness(agent, StubTasks(backend))  # type: ignore[arg-type]

    await runtime.decide("thread", user("Now change it"))

    routed_text = "\n".join(
        part.text or ""
        for message in backend.requests[0]
        for part in message.content
        if part.kind == "text"
    )
    assert "The artifact is result.html" in routed_text
    assert "Now change it" in routed_text
    await runtime.aclose()


async def test_routing_failure_falls_back_to_the_normal_agent_path() -> None:
    backend = ScriptedBackend(BackendError("router unavailable"))
    runtime, _agent, _tasks = harness(backend)

    assert await runtime.decide("thread", user("hello")) == HarnessDecision("answer")


async def test_task_input_and_result_join_the_canonical_conversation() -> None:
    backend = ScriptedBackend()
    runtime, agent, tasks = harness(backend)
    original = user("Create an artifact")

    await runtime.start_task("thread", original, "Create result.txt")
    assert tasks.started == ("thread", "Create result.txt", ".")
    assert agent.recorded == [("thread", [original])]

    view = TaskView(
        subdirectory=".",
        grant=None,
        plan=None,
        implementation=ImplementationResult(
            "Created result.txt", tool_calls=1, artifacts=("result.txt",)
        ),
        outcome=TaskOutcome(
            "completed", "checks passed", 1, 1, 0.1, ("result.txt",)
        ),
        report=None,
    )
    result = runtime.finish_task("thread", view)

    assert result.role == "assistant"
    assert "result.txt" in result.content[0].text
    assert agent.recorded[-1] == ("thread", [result])


def test_chainlit_source_has_no_mode_selector_or_settings_route() -> None:
    source = Path("ui/chainlit_app.py").read_text(encoding="utf-8")

    assert "ChatSettings" not in source
    assert "@cl.on_settings_update" not in source
    assert 'user_session.set("mode"' not in source
