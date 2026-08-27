"""The SQLite implementation of the persistence contract.

One file holds threads, their messages, a rolling summary per thread, and
long-term facts. Facts are not scoped to a thread — the point of a long-term
fact is that a later conversation finds it — but they are scoped to a user,
because the point stops holding across people.

The store is synchronous. A local agent spends its time waiting on the model,
not on SQLite, and an async wrapper would buy nothing but a dependency. The
deployed profile does not share that property and gets its own implementation of
`ConversationStore` rather than an async disguise over this one.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.memory.base import LOCAL_USER_ID, ConversationStore, Thread
from app.models import ContentPart, Message, ToolCall

# Bumped whenever the schema changes. `PRAGMA user_version` is SQLite's own
# integer on the file, so the database states its shape rather than the code
# guessing it from which columns happen to exist.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL DEFAULT 'local-user',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    summary            TEXT,
    summarized_through INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    user_id    TEXT NOT NULL DEFAULT 'local-user',
    thread_id  TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS threads_by_user ON threads(user_id);
CREATE INDEX IF NOT EXISTS facts_by_user ON facts(user_id);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(text, content='facts', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

TOKEN = re.compile(r"\w+", re.UNICODE)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def dump_content(parts: Sequence[ContentPart]) -> str:
    """Serialize content parts. Media is stored, not dropped, so a reloaded
    conversation is the same conversation."""

    payload = [
        {
            "kind": part.kind,
            "text": part.text,
            "data": base64.b64encode(part.data).decode("ascii") if part.data else None,
            "media_type": part.media_type,
        }
        for part in parts
    ]
    return json.dumps(payload)


def load_content(raw: str) -> list[ContentPart]:
    return [
        ContentPart(
            kind=item["kind"],
            text=item["text"],
            data=base64.b64decode(item["data"]) if item["data"] else None,
            media_type=item["media_type"],
        )
        for item in json.loads(raw)
    ]


def _dump_tool_calls(calls: Sequence[ToolCall]) -> str | None:
    if not calls:
        return None
    return json.dumps([{"id": c.id, "name": c.name, "arguments": c.arguments} for c in calls])


def _load_tool_calls(raw: str | None) -> tuple[ToolCall, ...]:
    if not raw:
        return ()
    return tuple(ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"]) for c in json.loads(raw))


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        role=row["role"],
        content=load_content(row["content"]),
        tool_calls=_load_tool_calls(row["tool_calls"]),
        tool_call_id=row["tool_call_id"],
    )


def _opening_text(raw: str | None) -> str:
    """The words a thread began with. A picture on its own leaves none."""

    if not raw:
        return ""
    return " ".join(part.text or "" for part in load_content(raw) if part.kind == "text").strip()


def match_query(query: str) -> str:
    """Turn free text into an FTS5 MATCH expression.

    The query comes from a model, so it may contain anything. Every token is
    quoted and the rest is dropped, because an unescaped `-` or `*` is an FTS5
    syntax error rather than a poor search.
    """

    tokens = TOKEN.findall(query)
    return " OR ".join(f'"{token}"' for token in tokens)


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def migrate(db: sqlite3.Connection) -> int:
    """Bring a database up to `SCHEMA_VERSION`, returning the version found.

    Version 0 is either an empty file or a database written before conversations
    and facts had owners. In the second case every existing row belongs to the
    person who has been using the local profile all along, so the backfill hands
    them to `LOCAL_USER_ID` rather than inventing an owner or refusing to open.
    """

    found = int(db.execute("PRAGMA user_version").fetchone()[0])
    if found >= SCHEMA_VERSION:
        return found

    tables = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table in ("threads", "facts"):
        if table in tables and "user_id" not in _columns(db, table):
            db.execute(
                f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL"
                f" DEFAULT '{LOCAL_USER_ID}'"
            )
    db.executescript(SCHEMA)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()
    return found


class SqliteStore(ConversationStore):
    """The project's SQLite file."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        migrate(self._db)

    # --- threads -------------------------------------------------------------

    def ensure_thread(self, thread_id: str, user_id: str) -> None:
        now = _now()
        self._db.execute(
            "INSERT INTO threads (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO NOTHING",
            (thread_id, user_id, now, now),
        )
        self._db.commit()

    def threads(self, user_id: str) -> list[Thread]:
        """This user's conversations, most recently touched first.

        Carries what a chooser needs — how long it is and how it began — because
        a thread identifier is a session UUID and says nothing to anyone.
        """

        rows = self._db.execute(
            "SELECT t.id, t.user_id, t.created_at, t.updated_at,"
            "  (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS messages,"
            "  (SELECT m.content FROM messages m WHERE m.thread_id = t.id AND m.role = 'user'"
            "   ORDER BY m.position LIMIT 1) AS opening"
            " FROM threads t WHERE t.user_id = ?"
            " ORDER BY t.updated_at DESC, t.rowid DESC",
            (user_id,),
        ).fetchall()
        return [
            Thread(
                id=row["id"],
                user_id=row["user_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                messages=row["messages"],
                opening=_opening_text(row["opening"]),
            )
            for row in rows
        ]

    def thread_owner(self, thread_id: str) -> str | None:
        row = self._db.execute(
            "SELECT user_id FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        return None if row is None else row["user_id"]

    def delete_thread(self, thread_id: str) -> bool:
        """Delete one conversation while preserving separately approved facts."""

        with self._db:
            exists = self._db.execute(
                "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if exists is None:
                return False
            # Facts are the user's memory, not the conversation's. Removing their
            # deleted-conversation provenance avoids a dangling reference without
            # forgetting the fact or changing who it belongs to.
            self._db.execute(
                "UPDATE facts SET thread_id = NULL WHERE thread_id = ?", (thread_id,)
            )
            self._db.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
            self._db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        return True

    # --- messages ------------------------------------------------------------

    def append(self, thread_id: str, messages: Iterable[Message], user_id: str) -> int:
        """Append messages to a thread and return the new message count."""

        self.ensure_thread(thread_id, user_id)
        position = self._db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM messages WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()["next"]
        now = _now()
        for message in messages:
            self._db.execute(
                "INSERT INTO messages"
                " (thread_id, position, role, content, tool_calls, tool_call_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    position,
                    message.role,
                    dump_content(message.content),
                    _dump_tool_calls(message.tool_calls),
                    message.tool_call_id,
                    now,
                ),
            )
            position += 1
        self._db.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        self._db.commit()
        return position

    def messages(
        self, thread_id: str, after: int = -1, limit: int | None = None
    ) -> list[Message]:
        """Messages of a thread in order, optionally only those past a position."""

        sql = "SELECT * FROM messages WHERE thread_id = ? AND position > ? ORDER BY position"
        parameters: list[Any] = [thread_id, after]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        return [_row_to_message(row) for row in self._db.execute(sql, parameters)]

    def message_count(self, thread_id: str) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row["n"]

    # --- rolling summary -----------------------------------------------------

    def summary(self, thread_id: str) -> tuple[str | None, int]:
        """The thread's summary and the position it covers through."""

        row = self._db.execute(
            "SELECT summary, summarized_through FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            return None, 0
        return row["summary"], row["summarized_through"]

    def set_summary(self, thread_id: str, text: str, through: int) -> None:
        cursor = self._db.execute(
            "UPDATE threads SET summary = ?, summarized_through = ?, updated_at = ? WHERE id = ?",
            (text, through, _now(), thread_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"no such thread: {thread_id!r}")
        self._db.commit()

    # --- facts ---------------------------------------------------------------

    def remember(self, text: str, user_id: str, thread_id: str | None = None) -> int:
        text = text.strip()
        if not text:
            raise ValueError("a fact cannot be empty")
        cursor = self._db.execute(
            "INSERT INTO facts (text, user_id, thread_id, created_at) VALUES (?, ?, ?, ?)",
            (text, user_id, thread_id, _now()),
        )
        self._db.commit()
        return int(cursor.lastrowid or 0)

    def search(self, query: str, user_id: str, limit: int = 5) -> list[str]:
        """Full-text search over this user's facts, best match first."""

        match = match_query(query)
        if not match:
            return []
        rows = self._db.execute(
            "SELECT f.text FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
            " WHERE facts_fts MATCH ? AND f.user_id = ?"
            " ORDER BY bm25(facts_fts) LIMIT ?",
            (match, user_id, limit),
        ).fetchall()
        return [row["text"] for row in rows]

    def facts(self, user_id: str, limit: int = 50) -> list[str]:
        rows = self._db.execute(
            "SELECT text FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [row["text"] for row in rows]

    # --- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._db.close()
