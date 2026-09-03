"""Opening a database written before conversations and facts had owners.

The local profile has a populated file on disk. Adding scope must not ask the
human to throw it away, and must not guess an owner for rows that predate the
question: everything already there belongs to the one person who has been using
the local profile, so it is handed to `LOCAL_USER_ID`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.memory import LOCAL_USER_ID, SCHEMA_VERSION, SqliteStore

# The schema exactly as it stood before user scope existed. Kept literal so this
# test keeps describing the file it actually has to open, rather than whatever
# the current schema happens to say.
SCHEMA_V0 = """
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

CONTENT = '[{"kind": "text", "text": "an older conversation", "data": null, "media_type": null}]'


def write_v0(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA_V0)
    db.execute(
        "INSERT INTO threads (id, created_at, updated_at, summary, summarized_through)"
        " VALUES ('old-chat', '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00',"
        " 'they discussed the roadmap', 2)"
    )
    db.execute(
        "INSERT INTO messages (thread_id, position, role, content, created_at)"
        " VALUES ('old-chat', 0, 'user', ?, '2026-08-01T00:00:00+00:00')",
        (CONTENT,),
    )
    db.execute(
        "INSERT INTO facts (text, thread_id, created_at)"
        " VALUES ('The vLLM server runs in WSL2', 'old-chat', '2026-08-01T00:00:00+00:00')"
    )
    db.commit()
    db.close()


def test_a_database_without_owners_is_migrated_not_rejected(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    write_v0(path)

    with SqliteStore(path) as store:
        assert [thread.id for thread in store.threads(LOCAL_USER_ID)] == ["old-chat"]


def test_existing_rows_are_handed_to_the_local_user(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    write_v0(path)

    with SqliteStore(path) as store:
        assert store.thread_owner("old-chat") == LOCAL_USER_ID
        assert store.search("WSL2", LOCAL_USER_ID) == ["The vLLM server runs in WSL2"]
        assert store.search("WSL2", "somebody-else") == []


def test_migration_preserves_messages_and_summaries(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    write_v0(path)

    with SqliteStore(path) as store:
        [message] = store.messages("old-chat")
        assert message.content[0].text == "an older conversation"
        assert store.summary("old-chat") == ("they discussed the roadmap", 2)


def test_the_file_records_the_version_it_reached(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    write_v0(path)

    SqliteStore(path).close()

    db = sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        db.close()


def test_reopening_a_migrated_database_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    write_v0(path)

    SqliteStore(path).close()
    with SqliteStore(path) as store:
        store.remember("Added after the migration", LOCAL_USER_ID)
        assert store.thread_owner("old-chat") == LOCAL_USER_ID
        assert len(store.facts(LOCAL_USER_ID)) == 2


def test_the_failure_column_and_the_compaction_table_arrive_with_schema_3(tmp_path: Path) -> None:
    """A version-0 file has neither; after opening it has both, and its rows
    read as messages without a failure."""

    path = tmp_path / "memory.sqlite3"
    write_v0(path)

    with SqliteStore(path) as store:
        [message] = store.messages("old-chat")
        assert message.failure is None
        store.record_compaction("old-chat", through=1, folded=1, trigger="count", summary_chars=5)
        assert [c.through for c in store.compactions("old-chat")] == [1]


def test_a_fresh_database_starts_at_the_current_version(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"

    SqliteStore(path).close()

    db = sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        db.close()
