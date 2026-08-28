"""Transport-neutral Telegram webhook acceptance and worker execution.

An HTTP/platform adapter only has to pass headers and bytes to
``TelegramWebhook.accept`` and translate the returned status. The acceptor
validates, durably queues and requests a worker; it never runs the agent loop.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import TelegramSettings
from ui.telegram.inbox import UpdateInbox
from ui.telegram.wire import read_update


MAX_UPDATE_BYTES = 1024 * 1024
SECRET_HEADER = "x-telegram-bot-api-secret-token"


@dataclass(frozen=True)
class WebhookResponse:
    status: int
    detail: str


class UpdateHandler(Protocol):
    async def handle_update(self, update: dict[str, Any]) -> None: ...


class TelegramWebhook:
    """Validate and persist one update before asking for a worker."""

    def __init__(
        self,
        settings: TelegramSettings,
        inbox: UpdateInbox,
        spawn: Callable[[int], Awaitable[None]],
        *,
        max_update_bytes: int = MAX_UPDATE_BYTES,
    ) -> None:
        self.settings = settings
        self.inbox = inbox
        self.spawn = spawn
        self.max_update_bytes = max_update_bytes

    async def accept(self, headers: Mapping[str, str], body: bytes) -> WebhookResponse:
        supplied = {key.lower(): value for key, value in headers.items()}.get(SECRET_HEADER, "")
        expected = self.settings.webhook_secret
        if not expected:
            return WebhookResponse(503, "webhook secret is not configured")
        if not hmac.compare_digest(supplied, expected):
            return WebhookResponse(401, "invalid webhook secret")
        if len(body) > self.max_update_bytes:
            return WebhookResponse(413, "update is too large")
        try:
            update = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return WebhookResponse(400, "invalid JSON")
        if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
            return WebhookResponse(400, "update_id is required")

        incoming = read_update(update)
        if incoming is None:
            return WebhookResponse(200, "ignored update")
        if not (
            self.settings.open_access
            or incoming.telegram_user_id in self.settings.allowed
        ):
            # Acknowledge without persisting or spawning. Returning an error
            # would make Telegram retry an update that will never be admitted.
            return WebhookResponse(200, "ignored unauthorized account")

        queued = await self.inbox.enqueue(update["update_id"], update)
        if not queued.should_spawn:
            return WebhookResponse(200, "already accepted")
        try:
            await self.spawn(queued.update_id)
        except Exception:  # noqa: BLE001 - persistence makes a retry safe
            return WebhookResponse(503, "queued; worker was not started")
        return WebhookResponse(200, "accepted")


class TelegramUpdateWorker:
    """Claim one persisted update and run it through the existing adapter."""

    def __init__(self, inbox: UpdateInbox, handler: UpdateHandler) -> None:
        self.inbox = inbox
        self.handler = handler

    async def run(self, update_id: int) -> bool:
        job = await self.inbox.claim(update_id)
        if job is None:
            return False
        try:
            await self.handler.handle_update(job.payload)
        except Exception as error:
            await self.inbox.retry(job, f"{type(error).__name__}: {error}")
            raise
        await self.inbox.complete(job)
        return True

