from __future__ import annotations

import base64

import pytest

pytest.importorskip("chainlit", reason="the ui dependency group is optional")

from chainlit.types import Pagination, ThreadFilter

from app.memory import MemoryStore
from app.models import ContentPart, Message
from ui.chainlit_history import LOCAL_USER_ID, MemoryStoreDataLayer


@pytest.fixture
def layer(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    return MemoryStoreDataLayer(store)


@pytest.mark.asyncio
async def test_native_history_lists_existing_threads_newest_first(layer) -> None:
    layer.store.append("first", [Message(role="user", content=[ContentPart("text", text="old")])])
    layer.store.append("second", [Message(role="user", content=[ContentPart("text", text="new")])])

    result = await layer.list_threads(Pagination(first=10), ThreadFilter(userId=LOCAL_USER_ID))

    assert [thread["id"] for thread in result.data] == ["second", "first"]
    assert result.data[0]["name"] == "new"
    assert result.data[0]["steps"] == []


@pytest.mark.asyncio
async def test_native_history_resumes_text_and_media(layer) -> None:
    layer.store.append(
        "chat",
        [
            Message(
                role="user",
                content=[
                    ContentPart("text", text="look"),
                    ContentPart("image", data=b"png", media_type="image/png"),
                ],
            ),
            Message(role="assistant", content=[ContentPart("text", text="I see it")]),
        ],
    )

    thread = await layer.get_thread("chat")

    assert thread is not None
    assert [step["type"] for step in thread["steps"]] == [
        "user_message",
        "assistant_message",
    ]
    assert [step["output"] for step in thread["steps"]] == ["look", "I see it"]
    element = thread["elements"][0]
    assert element["forId"] == thread["steps"][0]["id"]
    assert element["url"] == f"data:image/png;base64,{base64.b64encode(b'png').decode('ascii')}"


@pytest.mark.asyncio
async def test_native_history_paginates_and_searches(layer) -> None:
    for thread_id, opening in (("one", "alpha"), ("two", "beta"), ("three", "gamma")):
        layer.store.append(
            thread_id, [Message(role="user", content=[ContentPart("text", text=opening)])]
        )

    first = await layer.list_threads(Pagination(first=2), ThreadFilter())
    second = await layer.list_threads(
        Pagination(first=2, cursor=first.pageInfo.endCursor), ThreadFilter()
    )
    found = await layer.list_threads(Pagination(first=10), ThreadFilter(search="ALPHA"))

    assert first.pageInfo.hasNextPage is True
    assert len(second.data) == 1
    assert [thread["id"] for thread in found.data] == ["one"]


@pytest.mark.asyncio
async def test_chainlit_thread_initialization_creates_a_canonical_empty_thread(layer) -> None:
    await layer.update_thread("new-chat", name="first message", user_id=LOCAL_USER_ID)

    assert await layer.get_thread_author("new-chat") == "local"
    assert (await layer.get_thread("new-chat"))["steps"] == []
