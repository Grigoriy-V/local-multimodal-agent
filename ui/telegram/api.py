"""The Telegram Bot API wire format, and nothing else.

Only this module knows what Telegram's JSON looks like. It is written directly
over `httpx` for the same reason the model backend is: the surface actually
needed here is six methods, while a bot framework would bring its own event
loop, handler registry and lifecycle to a project where LangGraph already owns
orchestration.

Model text is never marked up. Telegram's Markdown modes reject unbalanced
punctuation, and model output is exactly where unbalanced punctuation comes
from, so an assistant that formatted its own answers would intermittently fail
to send them. `Formatted` is the one exception and stays safe for two reasons:
the headings are written here, everything from the model is escaped, and a
message too long to send whole falls back to plain text rather than risking a
tag cut in half by the splitter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from typing import Any, Self

import httpx

from app.config import TelegramSettings

# Telegram refuses a longer message outright rather than truncating it.
MAX_MESSAGE_CHARS = 4096
# Documents Telegram will accept from a bot.
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
# Telegram's own cap for `sendPhoto`, which is much smaller than a document's.
MAX_PHOTO_BYTES = 10 * 1024 * 1024


class TelegramError(RuntimeError):
    """Telegram was reached but refused, or could not be reached at all."""


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Cut text into sendable pieces, preferring a line break to a hard cut.

    An answer that is one character too long is not an error the user should
    ever see, and a piece cut mid-word is not one they should have to read.
    """

    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        pieces.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


@dataclass(frozen=True)
class Formatted:
    """A message with headings, and the plain text it degrades to.

    Both renderings are carried because the choice is made at send time: only a
    message that fits in one piece can be sent as HTML.
    """

    html: str
    plain: str

    @classmethod
    def build(cls, blocks: Iterable[tuple[str, str]]) -> Formatted:
        """Compose from (heading, body) pairs; either side may be empty.

        Headings are this project's own words and bodies are anything, model
        output included, so only the body is ever escaped — and it is escaped
        every time.
        """

        marked: list[str] = []
        plain: list[str] = []
        for heading, body in blocks:
            if not heading and not body:
                continue
            marked.append(
                "\n".join(
                    piece
                    for piece in (f"<b>{escape(heading)}</b>" if heading else "", escape(body))
                    if piece
                )
            )
            plain.append("\n".join(piece for piece in (heading, body) if piece))
        return cls("\n\n".join(marked), "\n\n".join(plain))


def approval_keyboard(approve: str, decline: str) -> dict[str, Any]:
    """The two-button reply markup used for every consent question."""

    return {
        "inline_keyboard": [
            [
                {"text": "Run it", "callback_data": approve},
                {"text": "Don't", "callback_data": decline},
            ]
        ]
    }


class TelegramClient:
    """The handful of Bot API calls this adapter makes."""

    def __init__(
        self,
        settings: TelegramSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or TelegramSettings()
        if not self.settings.token:
            raise TelegramError("TELEGRAM_TOKEN is not configured")
        base = self.settings.api_base.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{base}/bot{self.settings.token}",
            timeout=self.settings.timeout,
            transport=transport,
        )
        self._files = httpx.AsyncClient(
            base_url=f"{base}/file/bot{self.settings.token}",
            timeout=self.settings.timeout,
            transport=transport,
        )

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(f"/{method}", json=payload)
        except httpx.HTTPError as error:
            detail = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
            raise TelegramError(f"telegram could not be reached ({detail})") from error
        try:
            body = response.json()
        except ValueError as error:
            raise TelegramError(f"telegram returned no JSON for {method}") from error
        if not body.get("ok"):
            raise TelegramError(
                f"telegram refused {method}: {body.get('description', response.status_code)}"
            )
        return body.get("result")

    async def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": self.settings.poll_timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload)
        return list(result or [])

    async def send_message(
        self,
        chat_id: int,
        text: str | Formatted,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Send text, splitting it when Telegram would refuse the length.

        Returns the last message sent, which is the one a caller may later edit.
        """

        pieces, parse_mode = self._render(text)
        sent = None
        for index, piece in enumerate(pieces):
            if not piece:
                continue
            payload: dict[str, Any] = {"chat_id": chat_id, "text": piece}
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            # Buttons belong to the final piece; a keyboard attached to the first
            # would sit above the rest of the answer.
            if reply_markup is not None and index == len(pieces) - 1:
                payload["reply_markup"] = reply_markup
            sent = await self._call("sendMessage", payload)
        return sent

    @staticmethod
    def _render(text: str | Formatted) -> tuple[list[str], str | None]:
        """Choose between the formatted rendering and the plain one.

        Formatting survives only while the message fits whole. `split_message`
        cuts on length, so a second piece could begin inside a `<b>` — and
        Telegram then refuses the message rather than showing it unstyled.
        """

        if isinstance(text, Formatted):
            marked = split_message(text.html)
            if len(marked) == 1:
                return marked, "HTML"
            return split_message(text.plain) or [""], None
        return split_message(text) or [""], None

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """Replace a message's text, ignoring Telegram's "nothing changed" refusal."""

        try:
            await self._call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": split_message(text)[-1] if text else "…",
                },
            )
        except TelegramError as error:
            if "not modified" not in str(error).lower():
                raise

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        """Show Telegram's own "typing…" for a few seconds.

        Never raises. This exists so a person can tell the difference between
        thinking and dead, and failing to say that must not fail the turn it was
        describing.
        """

        try:
            await self._call("sendChatAction", {"chat_id": chat_id, "action": action})
        except TelegramError:
            pass

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._call(
            "answerCallbackQuery", {"callback_query_id": callback_id, "text": text}
        )

    async def _upload(
        self, method: str, field: str, chat_id: int, name: str, data: bytes, limit: int
    ) -> None:
        if len(data) > limit:
            await self.send_message(
                chat_id, f"{name} is too large to send ({len(data)} bytes)."
            )
            return
        try:
            response = await self._client.post(
                f"/{method}",
                data={"chat_id": str(chat_id)},
                files={field: (name, data)},
            )
        except httpx.HTTPError as error:
            raise TelegramError(f"telegram could not be reached ({error})") from error
        body = response.json()
        if not body.get("ok"):
            raise TelegramError(f"telegram refused {method}: {body.get('description')}")

    async def send_document(self, chat_id: int, name: str, data: bytes) -> None:
        await self._upload(
            "sendDocument", "document", chat_id, name, data, MAX_DOCUMENT_BYTES
        )

    async def send_photo(self, chat_id: int, name: str, data: bytes) -> None:
        """Send an image so it appears in the chat rather than as a file.

        Telegram's photo limit is far lower than its document limit, and a
        screenshot that is merely large is still worth seeing, so anything over
        it falls back to the document path instead of being dropped.
        """

        if len(data) > MAX_PHOTO_BYTES:
            await self.send_document(chat_id, name, data)
            return
        await self._upload("sendPhoto", "photo", chat_id, name, data, MAX_PHOTO_BYTES)

    async def download(self, file_id: str) -> bytes:
        """Fetch an uploaded file's bytes through the two-step file API."""

        described = await self._call("getFile", {"file_id": file_id})
        path = (described or {}).get("file_path")
        if not path:
            raise TelegramError("telegram did not return a file path")
        try:
            response = await self._files.get(f"/{path}")
        except httpx.HTTPError as error:
            raise TelegramError(f"telegram file could not be fetched ({error})") from error
        if response.status_code >= 400:
            raise TelegramError(f"telegram file download failed: HTTP {response.status_code}")
        return response.content

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._files.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exception: object) -> None:
        await self.aclose()
