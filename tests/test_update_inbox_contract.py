"""What the durable queue promises, asserted against PostgreSQL itself.

There is no offline half of this file, and that is deliberate. The rules below
live in one `UPDATE` statement and an advisory lock; a stand-in that passes them
has demonstrated something about the stand-in. `tests/fakes.py` holds the same
rules for tests whose subject is the worker rather than the queue, and this file
is what keeps the two honest — so `AGENT_TEST_DATABASE_URL` is what makes the
queue answerable, exactly as it is for the conversation store.

The live defect these are about: a screenshot and the question that followed it
were sent seconds apart, ran in two containers and were answered out of order.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest

from ui.telegram.inbox import PostgresUpdateInbox

POSTGRES_DSN = os.environ.get("AGENT_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="AGENT_TEST_DATABASE_URL is not set; the queue is only testable live",
)

ALICE = "person-alice"
BOB = "person-bob"


@pytest.fixture
async def inbox() -> AsyncIterator[PostgresUpdateInbox]:
    """A queue in a schema of its own, dropped whatever the test did to it."""

    import psycopg

    schema = f"inbox_{uuid.uuid4().hex[:12]}"
    queue = PostgresUpdateInbox(POSTGRES_DSN, schema)
    await queue.setup()
    try:
        yield queue
    finally:
        connection = await psycopg.AsyncConnection.connect(POSTGRES_DSN, autocommit=True)
        async with connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def payload(update_id: int) -> dict[str, object]:
    return {"update_id": update_id, "message": {"text": "hello"}}


async def queue(
    inbox: PostgresUpdateInbox, *update_ids: int, key: str = ALICE
) -> None:
    for update_id in update_ids:
        await inbox.enqueue(
            update_id, payload(update_id), run_id=f"run-{update_id}", conversation_key=key
        )


async def test_one_conversation_runs_one_update_at_a_time(
    inbox: PostgresUpdateInbox,
) -> None:
    await queue(inbox, 5, 7)

    first = await inbox.claim(5)
    assert first is not None and first.update_id == 5
    assert await inbox.claim(7) is None
    assert await inbox.claim_next(ALICE) is None

    await inbox.complete(first)
    second = await inbox.claim(7)
    assert second is not None and second.update_id == 7


async def test_the_oldest_update_is_answered_first(inbox: PostgresUpdateInbox) -> None:
    """The worker is woken by whichever spawn won, not by the older message."""

    await queue(inbox, 5, 7)

    claimed = await inbox.claim(7)

    assert claimed is not None
    assert claimed.update_id == 5
    assert claimed.conversation_key == ALICE
    assert claimed.run_id == "run-5"


async def test_a_finished_update_still_names_its_conversation(
    inbox: PostgresUpdateInbox,
) -> None:
    """How a hand-off works: any id of the conversation finds the rest of it."""

    await queue(inbox, 5, 7)
    done = await inbox.claim(5)
    assert done is not None
    await inbox.complete(done)

    following = await inbox.claim(5)

    assert following is not None and following.update_id == 7


async def test_two_people_do_not_wait_for_each_other(
    inbox: PostgresUpdateInbox,
) -> None:
    await queue(inbox, 5, key=ALICE)
    await queue(inbox, 6, key=BOB)

    mine = await inbox.claim(5)
    theirs = await inbox.claim(6)

    assert mine is not None and theirs is not None


async def test_a_dead_worker_does_not_hold_a_conversation_forever(
    inbox: PostgresUpdateInbox,
) -> None:
    """Nothing releases the lease of a container that disappeared."""

    await queue(inbox, 5)
    lost = await inbox.claim(5, lease_seconds=1)
    assert lost is not None

    await asyncio.sleep(1.2)
    recovered = await inbox.claim(5, lease_seconds=30)

    assert recovered is not None
    assert recovered.update_id == 5
    assert recovered.lease_token != lost.lease_token


async def test_a_failed_turn_returns_to_the_queue(inbox: PostgresUpdateInbox) -> None:
    await queue(inbox, 5)
    failed = await inbox.claim(5)
    assert failed is not None

    await inbox.retry(failed, "RuntimeError: failed turn")
    again = await inbox.claim(5)

    assert again is not None
    assert again.lease_token != failed.lease_token


async def test_an_update_queued_before_conversations_existed_is_answered_alone(
    inbox: PostgresUpdateInbox,
) -> None:
    """The column was added to a table that already held rows."""

    await inbox.enqueue(5, payload(5))
    await inbox.enqueue(7, payload(7))

    first = await inbox.claim(5)
    second = await inbox.claim(7)

    assert first is not None and first.update_id == 5
    assert second is not None and second.update_id == 7
    assert first.conversation_key == ""


async def test_a_redelivered_update_keeps_one_identity(
    inbox: PostgresUpdateInbox,
) -> None:
    first = await inbox.enqueue(5, payload(5), run_id="run-5", conversation_key=ALICE)
    second = await inbox.enqueue(5, payload(5), run_id="run-again", conversation_key=ALICE)

    assert first.run_id == "run-5"
    # The stored identity wins: one update seen twice is one turn, not two.
    assert second.run_id == "run-5"
    # And it is still owed an answer, so asking for a worker again is correct.
    assert second.should_spawn is True


async def test_a_claimed_update_is_not_spawned_a_second_time(
    inbox: PostgresUpdateInbox,
) -> None:
    await queue(inbox, 5)
    claimed = await inbox.claim(5, lease_seconds=300)
    assert claimed is not None

    again = await inbox.enqueue(5, payload(5), conversation_key=ALICE)

    assert again.should_spawn is False


async def test_setting_the_queue_up_twice_changes_nothing(
    inbox: PostgresUpdateInbox,
) -> None:
    """Every deployment runs it, so it has to be safe on a populated table."""

    await queue(inbox, 5)
    await inbox.setup()

    claimed = await inbox.claim(5)

    assert claimed is not None and claimed.update_id == 5
