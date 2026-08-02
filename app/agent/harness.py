"""One application harness for conversation and bounded autonomous work.

The UI submits every ordinary request here. A model-owned routing decision
chooses whether the existing conversational agent should answer (and use its
normal tools when useful) or whether the bounded plan/implement/test lifecycle
is required. No interface mode or keyword contract participates in the choice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from app.agent.runtime import Agent
from app.agent.task_runtime import TaskRuntime, TaskView
from app.models import BackendError, ContentPart, Message

ROUTE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "request_route",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "route": {"type": "string", "enum": ["answer", "act"]},
                "task": {"type": "string"},
            },
            "required": ["route", "task"],
            "additionalProperties": False,
        },
    },
}

ROUTER_SYSTEM_PROMPT = (
    "Route this ordinary request inside one general autonomous agent. "
    "Choose answer for conversation, explanation, analysis of supplied media, "
    "clarification, read-only inspection, or a request the normal tool-using "
    "conversation can complete directly. Choose act only when the requested "
    "outcome requires creating or modifying workspace artifacts through a bounded "
    "implementation and validation lifecycle. If a required path or scope is "
    "ambiguous, choose answer so the agent can clarify it. For answer, task must be "
    "an empty string. For act, task must be a concise faithful restatement of the "
    "user's observable outcome and constraints, not a plan; preserve exact paths "
    "and do not invent requirements. Return only the requested structured object."
)


@dataclass(frozen=True)
class HarnessDecision:
    route: Literal["answer", "act"]
    task: str = ""


def parse_decision(text: str) -> HarnessDecision:
    """Accept exactly the router schema and no hidden prose."""

    payload = json.loads(text)
    if not isinstance(payload, dict) or set(payload) != {"route", "task"}:
        raise ValueError("route response has missing or unexpected fields")
    route = payload["route"]
    task = payload["task"]
    if route not in {"answer", "act"} or not isinstance(task, str):
        raise ValueError("route response has invalid field types")
    task = task.strip()
    if route == "answer" and task:
        raise ValueError("answer route must not contain a task")
    if route == "act" and not task:
        raise ValueError("act route requires a task")
    return HarnessDecision(route, task)


def task_result_message(view: TaskView) -> Message:
    """Turn durable task state into the factual conversation result."""

    if view.outcome is None:
        body = "The task stopped without an outcome."
    else:
        lines = [
            view.implementation.summary if view.implementation else view.outcome.summary,
            "",
            f"Status: {view.outcome.status}; iterations: {view.outcome.iterations}; "
            f"tool calls: {view.outcome.tool_calls}.",
            f"Outcome: {view.outcome.summary.rstrip('.')}.",
        ]
        if view.report is not None:
            lines.extend(["", "Available checks:"])
            lines.extend(
                f"- {'passed' if check.passed else 'failed'} — {check.name}: {check.detail}"
                for check in view.report.checks
            )
        if view.outcome.artifacts:
            lines.extend(["", "Artifacts:"])
            lines.extend(f"- {artifact}" for artifact in view.outcome.artifacts)
        body = "\n".join(lines)
    evidence = (
        [part for part in view.report.evidence if isinstance(part, ContentPart)]
        if view.report is not None
        else []
    )
    return Message(
        role="assistant",
        content=[ContentPart(kind="text", text=body), *evidence],
    )


class GeneralHarness:
    """Own the internal answer/act choice and both execution paths."""

    def __init__(self, agent: Agent, tasks: TaskRuntime) -> None:
        if tasks.backend is not agent.backend:
            raise ValueError("the conversational and task paths must share one backend")
        self.agent = agent
        self.tasks = tasks

    async def decide(self, thread_id: str, message: Message) -> HarnessDecision:
        try:
            completion = await self.agent.backend.invoke(
                self.agent.context_prompt(thread_id, [message], ROUTER_SYSTEM_PROMPT),
                response_format=ROUTE_RESPONSE_FORMAT,
            )
            return parse_decision(completion.text)
        except (BackendError, json.JSONDecodeError, ValueError, TypeError):
            # Routing must never make a usable conversational request fail. The
            # normal agent can still answer, clarify, or select its governed tools.
            return HarnessDecision("answer")

    async def start_task(
        self, thread_id: str, original: Message, task: str
    ) -> TaskView:
        self.agent.record(thread_id, [original])
        return await self.tasks.start(thread_id, task, subdirectory=".")

    async def task_view(self, thread_id: str) -> TaskView:
        return await self.tasks.view(thread_id)

    async def resume_task(self, thread_id: str, approved: bool) -> TaskView:
        return await self.tasks.resume(thread_id, approved)

    def finish_task(self, thread_id: str, view: TaskView) -> Message:
        result = task_result_message(view)
        self.agent.record(thread_id, [result])
        return result

    async def aclose(self) -> None:
        await self.tasks.aclose()
        await self.agent.aclose()
