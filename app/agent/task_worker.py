"""Gemma/model adapter for the bounded task graph.

The worker has no provider imports and no UI assumptions. It plans through the
`ModelBackend`, then implements against filesystem tools rooted at the active
task grant. Test/evaluation remain graph concerns and receive real evidence
through the separate task validator.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import assistant_message
from app.agent.task_graph import (
    ImplementationResult,
    TaskBudget,
    TaskContext,
    TaskPlan,
    TaskStageError,
    Tester,
    ValidationStep,
    build_task_graph,
)
from app.models import BackendError, ContentPart, Message, ModelBackend, ToolCall
from app.tools import (
    BROWSER_INSPECT,
    CapabilityRegistry,
    FILESYSTEM_READ,
    FILESYSTEM_WRITE,
)

VALIDATION_CAPABILITIES = (FILESYSTEM_READ, BROWSER_INSPECT)

PLAN_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "task_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "validation_strategy": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {"type": "string"},
                            "evidence": {"type": "string"},
                            "capabilities": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": list(VALIDATION_CAPABILITIES),
                                },
                            },
                        },
                        "required": ["criterion", "evidence", "capabilities"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "summary",
                "steps",
                "acceptance_criteria",
                "validation_strategy",
            ],
            "additionalProperties": False,
        },
    },
}

PLANNER_SYSTEM_PROMPT = (
    "Create a concise implementation plan for the task. Return only the requested "
    "structured object. Store observable steps and acceptance criteria, never private "
    "reasoning or chain-of-thought. Define exactly one validation_strategy item for "
    "each acceptance criterion, copying the criterion text exactly. The model chooses "
    "the minimum evidence capabilities required by the criterion: filesystem.read can "
    "list and read sandbox files; browser.inspect can render a self-contained local HTML "
    "file and return page facts, console errors and a screenshot. Use browser.inspect only "
    "when rendered appearance or browser behavior is material. Evidence instructions must "
    "describe what to observe, not claim that it already passed."
)

IMPLEMENTER_SYSTEM_PROMPT = (
    "Implement the task inside the provided sandbox. Inspect files instead of guessing. "
    "Use write_file to create or fully replace a file, edit_file for an exact unique "
    "repair, and read_file after a failure or whenever current contents matter. Tool paths "
    "may be relative to the granted directory or absolute when they resolve inside it. "
    "Choose paths from the task and do not guess the location of an ambiguous bare filename. "
    "Tool results and test feedback are "
    "authoritative; repair every reported failure that is within the task. When the "
    "implementation attempt is complete, answer with a concise factual summary."
)


def text_message(role: str, text: str) -> Message:
    return Message(role=role, content=[ContentPart(kind="text", text=text)])


def parse_plan(text: str) -> TaskPlan:
    """Parse the structured planner response without accepting hidden prose."""

    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as error:
        raise TaskStageError(
            f"planning failed: model returned invalid JSON ({error.msg})"
        ) from error
    if not isinstance(payload, dict):
        raise TaskStageError("planning failed: model plan is not an object")
    expected = {
        "summary",
        "steps",
        "acceptance_criteria",
        "validation_strategy",
    }
    if set(payload) != expected:
        raise TaskStageError("planning failed: model plan has missing or unexpected fields")
    if not isinstance(payload["summary"], str):
        raise TaskStageError("planning failed: plan summary is not text")
    for field in ("steps", "acceptance_criteria"):
        if not isinstance(payload[field], list) or not all(
            isinstance(item, str) for item in payload[field]
        ):
            raise TaskStageError(f"planning failed: {field} must be a list of text")
    if not isinstance(payload["validation_strategy"], list):
        raise TaskStageError("planning failed: validation_strategy must be a list")
    strategy: list[ValidationStep] = []
    for item in payload["validation_strategy"]:
        if not isinstance(item, dict) or set(item) != {
            "criterion",
            "evidence",
            "capabilities",
        }:
            raise TaskStageError("planning failed: validation strategy item is invalid")
        if not isinstance(item["criterion"], str) or not isinstance(item["evidence"], str):
            raise TaskStageError("planning failed: validation strategy text is invalid")
        capabilities = item["capabilities"]
        if not isinstance(capabilities, list) or not all(
            isinstance(capability, str) and capability in VALIDATION_CAPABILITIES
            for capability in capabilities
        ):
            raise TaskStageError("planning failed: validation capabilities are invalid")
        try:
            strategy.append(
                ValidationStep(
                    criterion=item["criterion"],
                    evidence=item["evidence"],
                    capabilities=tuple(capabilities),
                )
            )
        except ValueError as error:
            raise TaskStageError(f"planning failed: {error}") from error
    try:
        return TaskPlan(
            summary=payload["summary"],
            steps=tuple(payload["steps"]),
            acceptance_criteria=tuple(payload["acceptance_criteria"]),
            validation_strategy=tuple(strategy),
        )
    except ValueError as error:
        raise TaskStageError(f"planning failed: {error}") from error


def implementation_prompt(context: TaskContext, listing: str) -> str:
    steps = "\n".join(f"- {step}" for step in context.plan.steps)
    criteria = "\n".join(f"- {item}" for item in context.plan.acceptance_criteria)
    validation = "\n".join(
        f"- {step.criterion}: {step.evidence} "
        f"(capabilities: {', '.join(step.capabilities)})"
        for step in context.plan.validation_strategy
    )
    feedback = context.feedback or "none; this is the first attempt"
    return (
        f"Task: {context.task}\n"
        f"Granted directory: {context.grant.subdirectory}\n"
        "Tool path rule: relative paths resolve from the granted directory; absolute paths "
        "are allowed only when they resolve inside it.\n"
        f"Attempt: {context.iteration}\n"
        f"Plan:\n{steps}\n"
        f"Acceptance criteria:\n{criteria}\n"
        f"Validation strategy:\n{validation}\n"
        f"Previous test feedback: {feedback}\n"
        f"Current directory listing:\n{listing}\n"
        f"Tool calls remaining after this inspection: {context.remaining_tool_calls - 1}"
    )


def repeats_grant_directory(path: str, subdirectory: str) -> bool:
    """Catch a common rooted-tool mistake before it creates a nested duplicate."""

    requested = PurePosixPath(path.replace("\\", "/")).parts
    granted = PurePosixPath(subdirectory.replace("\\", "/")).parts
    return bool(granted) and len(requested) > len(granted) and requested[: len(granted)] == granted


class ModelTaskWorker:
    """Plan and implement task attempts through one model backend."""

    def __init__(self, backend: ModelBackend, workspace: Path) -> None:
        self.backend = backend
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"task workspace {self.workspace} is not a directory")

    async def plan(self, task: str) -> TaskPlan:
        messages = [
            text_message("system", PLANNER_SYSTEM_PROMPT),
            text_message("user", task),
        ]
        try:
            completion = await self.backend.invoke(
                messages, response_format=PLAN_RESPONSE_FORMAT
            )
        except BackendError as error:
            raise TaskStageError(f"planning failed: {error}") from error
        return parse_plan(completion.text)

    async def implement(self, context: TaskContext) -> ImplementationResult:
        if not context.grant.allows(FILESYSTEM_WRITE):
            raise TaskStageError("implementation refused: task grant is not active")
        if context.remaining_tool_calls < 1:
            raise TaskStageError("implementation stopped: tool-call budget is exhausted")

        root = context.grant.root(self.workspace)
        root.mkdir(parents=True, exist_ok=True)
        registry = CapabilityRegistry(root)
        capabilities = tuple(
            capability
            for capability in (FILESYSTEM_READ, FILESYSTEM_WRITE)
            if context.grant.allows(capability)
        )
        toolbox = registry.toolbox(registry.grant(capabilities=capabilities))
        inspection = toolbox.run(ToolCall("task_inspect", "list_files", {}))
        listing = inspection.content[0].text or "(empty)"
        used = 1
        artifacts: set[str] = set()
        messages = [
            text_message("system", IMPLEMENTER_SYSTEM_PROMPT),
            text_message("user", implementation_prompt(context, listing)),
        ]

        while True:
            remaining = context.remaining_tool_calls - used
            schemas = toolbox.schemas() if remaining > 0 else None
            try:
                completion = await self.backend.invoke(messages, tools=schemas)
            except BackendError as error:
                raise TaskStageError(f"implementation failed: {error}") from error
            messages.append(assistant_message(completion))
            if not completion.tool_calls:
                summary = completion.text.strip() or "model returned no implementation summary"
                return ImplementationResult(
                    summary, tool_calls=used, artifacts=tuple(sorted(artifacts))
                )

            runnable = completion.tool_calls[:remaining]
            overflow = completion.tool_calls[remaining:]
            for call in runnable:
                path = call.arguments.get("path")
                if isinstance(path, str) and repeats_grant_directory(
                    path, context.grant.subdirectory
                ):
                    result = text_message(
                        "tool",
                        "error: tool paths are already relative to the granted directory; "
                        "remove the repeated grant prefix",
                    )
                    result = Message(
                        role="tool", content=result.content, tool_call_id=call.id
                    )
                elif toolbox.destructive(call.name) and not context.grant.allows(
                    FILESYSTEM_WRITE
                ):
                    result = text_message(
                        "tool", f"error: task grant does not allow {call.name}"
                    )
                    result = Message(
                        role="tool", content=result.content, tool_call_id=call.id
                    )
                else:
                    result = toolbox.run(call)
                messages.append(result)
                result_text = " ".join(part.text or "" for part in result.content)
                artifact = path
                if (
                    call.name in {"write_file", "edit_file"}
                    and not result_text.startswith("error:")
                    and isinstance(artifact, str)
                ):
                    artifacts.add(Path(artifact).as_posix())
                used += 1
            for call in overflow:
                messages.append(
                    Message(
                        role="tool",
                        content=[
                            ContentPart(
                                kind="text",
                                text="error: tool-call budget exhausted; this call did not run",
                            )
                        ],
                        tool_call_id=call.id,
                    )
                )

            if overflow or used >= context.remaining_tool_calls:
                try:
                    final = await self.backend.invoke(messages, tools=None)
                except BackendError as error:
                    raise TaskStageError(f"implementation failed: {error}") from error
                summary = final.text.strip() or "tool-call budget exhausted"
                return ImplementationResult(
                    summary, tool_calls=used, artifacts=tuple(sorted(artifacts))
                )


def build_model_task_graph(
    backend: ModelBackend,
    workspace: Path,
    tester: Tester,
    budget: TaskBudget | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Wire model planning and sandbox implementation into the task lifecycle."""

    worker = ModelTaskWorker(backend, workspace)
    return build_task_graph(
        worker.plan,
        worker.implement,
        tester,
        workspace,
        budget,
        checkpointer,
    )
