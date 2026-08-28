"""Which store a profile gets, decided in one place.

The local and deployed profiles run the same `app/`, so the choice between a
file on a personal machine and a networked database is configuration, not a
fork. Every caller that needs a store goes through here rather than naming an
implementation, which is what keeps that true.

The PostgreSQL import is deferred so that a machine without its driver — every
machine running the local profile — still starts.
"""

from __future__ import annotations

from app.config import AgentSettings
from app.memory.base import ConversationStore
from app.memory.store import SqliteStore


def open_store(settings: AgentSettings | None = None) -> ConversationStore:
    settings = settings or AgentSettings()
    if settings.database_url:
        from app.memory.postgres import PostgresStore

        return PostgresStore(settings.database_url, settings.database_schema)
    return SqliteStore(settings.database)
