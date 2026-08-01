"""The two tools that make memory the model's decision.

Saving is an explicit act, never a side effect of the model saying something.
That is why `remember_fact` is a tool the model has to call rather than a
listener that harvests statements out of the conversation.
"""

from __future__ import annotations

from app.memory import MemoryStore
from app.tools.base import Tool, ToolError

MAX_FACT_CHARS = 500


def _remember(store: MemoryStore, thread_id: str | None, text: str) -> str:
    text = text.strip()
    if not text:
        raise ToolError("a fact cannot be empty")
    if len(text) > MAX_FACT_CHARS:
        raise ToolError(f"a fact must be shorter than {MAX_FACT_CHARS} characters")
    store.remember(text, thread_id=thread_id)
    return f"saved: {text}"


def _search(store: MemoryStore, query: str, limit: int) -> str:
    found = store.search(query, limit=limit)
    if not found:
        return f"no memory matches {query!r}"
    return "\n".join(f"- {fact}" for fact in found)


def memory_tools(store: MemoryStore, thread_id: str | None = None, limit: int = 5) -> list[Tool]:
    """Build `remember_fact` and `search_memory` over one store.

    `thread_id` is provenance only. A fact saved in one conversation is
    searchable from every other one, which is the whole point of saving it.
    """

    return [
        Tool(
            name="remember_fact",
            description=(
                "Save one durable fact about the user or the project for future conversations. "
                "Use it only when the user states something worth remembering later."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The fact, stated in one self-contained sentence.",
                    }
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            run=lambda text: _remember(store, thread_id, text),
        ),
        Tool(
            name="search_memory",
            description="Search previously saved facts by keyword.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words to look for."}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            run=lambda query: _search(store, query, limit),
        ),
    ]
