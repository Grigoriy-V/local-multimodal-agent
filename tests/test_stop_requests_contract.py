"""Where a stop is recorded when the turn is in another container.

Deployed, `/stop` is answered by one container and the turn it ends is running
in a different one, so the only thing both can see is the control plane's
database. Like the queue's own contract suite, there is no offline half of
this: an in-memory stand-in that passes says nothing about the SQL.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest

from app.agent.stop import PostgresStopRequests

POSTGRES_DSN = os.environ.get("AGENT_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="AGENT_TEST_DATABASE_URL is not set; this is only testable live",
)

ALICE = "person-alice"
BOB = "person-bob"


@pytest.fixture
async def stops() -> AsyncIterator[PostgresStopRequests]:
    import psycopg

    schema = f"stops_{uuid.uuid4().hex[:12]}"
    requests = PostgresStopRequests(POSTGRES_DSN, schema)
    await requests.setup()
    try:
        yield requests
    finally:
        connection = await psycopg.AsyncConnection.connect(POSTGRES_DSN, autocommit=True)
        async with connection:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


async def test_a_stop_applies_to_everything_that_began_before_it(
    stops: PostgresStopRequests,
) -> None:
    await stops.request(ALICE, 5)

    assert await stops.requested(ALICE, 4) is True
    assert await stops.requested(ALICE, 5) is False
    assert await stops.requested(ALICE, 6) is False


async def test_a_conversation_nobody_stopped_is_not_stopped(
    stops: PostgresStopRequests,
) -> None:
    assert await stops.requested(ALICE, 0) is False


async def test_one_person_s_stop_is_not_another_person_s(
    stops: PostgresStopRequests,
) -> None:
    await stops.request(ALICE, 5)

    assert await stops.requested(BOB, 4) is False


async def test_a_second_stop_never_moves_the_mark_backwards(
    stops: PostgresStopRequests,
) -> None:
    """Two stops in quick succession are one intention, not an undo."""

    await stops.request(ALICE, 5)
    await stops.request(ALICE, 3)

    assert await stops.requested(ALICE, 4) is True


async def test_setting_it_up_twice_changes_nothing(
    stops: PostgresStopRequests,
) -> None:
    """Every deployment runs the migration, so it is safe on a populated table."""

    await stops.request(ALICE, 5)
    await stops.setup()

    assert await stops.requested(ALICE, 4) is True
