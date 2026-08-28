"""A `ModelBackend` for any OpenAI-compatible chat endpoint.

The provider wire format lives here and nowhere else. The two parts that fail
silently rather than loudly — assembling media content parts and parsing tool
calls — are pure functions so they can be tested without a server.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Self

import httpx

from app.config import ModelSettings
from app.models.base import (
    BackendError,
    Completion,
    ContentPart,
    ContextOverflowError,
    Message,
    ModelBackend,
    ToolCall,
    Usage,
)

AUDIO_FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
}

# OpenAI's `input_audio` part validates `format` against a literal, so anything
# else is refused by the schema before the server decodes a byte — which is how
# a Telegram voice message, always Ogg/Opus, used to fail after waking the GPU.
# The rest go as an `audio_url` data URI: the container that serves this model
# reads the format from the URI and decodes whatever soundfile/PyAV supports.
# Splitting them keeps the common case on the portable, standard part.
OPENAI_AUDIO_FORMATS = frozenset({"wav", "mp3"})

# Statuses that mean "later", not "no": a server still starting, a queue that is
# full, a proxy that gave up early. A 4xx about the request itself is excluded —
# sending the same bad request again only wastes the time it takes to refuse it.
TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
CONTEXT_OVERFLOW_STATUS = frozenset({400, 413, 422})
CONTEXT_OVERFLOW_MARKERS = (
    "maximum context length",
    "context length exceeded",
    "context window",
    "too many tokens",
    "prompt is too long",
    "input is too long",
    "max_model_len",
)


def is_context_overflow(status_code: int, detail: str) -> bool:
    """Classify provider-specific overflow wording at the provider boundary."""

    lowered = detail.lower()
    return status_code in CONTEXT_OVERFLOW_STATUS and any(
        marker in lowered for marker in CONTEXT_OVERFLOW_MARKERS
    )


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
    if audio_format in OPENAI_AUDIO_FORMATS:
        return {
            "type": "input_audio",
            "input_audio": {"data": _encode(part), "format": audio_format},
        }
    return {
        "type": "audio_url",
        "audio_url": {"url": f"data:{part.media_type};base64,{_encode(part)}"},
    }


def build_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Turn the application's messages into the provider's message list."""

    payload: list[dict[str, Any]] = []
    for message in messages:
        # An outbound part is a transport action the agent already chose, not
        # fresh evidence for another model request. The accompanying tool text
        # is the receipt the model sees.
        parts = [_content_part(part) for part in message.content if not part.outbound]
        if message.role == "tool" and not parts:
            parts = [{"type": "text", "text": "The selected item was prepared for delivery."}]
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


def parse_context_limit(payload: dict[str, Any], name: str) -> int | None:
    """Find `max_model_len` for one model in a `/models` listing.

    vLLM reports it; other OpenAI-compatible servers may not, and an unknown
    limit is not an error — it only means the request cannot be bounded.
    """

    for entry in payload.get("data") or ():
        if entry.get("id") != name:
            continue
        limit = entry.get("max_model_len")
        return int(limit) if isinstance(limit, int) else None
    return None


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
            if self.settings.auth_style == "bearer":
                headers["Authorization"] = f"Bearer {self.settings.api_key}"
            else:
                key, separator, secret = self.settings.api_key.partition(".")
                if not separator or not key.startswith("wk-") or not secret.startswith("ws-"):
                    raise ValueError(
                        "MODEL_API_KEY must be '<wk-token-id>.<ws-token-secret>' "
                        "when MODEL_AUTH_STYLE=modal_proxy"
                    )
                headers["Modal-Key"] = key
                headers["Modal-Secret"] = secret
        elif self.settings.auth_style == "modal_proxy":
            raise ValueError("MODEL_API_KEY is required when MODEL_AUTH_STYLE=modal_proxy")
        self._client = httpx.AsyncClient(
            base_url=self.settings.endpoint.rstrip("/"),
            timeout=self.settings.timeout,
            headers=headers,
            transport=transport,
        )

    async def warm(self) -> bool:
        """Ask the endpoint to start, without waiting for it to finish starting.

        A scale-to-zero model container begins waking the moment a request
        reaches it, so the wake is bought by *sending* one, not by reading the
        answer. This sends the cheapest request the OpenAI-compatible surface
        has and abandons the response: connecting and writing are awaited
        because that is what triggers the wake, reading is given almost no time
        because the wake is what was wanted.

        Never raises. Warming is an optimization, and a failed optimization must
        not fail the request that asked for it. The boolean is for logging and
        for tests, not for control flow.
        """

        try:
            await self._client.get(
                "/models",
                timeout=httpx.Timeout(connect=5.0, write=5.0, pool=5.0, read=0.1),
            )
        except httpx.TimeoutException:
            # Expected, and the point: the request was written, so the container
            # is already starting. Waiting for the body would mean waiting out
            # the whole cold start here.
            return True
        except httpx.HTTPError:
            return False
        return True

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

    async def _completion(self, body: dict[str, Any]) -> dict[str, Any]:
        """Post one request, trying again while the failure looks transient.

        The graph sees one failure mode instead of two: either an answer, or a
        server that is really not going to answer. Backoff doubles, because the
        common case is a server that is busy, and asking it faster does not help.
        """

        attempt = 0
        while True:
            try:
                response = await self._client.post("/chat/completions", json=body)
            except httpx.HTTPError as error:
                # A timeout carries an empty message, so the class name is named
                # too: "could not be reached:" on its own tells nobody anything.
                detail = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
                failure = BackendError(
                    f"the endpoint {self.settings.endpoint} could not be reached ({detail})"
                )
                transient = True
            else:
                if response.status_code < 400:
                    return response.json()
                error_type = (
                    ContextOverflowError
                    if is_context_overflow(response.status_code, response.text)
                    else BackendError
                )
                failure = error_type(f"HTTP {response.status_code}: {response.text}")
                transient = response.status_code in TRANSIENT_STATUS
            if not transient or attempt >= self.settings.retries:
                raise failure
            await asyncio.sleep(self.settings.retry_backoff * 2**attempt)
            attempt += 1

    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        return parse_completion(await self._completion(self._body(messages, tools, response_format)))

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield text as it arrives. Not retried: see the note below.

        A stream that fails halfway has already given the caller part of an
        answer, and there is no way to ask for the rest — retrying would repeat
        what was said. `invoke`, which the agent uses, is retried instead.
        """

        body = self._body(messages, tools, response_format, stream=True)
        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            if response.status_code >= 400:
                await response.aread()
                error_type = (
                    ContextOverflowError
                    if is_context_overflow(response.status_code, response.text)
                    else BackendError
                )
                raise error_type(f"HTTP {response.status_code}: {response.text}")
            async for line in response.aiter_lines():
                text = parse_stream_line(line)
                if text:
                    yield text

    async def context_limit(self) -> int | None:
        """Ask the server how long a request it will take.

        A server that cannot be reached or does not report the number answers
        the same way: unknown. An unreachable server is not diagnosed here — the
        next model call says so, loudly and with the failure that matters.
        """

        try:
            response = await self._client.get("/models")
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        return parse_context_limit(response.json(), self.settings.name)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exception: object) -> None:
        await self.aclose()
