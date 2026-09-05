"""The wait for a launched browser's DevTools port is a time budget (ISS-0051)."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.tools import chromium


class LiveProcess:
    returncode = None

    def poll(self):
        return None


class DeadProcess:
    returncode = 7

    def poll(self):
        return 7


def test_the_budget_is_seconds_and_covers_a_cold_browser() -> None:
    assert chromium.DEVTOOLS_READY_SECONDS >= 10.0


async def test_a_port_that_never_opens_fails_after_the_budget_not_after_a_count(monkeypatch) -> None:
    def never(url, method="GET"):
        raise OSError("connection refused")

    monkeypatch.setattr(chromium, "_read_json", never)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="did not become ready"):
        await chromium._wait_for_debugger(9222, LiveProcess(), timeout=0.3)
    assert 0.25 <= time.monotonic() - started < 3.0


async def test_a_port_that_opens_late_is_waited_for(monkeypatch) -> None:
    calls = 0

    def late(url, method="GET"):
        nonlocal calls
        calls += 1
        if calls < 5:
            raise OSError("connection refused")
        return {"Browser": "Chrome/1"}

    monkeypatch.setattr(chromium, "_read_json", late)
    assert await chromium._wait_for_debugger(9222, LiveProcess(), timeout=5.0) == "Chrome/1"
    assert calls == 5


async def test_a_browser_that_exited_is_reported_at_once(monkeypatch) -> None:
    monkeypatch.setattr(chromium, "_read_json", lambda url, method="GET": (_ for _ in ()).throw(OSError()))
    with pytest.raises(RuntimeError, match="exited before"):
        await chromium._wait_for_debugger(9222, DeadProcess(), timeout=5.0)
