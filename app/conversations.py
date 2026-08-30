"""Lifecycle operations spanning conversation and in-flight graph storage."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.memory import ConversationStore


async def _discard_checkpoint(path: str | Path, thread_id: str) -> None:
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return
    connection = await aiosqlite.connect(str(checkpoint_path))
    try:
        saver = AsyncSqliteSaver(connection)
        await saver.setup()
        await saver.adelete_thread(thread_id)
    finally:
        await connection.close()


async def delete_conversation(
    store: ConversationStore,
    thread_id: str,
    checkpoints: str | Path,
) -> bool:
    """Delete canonical chat data and any turn of it still in flight."""

    await _discard_checkpoint(checkpoints, thread_id)
    return store.delete_thread(thread_id)
