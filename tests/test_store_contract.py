"""One suite every `ConversationStore` implementation must pass.

The deployed profile adds a second implementation on a networked database. A
second implementation that is not exercised by the same tests as the first one
drifts silently, so this file is parameterised over implementations rather than
written against SQLite: adding an entry to `STORE_FACTORIES` is what makes the
new implementation answerable to the contract.

Scope is the subject of most of it. Facts are deliberately shared across a
user's own conversations, and the tests below fix exactly where that sharing
stops.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app.memory import ConversationStore, SqliteStore
from app.models import ContentPart, Message

ALICE = "user-alice"
BOB = "user-bob"

# The PostgreSQL implementation answers the same questions over a real database
# or not at all. There is no fake: a store that passes against a stand-in has
# demonstrated nothing about the thing it will actually run on. So the entry
# below appears only when a DSN is configured, and the offline suite stays
# offline — `AGENT_TEST_DATABASE_URL` is deliberately its own variable, so
# running the tests can never reach the deployed database by accident.
POSTGRES_DSN = os.environ.get("AGENT_TEST_DATABASE_URL", "")


def postgres_store(_tmp_path: Path) -> ConversationStore:
    """A store in a schema of its own, so tests cannot see each other's rows."""

    from app.memory.postgres import PostgresStore

    return PostgresStore(POSTGRES_DSN, schema=f"contract_{uuid.uuid4().hex[:12]}")


STORE_FACTORIES: dict[str, Callable[[Path], ConversationStore]] = {
    "sqlite": lambda tmp_path: SqliteStore(tmp_path / "contract.sqlite3"),
}
if POSTGRES_DSN:
    STORE_FACTORIES["postgres"] = postgres_store


@pytest.fixture(params=sorted(STORE_FACTORIES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ConversationStore]:
    opened = STORE_FACTORIES[request.param](tmp_path)
    try:
        yield opened
    finally:
        drop = getattr(opened, "drop_schema", None)
        if drop is not None:
            drop()
        opened.close()


def user(value: str) -> Message:
    return Message(role="user", content=[ContentPart(kind="text", text=value)])


# --- ownership ---------------------------------------------------------------


def test_appending_creates_the_thread_under_its_owner(store: ConversationStore) -> None:
    store.append("t1", [user("hello")], ALICE)

    assert store.thread_owner("t1") == ALICE


def test_an_unknown_thread_has_no_owner(store: ConversationStore) -> None:
    assert store.thread_owner("never-seen") is None


def test_ownership_is_decided_once(store: ConversationStore) -> None:
    """A second writer does not take a conversation over by writing to it."""

    store.append("t1", [user("mine")], ALICE)
    store.ensure_thread("t1", BOB)

    assert store.thread_owner("t1") == ALICE


# --- conversation scope ------------------------------------------------------


def test_a_user_lists_only_their_own_threads(store: ConversationStore) -> None:
    store.append("hers", [user("alice writes")], ALICE)
    store.append("his", [user("bob writes")], BOB)

    assert [thread.id for thread in store.threads(ALICE)] == ["hers"]
    assert [thread.id for thread in store.threads(BOB)] == ["his"]


def test_a_new_user_sees_nothing(store: ConversationStore) -> None:
    store.append("hers", [user("alice writes")], ALICE)

    assert store.threads("user-carol") == []
    assert store.search("alice", "user-carol") == []


# --- fact scope --------------------------------------------------------------


def test_facts_are_shared_across_one_user_s_conversations(
    store: ConversationStore,
) -> None:
    """The reason facts exist: a later conversation finds what an earlier one saved."""

    store.remember("The GPU is an RTX 4090", ALICE, thread_id="session-one")

    assert store.search("4090", ALICE) == ["The GPU is an RTX 4090"]


def test_one_user_s_facts_never_reach_another(store: ConversationStore) -> None:
    store.remember("Alice flies to Lisbon on Friday", ALICE)
    store.remember("Bob is allergic to peanuts", BOB)

    assert store.search("Lisbon", BOB) == []
    assert store.search("peanuts", ALICE) == []
    assert store.facts(ALICE) == ["Alice flies to Lisbon on Friday"]
    assert store.facts(BOB) == ["Bob is allergic to peanuts"]


def test_a_shared_word_still_separates_the_users(store: ConversationStore) -> None:
    """Matching text is not a reason to cross the boundary."""

    store.remember("The deadline is Tuesday", ALICE)
    store.remember("The deadline is Thursday", BOB)

    assert store.search("deadline", ALICE) == ["The deadline is Tuesday"]
    assert store.search("deadline", BOB) == ["The deadline is Thursday"]


def test_deleting_a_conversation_keeps_the_owner_s_facts(
    store: ConversationStore,
) -> None:
    store.append("doomed", [user("remove this")], ALICE)
    store.remember("The user prefers concise answers", ALICE, thread_id="doomed")

    assert store.delete_thread("doomed") is True

    assert store.search("concise", ALICE) == ["The user prefers concise answers"]
    assert store.search("concise", BOB) == []


# --- summaries ---------------------------------------------------------------


def test_a_summary_belongs_to_an_existing_conversation(store: ConversationStore) -> None:
    store.append("t1", [user("hello")], ALICE)

    store.set_summary("t1", "they said hello", 1)

    assert store.summary("t1") == ("they said hello", 1)


def test_summarizing_an_unknown_thread_is_refused(store: ConversationStore) -> None:
    """A summary with no conversation would have no owner and cover nothing."""

    with pytest.raises(KeyError):
        store.set_summary("never-seen", "invented", 3)


def test_an_unknown_thread_has_no_summary(store: ConversationStore) -> None:
    assert store.summary("never-seen") == (None, 0)


# --- durability --------------------------------------------------------------


def test_scope_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "reopened.sqlite3"
    with SqliteStore(path) as first:
        first.append("hers", [user("alice writes")], ALICE)
        first.remember("Alice uses PowerShell", ALICE)

    with SqliteStore(path) as second:
        assert [thread.id for thread in second.threads(ALICE)] == ["hers"]
        assert second.threads(BOB) == []
        assert second.search("PowerShell", BOB) == []
        assert second.search("PowerShell", ALICE) == ["Alice uses PowerShell"]
