"""Durable application-facing task runtime."""

from __future__ import annotations

import json
from pathlib import Path

from app.agent.task_runtime import TaskRuntime
from app.agent.task_graph import CheckResult, TestReport as TaskTestReport
from tests.fakes import ScriptedBackend, says


def plan(summary: str) -> str:
    return json.dumps(
        {
            "summary": summary,
            "steps": ["create the file", "verify the result"],
            "acceptance_criteria": ["the file works"],
        }
    )


async def acceptance_placeholder(
    _context: object, _implementation: object
) -> TaskTestReport:
    return TaskTestReport((CheckResult("acceptance", True, "test-owned verifier"),))


async def test_pending_task_grant_is_exposed_and_can_be_declined(tmp_path: Path) -> None:
    backend = ScriptedBackend(says(plan("Create Snake.")))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = TaskRuntime(
        backend,
        workspace,
        tmp_path / "task-checkpoints.sqlite3",
        acceptance_placeholder,
    )

    pending = await runtime.start("chat-one", "Create Snake")

    assert pending.interrupt is not None
    assert pending.interrupt["subdirectory"] == runtime.subdirectory("chat-one")
    assert pending.interrupt["permissions"] == [
        "write_file",
        "edit_file",
        "browser_verify",
    ]
    assert not (workspace / pending.subdirectory).exists()

    declined = await runtime.resume("chat-one", False)

    assert declined.outcome is not None
    assert declined.outcome.status == "stopped"
    assert declined.grant is not None
    assert declined.grant.status == "revoked"
    await runtime.aclose()


async def test_a_second_task_in_one_chat_starts_with_clean_state(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        says(plan("First plan.")),
        says(plan("Second plan.")),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = TaskRuntime(
        backend,
        workspace,
        tmp_path / "task-checkpoints.sqlite3",
        acceptance_placeholder,
    )

    await runtime.start("chat", "First task")
    first = await runtime.resume("chat", False)
    assert first.outcome is not None

    second = await runtime.start("chat", "Second task")

    assert second.plan is not None
    assert second.plan.summary == "Second plan."
    assert second.outcome is None
    assert second.interrupt is not None
    await runtime.aclose()
