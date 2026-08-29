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

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from app.agent.harness import GeneralHarness
from app.agent.runtime import create_agent
from app.agent.task_runtime import TaskProgress, TaskRuntime, TaskView
from app.attachments import AttachmentBytes, AttachmentError, admit_uploads
from app.capabilities import Delivery
from app.config import AgentSettings, TelegramSettings
from app.memory import ConversationStore
from app.models import ContentPart, Message
from ui.telegram.api import (
    PRODUCT_COMMANDS,
    Formatted,
    TelegramClient,
    TelegramError,
    approval_keyboard,
    settled_keyboard,
)
from ui.telegram.wire import (
    SETTLED_CALLBACK_PREFIX,
    Incoming,
    needs_model,
    read_update,
)

# A fixed namespace so a chat maps to the same canonical identity on every run
# and on every machine. Changing it orphans every existing conversation.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "local-multimodal-agent:telegram")

REFUSAL = (
    "This assistant is private and your account is not on its allowed list. "
    "Nothing you send here is processed."
)
# What `/start` and `/help` say. One text for both: the first question a person
# has and the one they come back with are the same question, and a second
# wording is a second thing to keep true. Written as ordinary Markdown and put
# through the same renderer as an assistant answer, so this card is proof the
# formatting path works rather than a special case beside it.
#
# The command lines are generated from the native menu so the two cannot
# disagree. `/check` is named afterwards, in a sentence, because it is a
# diagnostic rather than one of the four things this assistant is for.
HELP_MARKDOWN = "\n".join(
    [
        "**Personal assistant**",
        "",
        "Talk to me normally. You can send text, images, voice messages and "
        "supported documents. I can read your files, use the web, and carry out "
        "longer tasks when they are needed. I ask before consequential actions.",
        "",
        "**Commands**",
        # Bold rather than code: Telegram turns a `/command` in message text
        # into something tappable, and monospace is the one style that reads as
        # a thing to copy rather than a thing to press.
        *(f"**/{entry.command}** — {entry.description}" for entry in PRODUCT_COMMANDS),
        "",
        "**/check** tries every capability for real and reports what actually works.",
    ]
)
HELP = Formatted.from_markdown(HELP_MARKDOWN)

# What `_send_media` can actually put in this chat, declared where that method
# is, so the two cannot drift apart. Images go as photos and sound as a file,
# but both arrive, and the model is told so instead of guessing.
DELIVERY = Delivery(media=("image", "audio"))

# Telegram names an upload by its filename, so an outgoing part needs a
# plausible extension. Only the types the assistant can produce are listed.
MEDIA_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
}


# What the person sees while a tool runs. Internal names are how the agent and
# the traces talk about a tool; they are not what a product says out loud, and
# `send_file` in a chat reads as a leaked implementation detail rather than as
# progress. Deliberately English whatever language the conversation is in: this
# is interface chrome, not part of the answer, and translating it would mean
# guessing a language from presentation code.
#
# Anything not listed says `Working…` — a new tool must be able to appear
# without leaking its name, so the default is the safe one rather than the
# informative one.
TOOL_ACTIVITY = {
    "search_web": "Searching the web…",
    "fetch_page": "Reading page…",
    "view_web_page": "Opening page…",
    "inspect_page": "Inspecting page…",
    "read_document": "Reading document…",
    "view_pages": "Inspecting document…",
    "list_files": "Listing files…",
    "read_file": "Reading file…",
    "write_file": "Writing file…",
    "edit_file": "Editing file…",
    "send_file": "Sending file…",
    "remember_fact": "Saving to memory…",
    "search_memory": "Searching memory…",
}
UNKNOWN_ACTIVITY = "Working…"


def activity_labels(calls: Iterable[Any]) -> list[str]:
    """The user-facing labels for one batch of tool calls, in order, deduped."""

    labels: list[str] = []
    for call in calls:
        label = TOOL_ACTIVITY.get(call.name, UNKNOWN_ACTIVITY)
        if label not in labels:
            labels.append(label)
    return labels


class ToolActivity:
    """One transient status message per turn, edited as the work moves on.

    A message per tool call turned a turn with a browser in it into a column of
    notifications that stayed in the history forever. This is the same
    information in one message that is edited while the tools run and deleted
    when there is an answer to read, so what remains in the chat afterwards is
    the conversation.

    Nothing here can fail a turn. A status that could not be sent, edited or
    removed is a cosmetic loss, and the answer it was describing is not.
    """

    def __init__(self, client: TelegramClient, chat_id: int) -> None:
        self.client = client
        self.chat_id = chat_id
        self.message_id: int | None = None
        self._shown: str | None = None

    async def show(self, labels: list[str]) -> None:
        text = "\n".join(labels)
        if not text or text == self._shown:
            return
        try:
            if self.message_id is None:
                sent = await self.client.send_message(self.chat_id, text)
                self.message_id = int(sent["message_id"]) if sent else None
            else:
                await self.client.edit_message(self.chat_id, self.message_id, text)
        except (TelegramError, KeyError, TypeError, ValueError):
            return
        self._shown = text

    async def clear(self) -> None:
        """Take the status out of the chat, so it cannot sit under the answer."""

        message_id, self.message_id, self._shown = self.message_id, None, None
        if message_id is not None:
            await self.client.delete_message(self.chat_id, message_id)


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


# Telegram clears the indicator after about five seconds, so a turn that lasts
# longer has to renew it. Four leaves room for the round trip.
TYPING_INTERVAL = 4.0


@asynccontextmanager
async def typing(
    client: TelegramClient, chat_id: int, active: bool = True
) -> AsyncIterator[None]:
    """Keep Telegram's "typing…" on screen for as long as the block runs.

    A cold turn spends most of its time waiting for a GPU to wake, where there
    is nothing to stream and nothing to report — the only honest thing to show
    is that the assistant is still there. This is that, and it is the platform's
    own indicator rather than a message that would have to be cleaned up.

    The renewing task is always cancelled and awaited, because a task left
    running in a container that is about to be frozen is a warning in the logs
    at best.
    """

    if not active:
        yield
        return

    async def keep() -> None:
        while True:
            await client.send_chat_action(chat_id)
            await asyncio.sleep(TYPING_INTERVAL)

    task = asyncio.create_task(keep())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def spoken(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content if part.kind == "text").strip()


def task_plan_text(view: TaskView, workspace: Path) -> str | Formatted:
    """The plan a person has to read before approving it.

    Shaped rather than dumped: this message is the one moment where someone
    decides whether the agent may touch their files, and a wall of text is how
    that decision gets made without being made.
    """

    if view.plan is None:
        return "Task planning did not produce a plan."
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(view.plan.steps, 1))
    criteria = "\n".join(f"• {item}" for item in view.plan.acceptance_criteria)
    permissions = ", ".join((view.interrupt or {}).get("permissions", []))
    return Formatted.build(
        [
            ("Plan", view.plan.summary),
            ("Steps", steps),
            ("Acceptance criteria", criteria),
            ("Scope", f"{workspace}\n{permissions}"),
            ("", "Run this plan?"),
        ]
    )


def task_result_text(view: TaskView, fallback: str) -> str | Formatted:
    """The finished task, in the order a person reads it.

    The outcome first, because that is the question being answered; then what
    was checked against real evidence, which is the part that separates a claim
    from a result.
    """

    if view.outcome is None:
        return fallback
    summary = view.implementation.summary if view.implementation else view.outcome.summary
    checks = "\n".join(
        f"{'✓' if check.passed else '✗'} {check.name}\n   {check.detail}"
        for check in (view.report.checks if view.report else ())
    )
    artifacts = "\n".join(f"• {artifact}" for artifact in view.outcome.artifacts)
    counted = (
        f"{view.outcome.status} · {view.outcome.iterations} iteration(s) · "
        f"{view.outcome.tool_calls} tool call(s)"
    )
    return Formatted.build(
        [
            ("Result", summary),
            ("Checks", checks),
            ("Files", artifacts),
            ("", counted),
        ]
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
        agent = create_agent(
            agent_settings=self.agent_settings, user_id=user_id, delivery=DELIVERY
        )
        return GeneralHarness(
            agent,
            TaskRuntime(
                backend=agent.backend,
                workspace=agent.workspace,
                checkpoints=self.agent_settings.task_checkpoints,
                checkpoint_database_url=self.agent_settings.database_url,
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

    async def to_message(self, incoming: Incoming, workspace: Path) -> Message:
        """Turn one update into a turn's input, saving what should not be pasted.

        The workspace is passed in rather than read here: which directory a
        person's files live in is the application's decision, and an adapter
        that worked it out for itself would be a second answer to it.
        """

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
        parts.extend(admit_uploads(uploads, workspace))
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
            # `needs_model` decides this as well as whether the webhook wakes the
            # GPU, and it should: the updates worth showing progress for are
            # exactly the ones that take long enough to need it. A command
            # answers from storage and is done before an indicator would appear.
            async with typing(self.client, incoming.chat_id, needs_model(incoming)):
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
        if command == "/can":
            # Answered from the wiring, not by the model. When the assistant
            # claims it cannot send a picture, this is what that is checked
            # against — and it costs nothing, because no GPU is involved.
            await self.client.send_message(
                incoming.chat_id,
                harness.agent.capabilities(current_thread(store, user_id)),
            )
            return
        if command == "/check":
            # `/can` is the claim; this is the claim tried. Free probes only —
            # the model is not called, so nothing here wakes a GPU.
            await self.client.send_message(
                incoming.chat_id,
                await harness.agent.selftest(current_thread(store, user_id)),
            )
            return
        if command == "/stop":
            result = await harness.cancel_task(current_thread(store, user_id))
            await self.client.send_message(
                incoming.chat_id,
                spoken(result) if result is not None else "Nothing is running.",
            )
            return

        try:
            message = await self.to_message(incoming, harness.agent.capability_grant.root)
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
        activity = ToolActivity(self.client, chat_id)
        try:
            async for produced in harness.agent.steps(thread_id, message):
                await self._deliver(chat_id, produced, activity)
        finally:
            # Including when the turn failed: the last thing a person should be
            # left looking at is not "Reading page…" on a turn that stopped.
            await activity.clear()
        await self._ask_pending_calls(harness, chat_id, thread_id)

    async def _deliver(
        self, chat_id: int, produced: Message, activity: ToolActivity | None = None
    ) -> None:
        body = spoken(produced)
        if produced.role == "tool":
            # Tool results are working material. Only a presentation tool can
            # mark a concrete item outbound; observing a page or screenshot is
            # never interpreted as a send decision by this adapter.
            if activity is not None and any(
                part.outbound and part.data for part in produced.content
            ):
                await activity.clear()
            await self._send_media(chat_id, produced, outbound_only=True)
            return
        if body:
            # The status has done its job the moment there is something to read.
            if activity is not None:
                await activity.clear()
            # The canonical answer is the model's ordinary Markdown, which is
            # what the store keeps. This renders that same text for Telegram.
            await self.client.send_message(chat_id, Formatted.from_markdown(body))
        await self._send_media(chat_id, produced)
        if produced.tool_calls:
            labels = activity_labels(produced.tool_calls)
            if activity is not None:
                await activity.show(labels)
            else:
                await self.client.send_message(chat_id, "\n".join(labels))

    async def _send_media(
        self, chat_id: int, produced: Message, *, outbound_only: bool = False
    ) -> None:
        """Translate media the application explicitly selected to Telegram."""

        for index, part in enumerate(produced.content, start=1):
            if part.kind == "text" or not part.data:
                continue
            if outbound_only and not part.outbound:
                continue
            name = part.name or (
                f"{part.kind}-{index}{MEDIA_SUFFIXES.get(part.media_type or '', '.bin')}"
            )
            if part.kind == "image":
                await self.client.send_photo(chat_id, name, part.data)
            else:
                await self.client.send_document(chat_id, name, part.data)

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
        self, harness: GeneralHarness, incoming: Incoming, thread_id: str, approved: bool
    ) -> None:
        chat_id = incoming.chat_id
        if not approved:
            view = await harness.resume_task(thread_id, False)
            await self._settle(incoming, approved=False)
            await self._finish_task(harness, chat_id, thread_id, view)
            return
        # Responsive without claiming anything yet. Until the resume has
        # produced proof that it happened, the only honest thing the chat can
        # say is that the press arrived: an "Approved" written here would
        # outlive a transition that never took place.
        sent = await self.client.send_message(chat_id, "Starting…")
        message_id = int(sent["message_id"]) if sent else None
        lines: list[str] = []
        settled = False

        async def confirm() -> None:
            # The first proof that the task really did resume, which is the
            # moment both the button and the text may say it was approved.
            nonlocal settled
            if settled:
                return
            await self._settle(incoming, approved=True)
            settled = True
            lines.append("Approved; working…")

        async for progress in harness.resume_task_with_progress(thread_id, True):
            await confirm()
            lines.append(progress_text(progress))
            if message_id is not None:
                await self.client.edit_message(chat_id, message_id, "\n".join(lines))
        view = await harness.task_view(thread_id)
        if not settled:
            # A resume that finished without reporting a stage still resumed.
            await confirm()
            if message_id is not None:
                await self.client.edit_message(chat_id, message_id, "\n".join(lines))
        await self._finish_task(harness, chat_id, thread_id, view)

    async def _finish_task(
        self, harness: GeneralHarness, chat_id: int, thread_id: str, view: TaskView
    ) -> None:
        result = harness.finish_task(thread_id, view)
        # The store keeps the harness's canonical text; the chat gets the same
        # facts in a shape someone can read. Presentation is the adapter's job.
        await self.client.send_message(
            chat_id,
            task_result_text(view, spoken(result) or "The task produced no result."),
        )
        await self._send_media(chat_id, result)
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
        if data.startswith(SETTLED_CALLBACK_PREFIX):
            # A button that already says what happened. Answering the callback
            # is all Telegram needs, and it is all this may do: before any
            # thread is read or created, so pressing it cannot start a
            # conversation, resume a task, or wake anything.
            if incoming.callback_id:
                await self.client.answer_callback(
                    incoming.callback_id,
                    "Already approved" if data.endswith("approved") else "Already rejected",
                )
            return

        thread_id = current_thread(harness.agent.store, user_id)
        if incoming.callback_id:
            await self.client.answer_callback(incoming.callback_id)

        if data.startswith("task:"):
            await self._run_task(harness, incoming, thread_id, data == "task:yes")
            return
        if data.startswith("call:"):
            _, verdict, call_id = data.split(":", 2)
            approved = verdict == "yes"
            settled = False
            activity = ToolActivity(self.client, incoming.chat_id)
            try:
                async for produced in harness.agent.resume(thread_id, {call_id: approved}):
                    if not settled:
                        await self._settle(incoming, approved=approved)
                        settled = True
                    await self._deliver(incoming.chat_id, produced, activity)
            finally:
                await activity.clear()
            if not settled:
                await self._settle(incoming, approved=approved)
            await self._ask_pending_calls(harness, incoming.chat_id, thread_id)

    async def _settle(self, incoming: Incoming, *, approved: bool) -> None:
        """Turn the choices back into the one state that was actually reached.

        Called only after the application transition succeeded, because that is
        what the button then claims. A settlement that could not be written is
        left unsettled rather than reported as done: a stale pair of buttons is
        honest, and a green tick over a transition that did not happen is not.
        """

        if incoming.callback_message_id is None:
            return
        for styled in (True, False):
            try:
                await self.client.edit_reply_markup(
                    incoming.chat_id,
                    incoming.callback_message_id,
                    settled_keyboard(approved, styled=styled),
                )
                return
            except TelegramError:
                # `style` is a recent Bot API field. An older server refuses the
                # whole edit for it, so the second attempt drops the colour and
                # keeps the state, which is the half that carries the meaning.
                continue

    async def aclose(self) -> None:
        for harness in self._harnesses.values():
            await harness.aclose()
        self._harnesses.clear()
