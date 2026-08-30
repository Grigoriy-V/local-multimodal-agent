"""What a `429 Too Many Requests` from Telegram is allowed to cost.

The live failure these are about: seven long answers in four and a half minutes,
each written into the chat by repeated edits, and Telegram refused the eighth
with `retry after 32`. The turn had already spent 22 seconds of GPU producing a
complete 770-token answer. Because a refused delivery fails the whole turn, and
a failed turn is re-run from the beginning rather than having its answer
re-sent, that answer was discarded and the update went back to the queue to cost
the same again.

A rate limit is the one refusal that carries its own remedy, and Telegram states
the number of seconds. Waiting is following the instruction; failing is ignoring
it.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.config import TelegramSettings
from ui.telegram.api import (
    MAX_RATE_LIMIT_HOLDS,
    MAX_RETRY_AFTER_SECONDS,
    TelegramClient,
    TelegramError,
    retry_after,
)


class Telegram:
    """Answers a scripted sequence of replies, recording what it was asked."""

    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append(request.url.path.rsplit("/", 1)[-1])
            reply = self.replies.pop(0) if self.replies else {"ok": True, "result": {}}
            status = 429 if reply.get("error_code") == 429 else 200
            return httpx.Response(status, json=reply)

        return httpx.MockTransport(handle)


def limited(seconds: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": 429,
        "description": f"Too Many Requests: retry after {seconds}",
        "parameters": {"retry_after": seconds},
    }


def sent(message_id: int = 7) -> dict[str, Any]:
    return {"ok": True, "result": {"message_id": message_id}}


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Waiting is asserted on, never actually waited out."""

    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("ui.telegram.api.asyncio.sleep", record)
    return waits


def client_for(telegram: Telegram) -> TelegramClient:
    return TelegramClient(
        TelegramSettings(token="test-token"), transport=telegram.transport()
    )


async def test_a_rate_limit_is_waited_out_and_the_message_still_arrives(
    slept: list[float],
) -> None:
    telegram = Telegram(limited(3), sent())

    result = await client_for(telegram).send_message(1, "an answer worth keeping")

    assert result == {"message_id": 7}
    assert telegram.calls == ["sendMessage", "sendMessage"]
    assert slept == [3.5]


async def test_the_wait_is_a_little_longer_than_telegram_asked_for(
    slept: list[float],
) -> None:
    """Arriving exactly on the boundary is how a flood wait gets extended."""

    telegram = Telegram(limited(32), sent())

    await client_for(telegram).send_message(1, "hello")

    assert slept == [32.5]


async def test_a_limit_that_outlasts_the_holds_is_still_a_failure(
    slept: list[float],
) -> None:
    """Bounded on purpose: a worker is killed at 600 s and cannot wait forever."""

    telegram = Telegram(*([limited(1)] * (MAX_RATE_LIMIT_HOLDS + 1)))

    with pytest.raises(TelegramError, match="Too Many Requests"):
        await client_for(telegram).send_message(1, "hello")

    assert len(telegram.calls) == MAX_RATE_LIMIT_HOLDS + 1
    assert len(slept) == MAX_RATE_LIMIT_HOLDS


async def test_an_unreasonably_long_wait_is_not_waited_out(slept: list[float]) -> None:
    """A wait longer than a turn has left is a failure to report, not to sit on."""

    telegram = Telegram(limited(MAX_RETRY_AFTER_SECONDS + 1), sent())

    with pytest.raises(TelegramError):
        await client_for(telegram).send_message(1, "hello")

    assert slept == []
    assert telegram.calls == ["sendMessage"]


async def test_an_ordinary_refusal_is_not_retried(slept: list[float]) -> None:
    """Only a rate limit carries its own remedy; nothing else is guessed at."""

    telegram = Telegram({"ok": False, "description": "Bad Request: chat not found"})

    with pytest.raises(TelegramError, match="chat not found"):
        await client_for(telegram).send_message(1, "hello")

    assert telegram.calls == ["sendMessage"]
    assert slept == []


async def test_a_successful_call_waits_for_nothing(slept: list[float]) -> None:
    telegram = Telegram(sent())

    await client_for(telegram).send_message(1, "hello")

    assert telegram.calls == ["sendMessage"]
    assert slept == []


def test_the_wait_is_read_from_the_structured_field_not_the_sentence() -> None:
    """The number is structured; the description is prose and not a contract."""

    assert retry_after(limited(12)) == 12.0
    assert retry_after({"ok": False, "description": "Too Many Requests: retry after 12"}) is None


@pytest.mark.parametrize("value", [0, -1, "12", None, True, {"seconds": 12}])
def test_an_unusable_wait_is_an_ordinary_refusal(value: Any) -> None:
    """Waiting for an unknown or nonsensical time is not a plan.

    `True` is in here on purpose: it is an `int` in Python, and a boolean that
    passed for one second of waiting would be a silent absurdity.
    """

    assert retry_after(limited(value)) is None


async def test_a_reply_that_is_not_an_object_is_refused_clearly() -> None:
    """A proxy or an error page can answer with valid JSON that is not a reply.

    Without this the rate-limit check would be the first thing to touch the
    body, and `.get` on a list is an `AttributeError` rather than a refusal
    anyone can read.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(["nope"]),
            headers={"content-type": "application/json"},
        )

    client = TelegramClient(
        TelegramSettings(token="test-token"), transport=httpx.MockTransport(handle)
    )

    with pytest.raises(TelegramError, match="no object"):
        await client.send_message(1, "hello")
