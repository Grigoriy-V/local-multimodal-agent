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
from dataclasses import dataclass, field

from app.models import ContentPart, Message

DEFAULT_SYSTEM_PROMPT = (
    "You are a local assistant with tools. Use list_files and read_file to look at the "
    "workspace instead of guessing, and write_file to change it. Call remember_fact when "
    "the user tells you something worth keeping for later conversations, and search_memory "
    "when an earlier fact would help. The user approves every write before it happens; if a "
    "call comes back declined, say so and do not try it again. Answer briefly."
)


@dataclass(frozen=True)
class ContextPolicy:
    """How much conversation stays verbatim, and when the rest is folded away."""

    keep_recent: int = 8
    summarize_after: int = 16
    retrieved_facts: int = 5


@dataclass(frozen=True)
class Context:
    """One turn's assembled context, kept apart from the turn itself.

    `prelude` is synthetic and must never be written back to the store;
    `history` is already stored. Only the new messages of the turn are new.
    """

    prelude: list[Message] = field(default_factory=list)
    history: list[Message] = field(default_factory=list)

    def prompt(self, new: Sequence[Message]) -> list[Message]:
        return [*self.prelude, *self.history, *new]


def system(text: str) -> Message:
    return Message(role="system", content=[ContentPart(kind="text", text=text)])


def describe(part: ContentPart) -> str:
    if part.kind == "text":
        return part.text or ""
    return f"[{part.kind} {part.media_type}]"


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
    """

    for index in range(start, len(messages)):
        if messages[index].role == "user":
            return index
    return len(messages)


def build_prelude(
    summary: str | None,
    facts: Sequence[str],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> list[Message]:
    prelude = [system(system_prompt)]
    if summary:
        prelude.append(system(f"Summary of the earlier conversation:\n{summary}"))
    if facts:
        listed = "\n".join(f"- {fact}" for fact in facts)
        prelude.append(system(f"Facts you saved in earlier conversations:\n{listed}"))
    return prelude
