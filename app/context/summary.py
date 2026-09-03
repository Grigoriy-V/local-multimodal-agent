"""The rolling summary: how older conversation is folded instead of dropped.

Folding is the only way a message leaves the verbatim window. The summary and
the position it covers move together, so a reader can always tell which
messages the summary accounts for.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.context.window import ContextPolicy, system, transcript, turn_boundary
from app.memory import ConversationStore
from app.models import ContentPart, Message, ModelBackend

# Structured rather than prose: a summary is read by a model that has to act
# on it, and what it acts on is the goal, what is already done, the names of
# things, and what is still open. Prose loses the file names first.
INSTRUCTION = (
    "You maintain a running summary of a conversation. Rewrite the summary so it "
    "covers the earlier summary and the new exchange together, at most 200 words, "
    "as four short sections: Goal (what the person wants), Done (what has been done, "
    "naming files, paths, numbers and decisions exactly as written), Open (questions "
    "or work not finished), Preferences (how the person wants things). Leave out a "
    "section that would be empty. Plain text, no preamble."
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
    store: ConversationStore,
    thread_id: str,
    policy: ContextPolicy,
    used_tokens: int | None = None,
    force: bool = False,
    reason: str | None = None,
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

    Every fold leaves a record — what it covered and why — so a later reader
    can tell which messages the summary stands for and recover them exactly.
    `reason` names the trigger when the caller knows it better than this
    function does (`asked`, for `/compact`).
    """

    previous, through = store.summary(thread_id)
    pending = store.messages(thread_id, after=through - 1)
    oversized = (
        policy.max_input_tokens is not None
        and used_tokens is not None
        and used_tokens > policy.max_input_tokens
    )
    if len(pending) <= policy.summarize_after and not oversized and not force:
        return None

    cut = turn_boundary(pending, len(pending) - policy.keep_recent)
    if cut <= 0 or cut >= len(pending):
        return None

    updated = await summarize(backend, previous, pending[:cut])
    if not updated:
        return None
    store.set_summary(thread_id, updated, through + cut)
    store.record_compaction(
        thread_id,
        through=through + cut,
        folded=cut,
        trigger=reason or ("forced" if force else "size" if oversized else "count"),
        summary_chars=len(updated),
    )
    return updated
