"""Durable application-facing task runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.task_runtime import TaskRuntime, artifact_tester
from app.agent.task_graph import (
    CheckResult,
    ImplementationResult,
    TaskContext,
    TaskGrant,
    TaskPlan,
    TaskStageError,
    TestReport as TaskTestReport,
)
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


async def test_default_artifact_check_is_limited_to_real_nonempty_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("done", encoding="utf-8")
    context = TaskContext(
        task="produce a result",
        plan=TaskPlan("Produce it", ("write it",), ("result is correct",)),
        iteration=1,
        feedback=None,
        remaining_tool_calls=10,
        grant=TaskGrant(".", status="active"),
    )

    report = await artifact_tester(workspace)(
        context,
        ImplementationResult("wrote it", artifacts=(str(workspace / "result.txt"),)),
    )

    assert report.passed
    assert report.checks[0].name == str(workspace / "result.txt")
    assert "non-empty" in report.checks[0].detail


async def test_default_artifact_check_does_not_claim_success_without_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = TaskContext(
        task="produce a result",
        plan=TaskPlan("Produce it", ("write it",), ("result is correct",)),
        iteration=1,
        feedback=None,
        remaining_tool_calls=10,
        grant=TaskGrant(".", status="active"),
    )

    with pytest.raises(
        TaskStageError,
        match="validation unavailable: no changed artifact was reported",
    ):
        await artifact_tester(workspace)(
            context, ImplementationResult("claimed completion")
        )


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
        "filesystem.read",
        "filesystem.write",
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
