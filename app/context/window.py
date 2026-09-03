"""What the model is actually sent, assembled from four layers.

1. Recent conversation messages, verbatim.
2. A rolling summary of everything older.
3. Long-term facts from SQLite.
4. Retrieval: only the facts that match the current turn.

Layers 2, 3 and 4 arrive as system messages the model can read. Nothing is
dropped without being summarized first — a message leaves the verbatim window
only once the summary covers it, which is why this module never truncates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.instructions import instruction_message
from app.models import ContentPart, Message

# How many media items of each kind one request may carry. This mirrors the
# served model's own per-prompt limits — `MM_LIMITS` in `deploy/modal/model_app.py`
# — and is duplicated rather than imported because the application never depends
# on a deployment. A model served with different limits needs this changed too;
# exceeding them is an HTTP 400, not a degraded answer.
MEDIA_BUDGET = {"image": 4, "audio": 1}

# The core names no tool, no file format and no workflow, and it is meant to
# stay this short. Anything true only because a particular capability is wired
# up is generated from that wiring in `app/capabilities.py`, and anything true
# only for one person is their own standing instructions. What is left is what
# has to hold whatever this assistant is given — which is also why this text is
# the most stable layer of the prompt and goes first, ahead of everything that
# changes per grant, per person and per turn.
DEFAULT_SYSTEM_PROMPT = (
    "You are a general-purpose assistant with tools. What you can actually do is "
    "listed below, generated from what is wired up rather than written from memory: "
    "trust that list about yourself. After it may come standing instructions from "
    "the person you are talking to, saying how they want you to work; follow them "
    "wherever they do not contradict what is above them. "
    "Text you write together with a tool call reaches the person at once. After "
    "the tool's result, add only what is new; if nothing is new, say nothing. "
    "Answer briefly."
)


@dataclass(frozen=True)
class ContextPolicy:
    """How much conversation stays verbatim, and when the rest is folded away.

    `max_input_tokens` is the size a request may reach before the conversation
    is folded, and is resolved at runtime from the model's own limit rather than
    configured here. `None` means the size is unknown and only the message
    counts bound the request.
    """

    keep_recent: int = 8
    summarize_after: int = 16
    retrieved_facts: int = 5
    max_input_tokens: int | None = None


@dataclass(frozen=True)
class Context:
    """One turn's assembled context, kept apart from the turn itself.

    `prelude` is synthetic and must never be written back to the store;
    `history` is already stored. Only the new messages of the turn are new.
    """

    prelude: list[Message] = field(default_factory=list)
    history: list[Message] = field(default_factory=list)

    def prompt(self, new: Sequence[Message]) -> list[Message]:
        # The new turn is never trimmed: it is what the person just asked. What
        # it spends of the budget is what history may no longer replay.
        used = count_media(new)
        budget = {kind: limit - used.get(kind, 0) for kind, limit in MEDIA_BUDGET.items()}
        return [*self.prelude, *within_media_budget(self.history, budget), *new]


def system(text: str) -> Message:
    return Message(role="system", content=[ContentPart(kind="text", text=text)])


def describe(part: ContentPart) -> str:
    if part.kind == "text":
        return part.text or ""
    return f"[{part.kind} {part.media_type}]"


def count_media(messages: Sequence[Message]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        for part in message.content:
            if part.kind != "text" and not part.outbound:
                counts[part.kind] = counts.get(part.kind, 0) + 1
    return counts


def within_media_budget(
    history: Sequence[Message], budget: dict[str, int]
) -> list[Message]:
    """Replay recent media, but only as much of it as one prompt may carry.

    A server caps how many items of each kind a single prompt may contain, and
    the whole conversation is re-sent every turn. Without a budget the second
    voice message in a thread is refused outright, for a reason that has nothing
    to do with what the person asked — that happened. Older media past the cap
    becomes the same placeholder summaries use, so the model still knows a voice
    message or a picture was there.

    The newest media survives: it is the one a follow-up question is about.
    """

    kept: list[Message] = []
    remaining = dict(budget)
    for message in reversed(history):
        if all(part.kind == "text" for part in message.content):
            kept.append(message)
            continue
        content: list[ContentPart] = []
        for part in message.content:
            if part.kind == "text":
                content.append(part)
            elif part.outbound:
                content.append(ContentPart(kind="text", text=describe(part)))
            elif remaining.get(part.kind, 0) > 0:
                remaining[part.kind] -= 1
                content.append(part)
            else:
                content.append(ContentPart(kind="text", text=describe(part)))
        kept.append(replace(message, content=content))
    kept.reverse()
    return kept


def transcript(messages: Sequence[Message]) -> str:
    """Render messages as plain text for summarization.

    Media becomes a placeholder: a summary of a picture is the model's job, not
    a base64 blob's.
    """

    lines = []
    for message in messages:
        body = " ".join(describe(part) for part in message.content).strip()
        for call in message.tool_calls:
            body = f"{body} [calls {call.name}({call.arguments})]".strip()
        lines.append(f"{message.role}: {body}")
    return "\n".join(lines)


def first_user_turn(messages: Sequence[Message], start: int) -> int:
    """Move a cut forward to the next user turn.

    Cutting between an assistant's tool call and the tool's reply would leave an
    orphan result the provider rejects, so a cut only lands where a turn begins.

    A negative `start` means the caller wanted to keep more messages than exist;
    it is clamped rather than left to index from the end of the list.
    """

    for index in range(max(0, start), len(messages)):
        if messages[index].role == "user":
            return index
    return len(messages)


def build_prelude(
    summary: str | None,
    facts: Sequence[str],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    instructions: str = "",
) -> list[Message]:
    """The synthetic layers, ordered by how rarely each one changes.

    The system message is the same for weeks, a person's standing instructions
    change when they decide to, the summary changes when a conversation is
    folded and the retrieved facts change every single turn. Ordering them that
    way is what lets a served prefix cache survive: a layer that changes
    invalidates everything after it, so the volatile ones go last.
    """

    prelude = [system(system_prompt)]
    overlay = instruction_message(instructions)
    if overlay is not None:
        prelude.append(overlay)
    if summary:
        prelude.append(system(f"Summary of the earlier conversation:\n{summary}"))
    if facts:
        listed = "\n".join(f"- {fact}" for fact in facts)
        prelude.append(system(f"Facts you saved in earlier conversations:\n{listed}"))
    return prelude
