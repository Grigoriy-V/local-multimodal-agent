"""A live check of the one loop. Needs the model endpoint, so it wakes a GPU.

    .venv\\Scripts\\python.exe -m scripts.loop_live

Five things the offline suite can only fake, because each of them is about what
a real model does with the loop rather than about what the loop does with a
scripted answer:

    A  an ordinary question           one model call, no tools, no mode
    B  a request that needs one tool  the tool runs and the answer uses it
    C  a multi-step workspace task    several steps, still no mode
    D  a stop while the work is live  the turn ends without another request
    E  a tool that fails              the typed result reaches the model, the
                                      model recovers, telemetry says why
    F  a page the model made          it looks at it with inspect_page, and the
                                      structure with refs is what it read
    G  the person's own request       an app, a look, and the files and the
                                      screenshot handed over unprompted, with
                                      no plan tool in the toolbox

Each scenario is checked, not only printed: a line starting with PASS or FAIL
says whether what happened is what the scenario expects, and the exit code is
the number of failures. The expectations are about the loop and the tool
boundary, never about the model's wording.

It writes into a temporary directory and its own telemetry file: nothing here
touches the deployed database, the real workspace, or the local profile's own
conversations. The run ids it prints can be read back with

    AGENT_TELEMETRY_DATABASE=<the file it names> python tools/show_run.py <id>

A to D are the acceptance evidence for roadmap sub-step 4.1; E is the live
half of 4.5 (`docs/v2_tool_system.md`, "Acceptance for 4.5"); F is the live
half of 4.5.5 and needs a browser where this runs; G is the request the
person tested live all day on 2026-09-03, in the plan-off shape that is the
default, with the numbers a plan-on run can be compared against. Every run of
it costs GPU time and needs permission at the time.
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
from app.models import Message, ToolFailure
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

    Workspace writes are autonomous, so none of these scenarios should stop at
    a consent question. If one ever does — a tool gains `requires_approval` —
    this says yes, which is what the person running the check is doing by
    running it, and counts it so the report shows it happened.
    """

    def __init__(self, agent, telemetry, sequence: int) -> None:
        self.agent = agent
        self.telemetry = telemetry
        self.sequence = sequence
        self.text: list[str] = []
        self.tools: list[str] = []
        self.failures: list[tuple[str, ToolFailure]] = []
        self.tool_results: list[Message] = []
        self.approvals = 0
        self.run_id = f"live-{sequence}"
        self._names: dict[str, str] = {}

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
        message: Message | None = getattr(event, "message", None)
        if message is None:
            return
        for call in message.tool_calls:
            self.tools.append(call.name)
            self._names[call.id] = call.name
        if message.role == "tool":
            self.tool_results.append(message)
            if message.failure is not None:
                self.failures.append(
                    (self._names.get(message.tool_call_id or "", "?"), message.failure)
                )
        said = " ".join(part.text or "" for part in message.content).strip()
        if said and message.role == "assistant":
            self.text.append(said)

    def read_from(self, tool: str) -> str:
        """The text the model was given back by every call of this tool."""

        calls = {call_id for call_id, called in self._names.items() if called == tool}
        return " ".join(
            part.text or ""
            for message in self.tool_results
            if message.tool_call_id in calls
            for part in message.content
        )

    @property
    def answer(self) -> str:
        return self.text[-1] if self.text else ""

    def budget_exhausted(self) -> bool:
        store = self.telemetry.store
        if store is None:
            return False
        return any(event.type == "turn_budget_exhausted" for event in store.events(self.run_id))

    def failed_events(self) -> list[dict]:
        """The `tool_failed` events the store kept for this turn, by their data."""

        store = self.telemetry.store
        if store is None:
            return []
        return [event.data for event in store.events(self.run_id) if event.type == "tool_failed"]

    def report(self, name: str, checks: dict[str, bool]) -> int:
        print(f"\n{name}")
        print(
            f"  model calls {self.run.model_calls}   tool calls {self.run.tool_calls}"
            f"   approvals {self.approvals}"
        )
        print(f"  tools       {self.tools or '-'}")
        if self.failures:
            print("  failures    " + "; ".join(f"{tool}: {why.code}" for tool, why in self.failures))
        print(f"  seconds     {self.seconds:6.2f}   run {self.run_id}")
        print(f"  answer      {(self.answer or '(nothing said)')[:160]}")
        for expectation, held in checks.items():
            print(f"  {'PASS' if held else 'FAIL'}  {expectation}")
        return sum(1 for held in checks.values() if not held)


# What runs after every deploy of the agent: two quick answers, so a change
# to the loop has not broken the simple case, then the person's own request,
# which is where every defect of 2026-09-03 showed. Asked for by the human
# that day. Everything else stays available by letter.
AFTER_DEPLOY = ("A", "B", "G")


def chosen(argv: list[str]) -> frozenset[str]:
    """Which scenarios to run: `--after-deploy`, letters, or all of them."""

    if "--after-deploy" in argv:
        return frozenset(AFTER_DEPLOY)
    letters = {arg.upper() for arg in argv if len(arg) == 1 and arg.upper() in "ABCDEFG"}
    return frozenset(letters) if letters else frozenset("ABCDEFG")


async def main() -> int:
    selected = chosen(sys.argv[1:])

    def wanted(letter: str) -> bool:
        return letter in selected

    room = Path(tempfile.mkdtemp(prefix="loop-live-"))
    settings = settings_in(room)
    telemetry = open_telemetry(settings)
    stops = MemoryStopRequests()
    agent = create_agent(
        agent_settings=settings, user_id=USER, telemetry=telemetry, stops=stops
    )
    root = agent.capability_grant.root
    print(f"workspace {root}")
    print(f"telemetry {settings.telemetry_database}")
    failed = 0

    try:
        if wanted("A"):
            # A — one request, no tools, no mode.
            a = await Turn(agent, telemetry, 10).ask("chat-a", "Привет! Как ты?")
            failed += a.report(
                "A ordinary question",
                {
                    "one model call": a.run.model_calls == 1,
                    "no tools": not a.tools,
                    "an answer was given": bool(a.answer),
                },
            )

        if wanted("B"):
            # B — one tool, chosen by the model rather than by a route.
            (root / "notes.txt").write_text("The passphrase is marmalade.", encoding="utf-8")
            b = await Turn(agent, telemetry, 20).ask(
                "chat-b", "Read notes.txt in my workspace and tell me the passphrase."
            )
            failed += b.report(
                "B one tool",
                {
                    "read_file ran": "read_file" in b.tools,
                    "no tool failed": not b.failures,
                    "the passphrase is in the answer": "marmalade" in b.answer.lower(),
                },
            )

        if wanted("C"):
            # C — several steps, with no lifecycle to enter.
            c = await Turn(agent, telemetry, 30).ask(
                "chat-c",
                "In my workspace, write a file plan.txt containing three short lines "
                "about how to store apples, then read it back and tell me what it says.",
            )
            failed += c.report(
                "C multi-step work",
                {
                    "write_file then read_file": "write_file" in c.tools and "read_file" in c.tools,
                    "plan.txt exists": (root / "plan.txt").is_file(),
                    "no tool failed": not c.failures,
                    "an answer was given": bool(c.answer),
                },
            )

        if wanted("D"):
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
            failed += stopped.report(
                "D stopped mid-flight",
                {
                    "the turn ended with the stop message": stopped.answer == "Stopped at your request.",
                    "fewer than five files were made": len(list(root.glob("apple*.txt"))) < 5,
                },
            )

        if wanted("E"):
            # E — a tool that fails, typed. The model must read the result, not
            # lose the turn, and telemetry must say why. The failure is one the
            # model cannot see coming from a listing: the text it is asked to edit
            # occurs twice, so the first `edit_file` is refused as ambiguous.
            (root / "fruit.txt").write_text("apple pie\napple tart\n", encoding="utf-8")
            e = await Turn(agent, telemetry, 50).ask(
                "chat-e",
                "In my workspace, use edit_file on fruit.txt to replace the word "
                "'apple' with 'pear'. Do not read the file first and do not rewrite it "
                "with write_file. Then tell me what happened.",
            )
            codes = [why.code for _, why in e.failures]
            events = e.failed_events()
            failed += e.report(
                "E a failing tool",
                {
                    "edit_file ran": "edit_file" in e.tools,
                    "the failure reached the loop as fs.ambiguous_edit": "fs.ambiguous_edit" in codes,
                    "the model answered after the failure": bool(e.answer),
                    "the turn was not ended by the repeat guard": e.run.model_calls <= 4,
                    "tool_failed carries code and message": any(
                        event.get("code") == "fs.ambiguous_edit" and event.get("message")
                        for event in events
                    ),
                },
            )

        if wanted("F"):
            # F — the model looks at what it made. The check is about the loop:
            # the browser tool ran, returned no failure, and what the model read
            # was the structure with refs rather than a count of buttons.
            f = await Turn(agent, telemetry, 60).ask(
                "chat-f",
                "In my workspace, write a small self-contained page counter.html with a "
                "heading, a button labelled Count and a script that increments a number "
                "in the heading when the button is pressed. Then open it with inspect_page "
                "and tell me what the page contains.",
            )
            failed += f.report(
                "F a page the model made, looked at",
                {
                    "write_file then inspect_page": "write_file" in f.tools
                    and "inspect_page" in f.tools,
                    "counter.html exists": (root / "counter.html").is_file(),
                    "no tool failed": not f.failures,
                    "the model read a structure with a ref": "[ref=e" in f.read_from("inspect_page"),
                    "an answer was given": bool(f.answer),
                },
            )

        if wanted("G"):
            # G — the person's own request, plan off (the default). What the checks
            # ask is what the person asked for: it was built, looked at, and both
            # the files and the screenshot came without a second request.
            g = await Turn(agent, telemetry, 70).ask(
                "chat-g",
                "Создай небольшое веб-приложение Task Board. В отдельной папке Task Board\n\n"
                "три колонки: To Do, In Progress, Done;\n"
                "можно создавать и удалять задачи;\n"
                "задачи можно переносить между колонками;\n"
                "состояние сохраняется в localStorage и восстанавливается после перезагрузки;\n"
                "добавь фильтр по тексту задачи;\n"
                "интерфейс должен нормально выглядеть на desktop и mobile;\n\n"
                "В итоге пришли в чат скриншот и файлы программы",
            )
            sent = [
                part.name or part.kind
                for message in g.tool_results
                for part in message.content
                if getattr(part, "outbound", False)
            ]
            failed += g.report(
                "G the person's request, plan off",
                {
                    "no plan tool was offered or called": "todo_write" not in g.tools
                    and "todo_write" not in agent.toolbox("chat-g").names,
                    "write_file then inspect_page": "write_file" in g.tools and "inspect_page" in g.tools,
                    "the files were sent": any(name.endswith(".html") for name in sent),
                    "the screenshot was sent": any(name.endswith(".png") for name in sent),
                    "no path was offered as delivery": "![" not in g.answer,
                    "one answer, not two": len(g.text) == 1,
                    "no tool failed": not g.failures,
                    # Test 9, 2026-09-03: eleven writes and the ceiling. Test 8
                    # wrote four; more than five is the rewrite loop again.
                    "at most five write_file calls": g.tools.count("write_file") <= 5,
                    "the turn ended before its ceiling": not g.budget_exhausted(),
                },
            )
            print(f"  sent        {sent}")
    finally:
        await agent.aclose()
        telemetry.close()

    print(f"\n{'all scenarios passed' if not failed else f'{failed} check(s) failed'}")
    print(
        f"\nRead any of them back with:\n  AGENT_TELEMETRY_DATABASE={settings.telemetry_database} "
        f"AGENT_DATABASE_URL= python tools/show_run.py --last 10 --summary"
    )
    return failed


if __name__ == "__main__":
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    raise SystemExit(asyncio.run(main(), loop_factory=loop_factory))
