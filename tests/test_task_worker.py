"""Model planning and real sandbox tool execution for the task graph."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from app.agent.runtime import CHECKPOINT_TYPES
from app.agent.task_graph import (
    CheckResult,
    ImplementationResult,
    TaskContext,
    TaskGrant,
    TaskPlan,
    TaskStageError,
    TestReport as Report,
)
from app.agent.task_worker import (
    PLAN_RESPONSE_FORMAT,
    ModelTaskWorker,
    build_model_task_graph,
    parse_plan,
)
from app.agent.web_verifier import WebVerifier
from app.models import Completion, ToolCall
from tests.fakes import ScriptedBackend, body, calls, says


def context(root: str = "run", remaining: int = 5, feedback: str | None = None) -> TaskContext:
    return TaskContext(
        task="Create game.html",
        plan=TaskPlan(
            "Create one file.",
            ("inspect", "create or repair"),
            ("game.html exists",),
        ),
        iteration=1,
        feedback=feedback,
        remaining_tool_calls=remaining,
        grant=TaskGrant(root, status="active"),
    )


def plan_json() -> str:
    return json.dumps(
        {
            "summary": "Create one game file.",
            "steps": ["inspect", "implement"],
            "acceptance_criteria": ["game.html exists"],
            "validation_strategy": [
                {
                    "criterion": "game.html exists",
                    "evidence": "Read game.html from the granted directory.",
                    "capabilities": ["filesystem.read"],
                }
            ],
        }
    )


async def test_planning_uses_structured_output(tmp_path: Path) -> None:
    backend = ScriptedBackend(says(plan_json()))
    worker = ModelTaskWorker(backend, tmp_path)

    result = await worker.plan("Create game.html")

    assert result.steps == ("inspect", "implement")
    assert result.validation_capabilities == ("filesystem.read",)
    assert result.validation_strategy[0].evidence.startswith("Read game.html")
    assert backend.formats_seen == [PLAN_RESPONSE_FORMAT]
    assert backend.tools_seen == [None]


@pytest.mark.parametrize("text", ["not json", "[]", '{"summary": "only"}'])
def test_invalid_plans_are_readable_stage_errors(text: str) -> None:
    with pytest.raises(TaskStageError, match="planning failed"):
        parse_plan(text)


async def test_write_file_creates_inside_the_granted_directory(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        calls("write_file", path="game.html", content="<html>game</html>"),
        says("Created game.html."),
    )
    worker = ModelTaskWorker(backend, tmp_path)

    result = await worker.implement(context())

    assert (tmp_path / "run" / "game.html").read_text(encoding="utf-8") == (
        "<html>game</html>"
    )
    assert result.tool_calls == 2  # automatic listing plus write_file
    assert result.artifacts == ("game.html",)
    assert body(backend.requests[1][-1]).startswith("created game.html")


async def test_the_implementer_is_told_which_tools_it_actually_has(
    tmp_path: Path,
) -> None:
    """It once told a user a tool was "not available in this environment".

    It had filesystem tools and no browser, which is true and not the user's
    business: validation runs afterwards with its own tools and produced the
    screenshot the same message said was impossible. So the prompt closes the
    list it does have, and forbids speaking for the delivery.
    """

    backend = ScriptedBackend(says("Created game.html."))
    worker = ModelTaskWorker(backend, tmp_path)

    await worker.implement(context())

    system = body(backend.requests[0][0])
    assert "Your tools are exactly: list_files, read_file, write_file, edit_file" in system
    assert "browser" not in system.split("Your tools are exactly")[1]
    assert "separate validation stage" in system


async def test_retry_reads_current_file_and_repairs_with_edit_file(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "game.html").write_text("score=0", encoding="utf-8")
    backend = ScriptedBackend(
        calls("read_file", path="game.html"),
        calls("edit_file", path="game.html", old_text="score=0", new_text="score=1"),
        says("Repaired the score."),
    )
    worker = ModelTaskWorker(backend, tmp_path)

    result = await worker.implement(context(feedback="score check failed"))

    assert (run / "game.html").read_text(encoding="utf-8") == "score=1"
    assert result.tool_calls == 3
    assert result.artifacts == ("game.html",)
    assert "game.html" in body(backend.requests[0][1])
    assert "score check failed" in body(backend.requests[0][1])
    assert body(backend.requests[1][-1]) == "score=0"
    assert body(backend.requests[2][-1]).startswith("edited game.html")


async def test_precise_tool_failure_returns_to_the_model(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "game.html").write_text("same same", encoding="utf-8")
    backend = ScriptedBackend(
        calls("edit_file", path="game.html", old_text="same", new_text="fixed"),
        says("The exact edit was ambiguous."),
    )
    worker = ModelTaskWorker(backend, tmp_path)

    await worker.implement(context())

    assert "found 2 matches" in body(backend.requests[1][-1])
    assert (run / "game.html").read_text(encoding="utf-8") == "same same"


async def test_repeated_grant_prefix_is_refused_and_repaired(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        calls(
            "write_file",
            path="tasks/run/snake.html",
            content="wrong nested target",
        ),
        calls("write_file", path="snake.html", content="correct target"),
        says("Created the file at the grant root."),
    )
    worker = ModelTaskWorker(backend, tmp_path)
    task_context = context(root="tasks/run")

    result = await worker.implement(task_context)

    assert "already relative" in body(backend.requests[1][-1])
    assert not (tmp_path / "tasks" / "run" / "tasks").exists()
    assert (tmp_path / "tasks" / "run" / "snake.html").read_text() == "correct target"
    assert result.artifacts == ("snake.html",)


async def test_calls_beyond_the_budget_do_not_run(tmp_path: Path) -> None:
    two_calls = Completion(
        text="",
        tool_calls=(
            ToolCall("a", "write_file", {"path": "first.txt", "content": "first"}),
            ToolCall("b", "write_file", {"path": "second.txt", "content": "second"}),
        ),
    )
    backend = ScriptedBackend(two_calls, says("Stopped at the budget."))
    worker = ModelTaskWorker(backend, tmp_path)

    result = await worker.implement(context(remaining=2))

    assert (tmp_path / "run" / "first.txt").is_file()
    assert not (tmp_path / "run" / "second.txt").exists()
    assert result.tool_calls == 2  # listing plus one executed model call
    assert "did not run" in body(backend.requests[1][-1])
    assert backend.tools_seen[-1] is None


async def test_inactive_grant_refuses_before_creating_a_directory(tmp_path: Path) -> None:
    worker = ModelTaskWorker(ScriptedBackend(), tmp_path)
    denied = context()
    denied = TaskContext(
        task=denied.task,
        plan=denied.plan,
        iteration=denied.iteration,
        feedback=None,
        remaining_tool_calls=5,
        grant=TaskGrant("run", status="revoked"),
    )

    with pytest.raises(TaskStageError, match="grant is not active"):
        await worker.implement(denied)

    assert not (tmp_path / "run").exists()


async def test_model_worker_is_wired_through_the_checkpointed_task_graph(
    tmp_path: Path,
) -> None:
    backend = ScriptedBackend(
        says(plan_json()),
        calls("write_file", path="game.html", content="<html>game</html>"),
        says("Created and checked game.html."),
    )

    async def tester(context: TaskContext, result: ImplementationResult) -> Report:
        target = context.grant.root(tmp_path) / "game.html"
        return Report((CheckResult("game exists", target.is_file(), str(target)),))

    saver = InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    )
    graph = build_model_task_graph(backend, tmp_path, tester, checkpointer=saver)
    run_config = {"configurable": {"thread_id": "integrated-task"}}
    await graph.ainvoke(
        {"task": "Create game.html", "subdirectory": "snake"},
        config=run_config,
    )

    result = await graph.ainvoke(Command(resume=True), config=run_config)

    assert result["outcome"].status == "completed"
    assert result["outcome"].tool_calls == 2
    assert result["grant"].status == "revoked"
    assert (tmp_path / "snake" / "game.html").is_file()


async def test_verifier_feedback_drives_a_model_repair_attempt(tmp_path: Path) -> None:
    draft_script = """const canvas = document.getElementById('game');
const context = canvas.getContext('2d');"""
    repaired_script = """const canvas = document.getElementById('game');
const context = canvas.getContext('2d');
document.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft') return 'left';
  if (event.key === 'ArrowUp') return 'up';
  if (event.key === 'ArrowRight') return 'right';
  if (event.key === 'ArrowDown') return 'down';
});
function loop() { context.fillRect(0, 0, 10, 10); requestAnimationFrame(loop); }
requestAnimationFrame(loop);"""
    draft = (
        "<!DOCTYPE html><html><head><title>Snake</title></head><body>"
        f"<canvas id='game'></canvas><script>{draft_script}</script></body></html>"
    )
    backend = ScriptedBackend(
        says(plan_json()),
        calls("write_file", path="snake.html", content=draft),
        says("Created a first draft."),
        calls("read_file", path="snake.html"),
        calls(
            "edit_file",
            path="snake.html",
            old_text=draft_script,
            new_text=repaired_script,
        ),
        says("Repaired every verifier failure."),
    )

    def syntax_ok(_source: str) -> CheckResult:
        return CheckResult("javascript_syntax", True, "test parser accepted JavaScript")

    saver = InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    )
    graph = build_model_task_graph(
        backend,
        tmp_path,
        WebVerifier(tmp_path, syntax_checker=syntax_ok),
        checkpointer=saver,
    )
    run_config = {"configurable": {"thread_id": "repair-task"}}
    await graph.ainvoke(
        {"task": "Create a working Snake", "subdirectory": "run"},
        config=run_config,
    )

    result = await graph.ainvoke(Command(resume=True), config=run_config)

    retry_prompt = body(backend.requests[3][1])
    assert "game_controls: missing signals:" in retry_prompt
    assert result["outcome"].status == "completed"
    assert result["outcome"].iterations == 2
    assert result["outcome"].tool_calls == 5
    assert result["outcome"].artifacts == ("snake.html",)
    assert result["outcome"].failures == ()
    assert "keydown" in (tmp_path / "run" / "snake.html").read_text(encoding="utf-8")
