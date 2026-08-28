"""Durable hand-off between the Telegram webhook and an agent worker.

The webhook acknowledges quickly after this inbox owns the update. A worker
then claims it with a lease, so duplicate Telegram deliveries or duplicate
spawn attempts cannot run the same update concurrently. PostgreSQL is opened
per operation because the deployed processes scale to zero between requests.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol


SCHEMA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class EnqueueResult:
    update_id: int
    should_spawn: bool


@dataclass(frozen=True)
class InboxJob:
    update_id: int
    payload: dict[str, Any]
    lease_token: str


class UpdateInbox(Protocol):
    async def enqueue(self, update_id: int, payload: dict[str, Any]) -> EnqueueResult: ...

    async def claim(self, update_id: int, lease_seconds: int = 900) -> InboxJob | None: ...

    async def complete(self, job: InboxJob) -> None: ...

    async def retry(self, job: InboxJob, error: str) -> None: ...


class PostgresUpdateInbox:
    """A small leased queue in the control plane's PostgreSQL database."""

    def __init__(self, dsn: str, schema: str = "public") -> None:
        if not dsn:
            raise ValueError("a PostgreSQL database URL is required")
        if not SCHEMA_NAME.fullmatch(schema):
            raise ValueError(f"not a usable schema name: {schema!r}")
        self.dsn = dsn
        self.schema = schema
        self.table = f'"{schema}"."telegram_updates"'

    async def _connection(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return await psycopg.AsyncConnection.connect(
            self.dsn, autocommit=True, row_factory=dict_row
        )

    async def setup(self) -> None:
        """Create the inbox table as an explicit deployment migration."""

        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                await cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table} (
                        update_id   BIGINT PRIMARY KEY,
                        payload     JSONB NOT NULL,
                        state       TEXT NOT NULL DEFAULT 'pending'
                                    CHECK (state IN ('pending', 'running', 'done')),
                        lease_token TEXT,
                        lease_until TIMESTAMPTZ,
                        attempts    INTEGER NOT NULL DEFAULT 0,
                        last_error  TEXT,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

    async def enqueue(self, update_id: int, payload: dict[str, Any]) -> EnqueueResult:
        from psycopg.types.json import Jsonb

        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"INSERT INTO {self.table} (update_id, payload) VALUES (%s, %s)"
                    " ON CONFLICT (update_id) DO NOTHING RETURNING state",
                    (update_id, Jsonb(payload)),
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    return EnqueueResult(update_id, True)
                await cursor.execute(
                    f"SELECT state, lease_until < CURRENT_TIMESTAMP AS expired"
                    f" FROM {self.table} WHERE update_id = %s",
                    (update_id,),
                )
                row = await cursor.fetchone()
        should_spawn = bool(
            row
            and (row["state"] == "pending" or (row["state"] == "running" and row["expired"]))
        )
        return EnqueueResult(update_id, should_spawn)

    async def claim(self, update_id: int, lease_seconds: int = 900) -> InboxJob | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        token = uuid.uuid4().hex
        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"UPDATE {self.table} SET state = 'running', lease_token = %s,"
                    " lease_until = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),"
                    " attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP"
                    " WHERE update_id = %s AND (state = 'pending' OR"
                    " (state = 'running' AND lease_until < CURRENT_TIMESTAMP))"
                    " RETURNING payload",
                    (token, lease_seconds, update_id),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        return InboxJob(update_id, dict(row["payload"]), token)

    async def complete(self, job: InboxJob) -> None:
        await self._finish(job, "done", None)

    async def retry(self, job: InboxJob, error: str) -> None:
        await self._finish(job, "pending", error[:1000])

    async def _finish(self, job: InboxJob, state: str, error: str | None) -> None:
        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"UPDATE {self.table} SET state = %s, lease_token = NULL,"
                    " lease_until = NULL, last_error = %s, updated_at = CURRENT_TIMESTAMP"
                    " WHERE update_id = %s AND lease_token = %s",
                    (state, error, job.update_id, job.lease_token),
                )

