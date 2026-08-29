"""What an autonomous task records about itself.

The conversational graph was measured first; the bounded task path is where the
expensive turns actually go, and it used to report one number — how many tool
calls were spent — for a run that could have done anything. These tests drive
the real runtime, worker and validator and assert on the stored trace.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.agent.task_graph import TaskBudget, TaskGrant, TaskPlan, TaskContext
from app.agent.task_runtime import TaskRuntime
from app.agent.task_worker import ModelTaskWorker
from app.models import Completion, ToolCall
from app.telemetry import Telemetry, TraceEvent, TurnRun, TurnTrace
from app.telemetry.sqlite import SqliteTelemetry
from tests.fakes import ScriptedBackend, calls, says

CRITERION = "result.txt contains STEP-4"


@pytest.fixture
def telemetry(tmp_path: Path) -> Iterator[Telemetry]:
    opened = Telemetry(SqliteTelemetry(tmp_path / "telemetry.sqlite3"))
    yield opened
    opened.close()


@pytest.fixture
def trace(telemetry: Telemetry) -> TurnTrace:
    return telemetry.start(TurnRun(run_id="run-1", user_id="user-alice"))


def events(telemetry: Telemetry) -> list[TraceEvent]:
    trace = telemetry.trace("run-1")
    trace.flush()
    store = telemetry.store
    assert store is not None
    return store.events("run-1")


def named(records: list[TraceEvent], *types: str) -> list[TraceEvent]:
    return [record for record in records if record.type in types]


def plan_json(criterion: str = CRITERION) -> str:
    return json.dumps(
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


def evaluation_json(criterion: str = CRITERION) -> str:
    return json.dumps(
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


def workspace(tmp_path: Path) -> Path:
    made = tmp_path / "workspace"
    made.mkdir(exist_ok=True)
    return made


async def run_task(tmp_path: Path, backend: ScriptedBackend, trace: TurnTrace):
    runtime = TaskRuntime(backend, workspace(tmp_path), tmp_path / "tasks.sqlite3")
    try:
        await runtime.start("chat", "Create result.txt with STEP-4", trace=trace)
        await runtime.resume("chat", True, trace)
        return await runtime.view("chat")
    finally:
        await runtime.aclose()


def whole_task() -> ScriptedBackend:
    return ScriptedBackend(
        says(plan_json()),
        calls("write_file", path="result.txt", content="STEP-4"),
        says("Created result.txt."),
        calls("read_file", path="result.txt"),
        says("Evidence collected."),
        says(evaluation_json()),
    )


# --- stages ------------------------------------------------------------------


async def test_every_stage_of_a_task_is_bracketed(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    view = await run_task(tmp_path, whole_task(), trace)

    assert view.outcome is not None and view.outcome.status == "completed"
    types = [record.type for record in events(telemetry)]
    for stage in ("plan", "implement", "validate"):
        assert types.count(f"task_{stage}_started") == 1
        assert types.count(f"task_{stage}_finished") == 1


async def test_everything_a_stage_spends_says_which_stage_spent_it(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    """A trace of twenty calls is only readable if each one is placed."""

    await run_task(tmp_path, whole_task(), trace)

    stages = {
        record.data.get("tool"): record.data.get("stage")
        for record in named(events(telemetry), "tool_started")
    }
    assert stages == {
        "list_files": "implement",
        "write_file": "implement",
        "read_file": "validate",
    }
    models = {record.data.get("stage") for record in named(events(telemetry), "model_started")}
    assert models == {"plan", "implement", "validate"}


async def test_an_attempt_number_is_recorded_with_the_work_it_did(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    await run_task(tmp_path, whole_task(), trace)

    written = next(
        record
        for record in named(events(telemetry), "tool_started")
        if record.data.get("tool") == "write_file"
    )
    assert written.data["iteration"] == 1


# --- tool calls --------------------------------------------------------------


async def test_each_executed_tool_has_one_start_and_one_terminal_event(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    await run_task(tmp_path, whole_task(), trace)

    records = events(telemetry)
    started = named(records, "tool_started")
    terminal = named(records, "tool_finished", "tool_failed")
    assert len(started) == 3
    assert [record.data["call_index"] for record in started] == [1, 2, 3]
    assert [record.data["call_index"] for record in terminal] == [1, 2, 3]
    assert trace.run.tool_calls == 3


async def test_the_turn_counts_each_task_tool_call_exactly_once(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    """The task's own total must not be added on top of the measured calls.

    Both numbers exist and mean different things: the graph counts budget spent,
    including calls it refused, while the trace counts calls that ran. Adding
    them was how the old summary was produced, and doing it now would double
    every autonomous turn in the baseline.
    """

    view = await run_task(tmp_path, whole_task(), trace)

    assert view.outcome is not None
    assert view.outcome.tool_calls == 3  # budget spent
    assert trace.run.tool_calls == 3  # calls executed


async def test_a_tool_that_fails_is_not_recorded_as_a_success(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    backend = ScriptedBackend(
        says(plan_json()),
        calls("read_file", path="absent.txt"),
        says("Nothing there."),
        default=says(evaluation_json()),
    )

    await run_task(tmp_path, backend, trace)

    failed = named(events(telemetry), "tool_failed")
    assert [record.data["tool"] for record in failed] == ["read_file"]
    assert failed[0].data["status"] == "failed"


async def test_the_path_is_recorded_and_the_content_is_not(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    """What makes twenty calls distinguishable, and nothing beyond it."""

    await run_task(tmp_path, whole_task(), trace)

    records = events(telemetry)
    paths = {record.data.get("path") for record in named(records, "tool_started")}
    assert paths == {"result.txt", None}
    written = json.dumps([record.data for record in records])
    assert "STEP-4" not in written
    assert "Evidence collected" not in written


# --- the budget --------------------------------------------------------------


def two_writes() -> Completion:
    return Completion(
        text="",
        tool_calls=(
            ToolCall(id="c1", name="write_file", arguments={"path": "a.txt", "content": "a"}),
            ToolCall(id="c2", name="write_file", arguments={"path": "b.txt", "content": "b"}),
        ),
        finish_reason="tool_calls",
    )


async def test_calls_beyond_the_budget_are_recorded_as_skipped_not_spent(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    """The exhaustion the failed PDF task hit, and could not explain.

    A call that never ran is not a call the turn spent — but a trace that omits
    it makes a task that stopped for no visible reason.
    """

    runtime = TaskRuntime(
        ScriptedBackend(
            says(plan_json()),
            two_writes(),
            says("Ran out."),
            default=says(evaluation_json()),
        ),
        workspace(tmp_path),
        tmp_path / "tasks.sqlite3",
        budget=TaskBudget(max_tool_calls=2),
    )
    try:
        await runtime.start("chat", "Create two files", trace=trace)
        await runtime.resume("chat", True, trace)
    finally:
        await runtime.aclose()

    records = events(telemetry)
    skipped = named(records, "tool_skipped")
    assert [record.data["tool"] for record in skipped] == ["write_file"]
    assert skipped[0].data["status"] == "budget_exhausted"
    assert skipped[0].data["path"] == "b.txt"
    # list_files plus the one write that fitted.
    assert trace.run.tool_calls == 2


# --- refusals ----------------------------------------------------------------


def context(root: str = "run") -> TaskContext:
    return TaskContext(
        task="Create game.html",
        plan=TaskPlan("Create one file.", ("create",), ("game.html exists",)),
        iteration=1,
        feedback=None,
        remaining_tool_calls=5,
        grant=TaskGrant(root, status="active"),
    )


async def test_a_call_refused_before_it_ran_is_visible_and_uncounted(
    tmp_path: Path, telemetry: Telemetry, trace: TurnTrace
) -> None:
    """A rejected path spends the budget without doing anything.

    It is recorded with its own status rather than as a failed execution,
    because "the model kept prefixing the grant directory" and "the tool broke"
    are different diagnoses.
    """

    backend = ScriptedBackend(
        calls("write_file", path="run/game.html", content="<html></html>"),
        says("Done."),
    )
    worker = ModelTaskWorker(backend, workspace(tmp_path), lambda: trace)

    await worker.implement(context())

    records = events(telemetry)
    rejected = [
        record for record in named(records, "tool_failed")
        if record.data.get("status") == "rejected"
    ]
    assert [record.data["tool"] for record in rejected] == ["write_file"]
    assert rejected[0].data["path"] == "run/game.html"
    executed = named(records, "tool_started")
    assert [record.data["tool"] for record in executed] == ["list_files"]
    assert trace.run.tool_calls == 1  # the automatic listing only


# --- isolation ---------------------------------------------------------------


async def test_an_unmeasured_task_runs_exactly_the_same(tmp_path: Path) -> None:
    """Chainlit, the tests and a disabled deployment take this path."""

    runtime = TaskRuntime(whole_task(), workspace(tmp_path), tmp_path / "tasks.sqlite3")
    try:
        await runtime.start("chat", "Create result.txt with STEP-4")
        await runtime.resume("chat", True)
        view = await runtime.view("chat")
    finally:
        await runtime.aclose()

    assert view.outcome is not None
    assert view.outcome.status == "completed"
