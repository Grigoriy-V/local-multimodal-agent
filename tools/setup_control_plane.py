"""Run the deployed control-plane migrations from a trusted local shell."""

import asyncio
import sys

from app.agent.runtime import CHECKPOINT_TYPES
from app.checkpoints import setup_postgres_checkpoints
from app.config import AgentSettings
from app.memory import ConversationStore
from app.memory.open import open_store
from app.telemetry.postgres import PostgresTelemetry
from ui.telegram.inbox import PostgresUpdateInbox


async def setup_control_plane(settings: AgentSettings | None = None) -> None:
    """Create or migrate conversations, checkpoints, the inbox and telemetry.

    Every step is additive against a populated database: the telemetry tables
    did not exist before, and the inbox gains a nullable `run_id` column whose
    existing rows stay valid as updates that were never measured.
    """

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
        PostgresTelemetry(
            settings.database_url,
            settings.database_schema,
            migrate_schema=True,
        ).close()
    finally:
        store.close()

def main() -> None:
    """Run psycopg on an event loop it supports on every deployment host."""

    settings = AgentSettings()
    if "--alternate" in sys.argv[1:]:
        # The comparison database gets the same schema through the same
        # migration. A second setup path would be a second thing to keep true.
        if not settings.alt_database_url:
            raise ValueError("AGENT_ALT_DATABASE_URL is not configured")
        settings = settings.model_copy(
            update={"database_url": settings.alt_database_url}
        )
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(setup_control_plane(settings), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
