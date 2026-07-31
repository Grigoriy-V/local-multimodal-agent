"""The backend contract, exercised through a fake so tests stay offline."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from app.models import Completion, ContentPart, Message, ModelBackend, ToolCall, Usage


class FakeBackend(ModelBackend):
    def __init__(self, completion: Completion) -> None:
        self.completion = completion
        self.seen: list[Sequence[Message]] = []

    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        self.seen.append(messages)
        return self.completion

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        self.seen.append(messages)
        for word in self.completion.text.split():
            yield word


def text_message(role: str = "user", text: str = "hello") -> Message:
    return Message(role=role, content=[ContentPart(kind="text", text=text)])


def test_text_part_requires_text() -> None:
    with pytest.raises(ValueError, match="requires text"):
        ContentPart(kind="text")


def test_media_part_requires_data_and_media_type() -> None:
    with pytest.raises(ValueError, match="requires data and media_type"):
        ContentPart(kind="image", data=b"\x89PNG")
    with pytest.raises(ValueError, match="requires data and media_type"):
        ContentPart(kind="audio", media_type="audio/wav")


def test_message_requires_content() -> None:
    with pytest.raises(ValueError, match="at least one content part"):
        Message(role="user", content=[])


def test_multimodal_message_preserves_part_order() -> None:
    parts = [
        ContentPart(kind="text", text="compare these"),
        ContentPart(kind="image", data=b"a", media_type="image/png"),
        ContentPart(kind="image", data=b"b", media_type="image/png"),
        ContentPart(kind="audio", data=b"c", media_type="audio/wav"),
    ]
    message = Message(role="user", content=parts)
    assert [part.kind for part in message.content] == ["text", "image", "image", "audio"]


def test_backend_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        ModelBackend()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_invoke_returns_completion_with_tool_calls() -> None:
    expected = Completion(
        text="",
        tool_calls=(ToolCall(id="1", name="read_file", arguments={"path": "README.md"}),),
        usage=Usage(input_tokens=12, output_tokens=3),
        finish_reason="tool_calls",
    )
    backend = FakeBackend(expected)

    result = await backend.invoke([text_message()])

    assert result is expected
    assert result.tool_calls[0].name == "read_file"
    assert result.usage.input_tokens == 12


@pytest.mark.asyncio
async def test_stream_yields_chunks() -> None:
    backend = FakeBackend(Completion(text="one two three"))

    chunks = [chunk async for chunk in backend.stream([text_message()])]

    assert chunks == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_completion_defaults_are_empty() -> None:
    backend = FakeBackend(Completion(text="hi"))

    result = await backend.invoke([text_message()])

    assert result.tool_calls == ()
    assert result.usage == Usage()
    assert result.finish_reason is None
