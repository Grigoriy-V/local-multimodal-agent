from unittest.mock import Mock

from app.context import load_turn_context
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import (
    LOCAL_USER_ID,
    ConversationStore,
    SqliteStore,
    TurnContextRecords,
)
from app.models import ContentPart, Message


def text(role: str, value: str) -> Message:
    return Message(role=role, content=[ContentPart(kind="text", text=value)])


def test_full_turn_read_assembles_summary_history_and_retrieved_facts() -> None:
    with SqliteStore() as store:
        store.append(
            "thread",
            [text("user", "old"), text("assistant", "answer")],
            LOCAL_USER_ID,
        )
        store.set_summary("thread", "earlier summary", 0)
        store.remember("the latency target is strict", LOCAL_USER_ID, "thread")

        context = load_turn_context(
            store,
            "thread",
            LOCAL_USER_ID,
            "latency",
            5,
            DEFAULT_SYSTEM_PROMPT,
        )

    assert [item.content[0].text for item in context.history] == ["old", "answer"]
    assert "earlier summary" in (context.prelude[1].content[0].text or "")
    assert "latency target" in (context.prelude[2].content[0].text or "")


def test_full_turn_read_uses_the_store_s_single_context_boundary() -> None:
    store = Mock(spec=ConversationStore)
    store.turn_context.return_value = TurnContextRecords(
        summary="earlier summary",
        summarized_through=0,
        messages=[text("user", "old")],
        facts=["the latency target is strict"],
    )

    context = load_turn_context(
        store,
        "thread",
        LOCAL_USER_ID,
        "latency",
        5,
        DEFAULT_SYSTEM_PROMPT,
    )

    store.turn_context.assert_called_once_with("thread", LOCAL_USER_ID, "latency", 5)
    assert [item.content[0].text for item in context.history] == ["old"]
