"""Checkpoint backend selection without a PostgreSQL service."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.checkpoints import CheckpointHandle, setup_postgres_checkpoints


async def test_local_handle_creates_and_reuses_sqlite_saver(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite3"
    handle = CheckpointHandle(path)

    first = await handle.open()
    second = await handle.open()

    assert first is second
    assert path.is_file()
    await handle.close()


def fake_postgres_module(monkeypatch: pytest.MonkeyPatch) -> tuple[type, list[object]]:
    events: list[object] = []

    class Connection:
        async def execute(self, statement: str) -> None:
            events.append(("execute", statement))

    class Saver:
        def __init__(self) -> None:
            self.conn = Connection()

        async def setup(self) -> None:
            events.append("setup")

    class Context:
        async def __aenter__(self) -> Saver:
            events.append("enter")
            return Saver()

        async def __aexit__(self, *error: object) -> None:
            events.append("exit")

    class AsyncPostgresSaver:
        @classmethod
        def from_conn_string(cls, dsn: str, **kwargs: object) -> Context:
            events.append((dsn, kwargs))
            return Context()

    package = ModuleType("langgraph.checkpoint.postgres")
    module = ModuleType("langgraph.checkpoint.postgres.aio")
    module.AsyncPostgresSaver = AsyncPostgresSaver  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", package)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres.aio", module)
    return AsyncPostgresSaver, events


async def test_deployed_handle_opens_postgres_lazily_without_migrating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, events = fake_postgres_module(monkeypatch)
    handle = CheckpointHandle(
        tmp_path / "unused.sqlite3", database_url="postgresql://example/db"
    )

    assert events == []
    await handle.open()
    await handle.close()

    assert events[0][0] == "postgresql://example/db"  # type: ignore[index]
    assert events[1:] == [
        "enter",
        ("execute", "SET search_path TO public"),
        "exit",
    ]
    assert not (tmp_path / "unused.sqlite3").exists()


async def test_postgres_setup_is_a_separate_explicit_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, events = fake_postgres_module(monkeypatch)

    await setup_postgres_checkpoints("postgresql://example/db")

    assert events[1:] == [
        "enter",
        ("execute", "SET search_path TO public"),
        "setup",
        "exit",
    ]
