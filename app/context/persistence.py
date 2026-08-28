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
) -> Context:
    """Perform the complete durable read needed to prepare one model turn.

    This boundary is intentionally shared by production and the deployed
    latency acceptance. If the implementation needs several SQL round-trips,
    their combined cost remains the cost of this one logical read.
    """

    summary, through = store.summary(thread_id)
    history = store.messages(thread_id, after=through - 1)
    facts = store.search(query, user_id, limit=retrieved_facts) if query else []
    return Context(
        prelude=build_prelude(summary, facts, system_prompt),
        history=history,
    )
