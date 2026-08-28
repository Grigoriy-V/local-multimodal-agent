"""Run the deployed control-plane migrations from a trusted local shell."""

import asyncio
import sys

from app.agent.runtime import CHECKPOINT_TYPES
from app.checkpoints import setup_postgres_checkpoints
from app.config import AgentSettings
from app.memory import ConversationStore
from app.memory.open import open_store
from ui.telegram.inbox import PostgresUpdateInbox


async def setup_control_plane(settings: AgentSettings | None = None) -> None:
    """Create or migrate conversations, checkpoints and the Telegram inbox."""

    settings = settings or AgentSettings()
    if not settings.database_url:
        raise ValueError("AGENT_DATABASE_URL is required for control-plane setup")

    store: ConversationStore = open_store(settings, migrate_schema=True)
    try:
        await setup_postgres_checkpoints(
            settings.database_url,
            allowed_types=CHECKPOINT_TYPES,
        )
        await PostgresUpdateInbox(
            settings.database_url,
            settings.database_schema,
        ).setup()
    finally:
        store.close()

def main() -> None:
    """Run psycopg on an event loop it supports on every deployment host."""

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(setup_control_plane(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
