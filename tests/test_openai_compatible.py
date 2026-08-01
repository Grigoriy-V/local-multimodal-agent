"""The wire format, exercised without a server.

Media part assembly and tool-call parsing are the two things that fail quietly
against a live endpoint: a mis-shaped part is ignored by the model, and a
mis-parsed tool call looks like an empty answer.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from app.config import ModelSettings
from app.models import ContentPart, Message
from app.models.openai_compatible import (
    BackendError,
    OpenAICompatibleBackend,
    build_messages,
    parse_completion,
    parse_stream_line,
)


def text_part(text: str = "hello") -> ContentPart:
    return ContentPart(kind="text", text=text)


def settings(**overrides: Any) -> ModelSettings:
    base = {"endpoint": "http://test/v1", "name": "test-model", "api_key": None}
    return ModelSettings(_env_file=None, **{**base, **overrides})


def backend(handler, **overrides: Any) -> OpenAICompatibleBackend:
    return OpenAICompatibleBackend(settings(**overrides), transport=httpx.MockTransport(handler))


def completion_payload(**message: Any) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": "", **message}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }


# --- content parts -----------------------------------------------------------


def test_text_part_is_sent_as_text() -> None:
    [message] = build_messages([Message(role="user", content=[text_part("hi")])])

    assert message == {"role": "user", "content": [{"type": "text", "text": "hi"}]}


def test_image_part_becomes_a_data_url() -> None:
    part = ContentPart(kind="image", data=b"\x89PNG", media_type="image/png")

    [message] = build_messages([Message(role="user", content=[part])])

    url = message["content"][0]["image_url"]["url"]
    assert url == f"data:image/png;base64,{base64.b64encode(b'\x89PNG').decode()}"


def test_audio_part_carries_bare_base64_and_a_format() -> None:
    part = ContentPart(kind="audio", data=b"RIFF", media_type="audio/wav")

    [message] = build_messages([Message(role="user", content=[part])])

    audio = message["content"][0]["input_audio"]
    assert message["content"][0]["type"] == "input_audio"
    assert audio == {"data": base64.b64encode(b"RIFF").decode(), "format": "wav"}


def test_audio_media_type_maps_to_the_provider_format() -> None:
    part = ContentPart(kind="audio", data=b"fLaC", media_type="audio/flac")

    [message] = build_messages([Message(role="user", content=[part])])

    assert message["content"][0]["input_audio"]["format"] == "flac"


def test_unknown_audio_media_type_is_refused() -> None:
    part = ContentPart(kind="audio", data=b"\x00", media_type="audio/aiff")

    with pytest.raises(BackendError, match="unsupported audio media type"):
        build_messages([Message(role="user", content=[part])])


def test_mixed_message_keeps_part_order() -> None:
    parts = [
        text_part("compare"),
        ContentPart(kind="image", data=b"a", media_type="image/png"),
        ContentPart(kind="image", data=b"b", media_type="image/jpeg"),
        ContentPart(kind="audio", data=b"c", media_type="audio/wav"),
    ]

    [message] = build_messages([Message(role="user", content=parts)])

    assert [part["type"] for part in message["content"]] == [
        "text",
        "image_url",
        "image_url",
        "input_audio",
    ]


def test_roles_and_tool_call_id_survive() -> None:
    messages = [
        Message(role="system", content=[text_part("be brief")]),
        Message(role="tool", content=[text_part("21")], tool_call_id="call_1"),
    ]

    payload = build_messages(messages)

    assert [item["role"] for item in payload] == ["system", "tool"]
    assert "tool_call_id" not in payload[0]
    assert payload[1]["tool_call_id"] == "call_1"


# --- responses ---------------------------------------------------------------


def test_completion_carries_text_usage_and_finish_reason() -> None:
    result = parse_completion(completion_payload(content="pong"))

    assert result.text == "pong"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (7, 3)
    assert result.finish_reason == "stop"


def test_tool_call_arguments_are_decoded_from_the_json_string() -> None:
    payload = completion_payload(
        tool_calls=[
            {
                "id": "call_1",
                "function": {
                    "name": "get_weather",
                    "arguments": json.dumps({"city": "Tbilisi", "unit": "celsius"}),
                },
            }
        ]
    )

    [call] = parse_completion(payload).tool_calls

    assert (call.id, call.name) == ("call_1", "get_weather")
    assert call.arguments == {"city": "Tbilisi", "unit": "celsius"}


def test_several_tool_calls_keep_their_order() -> None:
    payload = completion_payload(
        tool_calls=[
            {"id": "a", "function": {"name": "list_files", "arguments": "{}"}},
            {"id": "b", "function": {"name": "read_file", "arguments": '{"path": "x"}'}},
        ]
    )

    calls = parse_completion(payload).tool_calls

    assert [call.name for call in calls] == ["list_files", "read_file"]
    assert calls[0].arguments == {}


def test_malformed_tool_arguments_raise_rather_than_look_empty() -> None:
    payload = completion_payload(
        tool_calls=[{"id": "a", "function": {"name": "read_file", "arguments": "{path: x"}}]
    )

    with pytest.raises(BackendError, match="invalid JSON"):
        parse_completion(payload)


def test_tool_arguments_that_are_not_an_object_are_refused() -> None:
    payload = completion_payload(
        tool_calls=[{"id": "a", "function": {"name": "read_file", "arguments": '"x"'}}]
    )

    with pytest.raises(BackendError, match="not an object"):
        parse_completion(payload)


def test_a_nameless_tool_call_is_refused() -> None:
    payload = completion_payload(tool_calls=[{"id": "a", "function": {"arguments": "{}"}}])

    with pytest.raises(BackendError, match="without a name"):
        parse_completion(payload)


def test_an_empty_response_is_refused() -> None:
    with pytest.raises(BackendError, match="no choices"):
        parse_completion({"choices": []})


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('data: {"choices": [{"delta": {"content": "one"}}]}', "one"),
        ('data: {"choices": [{"delta": {}}]}', None),
        ('data: {"choices": []}', None),
        ("data: [DONE]", None),
        ("data:", None),
        ("", None),
        (": keep-alive", None),
    ],
)
def test_stream_lines_yield_only_text(line: str, expected: str | None) -> None:
    assert parse_stream_line(line) == expected


# --- requests ----------------------------------------------------------------


async def test_invoke_posts_a_complete_request() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion_payload(content="pong"))

    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    response_format = {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}

    async with backend(handler, api_key="secret") as client:
        result = await client.invoke([Message(role="user", content=[text_part()])], tools, response_format)

    assert result.text == "pong"
    assert seen["url"] == "http://test/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["tools"] == tools
    assert seen["body"]["tool_choice"] == "auto"
    assert seen["body"]["response_format"] == response_format
    assert "stream" not in seen["body"]


async def test_a_request_without_tools_omits_them() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=completion_payload(content="pong"))

    async with backend(handler) as client:
        await client.invoke([Message(role="user", content=[text_part()])])

    assert "tools" not in seen
    assert "response_format" not in seen


async def test_stream_yields_the_text_chunks_in_order() -> None:
    body = "".join(
        f'data: {json.dumps({"choices": [{"delta": {"content": word}}]})}\n\n'
        for word in ("one", " two", " three")
    ) + "data: [DONE]\n\n"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=body.encode())

    async with backend(handler) as client:
        chunks = [chunk async for chunk in client.stream([Message(role="user", content=[text_part()])])]

    assert chunks == ["one", " two", " three"]
    assert seen["stream"] is True


async def test_an_http_error_becomes_a_backend_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    async with backend(handler) as client:
        with pytest.raises(BackendError, match="HTTP 400"):
            await client.invoke([Message(role="user", content=[text_part()])])
