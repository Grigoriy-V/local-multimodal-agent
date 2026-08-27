"""The four context layers and the fold that keeps them bounded."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from app.context import Context, ContextPolicy, build_prelude, fold_older_messages, transcript
from app.context.window import DEFAULT_SYSTEM_PROMPT, first_user_turn, system
from app.memory import LOCAL_USER_ID, SqliteStore
from app.models import Completion, ContentPart, Message, ModelBackend, ToolCall


class EchoBackend(ModelBackend):
    """Returns a fixed summary and remembers what it was asked to summarize."""

    def __init__(self, summary: str = "they talked about files") -> None:
        self.summary = summary
        self.requests: list[list[Message]] = []

    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        self.requests.append(list(messages))
        return Completion(text=self.summary)

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        yield self.summary


def user(value: str) -> Message:
    return Message(role="user", content=[ContentPart(kind="text", text=value)])


def assistant(value: str) -> Message:
    return Message(role="assistant", content=[ContentPart(kind="text", text=value)])


def exchange(count: int) -> list[Message]:
    messages: list[Message] = []
    for index in range(count):
        messages.append(user(f"question {index}"))
        messages.append(assistant(f"answer {index}"))
    return messages


@pytest.fixture
def store() -> SqliteStore:
    with SqliteStore() as store:
        yield store


# --- assembly ----------------------------------------------------------------


def test_a_prelude_without_summary_or_facts_is_just_the_system_prompt() -> None:
    [message] = build_prelude(None, [])

    assert message.role == "system"
    assert message.content[0].text == DEFAULT_SYSTEM_PROMPT


def test_the_summary_and_the_facts_become_readable_layers() -> None:
    prelude = build_prelude("earlier they discussed cats", ["The human has two cats"])

    bodies = [message.content[0].text for message in prelude]
    assert all(message.role == "system" for message in prelude)
    assert "earlier they discussed cats" in bodies[1]
    assert "- The human has two cats" in bodies[2]


def test_the_prompt_is_prelude_then_history_then_the_new_turn() -> None:
    context = Context(prelude=[system("rules")], history=[user("old"), assistant("older answer")])

    prompt = context.prompt([user("new")])

    assert [m.content[0].text for m in prompt] == ["rules", "old", "older answer", "new"]


def test_the_context_does_not_mutate_when_a_prompt_is_built() -> None:
    context = Context(prelude=[system("rules")], history=[user("old")])

    context.prompt([user("new")])

    assert len(context.history) == 1


# --- rendering ---------------------------------------------------------------


def test_a_transcript_names_media_instead_of_carrying_it() -> None:
    message = Message(
        role="user",
        content=[
            ContentPart(kind="text", text="what is this"),
            ContentPart(kind="image", data=b"\x89PNG", media_type="image/png"),
        ],
    )

    assert transcript([message]) == "user: what is this [image image/png]"


def test_a_transcript_shows_which_tool_was_called() -> None:
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.txt"})

    rendered = transcript([Message(role="assistant", tool_calls=(call,))])

    assert "calls read_file" in rendered


# --- where a cut may land ----------------------------------------------------


def test_a_cut_moves_forward_to_the_start_of_a_turn() -> None:
    messages = [
        user("ask"),
        Message(role="assistant", tool_calls=(ToolCall(id="c1", name="t", arguments={}),)),
        Message(role="tool", content=[ContentPart(kind="text", text="r")], tool_call_id="c1"),
        user("ask again"),
    ]

    assert first_user_turn(messages, 1) == 3


def test_a_cut_with_no_later_turn_lands_at_the_end() -> None:
    assert first_user_turn([user("only")], 1) == 1


def test_a_cut_before_the_first_message_is_clamped_not_taken_from_the_end() -> None:
    """A caller asking to keep more messages than exist passes a negative start.

    Python would read that as an index from the end; here it means the beginning.
    """

    assert first_user_turn([user("only")], -4) == 0
    assert first_user_turn([], -4) == 0


# --- folding -----------------------------------------------------------------


async def test_a_short_thread_is_not_summarized(store: SqliteStore) -> None:
    backend = EchoBackend()
    store.append("t1", exchange(3), LOCAL_USER_ID)

    result = await fold_older_messages(backend, store, "t1", ContextPolicy())

    assert result is None
    assert backend.requests == []
    assert store.summary("t1") == (None, 0)


async def test_a_long_thread_is_folded_and_the_summary_records_its_reach(
    store: SqliteStore,
) -> None:
    store.append("t1", exchange(12), LOCAL_USER_ID)

    await fold_older_messages(EchoBackend(), store, "t1", ContextPolicy())

    summary, through = store.summary("t1")
    assert summary == "they talked about files"
    assert 0 < through < 24


async def test_folding_leaves_the_recent_window_verbatim(store: SqliteStore) -> None:
    policy = ContextPolicy(keep_recent=8, summarize_after=16)
    store.append("t1", exchange(12), LOCAL_USER_ID)

    await fold_older_messages(EchoBackend(), store, "t1", policy)

    _, through = store.summary("t1")
    remaining = store.messages("t1", after=through - 1)
    assert len(remaining) >= policy.keep_recent
    assert remaining[0].role == "user"


async def test_the_summarizer_is_shown_the_older_messages_not_the_recent_ones(
    store: SqliteStore,
) -> None:
    backend = EchoBackend()
    store.append("t1", exchange(12), LOCAL_USER_ID)

    await fold_older_messages(backend, store, "t1", ContextPolicy())

    [request] = backend.requests
    body = request[-1].content[0].text
    assert "question 0" in body
    assert "question 11" not in body


async def test_folding_twice_carries_the_earlier_summary_forward(store: SqliteStore) -> None:
    backend = EchoBackend()
    store.append("t1", exchange(12), LOCAL_USER_ID)
    await fold_older_messages(backend, store, "t1", ContextPolicy())
    store.append("t1", exchange(12), LOCAL_USER_ID)

    await fold_older_messages(backend, store, "t1", ContextPolicy())

    body = backend.requests[1][-1].content[0].text
    assert "Earlier summary:" in body


# --- folding because the request grew, not because it got long ---------------


async def test_a_short_thread_that_filled_the_request_is_folded(store: SqliteStore) -> None:
    """Eight turns of text and eight turns of images are the same message count."""

    policy = ContextPolicy(keep_recent=4, summarize_after=100, max_input_tokens=1000)
    store.append("t1", exchange(6), LOCAL_USER_ID)

    result = await fold_older_messages(EchoBackend(), store, "t1", policy, used_tokens=1200)

    assert result == "they talked about files"
    assert store.summary("t1")[1] > 0


async def test_a_request_within_the_budget_leaves_the_thread_alone(store: SqliteStore) -> None:
    policy = ContextPolicy(keep_recent=4, summarize_after=100, max_input_tokens=1000)
    store.append("t1", exchange(6), LOCAL_USER_ID)

    result = await fold_older_messages(EchoBackend(), store, "t1", policy, used_tokens=400)

    assert result is None
    assert store.summary("t1") == (None, 0)


async def test_an_oversized_thread_shorter_than_the_window_is_left_alone(
    store: SqliteStore,
) -> None:
    """A request can be over budget with nothing older than the verbatim window.

    Folding cannot help there — every message is one the policy says to keep —
    and the fold must decline rather than cut at a negative position.
    """

    policy = ContextPolicy(keep_recent=8, summarize_after=100, max_input_tokens=100)
    store.append("t1", exchange(1), LOCAL_USER_ID)

    result = await fold_older_messages(EchoBackend(), store, "t1", policy, used_tokens=5000)

    assert result is None
    assert store.summary("t1") == (None, 0)


async def test_an_oversized_thread_folded_to_nothing_stops_folding(store: SqliteStore) -> None:
    """Once everything foldable is folded, the next turn must not fold again.

    This is what a budget too small for the system prompt alone produces: every
    request overshoots, so the trigger fires on a `pending` that is empty.
    """

    policy = ContextPolicy(keep_recent=2, summarize_after=100, max_input_tokens=100)
    store.append("t1", exchange(4), LOCAL_USER_ID)
    await fold_older_messages(EchoBackend(), store, "t1", policy, used_tokens=5000)
    _, through = store.summary("t1")

    result = await fold_older_messages(EchoBackend(), store, "t1", policy, used_tokens=5000)

    assert result is None
    assert store.summary("t1")[1] == through


async def test_without_a_known_limit_only_the_message_count_folds(store: SqliteStore) -> None:
    """A model that does not state its context length is not guessed at."""

    policy = ContextPolicy(keep_recent=4, summarize_after=100)
    store.append("t1", exchange(6), LOCAL_USER_ID)

    result = await fold_older_messages(EchoBackend(), store, "t1", policy, used_tokens=999_999)

    assert result is None


async def test_nothing_is_lost_when_a_thread_is_folded(store: SqliteStore) -> None:
    """The fold moves the window; it never deletes a message."""

    store.append("t1", exchange(12), LOCAL_USER_ID)

    await fold_older_messages(EchoBackend(), store, "t1", ContextPolicy())

    assert store.message_count("t1") == 24
