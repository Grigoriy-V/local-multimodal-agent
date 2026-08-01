"""The memory tools, and the boundary that saving is a decision."""

from __future__ import annotations

import pytest

from app.memory import MemoryStore
from app.models import ToolCall
from app.tools import Toolbox, ToolError, memory_tools


@pytest.fixture
def store() -> MemoryStore:
    with MemoryStore() as store:
        yield store


def tools(store: MemoryStore, thread_id: str = "t1") -> dict[str, object]:
    return {tool.name: tool for tool in memory_tools(store, thread_id)}


def test_remembering_puts_the_fact_where_search_finds_it(store: MemoryStore) -> None:
    tools(store)["remember_fact"].run(text="The human works on Windows with an RTX 4090")

    assert store.search("4090") != []


def test_searching_lists_the_matches(store: MemoryStore) -> None:
    store.remember("The endpoint is reached over MODEL_ENDPOINT")

    result = tools(store)["search_memory"].run(query="endpoint")

    assert result == "- The endpoint is reached over MODEL_ENDPOINT"


def test_a_miss_says_so_rather_than_returning_nothing(store: MemoryStore) -> None:
    result = tools(store)["search_memory"].run(query="kangaroo")

    assert "no memory matches" in result


def test_an_empty_fact_is_refused(store: MemoryStore) -> None:
    with pytest.raises(ToolError, match="cannot be empty"):
        tools(store)["remember_fact"].run(text="  ")


def test_an_overlong_fact_is_refused(store: MemoryStore) -> None:
    with pytest.raises(ToolError, match="shorter than"):
        tools(store)["remember_fact"].run(text="x" * 501)


def test_nothing_is_saved_unless_the_tool_is_called(store: MemoryStore) -> None:
    """Talking about a fact is not saving it."""

    box = Toolbox(memory_tools(store, "t1"))
    box.run(ToolCall(id="c1", name="search_memory", arguments={"query": "anything"}))

    assert store.facts() == []


def test_a_fact_saved_in_one_thread_is_found_from_another(store: MemoryStore) -> None:
    tools(store, "session-one")["remember_fact"].run(text="The model is Gemma 4 12B IT")

    result = tools(store, "session-two")["search_memory"].run(query="Gemma")

    assert "Gemma 4 12B IT" in result
