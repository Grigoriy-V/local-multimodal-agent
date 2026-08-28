"""The Telegram adapter, driven without a network or a model endpoint.

Telegram is replaced by an `httpx.MockTransport` so the real wire format in
`ui/telegram/api.py` is exercised rather than mocked away, and the model is the
shared `ScriptedBackend`. Nothing here reaches outside the process.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agent.harness import GeneralHarness
from app.agent.runtime import Agent
from app.agent.task_graph import (
    CheckResult,
    ImplementationResult,
    TaskOutcome,
)
# Aliased: pytest tries to collect any imported name starting with "Test".
from app.agent.task_graph import TestReport as Report
from app.agent.task_runtime import TaskRuntime, TaskView
from app.config import AgentSettings, TelegramSettings
from app.memory import SqliteStore
from app.models import Completion, ContentPart, Message, ToolCall
from tests.fakes import ScriptedBackend, says
from ui.telegram.adapter import (
    REFUSAL,
    TelegramAdapter,
    canonical_user_id,
    current_thread,
    start_thread,
    task_result_text,
)
from ui.telegram.wire import MODEL_FREE_COMMANDS, read_update
from ui.telegram.api import (
    MAX_MESSAGE_CHARS,
    Formatted,
    TelegramClient,
    split_message,
)

ALLOWED = 4242
STRANGER = 9999
CHAT = 1000


def route(text: str = "", task: str = "") -> Completion:
    """A router answer, which the harness always asks for first."""

    payload = {"route": "act" if task else "answer", "task": task}
    return Completion(text=json.dumps(payload), finish_reason="stop")


class FakeTelegram:
    """Records every Bot API call and answers it the way Telegram would."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sent: list[str] = []
        self.keyboards: list[dict[str, Any]] = []
        self.documents: list[str] = []
        self.photos: list[str] = []
        self.files: dict[str, bytes] = {}
        self._next_message_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/file/bot" in path:
            name = path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=self.files.get(name, b""))

        method = path.rsplit("/", 1)[-1]
        if method in {"sendDocument", "sendPhoto"}:
            # Uploads are multipart, so the filename is read off the body rather
            # than from JSON like every other call.
            body = request.content.decode("latin-1")
            name = body.partition('filename="')[2].partition('"')[0]
            (self.photos if method == "sendPhoto" else self.documents).append(name)
            self.calls.append((method, {}))
            return httpx.Response(200, json={"ok": True, "result": {}})

        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if method == "sendMessage":
            self.sent.append(payload["text"])
            if payload.get("reply_markup"):
                self.keyboards.append(payload["reply_markup"])
            self._next_message_id += 1
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": self._next_message_id}}
            )
        if method == "getFile":
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": payload["file_id"]}}
            )
        return httpx.Response(200, json={"ok": True, "result": {}})


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def settings() -> TelegramSettings:
    return TelegramSettings(token="test-token", allowed_users=str(ALLOWED))


BUILT: list[TelegramAdapter] = []


@pytest.fixture(autouse=True)
async def close_adapters():
    """Close every adapter a test built.

    An adapter owns a harness per user, and a harness owns SQLite connections
    and a checkpoint file; leaving them open leaks worker threads into the next
    test and makes the suite's failures depend on its order.
    """

    yield
    while BUILT:
        adapter = BUILT.pop()
        await adapter.aclose()
        await adapter.client.aclose()


def build(
    telegram: FakeTelegram,
    settings: TelegramSettings,
    tmp_path: Path,
    backend: ScriptedBackend,
) -> TelegramAdapter:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    agent_settings = AgentSettings(
        database=str(tmp_path / "memory.sqlite3"),
        checkpoints=str(tmp_path / "checkpoints.sqlite3"),
        task_checkpoints=str(tmp_path / "tasks.sqlite3"),
        workspace=str(workspace),
    )

    def factory(user_id: str) -> GeneralHarness:
        agent = Agent(
            backend,
            SqliteStore(agent_settings.database),
            workspace,
            checkpoints=agent_settings.checkpoints,
            user_id=user_id,
        )
        return GeneralHarness(
            agent,
            TaskRuntime(
                backend=backend,
                workspace=workspace,
                checkpoints=agent_settings.task_checkpoints,
            ),
        )

    client = TelegramClient(settings, transport=telegram.transport())
    adapter = TelegramAdapter(client, settings, agent_settings, harness_factory=factory)
    BUILT.append(adapter)
    return adapter


def text_update(text: str, sender: int = ALLOWED, update_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {"chat": {"id": CHAT}, "from": {"id": sender}, "text": text},
    }


# --- identity ----------------------------------------------------------------


def test_a_telegram_id_is_mapped_not_adopted() -> None:
    """The canonical identifier must not be Telegram's own."""

    derived = canonical_user_id(ALLOWED)

    assert derived != str(ALLOWED)
    assert str(ALLOWED) not in derived
    assert derived == canonical_user_id(ALLOWED)
    assert derived != canonical_user_id(ALLOWED + 1)


def test_the_open_conversation_is_the_newest_one(tmp_path: Path) -> None:
    with SqliteStore(tmp_path / "m.sqlite3") as store:
        user_id = canonical_user_id(ALLOWED)
        first = current_thread(store, user_id)

        assert current_thread(store, user_id) == first

        second = start_thread(store, user_id)
        assert second != first
        assert current_thread(store, user_id) == second


def test_a_new_conversation_survives_reopening_the_store(tmp_path: Path) -> None:
    path = tmp_path / "m.sqlite3"
    user_id = canonical_user_id(ALLOWED)
    with SqliteStore(path) as store:
        started = start_thread(store, user_id)

    with SqliteStore(path) as reopened:
        assert current_thread(reopened, user_id) == started


# --- reading updates ---------------------------------------------------------


def test_a_plain_message_is_read() -> None:
    incoming = read_update(text_update("hello"))

    assert incoming is not None
    assert (incoming.chat_id, incoming.telegram_user_id, incoming.text) == (CHAT, ALLOWED, "hello")


def test_the_largest_photo_size_is_the_one_taken() -> None:
    update = {
        "message": {
            "chat": {"id": CHAT},
            "from": {"id": ALLOWED},
            "caption": "look at this",
            "photo": [{"file_id": "small"}, {"file_id": "large"}],
        }
    }

    incoming = read_update(update)

    assert incoming is not None
    assert incoming.text == "look at this"
    assert incoming.files == (("large", "photo.jpg", "image/jpeg"),)


def test_a_callback_carries_its_answer() -> None:
    update = {
        "callback_query": {
            "id": "cb1",
            "from": {"id": ALLOWED},
            "data": "task:yes",
            "message": {"chat": {"id": CHAT}},
        }
    }

    incoming = read_update(update)

    assert incoming is not None
    assert (incoming.callback_id, incoming.callback_data) == ("cb1", "task:yes")


@pytest.mark.parametrize(
    "update", [{}, {"message": {}}, {"edited_message": {"text": "x"}}, {"message": {"text": "x"}}]
)
def test_an_unusable_update_is_ignored(update: dict[str, Any]) -> None:
    assert read_update(update) is None


# --- access ------------------------------------------------------------------


async def test_a_stranger_is_refused_and_nothing_is_processed(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    backend = ScriptedBackend()
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("let me in", sender=STRANGER))

    assert telegram.sent == [REFUSAL]
    assert backend.requests == []


async def test_open_access_admits_a_stranger(
    telegram: FakeTelegram, tmp_path: Path
) -> None:
    opened = TelegramSettings(token="test-token", allowed_users="", open_access=True)
    backend = ScriptedBackend(route(), says("Hello, stranger."), default=says("summary"))
    adapter = build(telegram, opened, tmp_path, backend)

    await adapter.handle_update(text_update("hello", sender=STRANGER))

    assert "Hello, stranger." in telegram.sent
    assert REFUSAL not in telegram.sent


async def test_open_access_still_separates_the_people_it_admits(
    telegram: FakeTelegram, tmp_path: Path
) -> None:
    """Admitting everyone is not the same as merging them."""

    opened = TelegramSettings(token="test-token", allowed_users="", open_access=True)
    backend = ScriptedBackend(
        route(), says("one"), route(), says("two"), default=says("summary")
    )
    adapter = build(telegram, opened, tmp_path, backend)

    await adapter.handle_update(text_update("mine", sender=ALLOWED))
    await adapter.handle_update(text_update("theirs", sender=STRANGER))

    store = SqliteStore(tmp_path / "memory.sqlite3")
    try:
        assert len(store.threads(canonical_user_id(ALLOWED))) == 1
        assert len(store.threads(canonical_user_id(STRANGER))) == 1
        assert canonical_user_id(ALLOWED) != canonical_user_id(STRANGER)
    finally:
        store.close()


async def test_open_access_is_never_the_default() -> None:
    assert TelegramSettings(token="t").open_access is False


async def test_an_empty_allow_list_admits_nobody(
    telegram: FakeTelegram, tmp_path: Path
) -> None:
    closed = TelegramSettings(token="test-token", allowed_users="")
    adapter = build(telegram, closed, tmp_path, ScriptedBackend())

    assert adapter.allows(ALLOWED) is False

    await adapter.handle_update(text_update("hello"))

    assert telegram.sent == [REFUSAL]


# --- the answer branch -------------------------------------------------------


async def test_an_ordinary_message_is_answered_into_the_chat(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    backend = ScriptedBackend(route(), says("Hello back."), default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("hello"))

    assert "Hello back." in telegram.sent


async def test_media_the_agent_produced_reaches_the_chat(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """A browser screenshot lives in the message, not in an on-disk artifact.

    The model cannot be scripted to emit one, so the delivery step is driven
    directly; before this existed the picture stopped at the store.
    """

    adapter = build(telegram, settings, tmp_path, ScriptedBackend(default=says("x")))
    produced = Message(
        role="assistant",
        content=[
            ContentPart(kind="text", text="Here is the page."),
            ContentPart(kind="image", data=b"\x89PNG", media_type="image/png"),
        ],
    )

    await adapter._deliver(CHAT, produced)

    assert "Here is the page." in telegram.sent
    assert telegram.photos == ["image-2.png"]
    assert telegram.documents == []


async def test_non_image_media_is_sent_as_a_document(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    adapter = build(telegram, settings, tmp_path, ScriptedBackend(default=says("x")))
    produced = Message(
        role="assistant",
        content=[ContentPart(kind="audio", data=b"RIFF", media_type="audio/wav")],
    )

    await adapter._deliver(CHAT, produced)

    assert telegram.documents == ["audio-1.wav"]
    assert telegram.photos == []


async def test_the_conversation_is_stored_under_the_mapped_user(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    backend = ScriptedBackend(route(), says("Noted."), default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("remember this"))

    store = SqliteStore(tmp_path / "memory.sqlite3")
    try:
        threads = store.threads(canonical_user_id(ALLOWED))
        assert len(threads) == 1
        assert store.threads(canonical_user_id(STRANGER)) == []
    finally:
        store.close()


async def test_new_starts_a_separate_conversation(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    backend = ScriptedBackend(
        route(), says("first"), route(), says("second"), default=says("summary")
    )
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("one"))
    await adapter.handle_update(text_update("/new"))
    await adapter.handle_update(text_update("two"))

    store = SqliteStore(tmp_path / "memory.sqlite3")
    try:
        assert len(store.threads(canonical_user_id(ALLOWED))) == 2
    finally:
        store.close()


async def test_help_does_not_reach_the_model(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    backend = ScriptedBackend()
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("/help"))

    assert backend.requests == []
    assert telegram.sent and "/new" in telegram.sent[0]


# --- attachments -------------------------------------------------------------


async def test_a_photo_becomes_model_input(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    telegram.files["large"] = b"\x89PNG-bytes"
    backend = ScriptedBackend(route(), says("A picture."), default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(
        {
            "message": {
                "chat": {"id": CHAT},
                "from": {"id": ALLOWED},
                "caption": "what is this",
                "photo": [{"file_id": "small"}, {"file_id": "large"}],
            }
        }
    )

    kinds = [part.kind for request in backend.requests for m in request for part in m.content]
    assert "image" in kinds
    assert "A picture." in telegram.sent


async def test_a_document_is_saved_and_named_rather_than_pasted_into_the_turn(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """The bytes never reach the model; the name and the tool do.

    A long document pasted into a turn spends the context before the model has
    decided which part of it mattered, so it is saved and read on demand.
    """

    telegram.files["doc1"] = b"%PDF-1.7 pretend"
    backend = ScriptedBackend(route(), says("Read it."), default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(
        {
            "message": {
                "chat": {"id": CHAT},
                "from": {"id": ALLOWED},
                "caption": "what does it say",
                "document": {
                    "file_id": "doc1",
                    "file_name": "notes.pdf",
                    "mime_type": "application/pdf",
                },
            }
        }
    )

    saved = list(tmp_path.rglob("notes.pdf"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"%PDF-1.7 pretend"
    sent_text = [
        part.text or ""
        for request in backend.requests
        for message in request
        for part in message.content
    ]
    assert any("notes.pdf" in text for text in sent_text)
    assert any("read_document" in text for text in sent_text)
    assert b"%PDF" not in b"".join(
        part.data or b""
        for request in backend.requests
        for message in request
        for part in message.content
    )


async def test_an_unsupported_upload_is_still_refused_before_the_model(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """Accepting documents is not accepting everything.

    A format nothing here can read must fail at the door rather than land in the
    workspace, or the workspace becomes a place unopened files accumulate.
    """

    telegram.files["doc1"] = b"MZ-executable"
    backend = ScriptedBackend()
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(
        {
            "message": {
                "chat": {"id": CHAT},
                "from": {"id": ALLOWED},
                "document": {
                    "file_id": "doc1",
                    "file_name": "tool.exe",
                    "mime_type": "application/x-msdownload",
                },
            }
        }
    )

    assert backend.requests == []
    assert any("Upload refused" in sent for sent in telegram.sent)
    assert not list(tmp_path.rglob("tool.exe"))


# --- the act branch ----------------------------------------------------------


async def test_a_work_request_asks_before_touching_the_workspace(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    plan = Completion(
        text=json.dumps(
            {
                "summary": "Create the file",
                "steps": ["write notes.txt"],
                "acceptance_criteria": ["notes.txt exists"],
                "validation_strategy": [
                    {
                        "criterion": "notes.txt exists",
                        "evidence": "list the directory",
                        "capabilities": ["filesystem.read"],
                    }
                ],
            }
        ),
        finish_reason="stop",
    )
    backend = ScriptedBackend(route(task="create notes.txt"), plan, default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("create notes.txt in the workspace"))

    assert telegram.keyboards, "the workspace grant must be offered as a choice"
    buttons = telegram.keyboards[-1]["inline_keyboard"][0]
    assert [button["callback_data"] for button in buttons] == ["task:yes", "task:no"]
    assert any("Acceptance criteria" in sent for sent in telegram.sent)


async def test_declining_the_grant_stops_the_task(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    plan = Completion(
        text=json.dumps(
            {
                "summary": "Create the file",
                "steps": ["write notes.txt"],
                "acceptance_criteria": ["notes.txt exists"],
                "validation_strategy": [
                    {
                        "criterion": "notes.txt exists",
                        "evidence": "list the directory",
                        "capabilities": ["filesystem.read"],
                    }
                ],
            }
        ),
        finish_reason="stop",
    )
    backend = ScriptedBackend(route(task="create notes.txt"), plan, default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)
    await adapter.handle_update(text_update("create notes.txt"))

    await adapter.handle_update(
        {
            "callback_query": {
                "id": "cb1",
                "from": {"id": ALLOWED},
                "data": "task:no",
                "message": {"chat": {"id": CHAT}},
            }
        }
    )

    assert any("declined" in sent.lower() for sent in telegram.sent)
    assert not (tmp_path / "workspace" / "notes.txt").exists()


# --- robustness --------------------------------------------------------------


async def test_a_failing_turn_answers_instead_of_killing_the_bot(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    backend = ScriptedBackend(route(), RuntimeError("model exploded"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("hello"))

    assert any("failed" in sent for sent in telegram.sent)


# --- what the person reads ---------------------------------------------------


async def test_can_is_answered_from_the_wiring_and_never_by_the_model(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """The check has to be worth trusting, so no model and no GPU touch it."""

    backend = ScriptedBackend()
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("/can"))

    assert backend.requests == []
    answer = telegram.sent[0]
    assert "inspect_page" in answer
    assert "image/png" in answer
    assert "Ask first: write_file, edit_file" in answer


async def test_a_batch_of_tool_calls_arrives_as_one_message(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    adapter = build(telegram, settings, tmp_path, ScriptedBackend(default=says("x")))
    produced = Message(
        role="assistant",
        content=[],
        tool_calls=(
            ToolCall(id="a", name="read_file", arguments={}),
            ToolCall(id="b", name="list_files", arguments={}),
        ),
    )

    await adapter._deliver(CHAT, produced)

    assert telegram.sent == ["· read_file\n· list_files"]


async def test_a_formatted_message_marks_its_own_headings_and_escapes_the_rest(
    telegram: FakeTelegram, settings: TelegramSettings
) -> None:
    client = TelegramClient(settings, transport=telegram.transport())
    try:
        await client.send_message(
            CHAT, Formatted.build([("Result", "wrote <b>a & b</b>")])
        )
    finally:
        await client.aclose()

    _, payload = telegram.calls[-1]
    assert payload["parse_mode"] == "HTML"
    assert payload["text"] == "<b>Result</b>\nwrote &lt;b&gt;a &amp; b&lt;/b&gt;"


async def test_a_formatted_message_too_long_to_send_whole_arrives_plain(
    telegram: FakeTelegram, settings: TelegramSettings
) -> None:
    """A cut tag makes Telegram refuse the message; unstyled text is the price."""

    client = TelegramClient(settings, transport=telegram.transport())
    long_body = "\n".join(f"line {index}" for index in range(1200))
    try:
        await client.send_message(CHAT, Formatted.build([("Result", long_body)]))
    finally:
        await client.aclose()

    assert len(telegram.sent) > 1
    assert all("parse_mode" not in payload for _, payload in telegram.calls)
    assert "<b>" not in "".join(telegram.sent)
    assert telegram.sent[0].startswith("Result\nline 0")


def test_the_finished_task_leads_with_the_result_then_its_evidence() -> None:
    view = TaskView(
        subdirectory=".",
        grant=None,
        plan=None,
        implementation=ImplementationResult("wrote square.html", tool_calls=3),
        outcome=TaskOutcome(
            status="completed",
            summary="all criteria passed",
            iterations=1,
            tool_calls=7,
            elapsed_seconds=1.0,
            artifacts=("square.html",),
        ),
        report=Report(
            checks=(
                CheckResult(name="the file exists", passed=True, detail="listed"),
                CheckResult(name="it is green", passed=False, detail="not observed"),
            )
        ),
    )

    shown = task_result_text(view, "unused")

    assert isinstance(shown, Formatted)
    assert shown.plain.startswith("Result\nwrote square.html")
    assert "✓ the file exists" in shown.plain
    assert "✗ it is green" in shown.plain
    assert "square.html" in shown.plain
    assert "completed · 1 iteration(s) · 7 tool call(s)" in shown.plain


def test_a_task_that_produced_no_outcome_still_says_something() -> None:
    view = TaskView(
        subdirectory=".",
        grant=None,
        plan=None,
        implementation=None,
        outcome=None,
        report=None,
    )

    assert task_result_text(view, "the task produced no result") == (
        "the task produced no result"
    )


def test_a_long_answer_is_split_rather_than_refused() -> None:
    text = "\n".join(f"line {index}" for index in range(1200))

    pieces = split_message(text)

    assert len(pieces) > 1
    assert all(len(piece) <= MAX_MESSAGE_CHARS for piece in pieces)
    assert "".join(piece.replace("\n", "") for piece in pieces) == text.replace("\n", "")


def test_a_short_answer_is_left_alone() -> None:
    assert split_message("just this") == ["just this"]


@pytest.mark.parametrize("command", sorted(MODEL_FREE_COMMANDS))
async def test_every_command_declared_model_free_really_is(
    command: str, telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """The webhook trusts this list to decide whether to spend a GPU wake.

    That list lives in `wire.py`, next to the front door, and the commands live
    here — so without this the two drift apart silently and the bill is what
    notices. `ScriptedBackend()` has nothing scripted, so any model call raises.
    """

    backend = ScriptedBackend()
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update(command))

    assert backend.requests == []
    assert telegram.sent, f"{command} answered nothing"


# --- progress ----------------------------------------------------------------


async def test_a_turn_that_reaches_the_model_says_it_is_working(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """Most of a cold turn is spent waiting for a GPU, where the only honest
    thing to show is that the assistant is still there."""

    backend = ScriptedBackend(route(), says("Hello."), default=says("summary"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("hello"))

    actions = [payload for method, payload in telegram.calls if method == "sendChatAction"]
    assert actions and actions[0]["action"] == "typing"


async def test_a_command_does_not_pretend_to_be_working(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """It answers from storage and is finished before an indicator would show."""

    adapter = build(telegram, settings, tmp_path, ScriptedBackend())

    await adapter.handle_update(text_update("/help"))

    assert [method for method, _ in telegram.calls if method == "sendChatAction"] == []


async def test_the_indicator_stops_when_the_turn_fails(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """A renewing task outliving its turn is a leak in a container about to be
    frozen, and the failing path is where that is easiest to forget."""

    backend = ScriptedBackend(route(), RuntimeError("model exploded"))
    adapter = build(telegram, settings, tmp_path, backend)

    await adapter.handle_update(text_update("hello"))

    running = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]

    assert running == []
    assert any("failed" in message for message in telegram.sent)


async def test_a_page_a_tool_rendered_stays_internal(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    """Observation is evidence for the agent, not an adapter send decision."""

    adapter = build(telegram, settings, tmp_path, ScriptedBackend(default=says("x")))
    produced = Message(
        role="tool",
        content=[
            ContentPart(kind="text", text="notes.pdf: page 1 of 3"),
            ContentPart(kind="image", data=b"rendered-page", media_type="image/png"),
        ],
        tool_call_id="call-1",
    )

    await adapter._deliver(CHAT, produced)

    assert telegram.photos == []
    assert not any("page 1 of 3" in sent for sent in telegram.sent)


async def test_a_file_the_agent_explicitly_selected_reaches_the_person(
    telegram: FakeTelegram, settings: TelegramSettings, tmp_path: Path
) -> None:
    adapter = build(telegram, settings, tmp_path, ScriptedBackend(default=says("x")))
    produced = Message(
        role="tool",
        content=[
            ContentPart(kind="text", text="Selected page.png for delivery."),
            ContentPart(
                kind="image",
                data=b"rendered-page",
                media_type="image/png",
                name="page.png",
                outbound=True,
            ),
        ],
        tool_call_id="send-1",
    )

    await adapter._deliver(CHAT, produced)

    assert telegram.photos == ["page.png"]
    assert not any("Selected page.png" in sent for sent in telegram.sent)
