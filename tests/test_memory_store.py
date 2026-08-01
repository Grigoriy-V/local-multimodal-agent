"""Persistence, including the part that only matters after a restart."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.memory import MemoryStore
from app.memory.store import match_query
from app.models import ContentPart, Message, ToolCall


def text(value: str) -> list[ContentPart]:
    return [ContentPart(kind="text", text=value)]


def user(value: str) -> Message:
    return Message(role="user", content=text(value))


@pytest.fixture
def store() -> MemoryStore:
    with MemoryStore() as store:
        yield store


# --- messages ----------------------------------------------------------------


def test_messages_come_back_in_order(store: MemoryStore) -> None:
    store.append("t1", [user("one"), user("two"), user("three")])

    assert [m.content[0].text for m in store.messages("t1")] == ["one", "two", "three"]


def test_appending_twice_continues_the_positions(store: MemoryStore) -> None:
    store.append("t1", [user("one")])
    store.append("t1", [user("two")])

    assert store.message_count("t1") == 2
    assert [m.content[0].text for m in store.messages("t1")] == ["one", "two"]


def test_threads_do_not_see_each_other(store: MemoryStore) -> None:
    store.append("t1", [user("mine")])
    store.append("t2", [user("yours")])

    assert [m.content[0].text for m in store.messages("t1")] == ["mine"]
    assert set(store.threads()) == {"t1", "t2"}


def test_tool_calls_and_ids_survive_a_round_trip(store: MemoryStore) -> None:
    call = ToolCall(id="call_1", name="read_file", arguments={"path": "a.txt"})
    store.append(
        "t1",
        [
            Message(role="assistant", tool_calls=(call,)),
            Message(role="tool", content=text("contents"), tool_call_id="call_1"),
        ],
    )

    assistant, tool = store.messages("t1")
    assert assistant.content == ()
    assert assistant.tool_calls == (call,)
    assert tool.tool_call_id == "call_1"


def test_media_bytes_survive_a_round_trip(store: MemoryStore) -> None:
    part = ContentPart(kind="image", data=b"\x89PNG\x00\xff", media_type="image/png")
    store.append("t1", [Message(role="user", content=[ContentPart(kind="text", text="see"), part])])

    [message] = store.messages("t1")
    assert message.content[1].data == b"\x89PNG\x00\xff"
    assert message.content[1].media_type == "image/png"


def test_messages_can_be_read_from_a_position(store: MemoryStore) -> None:
    store.append("t1", [user("one"), user("two"), user("three")])

    assert [m.content[0].text for m in store.messages("t1", after=0)] == ["two", "three"]


def test_a_thread_survives_reopening_the_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    with MemoryStore(path) as first:
        first.append("t1", [user("remember me")])

    with MemoryStore(path) as second:
        assert [m.content[0].text for m in second.messages("t1")] == ["remember me"]


# --- rolling summary ---------------------------------------------------------


def test_a_thread_starts_without_a_summary(store: MemoryStore) -> None:
    store.ensure_thread("t1")

    assert store.summary("t1") == (None, 0)


def test_the_summary_records_what_it_covers(store: MemoryStore) -> None:
    store.set_summary("t1", "they discussed cats", 6)

    assert store.summary("t1") == ("they discussed cats", 6)


def test_an_unknown_thread_has_no_summary(store: MemoryStore) -> None:
    assert store.summary("never-seen") == (None, 0)


# --- facts -------------------------------------------------------------------


def test_a_fact_is_found_by_a_word_in_it(store: MemoryStore) -> None:
    store.remember("The human prefers PowerShell over cmd")

    assert store.search("powershell") == ["The human prefers PowerShell over cmd"]


def test_facts_are_not_scoped_to_the_thread_that_saved_them(store: MemoryStore) -> None:
    store.remember("The project targets an RTX 4090", thread_id="session-one")

    assert store.search("4090", limit=1) == ["The project targets an RTX 4090"]


def test_a_fact_found_in_a_later_session_survives_the_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    with MemoryStore(path) as first:
        first.remember("The vLLM server runs in WSL2", thread_id="session-one")

    with MemoryStore(path) as second:
        assert second.search("wsl2") == ["The vLLM server runs in WSL2"]


def test_search_returns_nothing_rather_than_everything_when_it_misses(store: MemoryStore) -> None:
    store.remember("The human prefers PowerShell")

    assert store.search("kangaroo") == []


def test_search_respects_the_limit(store: MemoryStore) -> None:
    for index in range(5):
        store.remember(f"fact number {index} about memory")

    assert len(store.search("memory", limit=2)) == 2


def test_an_empty_fact_is_refused(store: MemoryStore) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        store.remember("   ")


@pytest.mark.parametrize(
    "query", ["what about C++ ?", "NOT AND OR", "-dash *star", "", "   ", "((("]
)
def test_punctuation_in_a_query_does_not_reach_fts(store: MemoryStore, query: str) -> None:
    """A model writes the query, so FTS5 syntax must never leak through it."""

    store.remember("something unrelated")

    assert store.search(query) == []


def test_a_query_matches_any_of_its_words(store: MemoryStore) -> None:
    store.remember("The GPU is an RTX 4090 with 24 GB")

    assert store.search("How much VRAM does the GPU have?") != []


def test_match_query_quotes_every_token() -> None:
    assert match_query("C++ and Rust!") == '"C" OR "and" OR "Rust"'
