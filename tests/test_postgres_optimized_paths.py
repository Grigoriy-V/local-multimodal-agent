from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.memory.postgres import PostgresStore
from app.memory.records import dump_content
from app.models import ContentPart, Message


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exception: object) -> None:
        return None

    def execute(self, statement: Any, parameters: object = None) -> None:
        rendered = statement.as_string() if hasattr(statement, "as_string") else statement
        self.connection.executions.append((rendered, parameters))

    def fetchone(self) -> dict[str, object]:
        return self.connection.row


class FakeConnection:
    broken = False

    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.closed = False
        self.autocommit = False
        self.executions: list[tuple[str, object]] = []
        self.commits = 0
        self.pipeline_entries = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @contextmanager
    def pipeline(self) -> Iterator[None]:
        self.pipeline_entries += 1
        yield

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def install_connection(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, object]
) -> FakeConnection:
    connection = FakeConnection(row)
    monkeypatch.setattr(
        "app.memory.postgres.psycopg.connect",
        lambda _dsn, *, row_factory: connection,
    )
    return connection


def test_runtime_open_does_not_execute_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = install_connection(monkeypatch, {})

    PostgresStore("postgresql://example/db", "assistant")

    assert connection.executions == []


def test_turn_context_is_one_schema_qualified_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = install_connection(
        monkeypatch,
        {
            "summary": "earlier",
            "summarized_through": 0,
            "history": [
                {
                    "position": 0,
                    "role": "user",
                    "content": dump_content(
                        [ContentPart(kind="text", text="hello")]
                    ),
                    "tool_calls": None,
                    "tool_call_id": None,
                }
            ],
            "facts": ["remembered"],
        },
    )
    store = PostgresStore("postgresql://example/db", "assistant")

    records = store.turn_context("thread", "owner", "hello", 5)

    assert records.summary == "earlier"
    assert records.messages[0].content[0].text == "hello"
    assert records.facts == ["remembered"]
    assert len(connection.executions) == 1
    statement, _ = connection.executions[0]
    assert '"assistant".threads' in statement
    assert '"assistant".messages' in statement
    assert '"assistant".facts' in statement
    assert "SET LOCAL" not in statement
    assert connection.autocommit is False


def test_append_is_one_execute_with_a_pipelined_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = install_connection(monkeypatch, {"count": 2})
    store = PostgresStore("postgresql://example/db", "assistant")

    count = store.append(
        "thread",
        [
            Message(role="user", content=[ContentPart(kind="text", text="hello")]),
            Message(
                role="assistant",
                content=[ContentPart(kind="text", text="hi")],
            ),
        ],
        "owner",
    )

    assert count == 2
    assert len(connection.executions) == 1
    assert connection.pipeline_entries == 1
    assert connection.commits == 1
    statement, _ = connection.executions[0]
    assert 'INSERT INTO "assistant".threads' in statement
    assert 'INSERT INTO "assistant".messages' in statement
    assert "SET LOCAL" not in statement
