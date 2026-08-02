"""Task-derived validation over real capability evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.task_graph import (
    ImplementationResult,
    TaskContext,
    TaskGrant,
    TaskPlan,
    TaskStageError,
    ValidationStep,
)
from app.agent.task_validator import (
    EVALUATION_RESPONSE_FORMAT,
    ModelTaskValidator,
    parse_evaluation,
)
from app.models import ContentPart
from app.tools import BROWSER_INSPECT, Capability, CapabilityRegistry, Tool
from tests.fakes import ScriptedBackend, calls, prompt_text, says


def evaluation(criterion: str, passed: bool = True, detail: str = "confirmed") -> str:
    return json.dumps(
        {
            "checks": [
                {"criterion": criterion, "passed": passed, "detail": detail}
            ]
        }
    )


def context(
    criterion: str,
    capability: str,
    root: str = "run",
    remaining: int = 5,
) -> TaskContext:
    return TaskContext(
        task="Change the observable result",
        plan=TaskPlan(
            "Change and validate it.",
            ("implement", "validate"),
            (criterion,),
            (
                ValidationStep(
                    criterion,
                    "Collect direct evidence for the requested outcome.",
                    (capability,),
                ),
            ),
        ),
        iteration=1,
        feedback=None,
        remaining_tool_calls=remaining,
        grant=TaskGrant(
            root,
            status="active",
            permissions=("filesystem.read", "filesystem.write", capability),
        ),
    )


async def test_filesystem_evidence_is_collected_then_evaluated(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "result.txt").write_text("blue", encoding="utf-8")
    criterion = "result.txt contains blue"
    backend = ScriptedBackend(
        calls("read_file", path="result.txt"),
        says("Evidence collected."),
        says(evaluation(criterion, detail="read_file returned blue")),
    )

    report = await ModelTaskValidator(backend, tmp_path)(
        context(criterion, "filesystem.read"),
        ImplementationResult("Changed result.txt", artifacts=("result.txt",)),
    )

    assert report.passed
    assert report.tool_calls == 1
    assert report.checks[0].detail == "read_file returned blue"
    assert backend.formats_seen[-1] == EVALUATION_RESPONSE_FORMAT
    evaluator_prompt = prompt_text(backend.requests[-1])
    assert "Evidence from read_file" in evaluator_prompt
    assert "blue" in evaluator_prompt
    assert "Changed result.txt" not in evaluator_prompt


async def test_model_can_choose_browser_evidence_and_return_its_screenshot(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "page.html").write_text("<p>blue</p>", encoding="utf-8")

    async def inspect_page(path: str):
        assert path == "page.html"
        return [
            ContentPart(kind="text", text='{"visible_text":"blue"}'),
            ContentPart(kind="image", data=b"screenshot", media_type="image/png"),
        ]

    registry = CapabilityRegistry(
        tmp_path,
        (
            Capability(
                BROWSER_INSPECT,
                lambda _root: [
                    Tool(
                        name="inspect_page",
                        description="render local page",
                        parameters={
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                        run=inspect_page,
                    )
                ],
            ),
        ),
    )
    criterion = "The rendered page is visibly blue"
    backend = ScriptedBackend(
        calls("inspect_page", path="page.html"),
        says("Evidence collected."),
        says(evaluation(criterion, detail="browser screenshot shows blue")),
    )

    report = await ModelTaskValidator(backend, tmp_path, registry)(
        context(criterion, BROWSER_INSPECT),
        ImplementationResult("Changed page.html", artifacts=("page.html",)),
    )

    assert report.passed
    assert report.tool_calls == 1
    assert len(report.evidence) == 1
    assert isinstance(report.evidence[0], ContentPart)
    assert report.evidence[0].data == b"screenshot"


async def test_validation_stops_when_model_does_not_collect_required_evidence(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    backend = ScriptedBackend(says("No tool needed."), says("Still no tool."))
    criterion = "result.txt contains blue"

    with pytest.raises(TaskStageError, match="no successful evidence"):
        await ModelTaskValidator(backend, tmp_path)(
            context(criterion, "filesystem.read"),
            ImplementationResult("Claimed completion", artifacts=("result.txt",)),
        )

    assert len(backend.requests) == 2
    assert "Evidence is still missing" in prompt_text(backend.requests[1])


def test_evaluator_must_cover_each_criterion_exactly() -> None:
    with pytest.raises(TaskStageError, match="cover every criterion exactly"):
        parse_evaluation(evaluation("different criterion"), ("expected criterion",))
