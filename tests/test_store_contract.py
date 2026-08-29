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

    return PostgresStore(
        POSTGRES_DSN,
        schema=f"contract_{uuid.uuid4().hex[:12]}",
        migrate_schema=True,
    )


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


# --- one store serves a whole turn, in the order a turn actually does it ------


def test_reading_first_does_not_break_the_context_read(store: ConversationStore) -> None:
    """The sequence a real turn performs, which no single-operation test covers.

    A turn lists the user's threads before it assembles context. On PostgreSQL
    that first read leaves the connection inside a transaction, and the
    single-round-trip context query — which turns autocommit on for one
    statement — was then refused outright. Every deployed message failed with
    `can't change 'autocommit' now`, while the latency probe passed, because the
    probe read context first on a fresh connection.
    """

    store.append("t1", [user("hello")], ALICE)
    store.remember("Alice uses PowerShell", ALICE)

    listed = store.threads(ALICE)
    context = store.turn_context("t1", ALICE, "PowerShell", 5)

    assert [thread.id for thread in listed] == ["t1"]
    assert [part.text for message in context.messages for part in message.content] == [
        "hello"
    ]
    assert context.facts == ["Alice uses PowerShell"]


def test_a_turn_can_read_then_write_then_read_again(store: ConversationStore) -> None:
    """Whatever a read leaves behind must not block the write that follows."""

    store.append("t1", [user("first")], ALICE)
    store.threads(ALICE)
    store.append("t1", [user("second")], ALICE)

    assert store.message_count("t1") == 2
    assert store.turn_context("t1", ALICE, "", 5).summarized_through == 0


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


# --- the chosen conversation -------------------------------------------------


def test_nobody_is_in_a_conversation_until_they_choose(store: ConversationStore) -> None:
    store.append("t1", [user("hello")], ALICE)

    assert store.active_thread(ALICE) is None


def test_the_choice_is_remembered(store: ConversationStore) -> None:
    store.append("t1", [user("hello")], ALICE)

    store.set_active_thread(ALICE, "t1")

    assert store.active_thread(ALICE) == "t1"


def test_writing_to_another_conversation_does_not_move_anyone(
    store: ConversationStore,
) -> None:
    """The whole point of storing the choice: recency is not selection.

    An older conversation someone deliberately returned to must stay theirs even
    while a background write touches a newer one.
    """

    store.append("old", [user("earlier")], ALICE)
    store.append("new", [user("later")], ALICE)
    store.set_active_thread(ALICE, "old")

    store.append("new", [user("later still")], ALICE)

    assert [thread.id for thread in store.threads(ALICE)] == ["new", "old"]
    assert store.active_thread(ALICE) == "old"


def test_one_user_cannot_choose_another_user_s_conversation(
    store: ConversationStore,
) -> None:
    store.append("hers", [user("alice writes")], ALICE)
    store.append("his", [user("bob writes")], BOB)
    store.set_active_thread(BOB, "his")

    with pytest.raises(KeyError):
        store.set_active_thread(BOB, "hers")

    assert store.active_thread(BOB) == "his"


def test_choosing_a_conversation_that_does_not_exist_is_refused(
    store: ConversationStore,
) -> None:
    """Indistinguishable from choosing somebody else's, deliberately."""

    with pytest.raises(KeyError):
        store.set_active_thread(ALICE, "never-seen")

    assert store.active_thread(ALICE) is None


def test_deleting_the_chosen_conversation_leaves_no_choice(
    store: ConversationStore,
) -> None:
    """Rather than an identifier that no longer resolves."""

    store.append("t1", [user("hello")], ALICE)
    store.set_active_thread(ALICE, "t1")

    assert store.delete_thread("t1") is True
    assert store.active_thread(ALICE) is None


def test_the_choice_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "chosen.sqlite3"
    with SqliteStore(path) as first:
        first.append("hers", [user("alice writes")], ALICE)
        first.set_active_thread(ALICE, "hers")

    with SqliteStore(path) as second:
        assert second.active_thread(ALICE) == "hers"


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
