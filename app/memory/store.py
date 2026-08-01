"""Everything that must outlive the process.

One SQLite file holds threads, their messages, a rolling summary per thread, and
long-term facts. Facts are deliberately not scoped to a thread: the point of a
long-term fact is that a later conversation finds it.

The store is synchronous. A local single-user agent spends its time waiting on
the model, not on SQLite, and an async wrapper would buy nothing but a
dependency.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from app.models import ContentPart, Message, ToolCall

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id                 TEXT PRIMARY KEY,
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
    thread_id  TEXT,
    created_at TEXT NOT NULL
);

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


@dataclass(frozen=True)
class Thread:
    """Enough about a conversation to choose it without opening it."""

    id: str
    created_at: str
    updated_at: str
    messages: int
    opening: str


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


class MemoryStore:
    """The project's SQLite file."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._db.commit()

    # --- threads -------------------------------------------------------------

    def ensure_thread(self, thread_id: str) -> None:
        now = _now()
        self._db.execute(
            "INSERT INTO threads (id, created_at, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(id) DO NOTHING",
            (thread_id, now, now),
        )
        self._db.commit()

    def threads(self) -> list[Thread]:
        """Every conversation, most recently touched first.

        Carries what a chooser needs — how long it is and how it began — because
        a thread identifier is a session UUID and says nothing to anyone.
        """

        rows = self._db.execute(
            "SELECT t.id, t.created_at, t.updated_at,"
            "  (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS messages,"
            "  (SELECT m.content FROM messages m WHERE m.thread_id = t.id AND m.role = 'user'"
            "   ORDER BY m.position LIMIT 1) AS opening"
            " FROM threads t ORDER BY t.updated_at DESC, t.rowid DESC"
        ).fetchall()
        return [
            Thread(
                id=row["id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                messages=row["messages"],
                opening=_opening_text(row["opening"]),
            )
            for row in rows
        ]

    # --- messages ------------------------------------------------------------

    def append(self, thread_id: str, messages: Iterable[Message]) -> int:
        """Append messages to a thread and return the new message count."""

        self.ensure_thread(thread_id)
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

    def messages(self, thread_id: str, after: int = -1, limit: int | None = None) -> list[Message]:
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
        self.ensure_thread(thread_id)
        self._db.execute(
            "UPDATE threads SET summary = ?, summarized_through = ?, updated_at = ? WHERE id = ?",
            (text, through, _now(), thread_id),
        )
        self._db.commit()

    # --- facts ---------------------------------------------------------------

    def remember(self, text: str, thread_id: str | None = None) -> int:
        text = text.strip()
        if not text:
            raise ValueError("a fact cannot be empty")
        cursor = self._db.execute(
            "INSERT INTO facts (text, thread_id, created_at) VALUES (?, ?, ?)",
            (text, thread_id, _now()),
        )
        self._db.commit()
        return int(cursor.lastrowid or 0)

    def search(self, query: str, limit: int = 5) -> list[str]:
        """Full-text search over facts, best match first."""

        match = match_query(query)
        if not match:
            return []
        rows = self._db.execute(
            "SELECT f.text FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
            " WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
        return [row["text"] for row in rows]

    def facts(self, limit: int = 50) -> list[str]:
        rows = self._db.execute(
            "SELECT text FROM facts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [row["text"] for row in rows]

    # --- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()
