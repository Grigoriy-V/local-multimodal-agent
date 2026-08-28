"""Opt-in live acceptance for the deployed PostgreSQL control-plane state."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

from app.agent.runtime import CHECKPOINT_TYPES
from app.checkpoints import CheckpointHandle
from ui.telegram.inbox import PostgresUpdateInbox

POSTGRES_DSN = os.environ.get("AGENT_TEST_DATABASE_URL", "")
POSTGRES_SCHEMA = os.environ.get("AGENT_DATABASE_SCHEMA", "assistant")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="AGENT_TEST_DATABASE_URL is not set; live services stay opt-in",
)


async def _accept_control_plane() -> None:
    import psycopg

    inbox = PostgresUpdateInbox(POSTGRES_DSN, POSTGRES_SCHEMA)
    update_id = uuid.uuid4().int % (2**63 - 1)
    checkpoint = CheckpointHandle(
        Path("unused-live-checkpoint.sqlite3"),
        database_url=POSTGRES_DSN,
        allowed_types=CHECKPOINT_TYPES,
    )
    try:
        queued = await inbox.enqueue(update_id, {"update_id": update_id, "message": {}})
        assert queued.should_spawn is True

        first = await inbox.claim(update_id, lease_seconds=30)
        assert first is not None
        assert first.payload["update_id"] == update_id
        await inbox.retry(first, "live retry")

        second = await inbox.claim(update_id, lease_seconds=30)
        assert second is not None
        assert second.lease_token != first.lease_token
        await inbox.complete(second)

        duplicate = await inbox.enqueue(update_id, {"update_id": update_id})
        assert duplicate.should_spawn is False

        saver = await checkpoint.open()
        missing = await saver.aget_tuple(
            {"configurable": {"thread_id": f"live:{uuid.uuid4()}", "checkpoint_ns": ""}}
        )
        assert missing is None
    finally:
        await checkpoint.close()
        connection = await psycopg.AsyncConnection.connect(POSTGRES_DSN, autocommit=True)
        async with connection:
            await connection.execute(
                f"DELETE FROM {inbox.table} WHERE update_id = %s",
                (update_id,),
            )


def test_live_inbox_and_checkpointer() -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_accept_control_plane(), loop_factory=loop_factory)
