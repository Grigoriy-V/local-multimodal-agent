"""Chainlit in front of the agent.

This file adapts between Chainlit's world and the project's own: attachments
become `ContentPart`s, agent messages become Chainlit messages and steps. It
holds no logic about tools, memory or context — that lives in `app/`, so a
second consumer can be added without moving any of it.

    .venv\\Scripts\\python.exe -m chainlit run ui/chainlit_app.py -w
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import chainlit as cl

from app.agent.runtime import Agent, create_agent
from app.memory import Thread
from app.models import ContentPart, Message

IMAGE = "image"
AUDIO = "audio"
CONFIRM_TIMEOUT = 600
CHOOSE_TIMEOUT = 120
# How many past conversations to offer. Beyond a handful the list stops being a
# choice and becomes a search problem, which this is not.
CHOICES = 5
OPENING_WIDTH = 48


def part_for(path: str, mime: str | None) -> ContentPart | None:
    """Turn one attachment into a content part, or ignore what the model cannot read."""

    kind = (
        IMAGE
        if (mime or "").startswith("image/")
        else AUDIO
        if (mime or "").startswith("audio/")
        else None
    )
    if kind is None:
        return None
    return ContentPart(kind=kind, data=Path(path).read_bytes(), media_type=mime)


def to_message(incoming: cl.Message) -> Message:
    parts: list[ContentPart] = []
    if incoming.content:
        parts.append(ContentPart(kind="text", text=incoming.content))
    for element in incoming.elements or ():
        path = getattr(element, "path", None)
        part = part_for(path, getattr(element, "mime", None)) if path else None
        if part is not None:
            parts.append(part)
    if not parts:
        parts.append(ContentPart(kind="text", text="(empty message)"))
    return Message(role="user", content=parts)


def rejected(incoming: cl.Message) -> list[str]:
    """Attachments the model cannot read, named so the user is told rather than
    left to wonder why the agent ignored the file."""

    names = []
    for element in incoming.elements or ():
        path = getattr(element, "path", None)
        if path and part_for(path, getattr(element, "mime", None)) is None:
            names.append(getattr(element, "name", None) or Path(path).name)
    return names


def spoken(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content).strip()


def media_parts(message: Message) -> list[ContentPart]:
    """The parts that have to be shown rather than said, in the order they came."""

    return [part for part in message.content if part.kind != "text"]


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


async def replay(agent: Agent, thread_id: str) -> None:
    """Show what the store already holds, so a restart looks like a continuation."""

    for message in agent.history(thread_id):
        if message.role == "user":
            await cl.Message(
                content=spoken(message), elements=attachments(message), author="you"
            ).send()
        elif message.role == "assistant" and spoken(message):
            await cl.Message(content=spoken(message)).send()


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


def summarise(thread: Thread) -> str:
    opening = thread.opening or "(no words)"
    if len(opening) > OPENING_WIDTH:
        opening = opening[: OPENING_WIDTH - 1] + "…"
    return f"{opening} · {thread.messages} messages"


async def choose_thread(agent: Agent) -> str:
    """Ask which conversation to open. No answer continues the most recent one."""

    threads = agent.threads()
    if not threads:
        return cl.context.session.id

    actions = [
        cl.Action(name=thread.id, payload={"thread_id": thread.id}, label=summarise(thread))
        for thread in threads[:CHOICES]
    ]
    actions.append(cl.Action(name="new", payload={"thread_id": ""}, label="New conversation"))
    response = await cl.AskActionMessage(
        content="Which conversation?", actions=actions, timeout=CHOOSE_TIMEOUT
    ).send()
    if response is None:
        return threads[0].id
    return response.get("payload", {}).get("thread_id") or cl.context.session.id


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
    agent = create_agent()
    thread_id = await choose_thread(agent)
    cl.user_session.set("agent", agent)
    cl.user_session.set("thread_id", thread_id)

    await replay(agent, thread_id)
    await cl.Message(
        content=f"Ready. Thread `{thread_id}`, workspace `{agent.workspace}`."
    ).send()

    if await agent.pending(thread_id) is not None:
        await cl.Message(content="This conversation stopped waiting for an answer.").send()
        await drive(agent, thread_id)


@cl.on_message
async def on_message(incoming: cl.Message) -> None:
    agent: Agent = cl.user_session.get("agent")
    thread_id: str = cl.user_session.get("thread_id")

    ignored = rejected(incoming)
    if ignored:
        await cl.Message(
            content=f"I can only read images and audio, so I ignored: {', '.join(ignored)}."
        ).send()

    await drive(agent, thread_id, agent.steps(thread_id, to_message(incoming)))


@cl.on_chat_end
async def end() -> None:
    agent: Agent | None = cl.user_session.get("agent")
    if agent is not None:
        await agent.aclose()
