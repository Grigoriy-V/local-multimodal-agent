"""Chainlit in front of the agent.

This file adapts between Chainlit's world and the project's own: attachments
become `ContentPart`s, agent messages become Chainlit messages and steps. It
holds no logic about tools, memory or context — that lives in `app/`, so a
second consumer can be added without moving any of it.

    .venv\\Scripts\\python.exe -m chainlit run ui/chainlit_app.py -w
"""

from __future__ import annotations

from pathlib import Path

import chainlit as cl

from app.agent.runtime import Agent, create_agent
from app.models import ContentPart, Message

IMAGE = "image"
AUDIO = "audio"


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


@cl.on_message
async def on_message(incoming: cl.Message) -> None:
    agent: Agent = cl.user_session.get("agent")
    thread_id: str = cl.user_session.get("thread_id")

    pending: dict[str, cl.Step] = {}
    async for produced in agent.steps(thread_id, to_message(incoming)):
        if produced.role == "tool":
            step = pending.pop(produced.tool_call_id or "", None)
            if step is not None:
                step.output = spoken(produced)
                await step.update()
            continue

        body = spoken(produced)
        if body:
            await cl.Message(content=body).send()
        for call in produced.tool_calls:
            step = cl.Step(name=call.name, type="tool")
            step.input = call.arguments
            await step.send()
            pending[call.id] = step
        if not body and not produced.tool_calls:
            await cl.Message(content="(no answer)").send()


@cl.on_chat_end
async def end() -> None:
    agent: Agent | None = cl.user_session.get("agent")
    if agent is not None:
        await agent.aclose()
