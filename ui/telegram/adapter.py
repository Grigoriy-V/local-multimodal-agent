"""Telegram in front of the harness.

This file adapts between Telegram's world and the project's own: an update
becomes a `Message`, harness output becomes chat messages, and a consent
question becomes two buttons. It holds no logic about routing, tools, memory or
validation — that lives in `app/`, which is why a second interface can exist
without moving any of it.

Two properties here are load-bearing for the deployed profile.

*Identity is mapped, never adopted.* A Telegram chat or user id is an input to
the derivation below, not the canonical identifier. Storing Telegram's own ids
as thread ids would mean a second interface could never address the same
conversation, and that is expensive to undo later rather than now.

*Accepting an update is separate from answering it.* `handle_update` is a plain
coroutine over one update; nothing in it assumes a caller that can be kept
waiting. Local polling drives it in `run.py`; a deployed webhook will hand the
same call to a spawned worker and answer Telegram immediately.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.harness import GeneralHarness
from app.agent.runtime import create_agent
from app.agent.task_runtime import TaskProgress, TaskRuntime, TaskView
from app.attachments import AttachmentBytes, AttachmentError, load_attachment_bytes
from app.config import AgentSettings, TelegramSettings
from app.memory import ConversationStore
from app.models import ContentPart, Message
from ui.telegram.api import TelegramClient, TelegramError, approval_keyboard

# A fixed namespace so a chat maps to the same canonical identity on every run
# and on every machine. Changing it orphans every existing conversation.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "local-multimodal-agent:telegram")

REFUSAL = (
    "This assistant is private and your account is not on its allowed list. "
    "Nothing you send here is processed."
)
HELP = (
    "Send a message and I will answer, or ask for work and I will plan it, "
    "ask before touching the workspace, and report what happened.\n\n"
    "/new — start a fresh conversation\n"
    "/stop — stop the task running in this chat"
)

PHOTO_MEDIA_TYPE = "image/jpeg"
VOICE_MEDIA_TYPE = "audio/ogg"


def canonical_user_id(telegram_user_id: int) -> str:
    """The application's own identifier for a Telegram account."""

    return str(uuid.uuid5(NAMESPACE, f"user:{telegram_user_id}"))


def current_thread(store: ConversationStore, user_id: str) -> str:
    """This user's open conversation, created if they have none yet.

    The newest thread is the open one. `/new` therefore only has to create an
    empty thread for it to become current, which keeps the mapping in the store
    rather than in memory that a restart would lose.
    """

    existing = store.threads(user_id)
    if existing:
        return existing[0].id
    return start_thread(store, user_id)


def start_thread(store: ConversationStore, user_id: str) -> str:
    thread_id = str(uuid.uuid4())
    store.ensure_thread(thread_id, user_id)
    return thread_id


def spoken(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content if part.kind == "text").strip()


@dataclass(frozen=True)
class Incoming:
    """One Telegram update, reduced to what the application needs."""

    chat_id: int
    telegram_user_id: int
    text: str
    files: tuple[tuple[str, str, str], ...] = ()  # (file_id, name, media_type)
    callback_id: str | None = None
    callback_data: str | None = None


def read_update(update: dict[str, Any]) -> Incoming | None:
    """Reduce a raw update, or return `None` for one this adapter ignores."""

    callback = update.get("callback_query")
    if callback:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        sender = callback.get("from") or {}
        if not chat.get("id") or not sender.get("id"):
            return None
        return Incoming(
            chat_id=int(chat["id"]),
            telegram_user_id=int(sender["id"]),
            text="",
            callback_id=str(callback.get("id", "")),
            callback_data=str(callback.get("data", "")),
        )

    message = update.get("message")
    if not message:
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if not chat.get("id") or not sender.get("id"):
        return None

    files: list[tuple[str, str, str]] = []
    photos = message.get("photo") or []
    if photos:
        # Telegram sends every rendered size; the last is the largest.
        largest = photos[-1]
        files.append((str(largest["file_id"]), "photo.jpg", PHOTO_MEDIA_TYPE))
    voice = message.get("voice")
    if voice:
        files.append(
            (str(voice["file_id"]), "voice.ogg", str(voice.get("mime_type") or VOICE_MEDIA_TYPE))
        )
    audio = message.get("audio")
    if audio:
        files.append(
            (
                str(audio["file_id"]),
                str(audio.get("file_name") or "audio"),
                str(audio.get("mime_type") or ""),
            )
        )
    document = message.get("document")
    if document:
        files.append(
            (
                str(document["file_id"]),
                str(document.get("file_name") or "document"),
                str(document.get("mime_type") or ""),
            )
        )

    return Incoming(
        chat_id=int(chat["id"]),
        telegram_user_id=int(sender["id"]),
        text=str(message.get("text") or message.get("caption") or ""),
        files=tuple(files),
    )


def task_plan_text(view: TaskView, workspace: Path) -> str:
    if view.plan is None:
        return "Task planning did not produce a plan."
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(view.plan.steps, 1))
    criteria = "\n".join(f"- {item}" for item in view.plan.acceptance_criteria)
    permissions = ", ".join((view.interrupt or {}).get("permissions", []))
    return (
        f"Plan\n\n{view.plan.summary}\n\n{steps}\n\n"
        f"Acceptance criteria\n{criteria}\n\n"
        f"Scope: {workspace}\n"
        f"Capabilities: {permissions}\n\nRun this plan?"
    )


def progress_text(progress: TaskProgress) -> str:
    labels = {
        "approval": "Approval",
        "implementation": "Implementation",
        "validation": "Validation",
        "evaluation": "Evaluation",
        "repair": "Repair",
        "finalization": "Finalization",
    }
    return f"{labels[progress.stage]}: {progress.detail}"


class TelegramAdapter:
    """Turn Telegram updates into harness work, for allowed accounts only."""

    def __init__(
        self,
        client: TelegramClient,
        settings: TelegramSettings | None = None,
        agent_settings: AgentSettings | None = None,
        harness_factory: Callable[[str], GeneralHarness] | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or TelegramSettings()
        self.agent_settings = agent_settings or AgentSettings()
        # Supplied by tests so a turn can be driven without a model endpoint.
        self.harness_factory = harness_factory or self._default_harness
        self._harnesses: dict[str, GeneralHarness] = {}

    def _default_harness(self, user_id: str) -> GeneralHarness:
        agent = create_agent(agent_settings=self.agent_settings, user_id=user_id)
        return GeneralHarness(
            agent,
            TaskRuntime(
                backend=agent.backend,
                workspace=agent.workspace,
                checkpoints=self.agent_settings.task_checkpoints,
            ),
        )

    # --- identity and access -------------------------------------------------

    def allows(self, telegram_user_id: int) -> bool:
        """Whether this account may use the assistant.

        Open access admits everyone. It does not merge them: each account still
        maps to its own canonical user, so conversations and memory stay
        separate. What they do share is one workspace and one GPU.
        """

        return self.settings.open_access or telegram_user_id in self.settings.allowed

    def harness(self, user_id: str) -> GeneralHarness:
        """One harness per person, because an `Agent` works for one owner."""

        if user_id not in self._harnesses:
            self._harnesses[user_id] = self.harness_factory(user_id)
        return self._harnesses[user_id]

    # --- inbound -------------------------------------------------------------

    async def to_message(self, incoming: Incoming) -> Message:
        parts: list[ContentPart] = []
        if incoming.text:
            parts.append(ContentPart(kind="text", text=incoming.text))
        uploads = [
            AttachmentBytes(
                name=name,
                media_type=media_type or None,
                data=await self.client.download(file_id),
            )
            for file_id, name, media_type in incoming.files
        ]
        parts.extend(load_attachment_bytes(uploads))
        if not parts:
            raise AttachmentError("the message has no text or usable attachments")
        return Message(role="user", content=parts)

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Handle one update to completion. Never raises at the transport."""

        incoming = read_update(update)
        if incoming is None:
            return
        if not self.allows(incoming.telegram_user_id):
            if incoming.callback_id:
                await self.client.answer_callback(incoming.callback_id, "Not allowed")
            else:
                await self.client.send_message(incoming.chat_id, REFUSAL)
            return

        user_id = canonical_user_id(incoming.telegram_user_id)
        harness = self.harness(user_id)
        try:
            if incoming.callback_data is not None:
                await self._on_callback(harness, user_id, incoming)
            else:
                await self._on_message(harness, user_id, incoming)
        except TelegramError:
            raise
        except Exception as error:  # noqa: BLE001 - a failed turn must not kill the bot
            await self.client.send_message(
                incoming.chat_id, f"That request failed: {type(error).__name__}: {error}"
            )

    async def _on_message(
        self, harness: GeneralHarness, user_id: str, incoming: Incoming
    ) -> None:
        store = harness.agent.store
        command = incoming.text.strip().lower()
        if command in {"/start", "/help"}:
            await self.client.send_message(incoming.chat_id, HELP)
            return
        if command == "/new":
            start_thread(store, user_id)
            await self.client.send_message(incoming.chat_id, "Started a new conversation.")
            return
        if command == "/stop":
            result = await harness.cancel_task(current_thread(store, user_id))
            await self.client.send_message(
                incoming.chat_id,
                spoken(result) if result is not None else "Nothing is running.",
            )
            return

        try:
            message = await self.to_message(incoming)
        except AttachmentError as error:
            await self.client.send_message(incoming.chat_id, f"Upload refused: {error}.")
            return

        thread_id = current_thread(store, user_id)
        decision = await harness.decide(thread_id, message)
        if decision.route == "act":
            await self._start_task(harness, incoming.chat_id, thread_id, message, decision.task)
            return
        await self._answer(harness, incoming.chat_id, thread_id, message)

    # --- the answer branch ---------------------------------------------------

    async def _answer(
        self, harness: GeneralHarness, chat_id: int, thread_id: str, message: Message
    ) -> None:
        async for produced in harness.agent.steps(thread_id, message):
            await self._deliver(chat_id, produced)
        await self._ask_pending_calls(harness, chat_id, thread_id)

    async def _deliver(self, chat_id: int, produced: Message) -> None:
        body = spoken(produced)
        if produced.role == "tool":
            return
        if body:
            await self.client.send_message(chat_id, body)
        for call in produced.tool_calls:
            await self.client.send_message(chat_id, f"· {call.name}")

    async def _ask_pending_calls(
        self, harness: GeneralHarness, chat_id: int, thread_id: str
    ) -> None:
        """Put the graph's own consent question in front of the user.

        The question lives in the checkpoint, not here, so a restart between
        asking and answering loses nothing.
        """

        pending = await harness.agent.pending(thread_id)
        for call in pending or []:
            await self.client.send_message(
                chat_id,
                f"Run {call['name']}?\n{call['arguments']}",
                approval_keyboard(f"call:yes:{call['id']}", f"call:no:{call['id']}"),
            )

    # --- the act branch ------------------------------------------------------

    async def _start_task(
        self,
        harness: GeneralHarness,
        chat_id: int,
        thread_id: str,
        original: Message,
        task: str,
    ) -> None:
        await self.client.send_message(chat_id, "Planning…")
        view = await harness.start_task(thread_id, original, task)
        if view.interrupt is not None:
            await self.client.send_message(
                chat_id,
                task_plan_text(view, harness.tasks.workspace),
                approval_keyboard("task:yes", "task:no"),
            )
            return
        await self._finish_task(harness, chat_id, thread_id, view)

    async def _run_task(
        self, harness: GeneralHarness, chat_id: int, thread_id: str, approved: bool
    ) -> None:
        if not approved:
            view = await harness.resume_task(thread_id, False)
            await self._finish_task(harness, chat_id, thread_id, view)
            return
        sent = await self.client.send_message(chat_id, "Approved; working…")
        lines = ["Approved; working…"]
        async for progress in harness.resume_task_with_progress(thread_id, True):
            lines.append(progress_text(progress))
            if sent:
                await self.client.edit_message(chat_id, int(sent["message_id"]), "\n".join(lines))
        await self._finish_task(harness, chat_id, thread_id, await harness.task_view(thread_id))

    async def _finish_task(
        self, harness: GeneralHarness, chat_id: int, thread_id: str, view: TaskView
    ) -> None:
        result = harness.finish_task(thread_id, view)
        await self.client.send_message(chat_id, spoken(result) or "The task produced no result.")
        for artifact in (view.outcome.artifacts if view.outcome else ()):
            try:
                path = harness.tasks.artifact_path(view, artifact)
                data = path.read_bytes()
            except (OSError, PermissionError, ValueError):
                continue
            await self.client.send_document(chat_id, path.name, data)

    # --- consent answers -----------------------------------------------------

    async def _on_callback(
        self, harness: GeneralHarness, user_id: str, incoming: Incoming
    ) -> None:
        data = incoming.callback_data or ""
        thread_id = current_thread(harness.agent.store, user_id)
        if incoming.callback_id:
            await self.client.answer_callback(incoming.callback_id)

        if data.startswith("task:"):
            await self._run_task(harness, incoming.chat_id, thread_id, data == "task:yes")
            return
        if data.startswith("call:"):
            _, verdict, call_id = data.split(":", 2)
            async for produced in harness.agent.resume(thread_id, {call_id: verdict == "yes"}):
                await self._deliver(incoming.chat_id, produced)
            await self._ask_pending_calls(harness, incoming.chat_id, thread_id)

    async def aclose(self) -> None:
        for harness in self._harnesses.values():
            await harness.aclose()
        self._harnesses.clear()
