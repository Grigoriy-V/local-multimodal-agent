"""The answer becomes visible while it is being written, and nothing else changes.

Streaming is worth exactly one thing: a person sees the answer appear instead of
waiting at a blank chat. Everything these tests guard is the other half of that
bargain — the turn the graph runs, the messages it stores, the tool loop and the
usage it reports must be the ones it produced before streaming existed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from app.agent.runtime import Agent, AssistantDelta, MessageProduced
from app.memory import SqliteStore
from app.models import (
    Completion,
    CompletionDone,
    Message,
    ModelBackend,
    StreamEvent,
    TextDelta,
)
from tests.fakes import ScriptedBackend, body, calls, says, user


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    room = tmp_path / "workspace"
    room.mkdir()
    (room / "notes.txt").write_text("the answer is 42", encoding="utf-8")
    return room


def open_agent(
    tmp_path: Path, workspace: Path, backend: ModelBackend, *, stream: bool = True
) -> Agent:
    return Agent(
        backend,
        SqliteStore(tmp_path / "memory.sqlite3"),
        workspace,
        stream_answers=stream,
    )


async def collect(agent: Agent, thread: str, message: Message) -> list[Any]:
    return [event async for event in agent.events(thread, message)]


def deltas(events: Sequence[Any]) -> list[str]:
    return [event.text for event in events if isinstance(event, AssistantDelta)]


def messages(events: Sequence[Any]) -> list[Message]:
    return [event.message for event in events if isinstance(event, MessageProduced)]


# --- the deltas are the answer, arriving early --------------------------------


async def test_the_deltas_join_into_the_message_that_is_produced(
    tmp_path: Path, workspace: Path
) -> None:
    agent = open_agent(tmp_path, workspace, ScriptedBackend(says("The answer is 42.")))

    events = await collect(agent, "t1", user("what is it"))

    assert "".join(deltas(events)) == "The answer is 42."
    assert body(messages(events)[0]) == "The answer is 42."


async def test_a_delta_arrives_before_the_model_call_has_finished(
    tmp_path: Path, workspace: Path
) -> None:
    """The whole point: the preview cannot wait for the completion.

    The backend below refuses to finish its stream until the test has already
    received a delta, so this deadlocks rather than passes if deltas are
    collected and handed over at the end of the node.
    """

    seen = asyncio.Event()

    class Slow(ModelBackend):
        async def invoke(self, messages, tools=None, response_format=None) -> Completion:
            raise AssertionError("a streaming turn must not fall back to invoke")

        async def stream(
            self, messages, tools=None, response_format=None
        ) -> AsyncIterator[StreamEvent]:
            yield TextDelta("Half ")
            await asyncio.wait_for(seen.wait(), timeout=5)
            yield TextDelta("an answer.")
            yield CompletionDone(Completion(text="Half an answer.", finish_reason="stop"))

    agent = open_agent(tmp_path, workspace, Slow())
    collected: list[Any] = []

    async for event in agent.events("t1", user("say something")):
        collected.append(event)
        if isinstance(event, AssistantDelta):
            seen.set()

    assert deltas(collected) == ["Half ", "an answer."]
    assert body(messages(collected)[0]) == "Half an answer."


async def test_switching_streaming_off_still_answers(
    tmp_path: Path, workspace: Path
) -> None:
    """The switch changes what is shown, never what is said."""

    agent = open_agent(
        tmp_path, workspace, ScriptedBackend(says("The answer is 42.")), stream=False
    )

    events = await collect(agent, "t1", user("what is it"))

    assert deltas(events) == []
    assert body(messages(events)[0]) == "The answer is 42."


# --- the turn is unchanged ----------------------------------------------------


async def test_tool_calls_still_run_and_the_second_call_also_streams(
    tmp_path: Path, workspace: Path
) -> None:
    backend = ScriptedBackend(
        calls("read_file", path="notes.txt"),
        says("Your notes say 42."),
    )
    agent = open_agent(tmp_path, workspace, backend)

    events = await collect(agent, "t1", user("read my notes"))

    produced = messages(events)
    assert [message.role for message in produced] == ["assistant", "tool", "assistant"]
    assert produced[0].tool_calls[0].name == "read_file"
    assert "42" in body(produced[1])
    # The text of the answer streamed; the tool-calling turn had none to stream.
    assert "".join(deltas(events)) == "Your notes say 42."
    kinds = [type(event).__name__ for event in events]
    assert kinds.index("MessageProduced") < kinds.index("AssistantDelta")


async def test_only_finished_messages_are_stored(tmp_path: Path, workspace: Path) -> None:
    """A delta is presentation. The store must not learn that streaming exists."""

    agent = open_agent(tmp_path, workspace, ScriptedBackend(says("The answer is 42.")))

    await collect(agent, "t1", user("what is it"))

    stored = agent.history("t1")
    assert [body(message) for message in stored] == ["what is it", "The answer is 42."]


async def test_usage_survives_the_stream(tmp_path: Path, workspace: Path) -> None:
    """Usage arrives in the last chunk of all, and the fold depends on it."""

    agent = open_agent(
        tmp_path, workspace, ScriptedBackend(says("Short.", input_tokens=1234), limit=10_000)
    )

    await collect(agent, "t1", user("what is it"))
    fill = await agent.fill()

    assert fill is not None
    assert fill.used == 1234


async def test_steps_still_yields_only_finished_messages(
    tmp_path: Path, workspace: Path
) -> None:
    """The older contract is untouched, so a UI that never asked for deltas is too."""

    agent = open_agent(tmp_path, workspace, ScriptedBackend(says("The answer is 42.")))

    produced = [message async for message in agent.steps("t1", user("what is it"))]

    assert [body(message) for message in produced] == ["The answer is 42."]
