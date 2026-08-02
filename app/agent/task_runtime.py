"""Durable application runtime for the bounded task graph.

UI adapters start, inspect and resume a task through this class. They never
compile graphs, open checkpoint databases or resolve artifact paths themselves.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.runtime import CHECKPOINT_TYPES
from app.agent.task_validator import ModelTaskValidator
from app.agent.task_graph import (
    ImplementationResult,
    Evaluation,
    TaskBudget,
    TaskGrant,
    TaskOutcome,
    TaskPlan,
    Tester,
    TestReport,
)
from app.agent.task_worker import build_model_task_graph
from app.models import ModelBackend


@dataclass(frozen=True)
class TaskView:
    subdirectory: str
    grant: TaskGrant | None
    plan: TaskPlan | None
    implementation: ImplementationResult | None
    outcome: TaskOutcome | None
    report: TestReport | None
    interrupt: dict[str, Any] | None = None


@dataclass(frozen=True)
class TaskProgress:
    """One durable lifecycle update for any UI adapter to render."""

    stage: Literal[
        "approval",
        "implementation",
        "validation",
        "evaluation",
        "repair",
        "finalization",
    ]
    detail: str


class TaskRuntime:
    """One sequential resumable task lane per canonical conversation."""

    def __init__(
        self,
        backend: ModelBackend,
        workspace: Path,
        checkpoints: str | Path,
        tester: Tester | None = None,
        budget: TaskBudget | None = None,
    ) -> None:
        self.backend = backend
        self.workspace = Path(workspace).resolve()
        self.checkpoints = Path(checkpoints)
        self.tester = tester or ModelTaskValidator(backend, self.workspace)
        self.budget = budget or TaskBudget(max_seconds=300.0)
        if not self.workspace.is_dir():
            raise ValueError(f"task workspace {self.workspace} is not a directory")
        self._connection: aiosqlite.Connection | None = None
        self._saver: AsyncSqliteSaver | None = None
        self._graph: CompiledStateGraph | None = None

    @staticmethod
    def subdirectory(thread_id: str) -> str:
        digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
        return f"tasks/{digest}"

    @staticmethod
    def _config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": f"task:{thread_id}"}}

    async def _compiled(self) -> CompiledStateGraph:
        if self._graph is None:
            self.checkpoints.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(str(self.checkpoints))
            serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
            self._saver = AsyncSqliteSaver(self._connection, serde=serde)
            await self._saver.setup()
            self._graph = build_model_task_graph(
                self.backend,
                self.workspace,
                self.tester,
                budget=self.budget,
                checkpointer=self._saver,
            )
        return self._graph

    async def start(
        self, thread_id: str, task: str, subdirectory: str | None = None
    ) -> TaskView:
        graph = await self._compiled()
        await graph.ainvoke(
            {"task": task, "subdirectory": subdirectory or self.subdirectory(thread_id)},
            config=self._config(thread_id),
        )
        return await self.view(thread_id)

    async def resume(self, thread_id: str, approved: bool) -> TaskView:
        async for _progress in self.resume_with_progress(thread_id, approved):
            pass
        return await self.view(thread_id)

    async def resume_with_progress(
        self, thread_id: str, approved: bool
    ) -> AsyncIterator[TaskProgress]:
        """Resume an approved task and expose real graph progress as it commits."""

        graph = await self._compiled()
        async for update in graph.astream(
            Command(resume=approved),
            config=self._config(thread_id),
            stream_mode="updates",
        ):
            progress = self._progress(update)
            if progress is not None:
                yield progress

    @staticmethod
    def _progress(update: object) -> TaskProgress | None:
        if not isinstance(update, dict) or len(update) != 1:
            return None
        node, patch = next(iter(update.items()))
        if not isinstance(patch, dict):
            return None
        if node == "authorize":
            grant = patch.get("grant")
            if isinstance(grant, TaskGrant) and grant.status == "active":
                return TaskProgress("approval", "Workspace grant approved.")
            return TaskProgress("approval", "Workspace grant declined.")
        if node == "implement":
            iteration = patch.get("iteration", 0)
            return TaskProgress(
                "implementation", f"Implementation attempt {iteration} completed."
            )
        if node == "test":
            report = patch.get("test_report")
            if isinstance(report, TestReport):
                passed = sum(check.passed for check in report.checks)
                return TaskProgress(
                    "validation",
                    f"Validation collected evidence for {passed}/{len(report.checks)} criteria.",
                )
        if node == "evaluate":
            evaluation = patch.get("evaluation")
            if isinstance(evaluation, Evaluation):
                if evaluation.decision == "retry":
                    return TaskProgress("repair", f"Repair requested: {evaluation.feedback}")
                return TaskProgress("evaluation", "All evaluated criteria passed.")
        if node == "finalize":
            outcome = patch.get("outcome")
            if isinstance(outcome, TaskOutcome):
                return TaskProgress("finalization", outcome.summary)
        return None

    async def cancel(self, thread_id: str) -> TaskView | None:
        """Persist a user cancellation so a stopped task cannot resume by accident."""

        graph = await self._compiled()
        config = self._config(thread_id)
        snapshot = await graph.aget_state(config)
        values = snapshot.values
        if not values or values.get("outcome") is not None:
            return None

        reason = "cancelled by user"
        grant = values.get("grant")
        revoked = grant
        if isinstance(grant, TaskGrant) and grant.status != "revoked":
            revoked = TaskGrant(
                grant.subdirectory,
                status="revoked",
                permissions=grant.permissions,
                revoked_reason=reason,
            )
        report = values.get("test_report")
        started_at = values.get("started_at")
        elapsed = (
            max(0.0, time.monotonic() - started_at)
            if isinstance(started_at, (int, float))
            else 0.0
        )
        outcome = TaskOutcome(
            status="stopped",
            summary=reason,
            iterations=int(values.get("iteration", 0)),
            tool_calls=int(values.get("tool_calls", 0)),
            elapsed_seconds=elapsed,
            artifacts=tuple(values.get("artifacts", ())),
            failures=report.failures if isinstance(report, TestReport) else (),
        )
        await graph.aupdate_state(
            config,
            {
                "stop_reason": reason,
                "grant": revoked,
                "outcome": outcome,
            },
            as_node="finalize",
        )
        return await self.view(thread_id)

    async def view(self, thread_id: str) -> TaskView:
        graph = await self._compiled()
        snapshot = await graph.aget_state(self._config(thread_id))
        interrupt = None
        for task in snapshot.tasks:
            if task.interrupts:
                value = task.interrupts[0].value
                interrupt = value if isinstance(value, dict) else None
                break
        values = snapshot.values
        return TaskView(
            subdirectory=values.get("subdirectory", self.subdirectory(thread_id)),
            grant=values.get("grant"),
            plan=values.get("plan"),
            implementation=values.get("implementation"),
            outcome=values.get("outcome"),
            report=values.get("test_report"),
            interrupt=interrupt,
        )

    def artifact_path(self, view: TaskView, artifact: str) -> Path:
        grant_root = (self.workspace / view.subdirectory).resolve()
        target = (grant_root / artifact).resolve()
        if target != grant_root and grant_root not in target.parents:
            raise PermissionError("task artifact is outside the granted directory")
        return target

    async def aclose(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._saver = None
            self._graph = None
