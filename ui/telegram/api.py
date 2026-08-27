"""The Telegram Bot API wire format, and nothing else.

Only this module knows what Telegram's JSON looks like. It is written directly
over `httpx` for the same reason the model backend is: the surface actually
needed here is six methods, while a bot framework would bring its own event
loop, handler registry and lifecycle to a project where LangGraph already owns
orchestration.

Text is sent unformatted. Telegram's Markdown modes reject unbalanced
punctuation, and model output is exactly where unbalanced punctuation comes
from, so an assistant that formats its answers would intermittently fail to
send them.
"""

from __future__ import annotations

from typing import Any, Self

import httpx

from app.config import TelegramSettings

# Telegram refuses a longer message outright rather than truncating it.
MAX_MESSAGE_CHARS = 4096
# Documents Telegram will accept from a bot.
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


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
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Send text, splitting it when Telegram would refuse the length.

        Returns the last message sent, which is the one a caller may later edit.
        """

        sent = None
        pieces = split_message(text) or [""]
        for index, piece in enumerate(pieces):
            if not piece:
                continue
            payload: dict[str, Any] = {"chat_id": chat_id, "text": piece}
            # Buttons belong to the final piece; a keyboard attached to the first
            # would sit above the rest of the answer.
            if reply_markup is not None and index == len(pieces) - 1:
                payload["reply_markup"] = reply_markup
            sent = await self._call("sendMessage", payload)
        return sent

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

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._call(
            "answerCallbackQuery", {"callback_query_id": callback_id, "text": text}
        )

    async def send_document(self, chat_id: int, name: str, data: bytes) -> None:
        if len(data) > MAX_DOCUMENT_BYTES:
            await self.send_message(
                chat_id, f"{name} is too large to send ({len(data)} bytes)."
            )
            return
        try:
            response = await self._client.post(
                "/sendDocument",
                data={"chat_id": str(chat_id)},
                files={"document": (name, data)},
            )
        except httpx.HTTPError as error:
            raise TelegramError(f"telegram could not be reached ({error})") from error
        body = response.json()
        if not body.get("ok"):
            raise TelegramError(f"telegram refused sendDocument: {body.get('description')}")

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
