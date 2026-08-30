"""Telegram in front of the agent.

This file adapts between Telegram's world and the project's own: an update
becomes a `Message`, what the loop produces becomes chat messages, and a
consent question becomes two buttons. It holds no logic about tools, memory or
stopping — that lives in `app/`, which is why a second interface can exist
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
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from app.agent.runtime import Agent, AnswerWithdrawn, AssistantDelta, create_agent
from app.agent.stop import MemoryStopRequests, PostgresStopRequests, StopRequests
from app.attachments import AttachmentBytes, AttachmentError, admit_uploads
from app.capabilities import Delivery
from app.config import AgentSettings, TelegramSettings
from app.memory import ConversationStore, Thread
from app.models import ContentPart, Message
from app.telemetry import NO_TRACE, Telemetry, TurnTrace
from ui.telegram.api import (
    PRODUCT_COMMANDS,
    Formatted,
    TelegramClient,
    TelegramError,
    approval_keyboard,
    conversations_keyboard,
    no_keyboard,
    settled_keyboard,
)
from ui.telegram.wire import (
    CHATS_CALLBACK_PREFIX,
    CHATS_CLOSE,
    SETTLED_CALLBACK_PREFIX,
    Incoming,
    canonical_user_id,
    needs_model,
    read_update,
)

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
        self.step = 0

    async def show(self, labels: list[str]) -> None:
        if not labels:
            return
        # One batch of tool calls is one step of the loop, so counting them here
        # is counting the loop. Shown only from the second onwards: a turn that
        # reads one file is not a process a person needs a progress report on,
        # and a turn on its fifth step is.
        self.step += 1
        text = "\n".join(labels)
        if self.step > 1:
            text = f"Step {self.step} · {text}"
        if text == self._shown:
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


# One edit per token would be refused by Telegram long before it would be
# readable. A second is roughly how fast an answer can be re-read anyway.
PREVIEW_INTERVAL = 1.0
# Below this, a preview is a bubble containing one word that is about to be
# replaced. The wait costs nothing: the deltas that follow arrive in the same
# breath, and a short answer simply arrives whole.
PREVIEW_START_CHARS = 24


class AnswerPreview:
    """The answer, shown in one message while it is still being written.

    The same message is edited and then finalized, rather than a preview being
    replaced by a fresh bubble: the person watches one answer appear once. What
    is shown is the model's raw text, because Markdown that is half-written is
    not valid markup — the rendering happens at the end, when the text is whole.

    Nothing here can fail a turn. A preview that could not be sent or edited is
    a turn that answers the ordinary way, which is why every failure ends with
    this object standing aside rather than raising.
    """

    def __init__(
        self,
        client: TelegramClient,
        chat_id: int,
        interval: float = PREVIEW_INTERVAL,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.interval = interval
        self._now = now
        self.text = ""
        self.message_id: int | None = None
        self._shown = ""
        self._edited_at = 0.0
        self._stood_aside = False

    async def add(self, delta: str) -> bool:
        """Take one delta. True when this is the moment the preview appeared."""

        self.text += delta
        if self._stood_aside:
            return False
        if self.message_id is None:
            if len(self.text.strip()) < PREVIEW_START_CHARS:
                return False
            return await self._send()
        if self._now() - self._edited_at >= self.interval:
            await self._edit()
        return False

    async def _send(self) -> bool:
        try:
            sent = await self.client.send_message(self.chat_id, self.text)
            self.message_id = int(sent["message_id"]) if sent else None
        except (TelegramError, KeyError, TypeError, ValueError):
            self._stood_aside = True
            return False
        self._shown, self._edited_at = self.text, self._now()
        return self.message_id is not None

    async def _edit(self) -> None:
        if self.text == self._shown or self.message_id is None:
            return
        try:
            await self.client.edit_message(self.chat_id, self.message_id, self.text)
        except (TelegramError, ValueError):
            self._stood_aside = True
            return
        self._shown, self._edited_at = self.text, self._now()

    async def finish(self, body: str) -> bool:
        """Make the preview the final answer. False means it must be sent normally.

        A failed final edit takes the half-written preview out of the chat: an
        answer arriving twice, once truncated, is worse than one arriving once.
        """

        message_id = self.message_id
        if message_id is None:
            self.reset()
            return False
        try:
            await self.client.replace_message(
                self.chat_id, message_id, Formatted.from_markdown(body)
            )
        except TelegramError:
            await self.discard()
            return False
        self.reset()
        return True

    async def discard(self) -> None:
        """Take an unfinished preview out of the chat. Never raises."""

        message_id = self.message_id
        self.reset()
        if message_id is not None:
            await self.client.delete_message(self.chat_id, message_id)

    def reset(self) -> None:
        """Forget this answer, so the next model call gets its own preview.

        One turn can produce several assistant messages — text, then a tool,
        then more text — and each is its own message in the chat.
        """

        self.text = self._shown = ""
        self.message_id = None
        self._edited_at = 0.0
        self._stood_aside = False


def current_thread(store: ConversationStore, user_id: str) -> str:
    """The conversation this user chose, created if they have none yet.

    Choosing is explicit and stored. It used to be inferred — the most recently
    updated thread was the open one — which meant a conversation could take
    somebody over merely by being written to, and made switching back to an
    older one impossible to express.

    A user who has threads but no recorded choice is one who was here before the
    choice existed. Adopting their most recent thread hands them back the
    conversation they were in, rather than opening an empty one beside it.
    """

    chosen = store.active_thread(user_id)
    if chosen is not None:
        return chosen
    existing = store.threads(user_id)
    if existing:
        store.set_active_thread(user_id, existing[0].id)
        return existing[0].id
    return start_thread(store, user_id)


def start_thread(store: ConversationStore, user_id: str) -> str:
    """Create a conversation and move the user into it."""

    thread_id = str(uuid.uuid4())
    store.ensure_thread(thread_id, user_id)
    store.set_active_thread(user_id, thread_id)
    return thread_id


def new_thread(store: ConversationStore, user_id: str) -> str:
    """What `/new` does: a fresh conversation, unless there already is one.

    An untouched conversation is what `/new` produces, so making another one is
    a promise to the person that something happened when nothing did — and it
    fills their list with identical unnamed entries they cannot tell apart.
    """

    chosen = store.active_thread(user_id)
    if chosen is not None and store.message_count(chosen) == 0:
        return chosen
    return start_thread(store, user_id)


# How many conversations `/chats` offers. Deliberately a plain cap rather than
# pagination: this is a personal assistant, the list is ordered by recency, and
# the tenth entry is already further back than anyone reaches for.
CONVERSATION_CHOICES = 10

# Telegram centres button text and squeezes it, so a long label becomes
# unreadable rather than truncated. This is where it is cut instead.
LABEL_CHARS = 40
UNNAMED_CONVERSATION = "New conversation"


def conversation_label(thread: Thread, *, chosen: bool) -> str:
    """One line naming a conversation by how it began.

    Model-written titles would read better and are deliberately not here: they
    would mean a model call to look at a list, and looking at the list must
    never wake anything.
    """

    opening = " ".join(thread.opening.split())
    if len(opening) > LABEL_CHARS:
        opening = opening[: LABEL_CHARS - 1].rstrip() + "…"
    label = opening or UNNAMED_CONVERSATION
    return f"● {label}" if chosen else label


def conversation_choices(
    store: ConversationStore, user_id: str, chosen: str
) -> list[tuple[str, str]]:
    """The buttons for `/chats`: label and callback data, most recent first."""

    return [
        (
            conversation_label(thread, chosen=thread.id == chosen),
            f"{CHATS_CALLBACK_PREFIX}{thread.id}",
        )
        for thread in store.threads(user_id)[:CONVERSATION_CHOICES]
    ]


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


class TelegramAdapter:
    """Turn Telegram updates into agent turns, for allowed accounts only."""

    def __init__(
        self,
        client: TelegramClient,
        settings: TelegramSettings | None = None,
        agent_settings: AgentSettings | None = None,
        agent_factory: Callable[[str], Agent] | None = None,
        telemetry: Telemetry | None = None,
        stops: StopRequests | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or TelegramSettings()
        self.agent_settings = agent_settings or AgentSettings()
        # One recorder for every person this process serves. Whether a turn is
        # measured at all is decided by whoever started the worker, not here.
        self.telemetry = telemetry or Telemetry(None)
        # Where a request to stop is recorded, chosen the same way the store is:
        # a personal machine runs one process, so memory is the whole truth,
        # while the deployed profile answers `/stop` in one container and runs
        # the turn in another, and only the database is visible to both.
        self.stops = stops or (
            PostgresStopRequests(
                self.agent_settings.database_url, self.agent_settings.database_schema
            )
            if self.agent_settings.database_url
            else MemoryStopRequests()
        )
        # Supplied by tests so a turn can be driven without a model endpoint.
        self.agent_factory = agent_factory or self._default_agent
        self._agents: dict[str, Agent] = {}

    def _default_agent(self, user_id: str) -> Agent:
        return create_agent(
            agent_settings=self.agent_settings,
            user_id=user_id,
            delivery=DELIVERY,
            telemetry=self.telemetry,
            stops=self.stops,
        )

    # --- identity and access -------------------------------------------------

    def allows(self, telegram_user_id: int) -> bool:
        """Whether this account may use the assistant.

        Open access admits everyone. It does not merge them: each account still
        maps to its own canonical user, so conversations and memory stay
        separate. What they do share is one workspace and one GPU.
        """

        return self.settings.open_access or telegram_user_id in self.settings.allowed

    def agent(self, user_id: str) -> Agent:
        """One agent per person, because an `Agent` works for one owner."""

        if user_id not in self._agents:
            self._agents[user_id] = self.agent_factory(user_id)
        return self._agents[user_id]

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

    async def handle_update(
        self, update: dict[str, Any], trace: TurnTrace = NO_TRACE
    ) -> None:
        """Handle one update to completion. Never raises at the transport.

        This is the only layer that knows what the person actually received, so
        it is where a turn's outcome is decided. A turn left without one is a
        turn that did not reach any of the endings below, which the worker
        closes as a failure rather than guessing.
        """

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
        # The application's own identifier, never Telegram's: per-user cost is
        # part of the product, and telemetry has no reason to hold an account id.
        trace.run.user_id = user_id
        agent = self.agent(user_id)
        try:
            # `needs_model` decides this as well as whether the webhook wakes the
            # GPU, and it should: the updates worth showing progress for are
            # exactly the ones that take long enough to need it. A command
            # answers from storage and is done before an indicator would appear.
            async with typing(self.client, incoming.chat_id, needs_model(incoming)):
                if incoming.callback_data is not None:
                    await self._on_callback(agent, user_id, incoming, trace)
                else:
                    await self._on_message(agent, user_id, incoming, trace)
        except TelegramError:
            raise
        except Exception as error:  # noqa: BLE001 - a failed turn must not kill the bot
            trace.finish("failed", error_type=type(error).__name__)
            await self.client.send_message(
                incoming.chat_id, f"That request failed: {type(error).__name__}: {error}"
            )

    async def _on_message(
        self,
        agent: Agent,
        user_id: str,
        incoming: Incoming,
        trace: TurnTrace = NO_TRACE,
    ) -> None:
        store = agent.store
        command = incoming.text.strip().lower()
        if command in {"/start", "/help"}:
            await self.client.send_message(incoming.chat_id, HELP)
            return
        if command == "/new":
            # Reusing an untouched conversation must not be reported as having
            # made one: the chat would claim an action that did not happen.
            before = store.active_thread(user_id)
            started = new_thread(store, user_id)
            await self.client.send_message(
                incoming.chat_id,
                "Started a new conversation."
                if started != before
                else "You are already in a new conversation.",
            )
            return
        if command == "/chats":
            await self._show_conversations(store, user_id, incoming.chat_id)
            return
        if command == "/can":
            # Answered from the wiring, not by the model. When the assistant
            # claims it cannot send a picture, this is what that is checked
            # against — and it costs nothing, because no GPU is involved.
            await self.client.send_message(
                incoming.chat_id,
                agent.capabilities(current_thread(store, user_id)),
            )
            return
        if command == "/check":
            # `/can` is the claim; this is the claim tried. Free probes only —
            # the model is not called, so nothing here wakes a GPU.
            await self.client.send_message(
                incoming.chat_id,
                await agent.selftest(current_thread(store, user_id)),
            )
            return
        if command == "/stop":
            # Recorded, not executed. This update reached here out of band, so
            # the turn it is about is still running — in another container, in
            # the deployed profile — and what ends it is the loop reading this
            # at its next step. Saying so is the honest message: claiming the
            # work has stopped before it has is how a person sends `/stop`
            # twice.
            await agent.stops.request(user_id, incoming.update_id)
            await self.client.send_message(
                incoming.chat_id,
                "Stopping. Anything running will stop at its next step.",
            )
            # Neither a failure nor a delivered answer. Its own outcome, so that
            # reliability figures do not count a person changing their mind as
            # the assistant breaking.
            trace.finish("cancelled", status="cancelled")
            return

        try:
            message = await self.to_message(incoming, agent.capability_grant.root)
        except AttachmentError as error:
            await self.client.send_message(incoming.chat_id, f"Upload refused: {error}.")
            return

        thread_id = current_thread(store, user_id)
        trace.run.thread_id = thread_id
        # One route, so nothing decides between two. What used to be a full
        # model request per message, before the answer the person was waiting
        # for, is now this line.
        trace.route("loop")
        await self._answer(
            agent, incoming.chat_id, thread_id, message, incoming.update_id, trace
        )

    # --- choosing a conversation ---------------------------------------------

    async def _show_conversations(
        self, store: ConversationStore, user_id: str, chat_id: int
    ) -> None:
        """Offer this user their own recent conversations, and nobody else's.

        `current_thread` first, so a person with no conversations is offered the
        one they are about to write in rather than an empty list.
        """

        chosen = current_thread(store, user_id)
        await self.client.send_message(
            chat_id,
            "Conversations",
            conversations_keyboard(
                conversation_choices(store, user_id, chosen), CHATS_CLOSE
            ),
        )

    async def _choose_conversation(
        self, store: ConversationStore, user_id: str, incoming: Incoming, data: str
    ) -> None:
        """Answer a press on the conversation list. Reads no model, wakes nothing."""

        if data == CHATS_CLOSE:
            if incoming.callback_id:
                await self.client.answer_callback(incoming.callback_id)
            if incoming.callback_message_id is not None:
                await self.client.edit_reply_markup(
                    incoming.chat_id, incoming.callback_message_id, no_keyboard()
                )
            return

        thread_id = data[len(CHATS_CALLBACK_PREFIX) :]
        try:
            store.set_active_thread(user_id, thread_id)
        except KeyError:
            # Somebody else's conversation, or one that has since been deleted.
            # The same answer for both, because the store deliberately does not
            # distinguish them.
            if incoming.callback_id:
                await self.client.answer_callback(
                    incoming.callback_id, "That conversation is not available"
                )
            return

        if incoming.callback_id:
            await self.client.answer_callback(incoming.callback_id, "Switched")
        if incoming.callback_message_id is not None:
            # The same message, remarked. Selecting does not touch `updated_at`,
            # so the order the person is looking at does not move under them.
            await self.client.edit_reply_markup(
                incoming.chat_id,
                incoming.callback_message_id,
                conversations_keyboard(
                    conversation_choices(store, user_id, thread_id), CHATS_CLOSE
                ),
            )

    # --- the answer branch ---------------------------------------------------

    async def _answer(
        self,
        agent: Agent,
        chat_id: int,
        thread_id: str,
        message: Message,
        sequence: int = 0,
        trace: TurnTrace = NO_TRACE,
    ) -> None:
        activity = ToolActivity(self.client, chat_id)
        preview = AnswerPreview(self.client, chat_id)
        try:
            async for event in agent.events(thread_id, message, trace, sequence):
                if isinstance(event, AssistantDelta):
                    if await preview.add(event.text):
                        # There is something to read now, so the status has
                        # done its job; it goes before the answer grows under it.
                        await activity.clear()
                        trace.visible("preview_started")
                    continue
                if isinstance(event, AnswerWithdrawn):
                    # The turn kept working instead of ending here, so what the
                    # person watched being written is not an answer. Same
                    # correction as a narrated tool call, for the same reason.
                    await preview.discard()
                    continue
                await self._deliver(chat_id, event.message, activity, preview, trace)
        finally:
            # Including when the turn failed: the last thing a person should be
            # left looking at is not "Reading page…" on a turn that stopped, and
            # not half an answer that is never going to be finished.
            await activity.clear()
            await preview.discard()
        asked = await self._ask_pending_calls(agent, chat_id, thread_id)
        # A turn that stopped to ask is not a turn that failed to answer. Both
        # are successful endings, and they are told apart here.
        trace.finish("approval_requested" if asked else "answer_delivered")

    async def _deliver(
        self,
        chat_id: int,
        produced: Message,
        activity: ToolActivity | None = None,
        preview: AnswerPreview | None = None,
        trace: TurnTrace = NO_TRACE,
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
        if produced.tool_calls:
            # A model may narrate its next action before emitting the tool call.
            # Deltas arrive before the completion reveals that this was not the
            # answer, so remove any preview instead of finalizing it as a first
            # response. The ordinary tool activity is the visible status until
            # a later model step actually answers.
            if preview is not None:
                await preview.discard()
        elif body:
            # The status has done its job the moment there is something to read.
            if activity is not None:
                await activity.clear()
            # The canonical answer is the model's ordinary Markdown, which is
            # what the store keeps. This renders that same text for Telegram —
            # into the message the person already watched being written, when
            # there was one, and as a new message when there was not.
            if preview is None or not await preview.finish(body):
                await self.client.send_message(chat_id, Formatted.from_markdown(body))
            # A short answer arrives whole and never previewed, and it did
            # become visible: `visible` keeps the first of the two.
            trace.visible("final_sent")
        elif preview is not None:
            # A completion with no spoken text cannot finalize a text preview.
            await preview.discard()
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
        self, agent: Agent, chat_id: int, thread_id: str
    ) -> bool:
        """Put the graph's own consent question in front of the user.

        The question lives in the checkpoint, not here, so a restart between
        asking and answering loses nothing. Returns whether anything was asked,
        because a turn that ends in a question ended differently from one that
        ends in an answer.
        """

        pending = await agent.pending(thread_id)
        for call in pending or []:
            await self.client.send_message(
                chat_id,
                f"Run {call['name']}?\n{call['arguments']}",
                approval_keyboard(f"call:yes:{call['id']}", f"call:no:{call['id']}"),
            )
        return bool(pending)

    # --- consent answers -----------------------------------------------------

    async def _on_callback(
        self,
        agent: Agent,
        user_id: str,
        incoming: Incoming,
        trace: TurnTrace = NO_TRACE,
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

        if data.startswith(CHATS_CALLBACK_PREFIX):
            # Also before any thread is read or created: choosing a conversation
            # is answered from storage, and a tap on this list must not become a
            # reason to start one, resume a turn or wake a GPU.
            await self._choose_conversation(agent.store, user_id, incoming, data)
            return

        thread_id = current_thread(agent.store, user_id)
        trace.run.thread_id = thread_id
        if incoming.callback_id:
            await self.client.answer_callback(incoming.callback_id)

        if data.startswith("call:"):
            trace.route("loop")
            _, verdict, call_id = data.split(":", 2)
            approved = verdict == "yes"
            settled = False
            activity = ToolActivity(self.client, incoming.chat_id)
            preview = AnswerPreview(self.client, incoming.chat_id)
            trace.event("approval_resumed" if approved else "approval_declined")
            try:
                events = agent.resume_events(thread_id, {call_id: approved}, trace)
                async for event in events:
                    if not settled:
                        await self._settle(incoming, approved=approved)
                        settled = True
                    if isinstance(event, AssistantDelta):
                        if await preview.add(event.text):
                            await activity.clear()
                            trace.visible("preview_started")
                        continue
                    if isinstance(event, AnswerWithdrawn):
                        await preview.discard()
                        continue
                    await self._deliver(
                        incoming.chat_id, event.message, activity, preview, trace
                    )
            finally:
                await activity.clear()
                await preview.discard()
            if not settled:
                await self._settle(incoming, approved=approved)
            asked = await self._ask_pending_calls(agent, incoming.chat_id, thread_id)
            trace.finish("approval_requested" if asked else "answer_delivered")

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
        for agent in self._agents.values():
            await agent.aclose()
        self._agents.clear()
