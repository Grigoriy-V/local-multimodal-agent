"""A live check of the one loop. Needs the model endpoint, so it wakes a GPU.

    .venv\\Scripts\\python.exe -m scripts.loop_live

Four things the offline suite can only fake, because each of them is about what
a real model does with the loop rather than about what the loop does with a
scripted answer:

    A  an ordinary question           one model call, no tools, no mode
    B  a request that needs one tool  the tool runs and the answer uses it
    C  a multi-step workspace task    several steps, still no mode
    D  a stop while the work is live  the turn ends without another request

It writes into a temporary directory and its own telemetry file: nothing here
touches the deployed database, the real workspace, or the local profile's own
conversations. The run ids it prints can be read back with

    AGENT_TELEMETRY_DATABASE=<the file it names> python tools/show_run.py <id>

This is the acceptance evidence for roadmap sub-step 4.1. Every run of it costs
GPU time and needs permission at the time.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from app.agent.runtime import create_agent, text_message
from app.agent.stop import MemoryStopRequests
from app.config import AgentSettings
from app.telemetry import TurnRun
from app.telemetry.open import open_telemetry

USER = "loop-live-check"


def settings_in(room: Path) -> AgentSettings:
    """The local profile, pointed entirely at a temporary directory.

    `database_url` is emptied deliberately: the developer's `.env` names the
    deployed database, and a check has no business writing conversations or
    telemetry into it.
    """

    (room / "workspace").mkdir(parents=True, exist_ok=True)
    return AgentSettings(
        database=str(room / "memory.sqlite3"),
        database_url="",
        checkpoints=str(room / "checkpoints.sqlite3"),
        telemetry=True,
        telemetry_database=str(room / "telemetry.sqlite3"),
        workspace=str(room / "workspace"),
    )


class Turn:
    """One measured turn driven directly, the way the worker drives one.

    Including the approvals: `write_file` is destructive, so a turn that writes
    anything stops at a consent question, and a check that ignored it would be
    measuring a turn that never happened. This says yes, which is what the
    person running the check is doing by running it.
    """

    def __init__(self, agent, telemetry, sequence: int) -> None:
        self.agent = agent
        self.telemetry = telemetry
        self.sequence = sequence
        self.text: list[str] = []
        self.tools: list[str] = []
        self.approvals = 0
        self.run_id = f"live-{sequence}"

    async def ask(self, thread_id: str, prompt: str) -> "Turn":
        run = TurnRun(run_id=self.run_id, source="loop-live", user_id=USER)
        run.thread_id = thread_id
        trace = self.telemetry.start(run)
        trace.route("loop")
        started = time.monotonic()
        try:
            async for event in self.agent.events(
                thread_id, text_message(prompt), trace, self.sequence
            ):
                self.observe(event)
            while (pending := await self.agent.pending(thread_id)) is not None:
                self.approvals += 1
                answers = {call["id"]: True for call in pending}
                async for event in self.agent.resume_events(thread_id, answers, trace):
                    self.observe(event)
        finally:
            trace.finish("answer_delivered")
            self.telemetry.release(self.run_id)
        self.seconds = time.monotonic() - started
        self.run = run
        return self

    def observe(self, event) -> None:
        message = getattr(event, "message", None)
        if message is None:
            return
        for call in message.tool_calls:
            self.tools.append(call.name)
        said = " ".join(part.text or "" for part in message.content).strip()
        if said and message.role == "assistant":
            self.text.append(said)

    def report(self, name: str, expectation: str) -> None:
        print(f"\n{name}  {expectation}")
        print(
            f"  model calls {self.run.model_calls}   tool calls {self.run.tool_calls}"
            f"   approvals {self.approvals}"
        )
        print(f"  tools       {self.tools or '-'}")
        print(f"  seconds     {self.seconds:6.2f}   run {self.run_id}")
        answer = self.text[-1] if self.text else "(nothing said)"
        print(f"  answer      {answer[:160]}")


async def main() -> int:
    room = Path(tempfile.mkdtemp(prefix="loop-live-"))
    settings = settings_in(room)
    telemetry = open_telemetry(settings)
    stops = MemoryStopRequests()
    agent = create_agent(
        agent_settings=settings, user_id=USER, telemetry=telemetry, stops=stops
    )
    print(f"workspace {agent.capability_grant.root}")
    print(f"telemetry {settings.telemetry_database}")

    try:
        # A — the question the router used to cost an extra request on.
        a = await Turn(agent, telemetry, 10).ask("chat-a", "Привет! Как ты?")
        a.report("A ordinary question", "expect 1 model call and no tools")

        # B — one tool, chosen by the model rather than by a route.
        (agent.capability_grant.root / "notes.txt").write_text(
            "The passphrase is marmalade.", encoding="utf-8"
        )
        b = await Turn(agent, telemetry, 20).ask(
            "chat-b", "Read notes.txt in my workspace and tell me the passphrase."
        )
        b.report("B one tool", "expect read_file and the passphrase in the answer")

        # C — several steps, with no lifecycle to enter.
        c = await Turn(agent, telemetry, 30).ask(
            "chat-c",
            "In my workspace, write a file plan.txt containing three short lines "
            "about how to store apples, then read it back and tell me what it says.",
        )
        c.report("C multi-step work", "expect write_file then read_file, one turn")

        # D — a stop recorded while the turn is running.
        stopped = Turn(agent, telemetry, 40)
        work = asyncio.create_task(
            stopped.ask(
                "chat-d",
                "In my workspace, create five files apple1.txt to apple5.txt, each "
                "with one sentence about apples, reading each one back after you "
                "write it.",
            )
        )
        # Late enough to be mid-work rather than mid-first-request: the stop is
        # only meaningful once the turn has actually started spending.
        while len(stopped.tools) < 2 and not work.done():
            await asyncio.sleep(0.05)
        await stops.request(USER, 41)
        print("\n  (stop recorded while the turn was running)")
        await work
        stopped.report("D stopped mid-flight", "expect it to end at the next step")
    finally:
        await agent.aclose()
        telemetry.close()

    print(f"\nRead any of them back with:\n  AGENT_TELEMETRY_DATABASE={settings.telemetry_database} "
          f"AGENT_DATABASE_URL= python tools/show_run.py --last 10 --summary")
    return 0


if __name__ == "__main__":
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    raise SystemExit(asyncio.run(main(), loop_factory=loop_factory))
