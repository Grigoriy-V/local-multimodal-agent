"""Deterministic verification of the self-contained Snake artifact."""

from __future__ import annotations

import shutil
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
    build_task_graph,
)
from app.agent.web_verifier import WebVerifier, node_javascript_syntax


def valid_game() -> str:
    return """<!DOCTYPE html>
<html><head><title>Snake</title></head><body>
<canvas id="game" width="400" height="400"></canvas>
<script>
const canvas = document.getElementById('game');
const context = canvas.getContext('2d');
document.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft') return 'left';
  if (event.key === 'ArrowUp') return 'up';
  if (event.key === 'ArrowRight') return 'right';
  if (event.key === 'ArrowDown') return 'down';
});
function loop() { context.fillRect(0, 0, 10, 10); requestAnimationFrame(loop); }
requestAnimationFrame(loop);
</script>
</body></html>"""


def accepted_syntax(_source: str) -> CheckResult:
    return CheckResult("javascript_syntax", True, "test parser accepted JavaScript")


def context(workspace: Path, subdirectory: str = "run") -> TaskContext:
    return TaskContext(
        task="Create Snake",
        plan=TaskPlan(
            "Create and verify Snake.",
            ("create HTML", "verify HTML"),
            ("deterministic checks pass",),
        ),
        iteration=1,
        feedback=None,
        remaining_tool_calls=5,
        grant=TaskGrant(subdirectory, status="active"),
    )


async def test_valid_standalone_game_passes_all_four_checks(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "snake.html").write_text(valid_game(), encoding="utf-8")

    report = await WebVerifier(tmp_path, syntax_checker=accepted_syntax)(
        context(tmp_path), ImplementationResult("created snake.html")
    )

    assert report.passed
    assert [check.name for check in report.checks] == [
        "file_presence",
        "html_structure",
        "javascript_syntax",
        "game_controls",
    ]


async def test_recursive_timeout_is_accepted_as_a_game_loop(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    document = valid_game().replace(
        "function loop() { context.fillRect(0, 0, 10, 10); requestAnimationFrame(loop); }\n"
        "requestAnimationFrame(loop);",
        "function loop() { context.fillRect(0, 0, 10, 10); setTimeout(loop, 100); }\n"
        "setTimeout(loop, 100);",
    )
    (run / "snake.html").write_text(document, encoding="utf-8")

    report = await WebVerifier(tmp_path, syntax_checker=accepted_syntax)(
        context(tmp_path), ImplementationResult("created snake.html")
    )

    assert report.passed


async def test_missing_file_returns_a_complete_failed_report(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()

    report = await WebVerifier(tmp_path, syntax_checker=accepted_syntax)(
        context(tmp_path), ImplementationResult("claimed success")
    )

    assert not report.passed
    assert len(report.checks) == 4
    assert report.failures[0] == (
        "file_presence: snake.html does not exist inside the task grant"
    )


async def test_malformed_document_and_missing_controls_are_explained(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "snake.html").write_text(
        "<!DOCTYPE html><html><head></head><body><canvas></body></html>",
        encoding="utf-8",
    )

    report = await WebVerifier(tmp_path, syntax_checker=accepted_syntax)(
        context(tmp_path), ImplementationResult("created malformed HTML")
    )

    checks = {check.name: check for check in report.checks}
    assert not checks["html_structure"].passed
    assert "inline <script>" in checks["html_structure"].detail
    assert "expected </canvas>" in checks["html_structure"].detail
    assert not checks["javascript_syntax"].passed
    assert checks["game_controls"].detail.startswith("missing signals:")


async def test_external_script_is_not_accepted_as_a_self_contained_artifact(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    document = valid_game().replace(
        "</body>", '<script src="https://example.invalid/game.js"></script></body>'
    )
    (run / "snake.html").write_text(document, encoding="utf-8")

    report = await WebVerifier(tmp_path, syntax_checker=accepted_syntax)(
        context(tmp_path), ImplementationResult("created dependent HTML")
    )

    assert not report.passed
    assert "external <script src> is not allowed" in report.failures[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_node_parser_accepts_valid_and_rejects_invalid_javascript() -> None:
    accepted = node_javascript_syntax("const answer = 42;")
    rejected = node_javascript_syntax("const answer = ;")

    assert accepted.passed
    assert not rejected.passed
    assert "rejected" in rejected.detail


@pytest.mark.parametrize(
    "target", ["", "../snake.html", str(Path(Path.cwd().anchor) / "x")]
)
def test_target_must_stay_relative_to_the_grant(tmp_path: Path, target: str) -> None:
    with pytest.raises(ValueError, match="relative path"):
        WebVerifier(tmp_path, target=target)


async def test_structured_report_reaches_graph_evaluation(tmp_path: Path) -> None:
    async def planner(_task: str) -> TaskPlan:
        return context(tmp_path).plan

    async def implement(task_context: TaskContext) -> ImplementationResult:
        root = task_context.grant.root(tmp_path)
        root.mkdir()
        (root / "snake.html").write_text(valid_game(), encoding="utf-8")
        return ImplementationResult("created snake.html", tool_calls=1)

    saver = InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    )
    graph = build_task_graph(
        planner,
        implement,
        WebVerifier(tmp_path, syntax_checker=accepted_syntax),
        tmp_path,
        checkpointer=saver,
    )
    run_config = {"configurable": {"thread_id": "web-verifier"}}
    await graph.ainvoke(
        {"task": "Create Snake", "subdirectory": "run"}, config=run_config
    )

    result = await graph.ainvoke(Command(resume=True), config=run_config)

    assert result["test_report"].passed
    assert result["evaluation"].decision == "finalize"
    assert result["outcome"].status == "completed"
