"""The PostgreSQL implementation of the persistence contract.

The deployed profile cannot use the SQLite file: workers are separate processes
on separate machines, and there is no shared disk under them. This answers the
same `ConversationStore` questions over a networked database, and is exercised
by the same contract suite — a second implementation that is not is a second
implementation that drifts.

**Provider-agnostic on purpose.** Nothing here knows which service is behind the
DSN. Where a deployment connects, whether it goes through a pooler, how TLS is
required and how aggressively idle connections are dropped are all connection
configuration, carried in the DSN. Today that is Neon, which means the pooled
endpoint for serverless workers — a scaled-to-zero worker fleet opens and closes
connections in bursts, and a direct endpoint runs out of them long before the
database runs out of capacity. Swapping the provider must be a change to
configuration and not to this file.

One consequence is handled here because it is not provider-specific: a networked
database closes idle connections, so a store that outlives a pause has to be
able to open a new one. `_cursor` does that once per call rather than assuming
the socket from start-up is still there.

The store is synchronous, like the SQLite one, because `ConversationStore` is.
The worker waits on the model, not on this.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.memory.base import ConversationStore, Thread, TurnContextRecords
from app.memory.records import (
    dump_content,
    dump_tool_calls,
    now,
    opening_text,
    row_to_message,
)
from app.models import Message

# Bumped whenever the schema changes, and stored in the database rather than
# inferred from which columns happen to exist. Postgres has no `user_version`,
# so the row below is this project's own equivalent.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    id                 TEXT PRIMARY KEY,
    seq                BIGSERIAL,
    user_id            TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    summary            TEXT,
    summarized_through INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    thread_id    TEXT NOT NULL REFERENCES threads(id),
    position     INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    tool_calls   TEXT,
    tool_call_id TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (thread_id, position)
);

CREATE TABLE IF NOT EXISTS facts (
    id         BIGSERIAL PRIMARY KEY,
    text       TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    thread_id  TEXT,
    created_at TEXT NOT NULL,
    search     tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);

CREATE INDEX IF NOT EXISTS threads_by_user ON threads (user_id);
CREATE INDEX IF NOT EXISTS facts_by_user ON facts (user_id);
CREATE INDEX IF NOT EXISTS facts_search ON facts USING GIN (search);
"""

TOKEN = re.compile(r"\w+", re.UNICODE)


def match_query(query: str) -> str:
    """Turn free text into a `tsquery` expression, or an empty string.

    The query comes from a model, so it may contain anything at all. Only word
    characters survive, which is both the sanitisation and the reason the result
    can be interpolated as a tsquery without becoming a syntax error.

    `simple` is the text-search configuration everywhere in this file: it does
    not stem, which matches what SQLite's FTS5 does in the local profile, and it
    does not assume the conversation is in English. An assistant used in Russian
    would otherwise search worse than the local one it replaces.
    """

    return " | ".join(TOKEN.findall(query))


def migrate(connection: psycopg.Connection, schema: str) -> int:
    """Bring the database up to `SCHEMA_VERSION`, returning the version found.

    Version 0 is an empty database. Unlike the SQLite store there is no earlier
    shape to carry forward: this implementation has never been deployed, so the
    first migration is the schema itself.
    """

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        # Transaction-local state cannot leak through a transaction pooler to
        # the next client that receives this server connection.
        cursor.execute(f'SET LOCAL search_path TO "{schema}"')
        cursor.execute(SCHEMA)
        cursor.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        found = 0 if row is None else int(row["version"])
        if found >= SCHEMA_VERSION:
            connection.commit()
            return found
        if row is None:
            cursor.execute("INSERT INTO schema_version (version) VALUES (%s)", (SCHEMA_VERSION,))
        else:
            cursor.execute("UPDATE schema_version SET version = %s", (SCHEMA_VERSION,))
    connection.commit()
    return found


class PostgresStore(ConversationStore):
    """Conversations, summaries and facts in PostgreSQL.

    `schema` keeps this application's tables together in a database that may
    hold other things, and gives a test its own namespace to create and drop.
    """

    def __init__(
        self, dsn: str, schema: str = "public", *, migrate_schema: bool = False
    ) -> None:
        if not TOKEN.fullmatch(schema):
            raise ValueError(f"not a usable schema name: {schema!r}")
        self.dsn = dsn
        self.schema = schema
        self._connection: psycopg.Connection | None = self._open()
        if migrate_schema:
            migrate(self._connection, self.schema)

    # --- connection ----------------------------------------------------------

    def _open(self) -> psycopg.Connection:
        connection = psycopg.connect(self.dsn, row_factory=dict_row)
        self._connection = connection
        return connection

    def _live_connection(self) -> psycopg.Connection:
        connection = self._connection
        if connection is None or connection.closed or connection.broken:
            connection = self._open()
        return connection

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor]:
        """A cursor on a live connection, reopening one that went away.

        A pooled or serverless database hangs up on an idle client, and this
        assistant is idle by design between messages. Reconnecting is therefore
        the normal path after a pause, not an error path.

        A connection that dies mid-statement is not retried here: the caller's
        statements would have to be replayed, and this cannot know whether that
        is safe. It is dropped instead, so the next call opens a new one.
        """

        connection = self._live_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL search_path TO "{self.schema}"')
                yield cursor
        except psycopg.OperationalError:
            self._connection = None
            connection.close()
            raise

    # --- threads -------------------------------------------------------------

    def ensure_thread(self, thread_id: str, user_id: str) -> None:
        stamp = now()
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO threads (id, user_id, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (thread_id, user_id, stamp, stamp),
            )
            cursor.connection.commit()

    def threads(self, user_id: str) -> list[Thread]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT t.id, t.user_id, t.created_at, t.updated_at,"
                "  (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS messages,"
                "  (SELECT m.content FROM messages m WHERE m.thread_id = t.id"
                "   AND m.role = 'user' ORDER BY m.position LIMIT 1) AS opening"
                " FROM threads t WHERE t.user_id = %s"
                " ORDER BY t.updated_at DESC, t.seq DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
        return [
            Thread(
                id=row["id"],
                user_id=row["user_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                messages=int(row["messages"]),
                opening=opening_text(row["opening"]),
            )
            for row in rows
        ]

    def thread_owner(self, thread_id: str) -> str | None:
        with self._cursor() as cursor:
            cursor.execute("SELECT user_id FROM threads WHERE id = %s", (thread_id,))
            row = cursor.fetchone()
        return None if row is None else row["user_id"]

    def delete_thread(self, thread_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("SELECT 1 FROM threads WHERE id = %s", (thread_id,))
            if cursor.fetchone() is None:
                return False
            # Facts are the user's memory, not the conversation's. Dropping the
            # provenance avoids a dangling reference without forgetting the fact
            # or changing who it belongs to.
            cursor.execute(
                "UPDATE facts SET thread_id = NULL WHERE thread_id = %s", (thread_id,)
            )
            cursor.execute("DELETE FROM messages WHERE thread_id = %s", (thread_id,))
            cursor.execute("DELETE FROM threads WHERE id = %s", (thread_id,))
            cursor.connection.commit()
        return True

    # --- messages ------------------------------------------------------------

    def append(self, thread_id: str, messages: Iterable[Message], user_id: str) -> int:
        pending = list(messages)
        stamp = now()
        statement = sql.SQL(
            """
            WITH input AS (
                SELECT ordinality - 1 AS offset,
                       role, content, tool_calls, tool_call_id
                FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[])
                     WITH ORDINALITY
                     AS item(role, content, tool_calls, tool_call_id, ordinality)
            ),
            owned_thread AS (
                INSERT INTO {}.threads
                    (id, user_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                    SET updated_at = EXCLUDED.updated_at
                RETURNING id
            ),
            base AS (
                SELECT COALESCE(MAX(position), -1) + 1 AS next
                FROM {}.messages
                WHERE thread_id = %s
            ),
            inserted AS (
                INSERT INTO {}.messages
                    (thread_id, position, role, content, tool_calls,
                     tool_call_id, created_at)
                SELECT %s, (base.next + input.offset)::integer, input.role,
                       input.content, input.tool_calls, input.tool_call_id, %s
                FROM input
                CROSS JOIN base
                CROSS JOIN owned_thread
                RETURNING position
            )
            SELECT COALESCE(
                MAX(position) + 1,
                (SELECT next FROM base)
            ) AS count
            FROM inserted
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
        )
        connection = self._live_connection()
        try:
            with connection.cursor() as cursor:
                with connection.pipeline():
                    cursor.execute(
                        statement,
                        (
                            [message.role for message in pending],
                            [dump_content(message.content) for message in pending],
                            [dump_tool_calls(message.tool_calls) for message in pending],
                            [message.tool_call_id for message in pending],
                            thread_id,
                            user_id,
                            stamp,
                            stamp,
                            thread_id,
                            thread_id,
                            stamp,
                        ),
                    )
                    connection.commit()
                row = cursor.fetchone()
        except psycopg.OperationalError:
            self._connection = None
            connection.close()
            raise
        if row is None:
            raise RuntimeError("append query returned no row")
        return int(row["count"])

    def messages(
        self, thread_id: str, after: int = -1, limit: int | None = None
    ) -> list[Message]:
        sql = (
            "SELECT role, content, tool_calls, tool_call_id FROM messages"
            " WHERE thread_id = %s AND position > %s ORDER BY position"
        )
        parameters: list[Any] = [thread_id, after]
        if limit is not None:
            sql += " LIMIT %s"
            parameters.append(limit)
        with self._cursor() as cursor:
            cursor.execute(sql, parameters)
            rows = cursor.fetchall()
        return [row_to_message(row) for row in rows]

    def message_count(self, thread_id: str) -> int:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE thread_id = %s", (thread_id,)
            )
            return int(cursor.fetchone()["n"])  # type: ignore[index]

    # --- rolling summary -----------------------------------------------------

    def summary(self, thread_id: str) -> tuple[str | None, int]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT summary, summarized_through FROM threads WHERE id = %s",
                (thread_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None, 0
        return row["summary"], int(row["summarized_through"])

    def set_summary(self, thread_id: str, text: str, through: int) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE threads SET summary = %s, summarized_through = %s,"
                " updated_at = %s WHERE id = %s",
                (text, through, now(), thread_id),
            )
            if cursor.rowcount == 0:
                cursor.connection.rollback()
                raise KeyError(f"no such thread: {thread_id!r}")
            cursor.connection.commit()

    # --- facts ---------------------------------------------------------------

    def remember(self, text: str, user_id: str, thread_id: str | None = None) -> int:
        text = text.strip()
        if not text:
            raise ValueError("a fact cannot be empty")
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO facts (text, user_id, thread_id, created_at)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (text, user_id, thread_id, now()),
            )
            saved = int(cursor.fetchone()["id"])  # type: ignore[index]
            cursor.connection.commit()
        return saved

    def search(self, query: str, user_id: str, limit: int = 5) -> list[str]:
        match = match_query(query)
        if not match:
            return []
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT text FROM facts"
                " WHERE user_id = %s AND search @@ to_tsquery('simple', %s)"
                " ORDER BY ts_rank(search, to_tsquery('simple', %s)) DESC, id DESC"
                " LIMIT %s",
                (user_id, match, match, limit),
            )
            rows = cursor.fetchall()
        return [row["text"] for row in rows]

    def facts(self, user_id: str, limit: int = 50) -> list[str]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT text FROM facts WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                (user_id, limit),
            )
            rows = cursor.fetchall()
        return [row["text"] for row in rows]

    def turn_context(
        self,
        thread_id: str,
        user_id: str,
        query: str,
        retrieved_facts: int,
    ) -> TurnContextRecords:
        """Fetch summary, unsummarized history and facts in one round-trip."""

        match = match_query(query) if query else ""
        statement = sql.SQL(
            """
            WITH thread AS (
                SELECT summary, summarized_through
                FROM {}.threads
                WHERE id = %s
            ),
            history AS (
                SELECT position, role, content, tool_calls, tool_call_id
                FROM {}.messages
                WHERE thread_id = %s
                  AND position > COALESCE(
                      (SELECT summarized_through FROM thread), 0
                  ) - 1
                ORDER BY position
            ),
            fact_query AS (
                SELECT CASE
                    WHEN %s = '' THEN NULL
                    ELSE to_tsquery('simple', %s)
                END AS value
            ),
            matched_facts AS (
                SELECT fact.text, fact.id,
                       ts_rank(fact.search, fact_query.value) AS rank
                FROM {}.facts AS fact
                CROSS JOIN fact_query
                WHERE fact.user_id = %s
                  AND fact_query.value IS NOT NULL
                  AND fact.search @@ fact_query.value
                ORDER BY rank DESC, fact.id DESC
                LIMIT %s
            )
            SELECT
                (SELECT summary FROM thread) AS summary,
                COALESCE(
                    (SELECT summarized_through FROM thread), 0
                ) AS summarized_through,
                COALESCE(
                    (SELECT jsonb_agg(to_jsonb(history) ORDER BY position)
                     FROM history),
                    '[]'::jsonb
                ) AS history,
                COALESCE(
                    (SELECT jsonb_agg(text ORDER BY rank DESC, id DESC)
                     FROM matched_facts),
                    '[]'::jsonb
                ) AS facts
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
        )
        connection = self._live_connection()
        restore_autocommit = not connection.autocommit
        try:
            if restore_autocommit:
                connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    statement,
                    (
                        thread_id,
                        thread_id,
                        match,
                        match,
                        user_id,
                        retrieved_facts,
                    ),
                )
                row = cursor.fetchone()
        except psycopg.OperationalError:
            self._connection = None
            connection.close()
            raise
        finally:
            if restore_autocommit and not connection.closed:
                connection.autocommit = False
        if row is None:
            raise RuntimeError("context query returned no row")
        return TurnContextRecords(
            summary=row["summary"],
            summarized_through=int(row["summarized_through"]),
            messages=[row_to_message(item) for item in row["history"]],
            facts=list(row["facts"]),
        )

    # --- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            self._connection.close()

    def drop_schema(self) -> None:
        """Remove this store's schema and everything in it.

        Exists for the contract suite, which gives every test a schema of its
        own and must not leave them behind. It refuses `public` outright: the
        default schema is where a real deployment's conversations live, and a
        method that can delete them by being called with default arguments is a
        method that eventually will be.
        """

        if self.schema == "public":
            raise ValueError("refusing to drop the public schema")
        with self._cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            cursor.connection.commit()
