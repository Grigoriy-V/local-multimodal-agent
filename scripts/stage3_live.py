"""A live check of confirmation and resumption. Needs the model server.

    .venv\\Scripts\\python.exe -m scripts.stage3_live

Writes only into a temporary workspace, and drives the real graph: the model is
asked to change a file, the turn stops, the agent is closed and reopened, and
the question is answered on the other side of the restart.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from app.agent.runtime import Agent, text_message
from app.config import ModelSettings
from app.memory import MemoryStore
from app.models.openai_compatible import OpenAICompatibleBackend


def open_agent(room: Path) -> Agent:
    return Agent(
        backend=OpenAICompatibleBackend(ModelSettings()),
        store=MemoryStore(room / "memory.sqlite3"),
        workspace=room / "workspace",
        checkpoints=room / "checkpoints.sqlite3",
    )


def show(title: str) -> None:
    print(f"\n=== {title} ===")


async def run(room: Path) -> None:
    workspace = room / "workspace"
    workspace.mkdir()
    note = workspace / "notes.txt"
    note.write_text("the answer is 42\n", encoding="utf-8")

    started = time.monotonic()

    show("turn one: the model is asked to change a file")
    agent = open_agent(room)
    async for message in agent.steps("t1", text_message("Rewrite notes.txt so it says 43.")):
        for call in message.tool_calls:
            print(f"  calls {call.name}({call.arguments})")
    question = await agent.pending("t1")
    print(f"  waiting on: {question}")
    print(f"  file on disk: {note.read_text(encoding='utf-8')!r}")
    assert question is not None, "the model never asked to write"
    assert note.read_text(encoding="utf-8") == "the answer is 42\n", "the file was written unasked"

    show("the process ends with the question unanswered")
    await agent.aclose()

    show("a new agent finds the same question and approves it")
    agent = open_agent(room)
    question = await agent.pending("t1")
    print(f"  still waiting on: {question}")
    assert question is not None, "the question did not survive the restart"
    async for message in agent.resume("t1", {call["id"]: True for call in question}):
        body = " ".join(part.text or "" for part in message.content).strip()
        print(f"  {message.role}: {body[:120]}")
    print(f"  file on disk: {note.read_text(encoding='utf-8')!r}")
    assert "43" in note.read_text(encoding="utf-8"), "approving did not write the file"

    show("turn two: the same request is declined")
    async for message in agent.steps("t1", text_message("Now rewrite notes.txt so it says 44.")):
        for call in message.tool_calls:
            print(f"  calls {call.name}({call.arguments})")
    question = await agent.pending("t1")
    assert question is not None, "the model never asked the second time"
    async for message in agent.resume("t1", {call["id"]: False for call in question}):
        body = " ".join(part.text or "" for part in message.content).strip()
        print(f"  {message.role}: {body[:200]}")
    print(f"  file on disk: {note.read_text(encoding='utf-8')!r}")
    assert "44" not in note.read_text(encoding="utf-8"), "a declined call wrote the file"

    show("what the store kept")
    for message in agent.history("t1"):
        body = " ".join(part.text or "" for part in message.content).strip()
        names = ",".join(call.name for call in message.tool_calls)
        print(f"  {message.role}: {body[:90] or f'[calls {names}]'}")
    await agent.aclose()

    print(f"\nwhole flow: {time.monotonic() - started:.1f} s")


def main() -> None:
    with tempfile.TemporaryDirectory() as room:
        asyncio.run(run(Path(room)))


if __name__ == "__main__":
    main()
