"""A `ModelBackend` for any OpenAI-compatible chat endpoint.

The provider wire format lives here and nowhere else. The two parts that fail
silently rather than loudly — assembling media content parts and parsing tool
calls — are pure functions so they can be tested without a server.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Self

import httpx

from app.config import ModelSettings
from app.models.base import Completion, ContentPart, Message, ModelBackend, ToolCall, Usage

AUDIO_FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
}


class BackendError(RuntimeError):
    """The endpoint was reached but its answer cannot be used."""


def _encode(part: ContentPart) -> str:
    # ContentPart.__post_init__ guarantees data on every non-text part.
    return base64.b64encode(part.data or b"").decode("ascii")


def _content_part(part: ContentPart) -> dict[str, Any]:
    if part.kind == "text":
        return {"type": "text", "text": part.text}
    if part.kind == "image":
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{part.media_type};base64,{_encode(part)}"},
        }
    audio_format = AUDIO_FORMATS.get(part.media_type or "")
    if audio_format is None:
        raise BackendError(f"unsupported audio media type: {part.media_type!r}")
    return {"type": "input_audio", "input_audio": {"data": _encode(part), "format": audio_format}}


def build_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Turn the application's messages into the provider's message list."""

    payload: list[dict[str, Any]] = []
    for message in messages:
        parts = [_content_part(part) for part in message.content]
        # An assistant turn that only calls tools has no content, and the wire
        # format spells that null rather than as an empty list.
        item: dict[str, Any] = {"role": message.role, "content": parts or None}
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            item["tool_call_id"] = message.tool_call_id
        payload.append(item)
    return payload


def parse_completion(payload: dict[str, Any]) -> Completion:
    """Turn one chat-completion response into a `Completion`."""

    choices = payload.get("choices") or []
    if not choices:
        raise BackendError(f"the response carried no choices: {payload}")
    choice = choices[0]
    message = choice.get("message") or {}

    calls = []
    for raw in message.get("tool_calls") or ():
        function = raw.get("function") or {}
        name = function.get("name")
        if not name:
            raise BackendError(f"a tool call arrived without a name: {raw}")
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise BackendError(f"tool call {name} sent invalid JSON: {arguments!r}") from error
        if not isinstance(parsed, dict):
            raise BackendError(f"tool call {name} sent arguments that are not an object: {parsed!r}")
        calls.append(ToolCall(id=raw.get("id") or "", name=name, arguments=parsed))

    usage = payload.get("usage") or {}
    return Completion(
        text=message.get("content") or "",
        tool_calls=tuple(calls),
        usage=Usage(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        ),
        finish_reason=choice.get("finish_reason"),
    )


def parse_stream_line(line: str) -> str | None:
    """Return the text carried by one server-sent-events line, if it carries any."""

    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    chunk = json.loads(data)
    choices = chunk.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("delta") or {}).get("content") or None


class OpenAICompatibleBackend(ModelBackend):
    """Talks to a chat-completions endpoint over plain HTTP."""

    def __init__(
        self,
        settings: ModelSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or ModelSettings()
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.settings.endpoint.rstrip("/"),
            timeout=self.settings.timeout,
            headers=headers,
            transport=transport,
        )

    def _body(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.name,
            "messages": build_messages(messages),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        if response_format:
            body["response_format"] = response_format
        if stream:
            body["stream"] = True
        return body

    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        response = await self._client.post(
            "/chat/completions", json=self._body(messages, tools, response_format)
        )
        if response.status_code >= 400:
            raise BackendError(f"HTTP {response.status_code}: {response.text}")
        return parse_completion(response.json())

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        body = self._body(messages, tools, response_format, stream=True)
        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            if response.status_code >= 400:
                await response.aread()
                raise BackendError(f"HTTP {response.status_code}: {response.text}")
            async for line in response.aiter_lines():
                text = parse_stream_line(line)
                if text:
                    yield text

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exception: object) -> None:
        await self.aclose()
