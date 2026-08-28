"""The deployed database setup remains explicit and all-or-nothing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.config import AgentSettings
from tools.setup_control_plane import setup_control_plane


class FakeStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("store.close")


async def test_setup_requires_the_deployed_database_url() -> None:
    with pytest.raises(ValueError, match="AGENT_DATABASE_URL"):
        await setup_control_plane(AgentSettings(database_url=""))


async def test_setup_runs_every_migration_and_closes_the_store(monkeypatch: Any) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        "tools.setup_control_plane.open_store",
        lambda _settings, *, migrate_schema: (
            events.append("store.setup") or FakeStore(events)
        ),
    )

    async def checkpoints(url: str, *, allowed_types: object) -> None:
        assert url == "postgresql://example/control"
        assert allowed_types
        events.append("checkpoints.setup")

    class FakeInbox:
        def __init__(self, url: str, schema: str) -> None:
            assert url == "postgresql://example/control"
            assert schema == "assistant"

        async def setup(self) -> None:
            events.append("inbox.setup")

    monkeypatch.setattr("tools.setup_control_plane.setup_postgres_checkpoints", checkpoints)
    monkeypatch.setattr("tools.setup_control_plane.PostgresUpdateInbox", FakeInbox)

    await setup_control_plane(
        AgentSettings(
            database_url="postgresql://example/control",
            database_schema="assistant",
        )
    )

    assert events == [
        "store.setup",
        "checkpoints.setup",
        "inbox.setup",
        "store.close",
    ]


async def test_setup_closes_the_store_when_a_later_migration_fails(monkeypatch: Any) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "tools.setup_control_plane.open_store",
        lambda _settings, *, migrate_schema: FakeStore(events),
    )

    async def fail(_url: str, *, allowed_types: object) -> None:
        assert allowed_types
        raise RuntimeError("migration failed")

    monkeypatch.setattr("tools.setup_control_plane.setup_postgres_checkpoints", fail)

    with pytest.raises(RuntimeError, match="migration failed"):
        await setup_control_plane(AgentSettings(database_url="postgresql://example/control"))

    assert events == ["store.close"]


def test_windows_setup_uses_a_psycopg_compatible_event_loop(monkeypatch: Any) -> None:
    seen: dict[str, object] = {}

    def run(coroutine: object, *, loop_factory: object) -> None:
        seen["loop_factory"] = loop_factory
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr("tools.setup_control_plane.sys.platform", "win32")
    monkeypatch.setattr("tools.setup_control_plane.asyncio.run", run)

    from tools.setup_control_plane import main

    main()

    assert seen["loop_factory"] is asyncio.SelectorEventLoop
