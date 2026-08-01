"""The rolling summary: how older conversation is folded instead of dropped.

Folding is the only way a message leaves the verbatim window. The summary and
the position it covers move together, so a reader can always tell which
messages the summary accounts for.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.context.window import ContextPolicy, first_user_turn, system, transcript
from app.memory import MemoryStore
from app.models import ContentPart, Message, ModelBackend

INSTRUCTION = (
    "You maintain a running summary of a conversation. Rewrite the summary so it "
    "covers the earlier summary and the new exchange together. Keep names, decisions, "
    "numbers and open questions. Write at most 150 words of plain prose, no preamble."
)


async def summarize(
    backend: ModelBackend,
    previous: str | None,
    messages: Sequence[Message],
) -> str:
    body = transcript(messages)
    if previous:
        body = f"Earlier summary:\n{previous}\n\nNew exchange:\n{body}"
    completion = await backend.invoke(
        [system(INSTRUCTION), Message(role="user", content=[ContentPart(kind="text", text=body)])]
    )
    return completion.text.strip()


async def fold_older_messages(
    backend: ModelBackend,
    store: MemoryStore,
    thread_id: str,
    policy: ContextPolicy,
) -> str | None:
    """Summarize everything past the verbatim window. Returns the new summary.

    Does nothing until the unsummarized tail is longer than `summarize_after`,
    so a short conversation never pays for a second model call.
    """

    previous, through = store.summary(thread_id)
    pending = store.messages(thread_id, after=through - 1)
    if len(pending) <= policy.summarize_after:
        return None

    cut = first_user_turn(pending, len(pending) - policy.keep_recent)
    if cut <= 0 or cut >= len(pending):
        return None

    updated = await summarize(backend, previous, pending[:cut])
    if not updated:
        return None
    store.set_summary(thread_id, updated, through + cut)
    return updated
