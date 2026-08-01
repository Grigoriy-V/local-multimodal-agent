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
from app.models import ContentPart, Message

IMAGE = "image"
AUDIO = "audio"
CONFIRM_TIMEOUT = 600


def part_for(path: str, mime: str | None) -> ContentPart | None:
    """Turn one attachment into a content part, or ignore what the model cannot read."""

    kind = IMAGE if (mime or "").startswith("image/") else AUDIO if (mime or "").startswith("audio/") else None
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


def spoken(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content).strip()


async def replay(agent: Agent, thread_id: str) -> None:
    """Show what the store already holds, so a restart looks like a continuation."""

    for message in agent.history(thread_id):
        body = spoken(message)
        if message.role == "user":
            await cl.Message(content=body, author="you").send()
        elif message.role == "assistant" and body:
            await cl.Message(content=body).send()


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
        if body:
            await cl.Message(content=body).send()
        for call in message.tool_calls:
            step = cl.Step(name=call.name, type="tool")
            step.input = call.arguments
            await step.send()
            steps[call.id] = step
        if not body and not message.tool_calls:
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


@cl.on_chat_start
async def start() -> None:
    agent = create_agent()
    # Continue the most recent conversation rather than opening an empty one:
    # persistence is only visible if something is there to come back to.
    threads = agent.threads()
    thread_id = threads[0] if threads else cl.context.session.id
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

    await drive(agent, thread_id, agent.steps(thread_id, to_message(incoming)))


@cl.on_chat_end
async def end() -> None:
    agent: Agent | None = cl.user_session.get("agent")
    if agent is not None:
        await agent.aclose()
