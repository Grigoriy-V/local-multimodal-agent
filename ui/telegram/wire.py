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
