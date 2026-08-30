"""Application-level persistence operations used while preparing one turn."""

from __future__ import annotations

from app.context.window import Context, build_prelude
from app.memory import ConversationStore


def load_turn_context(
    store: ConversationStore,
    thread_id: str,
    user_id: str,
    query: str,
    retrieved_facts: int,
    system_prompt: str,
    instructions: str = "",
) -> Context:
    """Perform the complete durable read needed to prepare one model turn.

    This boundary is intentionally shared by production and the deployed
    latency acceptance. If the implementation needs several SQL round-trips,
    their combined cost remains the cost of this one logical read.
    """

    records = store.turn_context(thread_id, user_id, query, retrieved_facts)
    return Context(
        prelude=build_prelude(
            records.summary, records.facts, system_prompt, instructions
        ),
        history=records.messages,
    )
