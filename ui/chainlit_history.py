"""Expose the canonical MemoryStore through Chainlit's native chat history.

Chainlit needs a data layer to draw its sidebar, but conversation content must
not acquire a second owner. This adapter therefore derives threads, steps and
elements from MemoryStore and ignores Chainlit's duplicate step writes.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Sequence
from typing import Any

from chainlit.data import BaseDataLayer
from chainlit.element import Element, ElementDict
from chainlit.step import StepDict
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import PersistedUser, User

from app.memory import MemoryStore, Thread
from app.models import ContentPart, Message
from app.conversations import delete_conversation

LOCAL_USER_ID = "local-user"
LOCAL_USER_IDENTIFIER = "local"
LOCAL_USER_CREATED_AT = "2026-01-01T00:00:00+00:00"


def _id(thread_id: str, position: int, suffix: str = "message") -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"local-agent:{thread_id}:{position}:{suffix}"))


def _text(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content if part.kind == "text").strip()


def _thread_name(thread: Thread) -> str:
    opening = thread.opening.strip()
    return opening[:80] if opening else "Conversation"


def _element(
    thread_id: str, step_id: str, position: int, part_index: int, part: ContentPart
) -> ElementDict:
    encoded = base64.b64encode(part.data or b"").decode("ascii")
    return {
        "id": _id(thread_id, position, f"part-{part_index}"),
        "threadId": thread_id,
        "forId": step_id,
        "type": part.kind,
        "name": f"{part.kind}-{part_index}",
        "display": "inline",
        "size": "medium" if part.kind == "image" else None,
        "mime": part.media_type,
        "url": f"data:{part.media_type};base64,{encoded}",
    }


def _step(thread_id: str, position: int, message: Message, created_at: str) -> StepDict:
    step_id = _id(thread_id, position)
    if message.role == "user":
        step_type = "user_message"
        name = "You"
    elif message.role == "assistant":
        step_type = "assistant_message"
        name = "Assistant"
    else:
        step_type = "tool"
        name = "Tool"
    output = _text(message)
    if message.tool_calls and not output:
        output = "\n".join(
            f"{call.name}({json.dumps(call.arguments, ensure_ascii=False)})"
            for call in message.tool_calls
        )
    return {
        "id": step_id,
        "threadId": thread_id,
        "parentId": None,
        "name": name,
        "type": step_type,
        "input": "" if step_type != "tool" else output,
        "output": output,
        "createdAt": created_at,
        "start": created_at,
        "end": created_at,
    }


class MemoryStoreDataLayer(BaseDataLayer):
    """Read native Chainlit history from the project's existing SQLite store."""

    def __init__(
        self,
        store: MemoryStore,
        checkpoints: str = "data/checkpoints.sqlite3",
        task_checkpoints: str = "data/task-checkpoints.sqlite3",
    ) -> None:
        self.store = store
        self.checkpoints = checkpoints
        self.task_checkpoints = task_checkpoints

    async def get_user(self, identifier: str) -> PersistedUser | None:
        if identifier != LOCAL_USER_IDENTIFIER:
            return None
        return PersistedUser(
            id=LOCAL_USER_ID,
            identifier=LOCAL_USER_IDENTIFIER,
            display_name="Local user",
            metadata={"provider": "header"},
            createdAt=LOCAL_USER_CREATED_AT,
        )

    async def create_user(self, user: User) -> PersistedUser | None:
        return await self.get_user(user.identifier)

    async def delete_feedback(self, feedback_id: str) -> bool:
        return False

    async def upsert_feedback(self, feedback: Feedback) -> str:
        raise NotImplementedError("feedback is not enabled")

    async def create_element(self, element: Element) -> None:
        return None

    async def get_element(self, thread_id: str, element_id: str) -> ElementDict | None:
        thread = await self.get_thread(thread_id)
        if thread is None:
            return None
        elements = thread.get("elements") or []
        return next((item for item in elements if item["id"] == element_id), None)

    async def delete_element(self, element_id: str, thread_id: str | None = None) -> None:
        return None

    async def create_step(self, step_dict: StepDict) -> None:
        return None

    async def update_step(self, step_dict: StepDict) -> None:
        return None

    async def delete_step(self, step_id: str) -> None:
        return None

    async def get_thread_author(self, thread_id: str) -> str:
        return LOCAL_USER_IDENTIFIER if any(t.id == thread_id for t in self.store.threads()) else ""

    async def delete_thread(self, thread_id: str) -> None:
        await delete_conversation(
            self.store,
            thread_id,
            self.checkpoints,
            self.task_checkpoints,
        )

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse[ThreadDict]:
        threads = self.store.threads()
        if filters.search:
            needle = filters.search.casefold()
            threads = [thread for thread in threads if needle in _thread_name(thread).casefold()]
        start = 0
        if pagination.cursor:
            for index, thread in enumerate(threads):
                if thread.id == pagination.cursor:
                    start = index + 1
                    break
        page = threads[start : start + pagination.first]
        data = [self._thread(thread, include_content=False) for thread in page]
        return PaginatedResponse(
            pageInfo=PageInfo(
                hasNextPage=start + len(page) < len(threads),
                startCursor=page[0].id if page else None,
                endCursor=page[-1].id if page else None,
            ),
            data=data,
        )

    async def get_thread(self, thread_id: str) -> ThreadDict | None:
        thread = next((item for item in self.store.threads() if item.id == thread_id), None)
        return self._thread(thread, include_content=True) if thread else None

    async def update_thread(
        self,
        thread_id: str,
        name: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        # Canonical threads are created when the application stores the first
        # message. Treating Chainlit's metadata callback as content creates
        # phantom empty chats and can resurrect a thread immediately after its
        # native deletion callback completed.
        return None

    async def build_debug_url(self) -> str:
        return ""

    async def close(self) -> None:
        self.store.close()

    async def get_favorite_steps(self, user_id: str) -> list[StepDict]:
        return []

    def _thread(self, thread: Thread, include_content: bool) -> ThreadDict:
        steps: list[StepDict] = []
        elements: list[ElementDict] = []
        if include_content:
            messages = self.store.messages(thread.id)
            for position, message in enumerate(messages):
                step = _step(thread.id, position, message, thread.created_at)
                steps.append(step)
                for part_index, part in enumerate(message.content):
                    if part.kind != "text":
                        elements.append(_element(thread.id, step["id"], position, part_index, part))
        return {
            "id": thread.id,
            "createdAt": thread.created_at,
            "name": _thread_name(thread),
            "userId": LOCAL_USER_ID,
            "userIdentifier": LOCAL_USER_IDENTIFIER,
            "tags": [],
            "metadata": {},
            "steps": steps,
            "elements": elements,
        }
