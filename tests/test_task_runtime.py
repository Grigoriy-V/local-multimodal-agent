"""Durable application-facing task runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.agent.task_runtime import TaskRuntime
from app.agent.task_graph import (
    CheckResult,
    TestReport as TaskTestReport,
)
from tests.fakes import ScriptedBackend, calls, says


class BlockingImplementationBackend(ScriptedBackend):
    def __init__(self, task_plan: str) -> None:
        super().__init__(says(task_plan))
        self.implementation_started = asyncio.Event()

    async def invoke(self, messages, tools=None, response_format=None):
        if self.completions:
            return await super().invoke(messages, tools, response_format)
        self.implementation_started.set()
        await asyncio.Future()


def plan(summary: str) -> str:
    return json.dumps(
        {
            "summary": summary,
            "steps": ["create the file", "verify the result"],
            "acceptance_criteria": ["the file works"],
            "validation_strategy": [
                {
                    "criterion": "the file works",
                    "evidence": "Read the produced file.",
                    "capabilities": ["filesystem.read"],
                }
            ],
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


async def test_default_runtime_validates_real_file_evidence(tmp_path: Path) -> None:
    criterion = "result.txt contains STEP-4"
    task_plan = json.dumps(
        {
            "summary": "Create and validate result.txt.",
            "steps": ["create result.txt", "validate its contents"],
            "acceptance_criteria": [criterion],
            "validation_strategy": [
                {
                    "criterion": criterion,
                    "evidence": "Read result.txt and verify its exact contents.",
                    "capabilities": ["filesystem.read"],
                }
            ],
        }
    )
    evaluation = json.dumps(
        {
            "checks": [
                {
                    "criterion": criterion,
                    "passed": True,
                    "detail": "read_file returned STEP-4",
                }
            ]
        }
    )
    backend = ScriptedBackend(
        says(task_plan),
        calls("write_file", path="result.txt", content="STEP-4"),
        says("Created result.txt."),
        calls("read_file", path="result.txt"),
        says("Evidence collected."),
        says(evaluation),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = TaskRuntime(
        backend,
        workspace,
        tmp_path / "task-checkpoints.sqlite3",
    )

    pending = await runtime.start("validated-chat", "Create result.txt with STEP-4")
    assert pending.interrupt is not None
    completed = await runtime.resume("validated-chat", True)

    assert completed.outcome is not None
    assert completed.outcome.status == "completed"
    assert completed.outcome.tool_calls == 3
    assert completed.report is not None
    assert completed.report.checks[0].detail == "read_file returned STEP-4"
    assert (workspace / completed.subdirectory / "result.txt").read_text() == "STEP-4"
    await runtime.aclose()


async def test_runtime_streams_committed_lifecycle_progress(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        says(plan("Create result.txt.")),
        calls("write_file", path="result.txt", content="done"),
        says("Created result.txt."),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = TaskRuntime(
        backend,
        workspace,
        tmp_path / "task-checkpoints.sqlite3",
        acceptance_placeholder,
    )

    await runtime.start("progress-chat", "Create result.txt")
    progress = [
        update
        async for update in runtime.resume_with_progress("progress-chat", True)
    ]

    assert [update.stage for update in progress] == [
        "approval",
        "implementation",
        "validation",
        "evaluation",
        "finalization",
    ]
    assert "1/1" in progress[2].detail
    assert (await runtime.view("progress-chat")).outcome.status == "completed"
    await runtime.aclose()


async def test_cancellation_revokes_grant_and_persists_stopped_outcome(
    tmp_path: Path,
) -> None:
    backend = ScriptedBackend(says(plan("Create result.txt.")))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = TaskRuntime(
        backend,
        workspace,
        tmp_path / "task-checkpoints.sqlite3",
        acceptance_placeholder,
    )

    await runtime.start("cancel-chat", "Create result.txt")
    cancelled = await runtime.cancel("cancel-chat")

    assert cancelled is not None
    assert cancelled.outcome is not None
    assert cancelled.outcome.status == "stopped"
    assert cancelled.outcome.summary == "cancelled by user"
    assert cancelled.grant is not None
    assert cancelled.grant.status == "revoked"
    assert cancelled.interrupt is None
    assert await runtime.cancel("cancel-chat") is None
    await runtime.aclose()


async def test_cancellation_after_chainlit_interrupts_active_implementation(
    tmp_path: Path,
) -> None:
    backend = BlockingImplementationBackend(plan("Create result.txt."))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = TaskRuntime(
        backend,
        workspace,
        tmp_path / "task-checkpoints.sqlite3",
        acceptance_placeholder,
    )
    await runtime.start("active-chat", "Create result.txt")
    active = asyncio.create_task(runtime.resume("active-chat", True))
    await asyncio.wait_for(backend.implementation_started.wait(), timeout=1)

    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    cancelled = await runtime.cancel("active-chat")

    assert cancelled is not None
    assert cancelled.outcome is not None
    assert cancelled.outcome.status == "stopped"
    assert cancelled.grant is not None
    assert cancelled.grant.status == "revoked"
    await runtime.aclose()
