"""Asking a turn that is already running to stop.

A stop is not an ordinary request. It arrives while the thing it is about is
still executing, usually in another process, and everything that makes an
ordinary turn correct — queue, order, one conversation at a time — is exactly
what would make a stop useless. So it travels out of band at the front door and
lands here, in the one piece of state a running turn can read.

**The sequence is what keeps a stop from outliving its turn.** Every incoming
event of a conversation gets a number that only grows: Telegram's own
`update_id` in the deployed and local profiles, a session counter in Chainlit.
A stop records the number it arrived with, and a running turn is stopped when
that number is greater than its own. The next turn's number is greater still,
so a stop nobody consumed cannot cancel a message sent after it — which is the
failure a plain boolean flag has.

Two implementations because the two profiles differ in exactly one way that
matters: locally the turn and the stop are in one process, deployed they are in
two containers with a database between them.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

SCHEMA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StopRequests(Protocol):
    """Where a conversation's most recent stop is recorded."""

    async def request(self, key: str, sequence: int) -> None:
        """Record that everything started before `sequence` should stop."""

    async def requested(self, key: str, since: int) -> bool:
        """Whether a turn that began at `since` has been asked to stop."""


class NoStopRequests:
    """For every caller that has no way to be stopped — tests, one-shot runs.

    A null object rather than an optional, for the same reason `NO_TRACE` is
    one: a loop that has to ask whether it can be stopped before checking ends
    up not checking.
    """

    async def request(self, key: str, sequence: int) -> None:
        return None

    async def requested(self, key: str, since: int) -> bool:
        return False


NO_STOPS = NoStopRequests()


class MemoryStopRequests:
    """The local profile: one process, so the running turn is in this memory."""

    def __init__(self) -> None:
        self._latest: dict[str, int] = {}

    async def request(self, key: str, sequence: int) -> None:
        self._latest[key] = max(sequence, self._latest.get(key, 0))

    async def requested(self, key: str, since: int) -> bool:
        return self._latest.get(key, 0) > since


class PostgresStopRequests:
    """The deployed profile: the stop and the turn are in different containers.

    One row per conversation in the control plane's own database, which is the
    only thing both containers can see. Connections are opened per operation,
    like the inbox, because these processes scale to zero between requests.
    """

    def __init__(self, dsn: str, schema: str = "public") -> None:
        if not dsn:
            raise ValueError("a PostgreSQL database URL is required")
        if not SCHEMA_NAME.fullmatch(schema):
            raise ValueError(f"not a usable schema name: {schema!r}")
        self.dsn = dsn
        self.schema = schema
        self.table = f'"{schema}"."turn_stops"'

    async def _connection(self) -> Any:
        import psycopg

        return await psycopg.AsyncConnection.connect(self.dsn, autocommit=True)

    async def setup(self) -> None:
        """Create the table as an explicit deployment migration."""

        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                await cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table} (
                        conversation_key TEXT PRIMARY KEY,
                        sequence         BIGINT NOT NULL,
                        requested_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

    async def request(self, key: str, sequence: int) -> None:
        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                # `GREATEST` rather than a plain overwrite: two stops sent in
                # quick succession must not move the mark backwards.
                await cursor.execute(
                    f"INSERT INTO {self.table} (conversation_key, sequence)"
                    " VALUES (%s, %s)"
                    " ON CONFLICT (conversation_key) DO UPDATE"
                    f" SET sequence = GREATEST({self.table}.sequence, EXCLUDED.sequence),"
                    " requested_at = CURRENT_TIMESTAMP",
                    (key, sequence),
                )

    async def requested(self, key: str, since: int) -> bool:
        connection = await self._connection()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT sequence > %s FROM {self.table} WHERE conversation_key = %s",
                    (since, key),
                )
                row = await cursor.fetchone()
        return bool(row and row[0])
