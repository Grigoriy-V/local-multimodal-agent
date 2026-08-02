"""The explicit bounded task lifecycle and its checkpointed write grant."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.agent.runtime import CHECKPOINT_TYPES
from app.agent.task_graph import (
    CheckResult,
    ImplementationResult,
    TaskBudget,
    TaskContext,
    TaskPlan,
    TaskStageError,
    TestReport as Report,
    ValidationStep,
    build_task_graph,
)


def plan() -> TaskPlan:
    return TaskPlan(
        summary="Create and verify one artifact.",
        steps=("implement", "test"),
        acceptance_criteria=("artifact passes its check",),
    )


async def planner(task: str) -> TaskPlan:
    return plan()


def passed() -> Report:
    return Report((CheckResult("artifact", True, "present"),))


def failed(detail: str = "missing") -> Report:
    return Report((CheckResult("artifact", False, detail),))


def config(thread_id: str = "task-1") -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def memory_saver() -> InMemorySaver:
    return InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    )


def graph_over(
    workspace: Path,
    implementer,
    tester,
    budget: TaskBudget | None = None,
    checkpointer: Any | None = None,
):
    return build_task_graph(
        planner,
        implementer,
        tester,
        workspace,
        budget,
        memory_saver() if checkpointer is None else checkpointer,
    )


async def approve(graph, task: str = "Create an artifact", subdirectory: str = "run"):
    run_config = config()
    await graph.ainvoke(
        {"task": task, "subdirectory": subdirectory},
        config=run_config,
    )
    snapshot = await graph.aget_state(run_config)
    [pending] = snapshot.tasks[0].interrupts
    assert pending.value == {
        "kind": "task_grant",
        "subdirectory": subdirectory,
        "permissions": ["filesystem.read", "filesystem.write"],
        "plan": "Create and verify one artifact.",
        "acceptance_criteria": ["artifact passes its check"],
    }
    return await graph.ainvoke(Command(resume=True), config=run_config)


async def test_the_named_route_finalizes_a_passing_task(tmp_path: Path) -> None:
    events: list[str] = []

    async def implement(context: TaskContext) -> ImplementationResult:
        assert context.grant.status == "active"
        assert context.grant.allows("filesystem.read")
        assert context.grant.allows("filesystem.write")
        assert context.grant.root(tmp_path) == tmp_path / "run"
        events.append(f"implement:{context.iteration}")
        return ImplementationResult("created artifact", tool_calls=2)

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        events.append(f"test:{context.iteration}")
        return passed()

    result = await approve(graph_over(tmp_path, implement, test))

    assert result["plan"].acceptance_criteria == ("artifact passes its check",)
    assert result["evaluation"].decision == "finalize"
    assert result["outcome"].status == "completed"
    assert result["outcome"].iterations == 1
    assert result["outcome"].tool_calls == 2
    assert result["grant"].status == "revoked"
    assert result["grant"].revoked_reason == "task completed"
    assert events == ["implement:1", "test:1"]


async def test_plan_validation_capability_is_approved_and_preserved(
    tmp_path: Path,
) -> None:
    async def browser_plan(_task: str) -> TaskPlan:
        criterion = "rendered result is correct"
        return TaskPlan(
            "Change and inspect it.",
            ("implement", "inspect"),
            (criterion,),
            (
                ValidationStep(
                    criterion,
                    "Render the artifact and inspect the screenshot.",
                    ("browser.inspect",),
                ),
            ),
        )

    async def implement(_context: TaskContext) -> ImplementationResult:
        return ImplementationResult("changed it")

    async def test(context: TaskContext, _result: ImplementationResult) -> Report:
        assert context.grant.allows("browser.inspect")
        return Report((CheckResult("rendered result is correct", True, "seen"),))

    graph = build_task_graph(
        browser_plan,
        implement,
        test,
        tmp_path,
        checkpointer=memory_saver(),
    )
    run_config = config("browser-grant")
    await graph.ainvoke(
        {"task": "Change the rendered result", "subdirectory": "run"},
        config=run_config,
    )
    snapshot = await graph.aget_state(run_config)
    [pending] = snapshot.tasks[0].interrupts

    assert pending.value["permissions"] == [
        "filesystem.read",
        "filesystem.write",
        "browser.inspect",
    ]

    result = await graph.ainvoke(Command(resume=True), config=run_config)
    assert result["outcome"].status == "completed"
    assert result["grant"].permissions[-1] == "browser.inspect"


async def test_validation_tool_calls_count_toward_the_task_budget(tmp_path: Path) -> None:
    async def implement(_context: TaskContext) -> ImplementationResult:
        return ImplementationResult("changed it", tool_calls=2)

    async def test(_context: TaskContext, _result: ImplementationResult) -> Report:
        return Report((CheckResult("artifact", True, "read"),), tool_calls=3)

    result = await approve(graph_over(tmp_path, implement, test))

    assert result["outcome"].tool_calls == 5


async def test_a_failed_report_returns_to_implementation_with_feedback(
    tmp_path: Path,
) -> None:
    contexts: list[TaskContext] = []

    async def implement(context: TaskContext) -> ImplementationResult:
        contexts.append(context)
        return ImplementationResult(f"attempt {context.iteration}", tool_calls=1)

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        return failed("first attempt failed") if context.iteration == 1 else passed()

    result = await approve(graph_over(tmp_path, implement, test))

    assert result["outcome"].status == "completed"
    assert result["outcome"].iterations == 2
    assert result["outcome"].tool_calls == 2
    assert contexts[0].feedback is None
    assert contexts[1].feedback == "artifact: first attempt failed"


async def test_iteration_budget_stops_a_persistently_failing_task(tmp_path: Path) -> None:
    async def implement(context: TaskContext) -> ImplementationResult:
        return ImplementationResult(
            "still incomplete", tool_calls=1, artifacts=("draft.html",)
        )

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        return failed()

    result = await approve(
        graph_over(
            tmp_path,
            implement,
            test,
            TaskBudget(max_iterations=2, max_tool_calls=10),
        )
    )

    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "iteration budget exhausted with failing checks"
    assert result["outcome"].iterations == 2
    assert result["outcome"].artifacts == ("draft.html",)
    assert result["outcome"].failures == ("artifact: missing",)
    assert result["grant"].status == "revoked"


async def test_tool_call_budget_stops_before_testing(tmp_path: Path) -> None:
    tested = False

    async def implement(context: TaskContext) -> ImplementationResult:
        assert context.remaining_tool_calls == 1
        return ImplementationResult("used too many calls", tool_calls=2)

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        nonlocal tested
        tested = True
        return passed()

    result = await approve(
        graph_over(
            tmp_path,
            implement,
            test,
            TaskBudget(max_iterations=3, max_tool_calls=1),
        )
    )

    assert tested is False
    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "tool-call budget exceeded during implementation"


async def test_unavailable_validation_stops_honestly_without_retry(tmp_path: Path) -> None:
    attempts = 0

    async def implement(context: TaskContext) -> ImplementationResult:
        nonlocal attempts
        attempts += 1
        return ImplementationResult("answered without an artifact")

    async def unavailable(context: TaskContext, result: ImplementationResult) -> Report:
        raise TaskStageError("validation unavailable: no evidence")

    result = await approve(graph_over(tmp_path, implement, unavailable))

    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "validation unavailable: no evidence"
    assert attempts == 1


async def test_a_failed_check_stops_when_the_tool_budget_is_spent(tmp_path: Path) -> None:
    async def implement(context: TaskContext) -> ImplementationResult:
        return ImplementationResult("used the final allowed call", tool_calls=1)

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        return failed("still broken")

    result = await approve(
        graph_over(
            tmp_path,
            implement,
            test,
            TaskBudget(max_iterations=3, max_tool_calls=1),
        )
    )

    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "tool-call budget exhausted with failing checks"
    assert result["outcome"].tool_calls == 1


async def test_time_budget_starts_after_approval_and_cancels_a_slow_stage(
    tmp_path: Path,
) -> None:
    async def slow_planner(task: str) -> TaskPlan:
        await asyncio.sleep(0.05)
        return plan()

    async def implement(context: TaskContext) -> ImplementationResult:
        raise AssertionError("implementation must not start")

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        raise AssertionError("testing must not start")

    graph = build_task_graph(
        slow_planner,
        implement,
        test,
        tmp_path,
        TaskBudget(max_seconds=0.005),
        memory_saver(),
    )
    result = await graph.ainvoke(
        {"task": "Create an artifact", "subdirectory": "run"},
        config=config(),
    )

    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "time budget exhausted during planning"


async def test_declining_revokes_the_grant_without_running_handlers(tmp_path: Path) -> None:
    async def forbidden(*args):
        raise AssertionError("handler must not run")

    graph = graph_over(tmp_path, forbidden, forbidden)
    run_config = config()
    await graph.ainvoke(
        {"task": "Create an artifact", "subdirectory": "run"}, config=run_config
    )

    result = await graph.ainvoke(Command(resume=False), config=run_config)

    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "user declined task grant"
    assert result["grant"].status == "revoked"
    assert result["grant"].revoked_reason == "user declined task grant"


@pytest.mark.parametrize("subdirectory", ["", "..", "../escape", "C:/Windows"])
async def test_invalid_grant_scopes_never_ask_or_run(
    tmp_path: Path, subdirectory: str
) -> None:
    async def forbidden(*args):
        raise AssertionError("handler must not run")

    graph = graph_over(tmp_path, forbidden, forbidden)
    run_config = config()
    result = await graph.ainvoke(
        {"task": "Create an artifact", "subdirectory": subdirectory},
        config=run_config,
    )

    assert result["outcome"].status == "stopped"
    assert (await graph.aget_state(run_config)).tasks == ()


async def test_workspace_root_is_a_valid_explicit_grant_scope(tmp_path: Path) -> None:
    async def forbidden(*args):
        raise AssertionError("execution must wait for approval")

    graph = graph_over(tmp_path, forbidden, forbidden)
    run_config = config()
    await graph.ainvoke(
        {"task": "Edit an existing workspace file", "subdirectory": "."},
        config=run_config,
    )

    snapshot = await graph.aget_state(run_config)
    assert snapshot.values["grant"].subdirectory == "."
    assert snapshot.tasks[0].interrupts[0].value["subdirectory"] == "."


async def test_without_a_checkpointer_the_grant_is_refused(tmp_path: Path) -> None:
    async def forbidden(*args):
        raise AssertionError("handler must not run")

    graph = build_task_graph(planner, forbidden, forbidden, tmp_path)
    result = await graph.ainvoke({"task": "Create an artifact", "subdirectory": "run"})

    assert result["outcome"].summary == "task grant cannot be approved without a checkpoint"
    assert result["grant"].status == "revoked"


async def test_an_empty_task_finalizes_without_requesting_a_grant(tmp_path: Path) -> None:
    async def forbidden(*args):
        raise AssertionError("handler must not run")

    graph = graph_over(tmp_path, forbidden, forbidden)
    run_config = config()
    result = await graph.ainvoke(
        {"task": "   ", "subdirectory": "run"}, config=run_config
    )

    assert result["outcome"].status == "stopped"
    assert result["outcome"].summary == "task is empty"
    assert result["outcome"].iterations == 0
    assert (await graph.aget_state(run_config)).tasks == ()


async def test_pending_grant_survives_a_sqlite_checkpoint_restart(tmp_path: Path) -> None:
    async def implement(context: TaskContext) -> ImplementationResult:
        assert context.grant.status == "active"
        return ImplementationResult("created", tool_calls=1)

    async def test(context: TaskContext, result: ImplementationResult) -> Report:
        return passed()

    checkpoint_path = tmp_path / "task-checkpoints.sqlite3"
    run_config = config("restart-task")
    serializer = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)

    first_connection = await aiosqlite.connect(str(checkpoint_path))
    first_saver = AsyncSqliteSaver(first_connection, serde=serializer)
    await first_saver.setup()
    first = graph_over(tmp_path, implement, test, checkpointer=first_saver)
    await first.ainvoke(
        {"task": "Create an artifact", "subdirectory": "restart-run"},
        config=run_config,
    )
    first_snapshot = await first.aget_state(run_config)
    assert first_snapshot.values["grant"].status == "pending"
    assert first_snapshot.tasks[0].interrupts[0].value["subdirectory"] == "restart-run"
    await first_connection.close()

    second_connection = await aiosqlite.connect(str(checkpoint_path))
    second_saver = AsyncSqliteSaver(second_connection, serde=serializer)
    await second_saver.setup()
    second = graph_over(tmp_path, implement, test, checkpointer=second_saver)
    restored = await second.aget_state(run_config)
    assert restored.values["grant"].status == "pending"

    result = await second.ainvoke(Command(resume=True), config=run_config)

    assert result["outcome"].status == "completed"
    assert result["grant"].status == "revoked"
    await second_connection.close()


@pytest.mark.parametrize(
    "budget",
    [
        TaskBudget(max_iterations=1),
        TaskBudget(max_tool_calls=0),
        TaskBudget(max_seconds=0.001),
    ],
)
def test_valid_budget_edges_are_accepted(budget: TaskBudget) -> None:
    assert budget.max_iterations >= 1


def test_the_graph_exposes_the_explicit_task_lifecycle(tmp_path: Path) -> None:
    async def forbidden(*args):
        raise AssertionError("graph is inspected, not run")

    graph = graph_over(tmp_path, forbidden, forbidden)

    assert {"task", "authorize", "plan", "implement", "test", "evaluate", "finalize"} <= set(
        graph.get_graph().nodes
    )
