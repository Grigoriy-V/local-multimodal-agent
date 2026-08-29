"""Telegram's wire format, reduced — and nothing else.

This is separate from `adapter.py` for one measured reason. The deployed
webhook only has to recognise an update and read the sender out of it, but it
imported this function from the adapter, and the adapter's first lines pull in
the harness, the agent runtime and through them LangGraph. Two thirds of the
webhook's import time was spent loading code it never executes.

So the rule for this module is its whole purpose: **it may import from the
standard library and nothing else.** Anything that needs a store, a model, a
setting or a client belongs in `adapter.py`, which imports from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PHOTO_MEDIA_TYPE = "image/jpeg"
VOICE_MEDIA_TYPE = "audio/ogg"

# An inline action that has already been carried out leaves one status button
# behind. Telegram needs callback data for a button to exist at all, so the
# settled state gets its own prefix — and the prefix is what tells the front
# door that pressing it is a no-op. Recognising it here rather than in the
# adapter is what keeps a curious tap from waking a GPU.
SETTLED_CALLBACK_PREFIX = "settled:"
SETTLED_APPROVED = f"{SETTLED_CALLBACK_PREFIX}approved"
SETTLED_REJECTED = f"{SETTLED_CALLBACK_PREFIX}rejected"

# The commands the adapter answers from wiring and storage, without a model.
# Listing the exceptions rather than the rule is the safe direction: anything
# new needs the model until someone says otherwise, and the cost of being wrong
# is asymmetric. A model-free update misjudged as needing one wastes a GPU wake;
# a model-using update misjudged as free simply waits for the wake it would have
# waited for anyway. The second is today's behaviour, so it is the failure to
# prefer.
#
# `tests/test_telegram_adapter.py` answers each of these with a backend that
# raises on any call, so this list cannot quietly stop being true.
MODEL_FREE_COMMANDS = frozenset({"/start", "/help", "/new", "/can", "/check", "/stop"})


@dataclass(frozen=True)
class Incoming:
    """One Telegram update, reduced to what the application needs."""

    chat_id: int
    telegram_user_id: int
    text: str
    files: tuple[tuple[str, str, str], ...] = ()  # (file_id, name, media_type)
    callback_id: str | None = None
    callback_data: str | None = None
    # The message the pressed button belongs to. Carried because settling an
    # inline action means editing that same message's keyboard, and without the
    # id the adapter would have to send a second message to say what happened.
    callback_message_id: int | None = None


def read_update(update: dict[str, Any]) -> Incoming | None:
    """Reduce a raw update, or return `None` for one this adapter ignores."""

    callback = update.get("callback_query")
    if callback:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        sender = callback.get("from") or {}
        if not chat.get("id") or not sender.get("id"):
            return None
        message_id = message.get("message_id")
        return Incoming(
            chat_id=int(chat["id"]),
            telegram_user_id=int(sender["id"]),
            text="",
            callback_id=str(callback.get("id", "")),
            callback_data=str(callback.get("data", "")),
            callback_message_id=int(message_id) if message_id is not None else None,
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


def needs_model(incoming: Incoming) -> bool:
    """Will answering this update reach the model?

    Asked at the front door so the GPU can start waking while the worker is
    still being scheduled. Those two took about 5.5 s and 4.9 s one after the
    other; overlapped, the second disappears into the first.

    The comparison matches the adapter's own dispatch exactly — stripped and
    lowercased, no arguments — because a command with anything after it already
    falls through to the model there.
    """

    if incoming.callback_data is not None:
        # An approval button resumes a task, and resuming one calls the model.
        # A settled status button is the exception: the action it describes has
        # already happened, so pressing it changes nothing and must not be paid
        # for with a GPU wake.
        return not incoming.callback_data.startswith(SETTLED_CALLBACK_PREFIX)
    return incoming.text.strip().lower() not in MODEL_FREE_COMMANDS
