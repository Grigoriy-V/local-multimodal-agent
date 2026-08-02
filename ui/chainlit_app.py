"""Chainlit in front of the agent.

This file adapts between Chainlit's world and the project's own: attachments
become `ContentPart`s, agent messages become Chainlit messages and steps. It
holds no logic about tools, memory or context — that lives in `app/`, so a
second consumer can be added without moving any of it.

    .venv\\Scripts\\python.exe -m chainlit run ui/chainlit_app.py -w
"""

from __future__ import annotations

import json
import mimetypes
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

from app.agent.harness import GeneralHarness
from app.agent.runtime import Agent, create_agent
from app.agent.task_runtime import TaskProgress, TaskRuntime, TaskView
from app.config import AgentSettings
from app.memory import MemoryStore
from app.models import ContentPart, Message
from ui.chainlit_history import LOCAL_USER_IDENTIFIER, MemoryStoreDataLayer

IMAGE = "image"
AUDIO = "audio"
CONFIRM_TIMEOUT = 600


@cl.header_auth_callback
async def local_auth(_headers: Any) -> cl.User:
    """A single transparent identity for this loopback-only application."""

    return cl.User(identifier=LOCAL_USER_IDENTIFIER, display_name="Local user")


@cl.data_layer
def history_layer() -> MemoryStoreDataLayer:
    settings = AgentSettings()
    return MemoryStoreDataLayer(
        MemoryStore(settings.database),
        checkpoints=settings.checkpoints,
        task_checkpoints=settings.task_checkpoints,
    )


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


def create_harness() -> GeneralHarness:
    agent = create_runtime()
    settings = AgentSettings()
    return GeneralHarness(
        agent,
        TaskRuntime(
            backend=agent.backend,
            workspace=agent.workspace,
            checkpoints=settings.task_checkpoints,
        ),
    )


def task_plan_text(view: TaskView) -> str:
    if view.plan is None:
        return "Task planning did not produce a plan."
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(view.plan.steps, 1))
    criteria = "\n".join(f"- {item}" for item in view.plan.acceptance_criteria)
    validation = "\n".join(
        f"- **{step.criterion}** — {step.evidence} "
        f"(`{', '.join(step.capabilities)}`)"
        for step in view.plan.validation_strategy
    )
    return (
        f"**Plan**\n\n{view.plan.summary}\n\n{steps}\n\n"
        f"**Acceptance criteria**\n\n{criteria}\n\n"
        f"**Validation strategy**\n\n{validation}"
    )


async def drive_task(
    harness: GeneralHarness,
    thread_id: str,
    original: Message | None = None,
    task: str | None = None,
) -> None:
    if task is not None and original is not None:
        planning = cl.Step(name="Planning", type="run")
        await planning.send()
        view = await harness.start_task(thread_id, original, task)
        planning.output = view.plan.summary if view.plan is not None else "Planning stopped."
        await planning.update()
    else:
        view = await harness.task_view(thread_id)
    if view.interrupt is not None:
        permissions = ", ".join(view.interrupt.get("permissions", []))
        response = await cl.AskActionMessage(
            content=(
                f"{task_plan_text(view)}\n\n"
                f"**Scope:** configured workspace (`{harness.tasks.workspace}`)\n\n"
                f"**Capabilities:** {permissions}\n\nRun this plan?"
            ),
            actions=[
                cl.Action(name="approve_task", payload={"approved": True}, label="Run it"),
                cl.Action(name="decline_task", payload={"approved": False}, label="Don't"),
            ],
            timeout=CONFIRM_TIMEOUT,
        ).send()
        approved = bool((response or {}).get("payload", {}).get("approved"))
        if approved:
            progress_step = cl.Step(name="Task progress", type="run")
            progress_lines = ["Workspace grant approved; execution started."]
            progress_step.output = "\n".join(progress_lines)
            await progress_step.send()
            async for progress in harness.resume_task_with_progress(thread_id, True):
                progress_lines.append(task_progress_text(progress))
                progress_step.output = "\n".join(progress_lines)
                await progress_step.update()
            view = await harness.task_view(thread_id)
        else:
            view = await harness.resume_task(thread_id, False)
    result = harness.finish_task(thread_id, view)
    elements = [*attachments(result), *task_artifacts(harness, view, thread_id)]
    await cl.Message(content=spoken(result), elements=elements).send()


def task_progress_text(progress: TaskProgress) -> str:
    labels = {
        "approval": "Approval",
        "implementation": "Implementation",
        "validation": "Validation",
        "evaluation": "Evaluation",
        "repair": "Repair",
        "finalization": "Finalization",
    }
    return f"{labels[progress.stage]}: {progress.detail}"


def task_artifacts(
    harness: GeneralHarness, view: TaskView, thread_id: str
) -> list[Any]:
    """Expose only real files that the application runtime resolves in scope."""

    if view.outcome is None:
        return []
    shown = []
    for artifact in view.outcome.artifacts:
        try:
            path = harness.tasks.artifact_path(view, artifact)
        except (OSError, PermissionError, ValueError):
            continue
        if path.is_file():
            shown.append(
                cl.File(
                    thread_id=thread_id,
                    name=path.name,
                    path=str(path),
                    display="inline",
                    mime=mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                )
            )
    return shown


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
    harness = create_harness()
    # The websocket session id is ephemeral and differs from the canonical
    # thread id that Chainlit puts in its sidebar and data layer.
    thread_id = canonical_thread_id(cl.context.session)
    cl.user_session.set("harness", harness)
    cl.user_session.set("thread_id", thread_id)


@cl.on_chat_resume
async def resume(thread: dict[str, Any]) -> None:
    harness = create_harness()
    thread_id = thread["id"]
    cl.user_session.set("harness", harness)
    cl.user_session.set("thread_id", thread_id)
    task_view = await harness.task_view(thread_id)
    if task_view.interrupt is not None:
        await cl.Message(content="This task stopped waiting for workspace approval.").send()
        await drive_task(harness, thread_id)
        return
    if await harness.agent.pending(thread_id) is not None:
        await cl.Message(content="This conversation stopped waiting for an answer.").send()
        await drive(harness.agent, thread_id)


@cl.on_message
async def on_message(incoming: cl.Message) -> None:
    harness: GeneralHarness = cl.user_session.get("harness")
    thread_id: str = cl.user_session.get("thread_id")

    try:
        message = to_message(incoming)
    except AttachmentError as exc:
        await cl.Message(
            content=f"Upload refused: {exc}."
        ).send()
        return

    decision = await harness.decide(thread_id, message)
    if decision.route == "act":
        await drive_task(harness, thread_id, message, decision.task)
        return

    await drive(
        harness.agent,
        thread_id,
        harness.agent.steps(thread_id, message),
    )


@cl.on_chat_end
async def end() -> None:
    harness: GeneralHarness | None = cl.user_session.get("harness")
    if harness is not None:
        await harness.aclose()


@cl.on_stop
async def stop() -> None:
    harness: GeneralHarness | None = cl.user_session.get("harness")
    thread_id: str | None = cl.user_session.get("thread_id")
    if harness is None or thread_id is None:
        return
    result = await harness.cancel_task(thread_id)
    if result is not None:
        await cl.Message(content=spoken(result), elements=attachments(result)).send()
