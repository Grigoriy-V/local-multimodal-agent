"""The webhook/control-plane boundary, entirely offline."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import TelegramSettings
from ui.telegram.inbox import EnqueueResult, InboxJob
from ui.telegram.webhook import TelegramUpdateWorker, TelegramWebhook


def update(update_id: int = 7, user_id: int = 42) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": 99},
            "from": {"id": user_id},
            "text": "hello",
        },
    }


class FakeInbox:
    def __init__(self) -> None:
        self.payloads: dict[int, dict[str, Any]] = {}
        self.claimed: set[int] = set()
        self.completed: list[int] = []
        self.retried: list[tuple[int, str]] = []

    async def enqueue(self, update_id: int, payload: dict[str, Any]) -> EnqueueResult:
        created = update_id not in self.payloads
        self.payloads.setdefault(update_id, payload)
        should_spawn = created or (
            update_id not in self.claimed and update_id not in self.completed
        )
        return EnqueueResult(update_id, should_spawn)

    async def claim(self, update_id: int, lease_seconds: int = 900) -> InboxJob | None:
        if update_id not in self.payloads or update_id in self.claimed:
            return None
        self.claimed.add(update_id)
        return InboxJob(update_id, self.payloads[update_id], "lease")

    async def complete(self, job: InboxJob) -> None:
        self.completed.append(job.update_id)

    async def retry(self, job: InboxJob, error: str) -> None:
        self.retried.append((job.update_id, error))
        self.claimed.remove(job.update_id)


def settings() -> TelegramSettings:
    return TelegramSettings(
        token="bot-token",
        webhook_secret="webhook-secret",
        allowed_users="42",
        _env_file=None,
    )


def body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


async def test_valid_update_is_persisted_before_spawn() -> None:
    inbox = FakeInbox()
    order: list[str] = []

    original_enqueue = inbox.enqueue

    async def enqueue(update_id: int, payload: dict[str, Any]) -> EnqueueResult:
        order.append("persist")
        return await original_enqueue(update_id, payload)

    inbox.enqueue = enqueue  # type: ignore[method-assign]

    async def spawn(update_id: int) -> None:
        assert update_id in inbox.payloads
        order.append("spawn")

    response = await TelegramWebhook(settings(), inbox, spawn).accept(
        {"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"}, body(update())
    )

    assert response.status == 200
    assert order == ["persist", "spawn"]


async def test_bad_secret_and_unauthorized_user_never_persist_or_spawn() -> None:
    inbox = FakeInbox()
    spawned: list[int] = []

    async def spawn(update_id: int) -> None:
        spawned.append(update_id)

    webhook = TelegramWebhook(settings(), inbox, spawn)
    bad_secret = await webhook.accept({}, body(update()))
    unauthorized = await webhook.accept(
        {"x-telegram-bot-api-secret-token": "webhook-secret"},
        body(update(user_id=100)),
    )

    assert bad_secret.status == 401
    assert unauthorized.status == 200
    assert inbox.payloads == {}
    assert spawned == []


async def test_duplicate_update_already_claimed_does_not_request_a_second_worker() -> None:
    inbox = FakeInbox()
    spawned: list[int] = []

    async def spawn(update_id: int) -> None:
        spawned.append(update_id)

    webhook = TelegramWebhook(settings(), inbox, spawn)
    headers = {"x-telegram-bot-api-secret-token": "webhook-secret"}

    first = await webhook.accept(headers, body(update()))
    assert await inbox.claim(7) is not None
    duplicate = await webhook.accept(headers, body(update()))

    assert first.detail == "accepted"
    assert duplicate.detail == "already accepted"
    assert spawned == [7]


async def test_spawn_failure_keeps_the_persisted_update_for_retry() -> None:
    inbox = FakeInbox()
    attempts = 0

    async def fail(_update_id: int) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("platform unavailable")

    webhook = TelegramWebhook(settings(), inbox, fail)
    headers = {"x-telegram-bot-api-secret-token": "webhook-secret"}
    response = await webhook.accept(headers, body(update()))
    retry = await webhook.accept(headers, body(update()))

    assert response.status == 503
    assert retry.status == 503
    assert attempts == 2
    assert 7 in inbox.payloads


class Handler:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.seen: list[dict[str, Any]] = []

    async def handle_update(self, payload: dict[str, Any]) -> None:
        self.seen.append(payload)
        if self.error:
            raise self.error


async def test_worker_claims_handles_and_completes_one_update() -> None:
    inbox = FakeInbox()
    await inbox.enqueue(7, update())
    handler = Handler()

    ran = await TelegramUpdateWorker(inbox, handler).run(7)
    duplicate = await TelegramUpdateWorker(inbox, handler).run(7)

    assert ran is True
    assert duplicate is False
    assert handler.seen == [update()]
    assert inbox.completed == [7]


async def test_worker_releases_failed_update_for_a_later_retry() -> None:
    inbox = FakeInbox()
    await inbox.enqueue(7, update())
    worker = TelegramUpdateWorker(inbox, Handler(RuntimeError("failed turn")))

    with pytest.raises(RuntimeError, match="failed turn"):
        await worker.run(7)

    assert inbox.retried == [(7, "RuntimeError: failed turn")]
