"""Chainlit in front of the agent.

This file adapts between Chainlit's world and the project's own: attachments
become `ContentPart`s, agent messages become Chainlit messages and steps. It
holds no logic about tools, memory or context — that lives in `app/`, so a
second consumer can be added without moving any of it.

    .venv\\Scripts\\python.exe -m chainlit run ui/chainlit_app.py -w
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.attachments import AttachmentError, AttachmentSource, load_attachments


def _auth_secret() -> str:
    """Return a stable local signing key without putting it in the repository."""

    local_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    secret_path = local_data / "local-multimodal-agent" / "chainlit-auth-secret"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    try:
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return secret_path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)
    return secret


# Chainlit requires authentication before it exposes native chat history. The
# transparent single-user login is only a UI identity; the signing key lives in
# the user's local application data, not in source control or conversation data.
os.environ.setdefault("CHAINLIT_AUTH_SECRET", _auth_secret())

import chainlit as cl

from app.agent.runtime import Agent, create_agent
from app.agent.task_runtime import TaskRuntime, TaskView
from app.config import AgentSettings
from app.memory import MemoryStore
from app.models import ContentPart, Message
from ui.chainlit_history import LOCAL_USER_IDENTIFIER, MemoryStoreDataLayer

IMAGE = "image"
AUDIO = "audio"
CONFIRM_TIMEOUT = 600
CONVERSATION_MODE = "Conversation"
AGENT_MODE = "Agent"


@cl.header_auth_callback
async def local_auth(_headers: Any) -> cl.User:
    """A single transparent identity for this loopback-only application."""

    return cl.User(identifier=LOCAL_USER_IDENTIFIER, display_name="Local user")


@cl.data_layer
def history_layer() -> MemoryStoreDataLayer:
    return MemoryStoreDataLayer(MemoryStore(AgentSettings().database))


def attachment_sources(incoming: cl.Message) -> list[AttachmentSource]:
    """Translate Chainlit metadata without deciding what the agent accepts."""

    sources = []
    for element in incoming.elements or ():
        path = getattr(element, "path", None)
        if path:
            sources.append(
                AttachmentSource(
                    path=Path(path),
                    media_type=getattr(element, "mime", None),
                    name=getattr(element, "name", None) or Path(path).name,
                )
            )
    return sources


def to_message(incoming: cl.Message) -> Message:
    parts: list[ContentPart] = []
    if incoming.content:
        parts.append(ContentPart(kind="text", text=incoming.content))
    parts.extend(load_attachments(attachment_sources(incoming)))
    if not parts:
        raise AttachmentError("the message has no text or usable attachments")
    return Message(role="user", content=parts)


def spoken(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content).strip()


def media_parts(message: Message) -> list[ContentPart]:
    """The parts that have to be shown rather than said, in the order they came."""

    return [part for part in message.content if part.kind != "text"]


def canonical_thread_id(session: Any) -> str:
    """Use Chainlit's persistent conversation id, never its websocket id."""

    return str(session.thread_id)


def attachments(message: Message) -> list[Any]:
    """Show the pictures and the sound, not just the words about them.

    Without this a reopened conversation is a transcript with holes in it: the
    image the whole exchange is about was stored, and then not shown.
    """

    shown = []
    for index, part in enumerate(media_parts(message)):
        element = cl.Image if part.kind == IMAGE else cl.Audio
        shown.append(
            element(
                name=f"{part.kind}-{index}",
                content=part.data,
                mime=part.media_type,
                display="inline",
            )
        )
    return shown


async def render(produced: AsyncIterator[Message]) -> None:
    """Show messages as their nodes finish: a tool call as a step, an answer as a message."""

    steps: dict[str, cl.Step] = {}
    async for message in produced:
        if message.role == "tool":
            step = steps.pop(message.tool_call_id or "", None)
            if step is None:
                # The call was announced before a restart, so there is no open
                # step to fill in; show the result on its own instead of losing it.
                step = cl.Step(name="tool result", type="tool")
                await step.send()
            step.output = spoken(message)
            await step.update()
            shown = attachments(message)
            if shown:
                await cl.Message(content="Browser evidence", elements=shown).send()
            continue

        body = spoken(message)
        shown = attachments(message)
        if body or shown:
            await cl.Message(content=body, elements=shown).send()
        for call in message.tool_calls:
            step = cl.Step(name=call.name, type="tool")
            step.input = call.arguments
            await step.send()
            steps[call.id] = step
        if not body and not shown and not message.tool_calls:
            await cl.Message(content="(no answer)").send()


async def confirm(question: list[dict[str, Any]]) -> dict[str, bool]:
    """Ask about each call the agent stopped for. No answer means no."""

    answers: dict[str, bool] = {}
    for call in question:
        arguments = json.dumps(call["arguments"], indent=2, ensure_ascii=False)
        response = await cl.AskActionMessage(
            content=f"Run `{call['name']}`?\n```json\n{arguments}\n```",
            actions=[
                cl.Action(name="approve", payload={"approved": True}, label="Run it"),
                cl.Action(name="decline", payload={"approved": False}, label="Don't"),
            ],
            timeout=CONFIRM_TIMEOUT,
        ).send()
        answers[call["id"]] = bool((response or {}).get("payload", {}).get("approved"))
    return answers


def create_runtime() -> Agent:
    return create_agent(agent_settings=AgentSettings())


def create_task_runtime(agent: Agent) -> TaskRuntime:
    settings = AgentSettings()
    return TaskRuntime(
        backend=agent.backend,
        workspace=agent.workspace,
        checkpoints=settings.task_checkpoints,
    )


async def send_mode_settings(initial: str = CONVERSATION_MODE) -> None:
    await cl.ChatSettings(
        [
            cl.input_widget.Select(
                id="Mode",
                label="Mode",
                values=[CONVERSATION_MODE, AGENT_MODE],
                initial_value=initial,
                description=(
                    "Conversation answers normally. Agent plans and executes a task "
                    "inside the configured workspace."
                ),
            )
        ]
    ).send()


def task_plan_text(view: TaskView) -> str:
    if view.plan is None:
        return "Task planning did not produce a plan."
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(view.plan.steps, 1))
    criteria = "\n".join(f"- {item}" for item in view.plan.acceptance_criteria)
    return (
        f"**Plan**\n\n{view.plan.summary}\n\n{steps}\n\n"
        f"**Acceptance criteria**\n\n{criteria}"
    )


async def render_task_result(view: TaskView) -> None:
    if view.outcome is None:
        await cl.Message(content="The task stopped without an outcome.").send()
        return
    lines = [
        view.implementation.summary if view.implementation else view.outcome.summary,
        "",
        f"Status: **{view.outcome.status}**; iterations: {view.outcome.iterations}; "
        f"tool calls: {view.outcome.tool_calls}.",
    ]
    if view.report is not None:
        lines.extend(["", "**Available checks**"])
        lines.extend(
            f"- {'passed' if check.passed else 'failed'} — {check.name}: {check.detail}"
            for check in view.report.checks
        )
    if view.outcome.artifacts:
        lines.extend(["", "**Artifacts**"])
        lines.extend(f"- `{artifact}`" for artifact in view.outcome.artifacts)
    lines.extend(
        [
            "",
            "Semantic and task-specific validation is not enabled yet; this mode currently "
            "checks only that changed artifacts exist and are non-empty.",
        ]
    )
    await cl.Message(content="\n".join(lines)).send()


async def drive_task(runtime: TaskRuntime, thread_id: str, task: str | None = None) -> None:
    view = (
        await runtime.start(thread_id, task, subdirectory=".")
        if task is not None
        else await runtime.view(thread_id)
    )
    if view.interrupt is not None:
        permissions = ", ".join(view.interrupt.get("permissions", []))
        response = await cl.AskActionMessage(
            content=(
                f"{task_plan_text(view)}\n\n"
                f"**Scope:** configured workspace (`{runtime.workspace}`)\n\n"
                f"**Capabilities:** {permissions}\n\nRun this plan?"
            ),
            actions=[
                cl.Action(name="approve_task", payload={"approved": True}, label="Run it"),
                cl.Action(name="decline_task", payload={"approved": False}, label="Don't"),
            ],
            timeout=CONFIRM_TIMEOUT,
        ).send()
        approved = bool((response or {}).get("payload", {}).get("approved"))
        view = await runtime.resume(thread_id, approved)
    await render_task_result(view)


async def report_fill(agent: Agent) -> None:
    """State how large the last request was, counted by the model itself."""

    fill = await agent.fill()
    if fill is None:
        return
    share = fill.fraction
    body = (
        f"context {fill.used} / {fill.budget} tokens ({share:.0%})"
        if share is not None
        else f"context {fill.used} tokens"
    )
    await cl.Message(content=body, author="context").send()


async def drive(
    agent: Agent, thread_id: str, produced: AsyncIterator[Message] | None = None
) -> None:
    """Run a turn to its end, answering every question it stops on.

    Without a stream it only finishes what is already waiting, which is how a
    turn interrupted before a restart is picked up.
    """

    if produced is not None:
        await render(produced)
    while (question := await agent.pending(thread_id)) is not None:
        await render(agent.resume(thread_id, await confirm(question)))
    await report_fill(agent)


@cl.on_chat_start
async def start() -> None:
    agent = create_runtime()
    task_runtime = create_task_runtime(agent)
    # The websocket session id is ephemeral and differs from the canonical
    # thread id that Chainlit puts in its sidebar and data layer.
    thread_id = canonical_thread_id(cl.context.session)
    cl.user_session.set("agent", agent)
    cl.user_session.set("task_runtime", task_runtime)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("mode", CONVERSATION_MODE)
    await send_mode_settings()


@cl.on_chat_resume
async def resume(thread: dict[str, Any]) -> None:
    agent = create_runtime()
    task_runtime = create_task_runtime(agent)
    thread_id = thread["id"]
    cl.user_session.set("agent", agent)
    cl.user_session.set("task_runtime", task_runtime)
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("mode", CONVERSATION_MODE)
    task_view = await task_runtime.view(thread_id)
    if task_view.interrupt is not None:
        cl.user_session.set("mode", AGENT_MODE)
        await send_mode_settings(AGENT_MODE)
        await cl.Message(content="This task stopped waiting for workspace approval.").send()
        await drive_task(task_runtime, thread_id)
        return
    await send_mode_settings()
    if await agent.pending(thread_id) is not None:
        await cl.Message(content="This conversation stopped waiting for an answer.").send()
        await drive(agent, thread_id)


@cl.on_settings_update
async def settings_update(settings: dict[str, Any]) -> None:
    mode = settings.get("Mode", CONVERSATION_MODE)
    cl.user_session.set("mode", AGENT_MODE if mode == AGENT_MODE else CONVERSATION_MODE)


@cl.on_message
async def on_message(incoming: cl.Message) -> None:
    agent: Agent = cl.user_session.get("agent")
    task_runtime: TaskRuntime = cl.user_session.get("task_runtime")
    thread_id: str = cl.user_session.get("thread_id")

    try:
        message = to_message(incoming)
    except AttachmentError as exc:
        await cl.Message(
            content=f"Upload refused: {exc}."
        ).send()
        return

    if cl.user_session.get("mode") == AGENT_MODE:
        if media_parts(message):
            await cl.Message(
                content=(
                    "Agent mode currently accepts text tasks only. Use Conversation mode "
                    "for image or audio attachments."
                )
            ).send()
            return
        await drive_task(task_runtime, thread_id, spoken(message))
        return

    await drive(agent, thread_id, agent.steps(thread_id, message))


@cl.on_chat_end
async def end() -> None:
    agent: Agent | None = cl.user_session.get("agent")
    task_runtime: TaskRuntime | None = cl.user_session.get("task_runtime")
    if task_runtime is not None:
        await task_runtime.aclose()
    if agent is not None:
        await agent.aclose()
