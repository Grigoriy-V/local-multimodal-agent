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
    # The identity this turn will be measured under. Born at ingress and kept
    # with the durable row, so a redelivered update or a second spawn attempt
    # continues the same turn instead of starting a second measured one.
    run_id: str = ""


@dataclass(frozen=True)
class InboxJob:
    update_id: int
    payload: dict[str, Any]
    lease_token: str
    run_id: str = ""
    # How long the update waited between arriving and being claimed: the queue
    # plus the worker's own cold start, which is the largest CPU number in the
    # chain and would otherwise fall outside every measurement.
    queued_ms: int = 0


class UpdateInbox(Protocol):
    async def enqueue(
        self, update_id: int, payload: dict[str, Any], run_id: str = ""
    ) -> EnqueueResult: ...

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
                        run_id      TEXT,
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
                # Additive, for a queue table that already holds rows. Existing
                # updates get a NULL run id and are handled as "not measured",
                # never as an error.
                await cursor.execute(
                    f"ALTER TABLE {self.table} ADD COLUMN IF NOT EXISTS run_id TEXT"
                )

    async def enqueue(
        self, update_id: int, payload: dict[str, Any], run_id: str = ""
    ) -> EnqueueResult:
        from psycopg.types.json import Jsonb

        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"INSERT INTO {self.table} (update_id, run_id, payload)"
                    " VALUES (%s, %s, %s)"
                    " ON CONFLICT (update_id) DO NOTHING RETURNING state",
                    (update_id, run_id or None, Jsonb(payload)),
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    return EnqueueResult(update_id, True, run_id)
                await cursor.execute(
                    f"SELECT state, run_id, lease_until < CURRENT_TIMESTAMP AS expired"
                    f" FROM {self.table} WHERE update_id = %s",
                    (update_id,),
                )
                row = await cursor.fetchone()
        should_spawn = bool(
            row
            and (row["state"] == "pending" or (row["state"] == "running" and row["expired"]))
        )
        # The stored run id wins over the one just generated. A second delivery
        # of one update is the same turn seen twice, not two turns.
        return EnqueueResult(update_id, should_spawn, (row or {}).get("run_id") or "")

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
                    " RETURNING payload, run_id,"
                    " EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at)) AS waited",
                    (token, lease_seconds, update_id),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        return InboxJob(
            update_id,
            dict(row["payload"]),
            token,
            run_id=row["run_id"] or "",
            queued_ms=max(0, int(float(row["waited"] or 0.0) * 1000)),
        )

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

