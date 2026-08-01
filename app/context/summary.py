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
    used_tokens: int | None = None,
) -> str | None:
    """Summarize everything past the verbatim window. Returns the new summary.

    Two things can trigger a fold: too many messages, or a request that grew
    past `max_input_tokens`. The second is what makes the bound a token bound —
    eight short turns and eight turns carrying images are the same number of
    messages and nothing like the same request.

    `used_tokens` is what the model reported for the request just made, not an
    estimate of it. That makes the trigger exact and one turn late, which is why
    the budget is a fraction of the model's limit: the turn that overshoots the
    budget still fits, and the fold happens before the next one.
    """

    previous, through = store.summary(thread_id)
    pending = store.messages(thread_id, after=through - 1)
    oversized = (
        policy.max_input_tokens is not None
        and used_tokens is not None
        and used_tokens > policy.max_input_tokens
    )
    if len(pending) <= policy.summarize_after and not oversized:
        return None

    cut = first_user_turn(pending, len(pending) - policy.keep_recent)
    if cut <= 0 or cut >= len(pending):
        return None

    updated = await summarize(backend, previous, pending[:cut])
    if not updated:
        return None
    store.set_summary(thread_id, updated, through + cut)
    return updated
