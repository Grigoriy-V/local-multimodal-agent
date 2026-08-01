"""Behavioral browser verification inside the bounded task harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from app.agent.browser_verifier import (
    BrowserProbeResult,
    BrowserVerifier,
    LayeredWebVerifier,
    find_chromium_browser,
)
from app.agent.runtime import CHECKPOINT_TYPES
from app.agent.task_graph import (
    ImplementationResult,
    TaskContext,
    TaskGrant,
    TaskPlan,
    build_task_graph,
)


def context(permissions: tuple[str, ...] | None = None) -> TaskContext:
    grant = (
        TaskGrant("run", status="active")
        if permissions is None
        else TaskGrant("run", status="active", permissions=permissions)
    )
    return TaskContext(
        task="Create Snake",
        plan=TaskPlan(
            "Create and verify Snake.",
            ("create", "browser test"),
            ("browser checks pass",),
        ),
        iteration=1,
        feedback=None,
        remaining_tool_calls=5,
        grant=grant,
    )


def game_html() -> str:
    return """<!DOCTYPE html><html><head><title>Snake</title></head><body>
<canvas id="game" width="200" height="200"></canvas>
<script>
const canvas = document.getElementById('game');
const context = canvas.getContext('2d');
let moving = false;
let x = 10;
document.addEventListener('keydown', event => {
  if (['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(event.key)) moving = true;
});
function frame() {
  context.fillStyle = 'black';
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = 'lime';
  context.fillRect(x, 80, 20, 20);
  if (moving) x = (x + 5) % canvas.width;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
</script></body></html>"""


async def passing_probe(html: Path, preview: Path, browser: Path) -> BrowserProbeResult:
    assert html.name == "snake.html"
    assert browser.name == "browser.exe"
    preview.write_bytes(b"preview")
    return BrowserProbeResult(
        loaded=True,
        console_errors=(),
        canvas_present=True,
        canvas_rendered=True,
        moved=True,
        keyboard_received=True,
        preview_written=True,
        detail="test browser",
    )


async def test_passing_probe_returns_checks_and_preview_artifact(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "snake.html").write_text(game_html(), encoding="utf-8")
    browser = tmp_path / "browser.exe"
    browser.write_bytes(b"fake")

    report = await BrowserVerifier(tmp_path, browser=browser, probe=passing_probe)(
        context(), ImplementationResult("created Snake")
    )

    assert report.passed
    assert report.artifacts == ("snake-preview.png",)
    assert [check.name for check in report.checks] == [
        "browser_load",
        "browser_console",
        "canvas_rendering",
        "time_movement",
        "keyboard_input",
        "preview",
    ]


async def test_browser_failures_are_structured_for_the_retry_prompt(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "snake.html").write_text(game_html(), encoding="utf-8")
    browser = tmp_path / "browser.exe"
    browser.write_bytes(b"fake")

    async def failing_probe(
        _html: Path, _preview: Path, _browser: Path
    ) -> BrowserProbeResult:
        return BrowserProbeResult(
            loaded=True,
            console_errors=("ReferenceError: score is not defined",),
            canvas_present=True,
            canvas_rendered=False,
            moved=False,
            keyboard_received=True,
            preview_written=False,
        )

    report = await BrowserVerifier(tmp_path, browser=browser, probe=failing_probe)(
        context(), ImplementationResult("created broken Snake")
    )

    assert not report.passed
    assert "browser_console: ReferenceError" in "; ".join(report.failures)
    assert "canvas_rendering:" in "; ".join(report.failures)
    assert "time_movement:" in "; ".join(report.failures)


async def test_browser_verification_requires_explicit_grant_permission(
    tmp_path: Path,
) -> None:
    (tmp_path / "run").mkdir()
    verifier = BrowserVerifier(tmp_path, browser=tmp_path / "missing.exe")

    with pytest.raises(PermissionError, match="does not allow"):
        await verifier(
            context(("write_file", "edit_file")),
            ImplementationResult("created Snake"),
        )


async def test_preview_artifact_reaches_the_final_task_outcome(tmp_path: Path) -> None:
    browser = tmp_path / "browser.exe"
    browser.write_bytes(b"fake")

    async def planner(_task: str) -> TaskPlan:
        return context().plan

    async def implement(task_context: TaskContext) -> ImplementationResult:
        root = task_context.grant.root(tmp_path)
        root.mkdir()
        (root / "snake.html").write_text(game_html(), encoding="utf-8")
        return ImplementationResult("created Snake", artifacts=("snake.html",))

    saver = InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    )
    graph = build_task_graph(
        planner,
        implement,
        BrowserVerifier(tmp_path, browser=browser, probe=passing_probe),
        tmp_path,
        checkpointer=saver,
    )
    run_config = {"configurable": {"thread_id": "browser-preview"}}
    await graph.ainvoke(
        {"task": "Create Snake", "subdirectory": "run"}, config=run_config
    )

    result = await graph.ainvoke(Command(resume=True), config=run_config)

    assert result["outcome"].status == "completed"
    assert result["outcome"].artifacts == ("snake.html", "snake-preview.png")


async def test_layered_verifier_runs_static_gate_before_browser(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "snake.html").write_text(game_html(), encoding="utf-8")
    browser = tmp_path / "browser.exe"
    browser.write_bytes(b"fake")

    report = await LayeredWebVerifier(
        tmp_path, browser=browser, browser_probe=passing_probe
    )(context(), ImplementationResult("created Snake"))

    assert report.passed
    assert len(report.checks) == 10
    assert report.artifacts == ("snake-preview.png",)


@pytest.mark.skipif(
    find_chromium_browser() is None, reason="Chrome/Edge is unavailable"
)
async def test_real_browser_renders_moves_and_receives_keyboard(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "snake.html").write_text(game_html(), encoding="utf-8")

    report = await BrowserVerifier(tmp_path)(
        context(), ImplementationResult("created moving game")
    )

    assert report.passed, report.failures
    assert (run / "snake-preview.png").stat().st_size > 0
