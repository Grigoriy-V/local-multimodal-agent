"""Asking before writing, and finishing a turn that stopped to ask.

Only the model is faked. The checkpoint file, the store and the tools are real,
because the property under test is that a question outlives the process that
asked it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.runtime import Agent
from app.memory import MemoryStore
from tests.fakes import ScriptedBackend, body, calls, says, user


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    room = tmp_path / "workspace"
    room.mkdir()
    (room / "notes.txt").write_text("the answer is 42", encoding="utf-8")
    return room


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "memory.sqlite3", tmp_path / "checkpoints.sqlite3"


def open_agent(
    paths: tuple[Path, Path],
    workspace: Path,
    backend: ScriptedBackend,
    checkpointed: bool = True,
) -> Agent:
    database, checkpoints = paths
    return Agent(
        backend,
        MemoryStore(database),
        workspace,
        checkpoints=checkpoints if checkpointed else None,
    )


def writes(path: str, content: str) -> ScriptedBackend:
    return ScriptedBackend(calls("write_file", path=path, content=content), says("Done."))


# --- the question ------------------------------------------------------------


async def test_a_write_stops_the_turn_and_asks(paths: tuple[Path, Path], workspace: Path) -> None:
    agent = open_agent(paths, workspace, writes("notes.txt", "43"))

    produced = await agent.answer("t1", user("Change notes.txt to 43."))
    question = await agent.pending("t1")

    assert [message.role for message in produced] == ["assistant"]
    assert question == [
        {
            "id": "call_write_file",
            "name": "write_file",
            "arguments": {"path": "notes.txt", "content": "43"},
        }
    ]
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "the answer is 42"
    await agent.aclose()


async def test_a_read_is_never_asked_about(paths: tuple[Path, Path], workspace: Path) -> None:
    backend = ScriptedBackend(calls("read_file", path="notes.txt"), says("42."))
    agent = open_agent(paths, workspace, backend)

    await agent.answer("t1", user("What does notes.txt say?"))

    assert await agent.pending("t1") is None
    await agent.aclose()


# --- the answer --------------------------------------------------------------


async def test_approving_writes_the_file_and_finishes_the_turn(
    paths: tuple[Path, Path], workspace: Path
) -> None:
    agent = open_agent(paths, workspace, writes("notes.txt", "43"))
    await agent.answer("t1", user("Change notes.txt to 43."))

    rest = [message async for message in agent.resume("t1", {"call_write_file": True})]

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "43"
    assert [message.role for message in rest] == ["tool", "assistant"]
    assert body(rest[0]) == "overwrote notes.txt (2 characters)"
    assert await agent.pending("t1") is None
    await agent.aclose()


async def test_declining_leaves_the_file_alone_and_tells_the_model(
    paths: tuple[Path, Path], workspace: Path
) -> None:
    backend = writes("notes.txt", "43")
    agent = open_agent(paths, workspace, backend)
    await agent.answer("t1", user("Change notes.txt to 43."))

    rest = [message async for message in agent.resume("t1", {"call_write_file": False})]

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "the answer is 42"
    assert body(rest[0]).startswith("error: the user declined")
    # The refusal is what the model sees next, so it can say so rather than retry.
    assert "declined" in body(backend.requests[-1][-1])
    await agent.aclose()


async def test_the_whole_turn_is_stored_once_it_finishes(
    paths: tuple[Path, Path], workspace: Path
) -> None:
    agent = open_agent(paths, workspace, writes("notes.txt", "43"))
    await agent.answer("t1", user("Change notes.txt to 43."))

    assert agent.history("t1") == []

    async for _ in agent.resume("t1", {"call_write_file": True}):
        pass

    assert [message.role for message in agent.history("t1")] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    await agent.aclose()


# --- the question outlives the process ---------------------------------------


async def test_a_pending_question_survives_a_restart(
    paths: tuple[Path, Path], workspace: Path
) -> None:
    first = open_agent(paths, workspace, writes("notes.txt", "43"))
    await first.answer("t1", user("Change notes.txt to 43."))
    await first.aclose()

    second = open_agent(paths, workspace, ScriptedBackend(says("Done.")))
    question = await second.pending("t1")
    rest = [message async for message in second.resume("t1", {"call_write_file": True})]

    assert question is not None and question[0]["name"] == "write_file"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "43"
    assert [message.role for message in rest] == ["tool", "assistant"]
    await second.aclose()


# --- without a checkpointer there is nowhere to wait -------------------------


async def test_without_checkpoints_a_write_is_refused_rather_than_run(
    paths: tuple[Path, Path], workspace: Path
) -> None:
    agent = open_agent(paths, workspace, writes("notes.txt", "43"), checkpointed=False)

    produced = await agent.answer("t1", user("Change notes.txt to 43."))

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "the answer is 42"
    assert body(produced[1]).startswith("error: the user declined")
    await agent.aclose()


# --- one turn does not leak into the next ------------------------------------


async def test_a_second_turn_starts_from_an_empty_state(
    paths: tuple[Path, Path], workspace: Path
) -> None:
    backend = ScriptedBackend(says("One."), says("Two."))
    agent = open_agent(paths, workspace, backend)

    await agent.answer("t1", user("First question."))
    produced = await agent.answer("t1", user("Second question."))

    # Everything earlier reaches the model through the context layers, and the
    # store holds each message once — the checkpointed state carries none of it.
    assert [message.role for message in produced] == ["assistant"]
    assert [body(message) for message in agent.history("t1")] == [
        "First question.",
        "One.",
        "Second question.",
        "Two.",
    ]
    await agent.aclose()
