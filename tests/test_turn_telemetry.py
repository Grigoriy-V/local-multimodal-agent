"""What a measured turn actually records, from ingress to the stored row.

Driven through the real webhook, the real worker and the real adapter, with
Telegram behind an `httpx.MockTransport` and the model behind the shared
scripted fake. Nothing here reaches outside the process, and nothing asserts on
model wording — only on the shape of the turn.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agent.harness import GeneralHarness
from app.agent.runtime import Agent
from app.agent.task_runtime import TaskRuntime
from app.config import AgentSettings, TelegramSettings
from app.memory import SqliteStore
from app.models import Completion, Usage
from app.telemetry import Telemetry, TraceEvent, TurnRun
from app.telemetry.sqlite import SqliteTelemetry
from app.tools import Tool, Toolbox
from tests.fakes import ScriptedBackend, calls, says
from ui.telegram.adapter import TelegramAdapter, canonical_user_id
from ui.telegram.api import TelegramClient
from ui.telegram.inbox import EnqueueResult, InboxJob
from ui.telegram.webhook import TelegramUpdateWorker, TelegramWebhook

ALLOWED = 4242
CHAT = 1000
SECRET = {"x-telegram-bot-api-secret-token": "webhook-secret"}


def route(task: str = "") -> Completion:
    """The router answer the harness always asks for first."""

    payload = {"route": "act" if task else "answer", "task": task}
    return Completion(text=json.dumps(payload), finish_reason="stop")


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self._next_message_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        if method == "sendMessage":
            self.sent.append(payload["text"])
            self._next_message_id += 1
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": self._next_message_id}}
            )
        return httpx.Response(200, json={"ok": True, "result": {}})


class FakeInbox:
    """The durable queue, reduced to what a turn's identity needs from it."""

    def __init__(self) -> None:
        self.payloads: dict[int, dict[str, Any]] = {}
        self.runs: dict[int, str] = {}
        self.claimed: set[int] = set()

    async def enqueue(
        self, update_id: int, payload: dict[str, Any], run_id: str = ""
    ) -> EnqueueResult:
        created = update_id not in self.payloads
        self.payloads.setdefault(update_id, payload)
        self.runs.setdefault(update_id, run_id)
        return EnqueueResult(update_id, created, self.runs[update_id])

    async def claim(self, update_id: int, lease_seconds: int = 900) -> InboxJob | None:
        if update_id not in self.payloads or update_id in self.claimed:
            return None
        self.claimed.add(update_id)
        return InboxJob(
            update_id,
            self.payloads[update_id],
            "lease",
            run_id=self.runs.get(update_id, ""),
            queued_ms=250,
        )

    async def complete(self, job: InboxJob) -> None:
        return None

    async def retry(self, job: InboxJob, error: str) -> None:
        self.claimed.discard(job.update_id)


BUILT: list[TelegramAdapter] = []


@pytest.fixture(autouse=True)
async def close_adapters():
    yield
    while BUILT:
        adapter = BUILT.pop()
        await adapter.aclose()
        await adapter.client.aclose()


def build(
    telegram: FakeTelegram,
    tmp_path: Path,
    backend: ScriptedBackend,
    telemetry: Telemetry,
    tools: Sequence[Tool] = (),
) -> TelegramAdapter:
    settings = TelegramSettings(
        token="test-token",
        webhook_secret="webhook-secret",
        allowed_users=str(ALLOWED),
        _env_file=None,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    agent_settings = AgentSettings(
        database=str(tmp_path / "memory.sqlite3"),
        checkpoints=str(tmp_path / "checkpoints.sqlite3"),
        task_checkpoints=str(tmp_path / "tasks.sqlite3"),
        workspace=str(workspace),
        _env_file=None,
    )

    def factory(user_id: str) -> GeneralHarness:
        agent = Agent(
            backend,
            SqliteStore(agent_settings.database),
            workspace,
            checkpoints=agent_settings.checkpoints,
            user_id=user_id,
            telemetry=telemetry,
        )
        if tools:
            agent.toolbox = lambda _thread_id: Toolbox(tools)  # type: ignore[assignment]
        return GeneralHarness(
            agent,
            TaskRuntime(
                backend=backend,
                workspace=workspace,
                checkpoints=agent_settings.task_checkpoints,
            ),
        )

    client = TelegramClient(settings, transport=telegram.transport())
    adapter = TelegramAdapter(
        client, settings, agent_settings, harness_factory=factory, telemetry=telemetry
    )
    BUILT.append(adapter)
    return adapter


def text_update(text: str, update_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {"chat": {"id": CHAT}, "from": {"id": ALLOWED}, "text": text},
    }


async def deliver(
    adapter: TelegramAdapter, inbox: FakeInbox, telemetry: Telemetry, update: dict[str, Any]
) -> None:
    """One update through the front door and the worker, as deployed."""

    async def spawn(_update_id: int) -> None:
        return None

    settings = adapter.settings
    await TelegramWebhook(settings, inbox, spawn).accept(
        SECRET, json.dumps(update).encode("utf-8")
    )
    await TelegramUpdateWorker(inbox, adapter, telemetry).run(update["update_id"])


@pytest.fixture
def telemetry(tmp_path: Path):
    opened = Telemetry(SqliteTelemetry(tmp_path / "telemetry.sqlite3"))
    yield opened
    opened.close()


def stored_run(telemetry: Telemetry, run_id: str) -> TurnRun:
    store = telemetry.store
    assert store is not None
    run = store.get_turn(run_id)
    assert run is not None
    return run


def stored_events(telemetry: Telemetry, run_id: str) -> list[TraceEvent]:
    store = telemetry.store
    assert store is not None
    return store.events(run_id)


def the_run_id(inbox: FakeInbox, update_id: int = 1) -> str:
    return inbox.runs[update_id]


# --- one turn, one row -------------------------------------------------------


async def test_one_turn_is_one_row_with_its_real_counts(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    backend = ScriptedBackend(
        route(),
        Completion(text="Two plus two is four.", finish_reason="stop"),
    )
    adapter = build(telegram, tmp_path, backend, telemetry)

    await deliver(adapter, inbox, telemetry, text_update("What is two plus two?"))

    run = stored_run(telemetry, the_run_id(inbox))
    assert (run.status, run.outcome) == ("completed", "answer_delivered")
    assert run.source == "telegram"
    assert run.source_update_id == "1"
    assert run.user_id == canonical_user_id(ALLOWED)
    assert run.thread_id
    assert run.route == "answer"
    # The router and the answer. A turn that counted only the visible half
    # would report every message as costing one request less than it does.
    assert run.model_calls == 2
    assert run.first_visible_ms is not None
    assert run.total_ms is not None and run.total_ms >= 250
    assert run.successful is True


async def test_the_identity_from_ingress_is_the_one_everything_records(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    backend = ScriptedBackend(route(), says("Hello."))
    adapter = build(telegram, tmp_path, backend, telemetry)

    await deliver(adapter, inbox, telemetry, text_update("Hi"))

    run_id = the_run_id(inbox)
    assert run_id
    events = stored_events(telemetry, run_id)
    assert {event.run_id for event in events} == {run_id}
    assert [event.seq for event in events] == sorted(event.seq for event in events)


async def test_a_redelivered_update_is_one_turn_seen_twice(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    backend = ScriptedBackend(route(), says("Hello."), default=says("Hello."))
    adapter = build(telegram, tmp_path, backend, telemetry)

    async def spawn(_update_id: int) -> None:
        return None

    webhook = TelegramWebhook(adapter.settings, inbox, spawn)
    body = json.dumps(text_update("Hi")).encode("utf-8")
    first = await webhook.accept(SECRET, body)
    second = await webhook.accept(SECRET, body)

    assert first.detail == "accepted"
    assert second.detail == "already accepted"
    assert len(inbox.runs) == 1


# --- model and tool detail ---------------------------------------------------


async def test_a_streamed_answer_records_one_first_token_and_the_router_none(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    """TTFT is a boundary the streamed call has and the router does not."""

    telegram, inbox = FakeTelegram(), FakeInbox()
    backend = ScriptedBackend(route(), says("A streamed answer, in pieces."))
    adapter = build(telegram, tmp_path, backend, telemetry)

    await deliver(adapter, inbox, telemetry, text_update("Say something"))

    run_id = the_run_id(inbox)
    first_tokens = [
        event for event in stored_events(telemetry, run_id)
        if event.type == "model_first_token"
    ]
    assert len(first_tokens) == 1
    assert first_tokens[0].data["purpose"] == "answer"
    assert stored_run(telemetry, run_id).first_model_token_ms is not None


async def test_token_counts_add_up_across_every_model_call(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    router = Completion(
        text=json.dumps({"route": "answer", "task": ""}),
        usage=Usage(input_tokens=100, output_tokens=10),
        finish_reason="stop",
    )
    answer = Completion(
        text="Done.",
        usage=Usage(input_tokens=400, output_tokens=40),
        finish_reason="stop",
    )
    adapter = build(telegram, tmp_path, ScriptedBackend(router, answer), telemetry)

    await deliver(adapter, inbox, telemetry, text_update("Anything"))

    run = stored_run(telemetry, the_run_id(inbox))
    assert (run.input_tokens, run.output_tokens) == (500, 50)


async def test_an_executed_tool_has_one_start_and_one_terminal_event(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    tool = Tool(
        name="ping",
        description="answer",
        parameters={"type": "object", "properties": {}},
        run=lambda: "pong",
    )
    backend = ScriptedBackend(route(), calls("ping"), says("It said pong."))
    adapter = build(telegram, tmp_path, backend, telemetry, tools=[tool])

    await deliver(adapter, inbox, telemetry, text_update("Ping it"))

    run_id = the_run_id(inbox)
    types = [event.type for event in stored_events(telemetry, run_id)]
    assert types.count("tool_started") == 1
    assert types.count("tool_finished") == 1
    assert types.count("tool_failed") == 0
    assert stored_run(telemetry, run_id).tool_calls == 1


async def test_a_tool_that_fails_is_not_recorded_as_a_success(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()

    def explode() -> str:
        raise OSError("no such device")

    tool = Tool(
        name="ping",
        description="answer",
        parameters={"type": "object", "properties": {}},
        run=explode,
    )
    backend = ScriptedBackend(route(), calls("ping"), says("It failed."))
    adapter = build(telegram, tmp_path, backend, telemetry, tools=[tool])

    await deliver(adapter, inbox, telemetry, text_update("Ping it"))

    events = stored_events(telemetry, the_run_id(inbox))
    failed = [event for event in events if event.type == "tool_failed"]
    assert [event.data["status"] for event in failed] == ["failed"]
    assert not [event for event in events if event.type == "tool_finished"]


# --- outcomes ----------------------------------------------------------------


async def test_a_turn_that_stops_to_ask_is_successful_not_failed(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    tool = Tool(
        name="wipe",
        description="destroy",
        parameters={"type": "object", "properties": {}},
        run=lambda: "gone",
        destructive=True,
    )
    backend = ScriptedBackend(route(), calls("wipe"))
    adapter = build(telegram, tmp_path, backend, telemetry, tools=[tool])

    await deliver(adapter, inbox, telemetry, text_update("Wipe it"))

    run = stored_run(telemetry, the_run_id(inbox))
    assert run.outcome == "approval_requested"
    assert run.status == "completed"
    assert run.successful is True
    types = [event.type for event in stored_events(telemetry, run.run_id)]
    assert "approval_requested" in types


async def test_a_failed_turn_closes_its_own_row(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    backend = ScriptedBackend(route(), RuntimeError("the model fell over"))
    adapter = build(telegram, tmp_path, backend, telemetry)

    await deliver(adapter, inbox, telemetry, text_update("Anything"))

    run = stored_run(telemetry, the_run_id(inbox))
    assert (run.status, run.outcome) == ("failed", "failed")
    assert run.error_type == "RuntimeError"
    assert run.successful is False
    # The events gathered before the failure are written, not lost with it.
    types = [event.type for event in stored_events(telemetry, run.run_id)]
    assert "model_failed" in types and "turn_failed" in types


async def test_stopping_work_is_cancelled_rather_than_failed(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    telegram, inbox = FakeTelegram(), FakeInbox()
    # A backend that refuses every call, because /stop must reach no model.
    adapter = build(telegram, tmp_path, ScriptedBackend(), telemetry)

    await deliver(adapter, inbox, telemetry, text_update("/stop"))

    run = stored_run(telemetry, the_run_id(inbox))
    assert (run.status, run.outcome) == ("cancelled", "cancelled")
    assert run.model_calls == 0
    assert run.successful is False


async def test_a_free_command_is_not_measured_at_all(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    """`/chats` costs nothing and would outnumber the turns worth measuring."""

    telegram, inbox = FakeTelegram(), FakeInbox()
    adapter = build(telegram, tmp_path, ScriptedBackend(), telemetry)

    await deliver(adapter, inbox, telemetry, text_update("/chats"))

    store = telemetry.store
    assert store is not None
    assert store.get_turn(the_run_id(inbox)) is None


# --- the rules the recorder itself has to obey -------------------------------


async def test_telemetry_that_fails_does_not_fail_the_turn(
    tmp_path: Path
) -> None:
    class Broken(SqliteTelemetry):
        def start_turn(self, run: TurnRun) -> None:
            raise RuntimeError("telemetry is down")

        def finish_turn(self, run: TurnRun) -> None:
            raise RuntimeError("telemetry is down")

        def record_events(self, events: Sequence[TraceEvent]) -> None:
            raise RuntimeError("telemetry is down")

    telemetry = Telemetry(Broken(tmp_path / "telemetry.sqlite3"))
    telegram, inbox = FakeTelegram(), FakeInbox()
    backend = ScriptedBackend(route(), says("The answer survives."))
    adapter = build(telegram, tmp_path, backend, telemetry)

    await deliver(adapter, inbox, telemetry, text_update("Anything"))
    telemetry.close()

    assert "The answer survives." in telegram.sent


async def test_no_conversation_content_reaches_telemetry(
    tmp_path: Path, telemetry: Telemetry
) -> None:
    """Timings and counts. Not what anybody said."""

    telegram, inbox = FakeTelegram(), FakeInbox()
    tool = Tool(
        name="ping",
        description="answer",
        parameters={"type": "object", "properties": {}},
        run=lambda: "the secret tool result",
    )
    backend = ScriptedBackend(route(), calls("ping"), says("The private answer."))
    adapter = build(telegram, tmp_path, backend, telemetry, tools=[tool])

    await deliver(adapter, inbox, telemetry, text_update("My private question"))

    run_id = the_run_id(inbox)
    run = stored_run(telemetry, run_id)
    written = json.dumps(
        [run.__dict__, [event.__dict__ for event in stored_events(telemetry, run_id)]],
        default=str,
    )
    for secret in (
        "My private question",
        "The private answer.",
        "the secret tool result",
        str(ALLOWED),
    ):
        assert secret not in written


def test_a_null_trace_records_nothing_and_costs_nothing() -> None:
    """Every path without telemetry keeps working, including the tests."""

    from app.telemetry import NO_TRACE

    NO_TRACE.event("anything")
    NO_TRACE.start()
    with NO_TRACE.model("answer") as measured:
        measured.first_token()
    NO_TRACE.finish("answer_delivered")

    assert NO_TRACE.run.run_id == ""
