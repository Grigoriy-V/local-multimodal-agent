"""The memory tools, and the boundary that saving is a decision."""

from __future__ import annotations

import pytest

from app.memory import LOCAL_USER_ID, SqliteStore
from app.models import ToolCall
from app.tools import Toolbox, ToolError, memory_tools


@pytest.fixture
def store() -> SqliteStore:
    with SqliteStore() as store:
        yield store


def tools(store: SqliteStore, thread_id: str = "t1") -> dict[str, object]:
    return {tool.name: tool for tool in memory_tools(store, LOCAL_USER_ID, thread_id)}


def test_remembering_puts_the_fact_where_search_finds_it(store: SqliteStore) -> None:
    tools(store)["remember_fact"].run(text="The human works on Windows with an RTX 4090")

    assert store.search("4090", LOCAL_USER_ID) != []


def test_searching_lists_the_matches(store: SqliteStore) -> None:
    store.remember("The endpoint is reached over MODEL_ENDPOINT", LOCAL_USER_ID)

    result = tools(store)["search_memory"].run(query="endpoint")

    assert result == "- The endpoint is reached over MODEL_ENDPOINT"


def test_a_miss_says_so_rather_than_returning_nothing(store: SqliteStore) -> None:
    result = tools(store)["search_memory"].run(query="kangaroo")

    assert "no memory matches" in result


def test_an_empty_fact_is_refused(store: SqliteStore) -> None:
    with pytest.raises(ToolError, match="cannot be empty"):
        tools(store)["remember_fact"].run(text="  ")


def test_an_overlong_fact_is_refused(store: SqliteStore) -> None:
    with pytest.raises(ToolError, match="shorter than"):
        tools(store)["remember_fact"].run(text="x" * 501)


def test_nothing_is_saved_unless_the_tool_is_called(store: SqliteStore) -> None:
    """Talking about a fact is not saving it."""

    box = Toolbox(memory_tools(store, LOCAL_USER_ID, "t1"))
    box.run(ToolCall(id="c1", name="search_memory", arguments={"query": "anything"}))

    assert store.facts(LOCAL_USER_ID) == []


def test_a_fact_saved_in_one_thread_is_found_from_another(store: SqliteStore) -> None:
    tools(store, "session-one")["remember_fact"].run(text="The model is Gemma 4 12B IT")

    result = tools(store, "session-two")["search_memory"].run(query="Gemma")

    assert "Gemma 4 12B IT" in result
