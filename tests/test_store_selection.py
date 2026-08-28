"""Which store a profile opens, and that the choice is configuration only.

The local and deployed profiles run the same `app/`. That claim is only true if
nothing above the store names an implementation, so this checks the one place
that is allowed to.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.config import AgentSettings
from app.memory import SqliteStore, open_store


def test_the_local_profile_opens_the_sqlite_file(tmp_path: Path) -> None:
    settings = AgentSettings(database=str(tmp_path / "memory.sqlite3"), _env_file=None)

    with open_store(settings) as opened:
        assert isinstance(opened, SqliteStore)


def test_a_database_url_opens_postgres_instead(monkeypatch: pytest.MonkeyPatch) -> None:
    """The branch is checked without a driver and without a connection.

    Standing in for the module rather than importing it keeps this test running
    on a machine that has only the local profile installed — which is every
    machine that runs the local profile.
    """

    opened: dict[str, str | bool] = {}

    class FakePostgresStore:
        def __init__(
            self,
            dsn: str,
            schema: str = "public",
            *,
            migrate_schema: bool = False,
        ) -> None:
            opened["dsn"] = dsn
            opened["schema"] = schema
            opened["migrate_schema"] = migrate_schema

    stand_in = ModuleType("app.memory.postgres")
    stand_in.PostgresStore = FakePostgresStore  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.memory.postgres", stand_in)
    settings = AgentSettings(
        database_url="postgresql://example/db",
        database_schema="assistant",
        _env_file=None,
    )

    store = open_store(settings)

    assert isinstance(store, FakePostgresStore)
    assert opened == {
        "dsn": "postgresql://example/db",
        "schema": "assistant",
        "migrate_schema": False,
    }

    open_store(settings, migrate_schema=True)
    assert opened["migrate_schema"] is True


def test_the_deployed_url_is_never_a_default() -> None:
    """An unconfigured deployment must not silently fall back to a local file
    it shares with nobody, nor point at someone else's database."""

    assert AgentSettings(_env_file=None).database_url == ""
