"""Durable application runtime for the bounded task graph.

UI adapters start, inspect and resume a task through this class. They never
compile graphs, open checkpoint databases or resolve artifact paths themselves.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.runtime import CHECKPOINT_TYPES
from app.agent.task_graph import (
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
    outcome: TaskOutcome | None
    report: TestReport | None
    interrupt: dict[str, Any] | None = None


class TaskRuntime:
    """One sequential resumable task lane per canonical conversation."""

    def __init__(
        self,
        backend: ModelBackend,
        workspace: Path,
        checkpoints: str | Path,
        tester: Tester,
        budget: TaskBudget | None = None,
    ) -> None:
        self.backend = backend
        self.workspace = Path(workspace).resolve()
        self.checkpoints = Path(checkpoints)
        self.tester = tester
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

    async def start(self, thread_id: str, task: str) -> TaskView:
        graph = await self._compiled()
        await graph.ainvoke(
            {"task": task, "subdirectory": self.subdirectory(thread_id)},
            config=self._config(thread_id),
        )
        return await self.view(thread_id)

    async def resume(self, thread_id: str, approved: bool) -> TaskView:
        graph = await self._compiled()
        await graph.ainvoke(Command(resume=approved), config=self._config(thread_id))
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
            outcome=values.get("outcome"),
            report=values.get("test_report"),
            interrupt=interrupt,
        )

    def artifact_path(self, view: TaskView, artifact: str) -> Path:
        grant_root = (self.workspace / view.subdirectory).resolve()
        target = (grant_root / artifact).resolve()
        if grant_root not in target.parents:
            raise PermissionError("task artifact is outside the granted directory")
        return target

    async def aclose(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._saver = None
            self._graph = None
