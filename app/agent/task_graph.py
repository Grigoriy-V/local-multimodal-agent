"""A bounded task loop, independent of any one model, tool or verifier.

The graph stores decisions that can be inspected and resumed: a concise plan,
acceptance criteria, implementation summaries and test reports. It never asks
for or stores private chain-of-thought. Concrete model/tool adapters arrive in
later Version 1.5 steps; this module owns only lifecycle and budgets.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt


@dataclass(frozen=True)
class TaskBudget:
    max_iterations: int = 3
    max_tool_calls: int = 20
    max_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if self.max_tool_calls < 0:
            raise ValueError("max_tool_calls cannot be negative")
        if self.max_seconds <= 0:
            raise ValueError("max_seconds must be positive")


@dataclass(frozen=True)
class TaskPlan:
    summary: str
    steps: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "acceptance_criteria", tuple(self.acceptance_criteria))
        if not self.summary.strip() or not self.steps or not self.acceptance_criteria:
            raise ValueError("a plan requires a summary, steps and acceptance criteria")
        if any(not item.strip() for item in (*self.steps, *self.acceptance_criteria)):
            raise ValueError("plan steps and acceptance criteria cannot be empty")


@dataclass(frozen=True)
class TaskGrant:
    subdirectory: str
    status: Literal["pending", "active", "revoked"] = "pending"
    permissions: tuple[str, ...] = ("write_file", "edit_file")
    revoked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", tuple(self.permissions))

    def allows(self, tool_name: str) -> bool:
        return self.status == "active" and tool_name in self.permissions

    def root(self, workspace: Path) -> Path:
        """Resolve the active grant again at use time, inside the workspace."""

        if self.status != "active":
            raise PermissionError("task grant is not active")
        workspace = Path(workspace).resolve()
        target = (workspace / self.subdirectory).resolve()
        if target == workspace or workspace not in target.parents:
            raise PermissionError("task grant is outside the workspace")
        return target


@dataclass(frozen=True)
class TaskContext:
    task: str
    plan: TaskPlan
    iteration: int
    feedback: str | None
    remaining_tool_calls: int
    grant: TaskGrant


@dataclass(frozen=True)
class ImplementationResult:
    summary: str
    tool_calls: int = 0

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("an implementation result requires a summary")
        if self.tool_calls < 0:
            raise ValueError("tool_calls cannot be negative")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class TestReport:
    checks: tuple[CheckResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))
        if not self.checks:
            raise ValueError("a test report requires at least one check")

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(
            f"{check.name}: {check.detail}" for check in self.checks if not check.passed
        )


@dataclass(frozen=True)
class Evaluation:
    decision: Literal["retry", "finalize"]
    feedback: str


@dataclass(frozen=True)
class TaskOutcome:
    status: Literal["completed", "stopped"]
    summary: str
    iterations: int
    tool_calls: int
    elapsed_seconds: float


@dataclass
class TaskState:
    task: str = ""
    subdirectory: str = ""
    grant: TaskGrant | None = None
    plan: TaskPlan | None = None
    iteration: int = 0
    tool_calls: int = 0
    implementation: ImplementationResult | None = None
    test_report: TestReport | None = None
    evaluation: Evaluation | None = None
    started_at: float | None = None
    stop_reason: str | None = None
    outcome: TaskOutcome | None = None


Planner = Callable[[str], Awaitable[TaskPlan]]
Implementer = Callable[[TaskContext], Awaitable[ImplementationResult]]
Tester = Callable[[TaskContext, ImplementationResult], Awaitable[TestReport]]


class TaskStageError(RuntimeError):
    """An expected planner/implementer failure that should stop honestly."""


def build_task_graph(
    planner: Planner,
    implementer: Implementer,
    tester: Tester,
    workspace: Path,
    budget: TaskBudget | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> CompiledStateGraph:
    """Compile the explicit task lifecycle with hard iteration/time/tool limits."""

    budget = budget or TaskBudget()
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError(f"task workspace {workspace} is not a directory")

    def elapsed(state: TaskState) -> float:
        return 0.0 if state.started_at is None else max(0.0, clock() - state.started_at)

    def time_left(state: TaskState) -> float:
        return max(0.0, budget.max_seconds - elapsed(state))

    async def bounded(awaitable: Awaitable[object], state: TaskState) -> object:
        remaining = time_left(state)
        if remaining <= 0:
            awaitable.close() if hasattr(awaitable, "close") else None
            raise TimeoutError
        return await asyncio.wait_for(awaitable, timeout=remaining)

    def context(state: TaskState, iteration: int | None = None) -> TaskContext:
        if state.plan is None:
            raise RuntimeError("task reached execution without a plan")
        if state.grant is None or state.grant.status != "active":
            raise RuntimeError("task reached execution without an active grant")
        return TaskContext(
            task=state.task,
            plan=state.plan,
            iteration=iteration if iteration is not None else state.iteration,
            feedback=state.evaluation.feedback if state.evaluation else None,
            remaining_tool_calls=budget.max_tool_calls - state.tool_calls,
            grant=state.grant,
        )

    def start_task(state: TaskState) -> dict[str, object]:
        task = state.task.strip()
        requested = state.subdirectory.strip()
        stop_reason = None
        scope = requested
        if not task:
            stop_reason = "task is empty"
        elif not requested:
            stop_reason = "task grant requires a sandbox subdirectory"
        else:
            try:
                target = (workspace / requested).resolve()
                scope = target.relative_to(workspace).as_posix()
            except (OSError, RuntimeError, ValueError):
                stop_reason = "task grant subdirectory is outside the workspace"
            else:
                if target == workspace:
                    stop_reason = "task grant must target a workspace subdirectory"
        return {
            "task": task,
            "subdirectory": scope,
            "grant": None if stop_reason else TaskGrant(scope),
            "stop_reason": stop_reason,
            "started_at": clock(),
        }

    def authorize(state: TaskState) -> dict[str, object]:
        if state.grant is None:
            raise RuntimeError("task reached authorization without a grant request")
        if checkpointer is None:
            return {
                "grant": TaskGrant(
                    state.grant.subdirectory,
                    status="revoked",
                    revoked_reason="no checkpoint available for explicit approval",
                ),
                "stop_reason": "task grant cannot be approved without a checkpoint",
            }
        approved = interrupt(
            {
                "kind": "task_grant",
                "subdirectory": state.grant.subdirectory,
                "permissions": list(state.grant.permissions),
                "plan": state.plan.summary if state.plan else None,
                "acceptance_criteria": (
                    list(state.plan.acceptance_criteria) if state.plan else []
                ),
            }
        )
        if approved is not True:
            return {
                "grant": TaskGrant(
                    state.grant.subdirectory,
                    status="revoked",
                    revoked_reason="user declined task grant",
                ),
                "stop_reason": "user declined task grant",
                "started_at": clock(),
            }
        return {
            "grant": TaskGrant(state.grant.subdirectory, status="active"),
            "started_at": clock(),
        }

    async def plan(state: TaskState) -> dict[str, object]:
        try:
            task_plan = await bounded(planner(state.task), state)
        except TimeoutError:
            return {"stop_reason": "time budget exhausted during planning"}
        except TaskStageError as error:
            return {"stop_reason": str(error)}
        return {"plan": task_plan}

    async def implement(state: TaskState) -> dict[str, object]:
        iteration = state.iteration + 1
        try:
            result = await bounded(implementer(context(state, iteration)), state)
        except TimeoutError:
            return {
                "iteration": iteration,
                "stop_reason": "time budget exhausted during implementation",
            }
        except TaskStageError as error:
            return {"iteration": iteration, "stop_reason": str(error)}
        if result.tool_calls > budget.max_tool_calls - state.tool_calls:
            return {
                "iteration": iteration,
                "stop_reason": "tool-call budget exceeded during implementation",
            }
        return {
            "iteration": iteration,
            "tool_calls": state.tool_calls + result.tool_calls,
            "implementation": result,
            "test_report": None,
        }

    async def test(state: TaskState) -> dict[str, object]:
        if state.implementation is None:
            raise RuntimeError("task reached testing without an implementation result")
        try:
            report = await bounded(tester(context(state), state.implementation), state)
        except TimeoutError:
            return {"stop_reason": "time budget exhausted during testing"}
        return {"test_report": report}

    def evaluate(state: TaskState) -> dict[str, object]:
        if state.test_report is None:
            raise RuntimeError("task reached evaluation without a test report")
        if state.test_report.passed:
            return {"evaluation": Evaluation("finalize", "all acceptance checks passed")}
        patch: dict[str, object] = {
            "evaluation": Evaluation("retry", "; ".join(state.test_report.failures))
        }
        if elapsed(state) >= budget.max_seconds:
            patch["stop_reason"] = "time budget exhausted with failing checks"
        elif state.iteration >= budget.max_iterations:
            patch["stop_reason"] = "iteration budget exhausted with failing checks"
        elif state.tool_calls >= budget.max_tool_calls:
            patch["stop_reason"] = "tool-call budget exhausted with failing checks"
        return patch

    def finalize(state: TaskState) -> dict[str, object]:
        completed = (
            state.stop_reason is None
            and state.test_report is not None
            and state.test_report.passed
        )
        if completed:
            summary = "all acceptance checks passed"
        else:
            summary = state.stop_reason or "iteration budget exhausted with failing checks"
        patch: dict[str, object] = {
            "outcome": TaskOutcome(
                status="completed" if completed else "stopped",
                summary=summary,
                iterations=state.iteration,
                tool_calls=state.tool_calls,
                elapsed_seconds=elapsed(state),
            )
        }
        if state.grant is not None and state.grant.status != "revoked":
            patch["grant"] = TaskGrant(
                state.grant.subdirectory,
                status="revoked",
                revoked_reason="task completed" if completed else summary,
            )
        return patch

    def after_task(state: TaskState) -> str:
        return "finalize" if state.stop_reason else "plan"

    def after_stage(state: TaskState) -> str:
        return "finalize" if state.stop_reason else "continue"

    def after_evaluate(state: TaskState) -> str:
        if state.stop_reason:
            return "finalize"
        if state.evaluation is None or state.evaluation.decision == "finalize":
            return "finalize"
        return "implement"

    graph = StateGraph(TaskState)
    graph.add_node("task", start_task)
    graph.add_node("authorize", authorize)
    graph.add_node("plan", plan)
    graph.add_node("implement", implement)
    graph.add_node("test", test)
    graph.add_node("evaluate", evaluate)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "task")
    graph.add_conditional_edges(
        "task", after_task, {"plan": "plan", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "plan", after_stage, {"continue": "authorize", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "authorize", after_stage, {"continue": "implement", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "implement", after_stage, {"continue": "test", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "test", after_stage, {"continue": "evaluate", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "evaluate", after_evaluate, {"implement": "implement", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
