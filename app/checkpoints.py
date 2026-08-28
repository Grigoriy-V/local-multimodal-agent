"""One lifecycle for LangGraph checkpoints in both deployment profiles.

Checkpoint data is disposable in-flight graph state, not conversation history.
SQLite keeps that state locally. A deployed process uses the same PostgreSQL
database as the conversation store so a different worker can resume the turn.

The PostgreSQL import is deliberately lazy. The local profile neither installs
its driver nor needs a network service, and opening a handle never creates a
connection until a graph actually asks for the saver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


class CheckpointHandle:
    """Lazily own one SQLite or PostgreSQL LangGraph saver."""

    def __init__(
        self,
        sqlite_path: str | Path,
        *,
        database_url: str = "",
        allowed_types: list[tuple[str, str]] | None = None,
    ) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.database_url = database_url
        self.allowed_types = allowed_types or []
        self._connection: aiosqlite.Connection | None = None
        self._context: Any = None
        self._saver: Any = None

    async def open(self) -> Any:
        if self._saver is not None:
            return self._saver

        serde = JsonPlusSerializer(allowed_msgpack_modules=self.allowed_types)
        if self.database_url:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # PostgreSQL migrations are an explicit deployment operation. The
            # runtime only opens tables prepared by that operation.
            self._context = AsyncPostgresSaver.from_conn_string(
                self.database_url, serde=serde
            )
            self._saver = await self._context.__aenter__()
            # Upstream uses unqualified table names. A pooled server connection
            # may have been used by another client, so normalize the session at
            # this boundary before any checkpoint query runs.
            await self._saver.conn.execute("SET search_path TO public")
            return self._saver

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(str(self.sqlite_path))
        self._saver = AsyncSqliteSaver(self._connection, serde=serde)
        await self._saver.setup()
        return self._saver

    async def close(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        elif self._connection is not None:
            await self._connection.close()
        self._context = None
        self._connection = None
        self._saver = None


async def setup_postgres_checkpoints(
    database_url: str,
    *,
    allowed_types: list[tuple[str, str]] | None = None,
) -> None:
    """Create/migrate LangGraph's tables as an explicit deployment action."""

    if not database_url:
        raise ValueError("a PostgreSQL database URL is required")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    serde = JsonPlusSerializer(allowed_msgpack_modules=allowed_types or [])
    async with AsyncPostgresSaver.from_conn_string(database_url, serde=serde) as saver:
        await saver.conn.execute("SET search_path TO public")
        await saver.setup()
