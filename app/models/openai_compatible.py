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
from dataclasses import dataclass
from typing import Any, Self

import httpx

from app.config import ModelSettings
from app.models.base import (
    CHARS_PER_TOKEN,
    BackendError,
    Completion,
    CompletionDone,
    ContentPart,
    ContextOverflowError,
    Message,
    ModelBackend,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
    measure_request,
)

# How far one observation moves the ratio the estimate uses. Small on purpose:
# the number decides when a conversation is folded, so it should follow what
# this endpoint is really like and not what the last message happened to be.
CALIBRATION_WEIGHT = 0.25

# Short requests are mostly the fixed overhead of the chat template rather than
# the text, so they say very little about what text is worth and would drag the
# ratio down. Anything conversational clears this.
CALIBRATION_MIN_CHARS = 500

# The ratio stays inside a range no real tokenizer leaves. The floor keeps a
# broken report from making every request look enormous; the ceiling is the one
# that matters, because a ratio that drifted too high would estimate every
# request as small and quietly stop folding anything.
CHARS_PER_TOKEN_FLOOR = 1.0
CHARS_PER_TOKEN_CEILING = 6.0

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


def parse_arguments(name: str, arguments: str) -> dict[str, Any]:
    """Read one tool call's arguments, which arrive as a JSON string."""

    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError as error:
        raise BackendError(f"tool call {name} sent invalid JSON: {arguments!r}") from error
    if not isinstance(parsed, dict):
        raise BackendError(f"tool call {name} sent arguments that are not an object: {parsed!r}")
    return parsed


def parse_usage(usage: dict[str, Any] | None) -> Usage:
    return Usage(
        input_tokens=(usage or {}).get("prompt_tokens"),
        output_tokens=(usage or {}).get("completion_tokens"),
    )


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
        calls.append(
            ToolCall(
                id=raw.get("id") or "",
                name=name,
                arguments=parse_arguments(name, function.get("arguments") or "{}"),
            )
        )

    return Completion(
        text=message.get("content") or "",
        tool_calls=tuple(calls),
        usage=parse_usage(payload.get("usage")),
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


def parse_stream_line(line: str) -> dict[str, Any] | None:
    """Return the chunk one server-sent-events line carries, if it carries one.

    Keep-alives, blank lines and the closing `[DONE]` are not chunks. A chunk
    with an empty `choices` list is: that is how usage arrives.
    """

    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    chunk = json.loads(data)
    return chunk if isinstance(chunk, dict) else None


@dataclass
class _PartialCall:
    """One tool call while its fragments are still arriving."""

    id: str = ""
    name: str = ""
    arguments: str = ""


class StreamedCompletion:
    """Assembles streamed chunks into the result `invoke` would have returned.

    Separate from the HTTP loop so the shapes a real server sends can be tested
    without one. Those shapes were read off the deployed vLLM rather than
    assumed; `reports/2026-08-29_v2_answer_streaming_preparation.md` records
    them. Three of them decide this code:

    - a tool call is opened by a chunk carrying `id` and `name` at an `index`,
      and continued by chunks carrying only that `index` and a slice of the
      argument string, so the JSON is parsed once at the end and never per
      chunk;
    - `finish_reason` arrives alone, in a chunk whose delta is empty;
    - `usage` arrives after that, in a chunk with no choices at all, and only
      because the request asked for it.
    """

    def __init__(self) -> None:
        self._text: list[str] = []
        self._calls: dict[int, _PartialCall] = {}
        self._usage = Usage()
        self._finish_reason: str | None = None

    def add(self, chunk: dict[str, Any]) -> str:
        """Take one chunk; return the assistant text it carried, if any.

        An empty string is the common answer: the opening chunk carries only a
        role, and every tool-call chunk carries no text at all.
        """

        if chunk.get("usage"):
            self._usage = parse_usage(chunk["usage"])
        choices = chunk.get("choices") or []
        if not choices:
            return ""
        choice = choices[0]
        if choice.get("finish_reason"):
            self._finish_reason = choice["finish_reason"]
        delta = choice.get("delta") or {}
        for raw in delta.get("tool_calls") or ():
            self._fragment(raw)
        # Reasoning, where a server separates it, is deliberately not returned:
        # `invoke` reads `content` alone, and a preview must show what the
        # answer will say, not the model thinking about it.
        text = delta.get("content") or ""
        if text:
            self._text.append(text)
        return text

    def _opens_another(self, partial: _PartialCall, identifier: str, name: str) -> bool:
        """Whether this fragment starts a new call rather than continuing one.

        A continuation carries only a slice of the argument string, and a server
        that echoes the id and name on every fragment is still describing the
        same call. What cannot be a continuation is a fragment naming a
        *different* tool, or carrying a different id: that is the next call,
        whatever position the server gave it.
        """

        if name and partial.name and name != partial.name:
            return True
        return bool(identifier and partial.id and identifier != partial.id)

    def _fragment(self, raw: dict[str, Any]) -> None:
        # Position is what ties fragments together — when the server gives one.
        # A server that omits it, or reuses a position it has already finished
        # with, is why identity is checked as well: appending a second call's
        # arguments to the first produces one call whose arguments are two
        # objects run together. Sometimes that is invalid JSON and the request
        # fails loudly. Sometimes it parses, and the model is handed back a call
        # it never made, with the other call's fields as keys and its own
        # required ones missing. That happened live on 2026-08-30: `write_file`
        # swallowed a `todo_write` list, lost `path`, and was retried eight
        # times.
        index = raw.get("index")
        function = raw.get("function") or {}
        name = function.get("name") or ""
        identifier = raw.get("id") or ""
        key = max(int(index), 0) if isinstance(index, int) else max(len(self._calls) - 1, 0)
        partial = self._calls.get(key)
        if partial is not None and self._opens_another(partial, identifier, name):
            key = max(self._calls) + 1
            partial = None
        if partial is None:
            partial = self._calls.setdefault(key, _PartialCall())
        if identifier:
            partial.id = identifier
        if name:
            partial.name = name
        partial.arguments += function.get("arguments") or ""

    def result(self) -> Completion:
        """The finished completion. Tool calls keep the order they were opened in."""

        calls = []
        for _, partial in sorted(self._calls.items()):
            if not partial.name:
                raise BackendError(f"a streamed tool call arrived without a name: {partial}")
            calls.append(
                ToolCall(
                    id=partial.id,
                    name=partial.name,
                    arguments=parse_arguments(partial.name, partial.arguments),
                )
            )
        return Completion(
            text="".join(self._text),
            tool_calls=tuple(calls),
            usage=self._usage,
            finish_reason=self._finish_reason,
        )


def auth_headers(settings: ModelSettings) -> dict[str, str]:
    """How this deployment proves it may talk to the model server.

    Its own function because the chat endpoint is not the only thing behind that
    door: the engine's `/metrics` is served by the same process behind the same
    proxy auth, and a second copy of this logic would be a second thing to keep
    true when the credential shape changes.
    """

    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        if settings.auth_style == "bearer":
            headers["Authorization"] = f"Bearer {settings.api_key}"
        else:
            key, separator, secret = settings.api_key.partition(".")
            if not separator or not key.startswith("wk-") or not secret.startswith("ws-"):
                raise ValueError(
                    "MODEL_API_KEY must be '<wk-token-id>.<ws-token-secret>' "
                    "when MODEL_AUTH_STYLE=modal_proxy"
                )
            headers["Modal-Key"] = key
            headers["Modal-Secret"] = secret
    elif settings.auth_style == "modal_proxy":
        raise ValueError("MODEL_API_KEY is required when MODEL_AUTH_STYLE=modal_proxy")
    return headers


class OpenAICompatibleBackend(ModelBackend):
    """Talks to a chat-completions endpoint over plain HTTP."""

    def __init__(
        self,
        settings: ModelSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or ModelSettings()
        headers = auth_headers(self.settings)
        self._client = httpx.AsyncClient(
            base_url=self.settings.endpoint.rstrip("/"),
            timeout=self.settings.timeout,
            headers=headers,
            transport=transport,
        )
        self._chars_per_token = CHARS_PER_TOKEN

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
            # Without this the streamed response carries no usage at all, and a
            # turn whose size is unknown cannot be folded or reported.
            body["stream_options"] = {"include_usage": True}
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
        completion = parse_completion(
            await self._completion(self._body(messages, tools, response_format))
        )
        self._calibrate(messages, completion.usage)
        return completion

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield text as it arrives, then the assembled result. Not retried.

        A stream that fails halfway has already given the caller part of an
        answer, and there is no way to ask for the rest — retrying would repeat
        what was said, in front of the person reading it. A failure before the
        first delta could be retried safely, and is not, for now: the caller
        sees one failure mode either way.

        `CompletionDone` is yielded only if the response ended; a stream that
        breaks raises out of here instead, so a caller can never mistake a
        truncated answer for a finished one.
        """

        body = self._body(messages, tools, response_format, stream=True)
        streamed = StreamedCompletion()
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
                chunk = parse_stream_line(line)
                if chunk is None:
                    continue
                text = streamed.add(chunk)
                if text:
                    yield TextDelta(text)
        finished = streamed.result()
        self._calibrate(messages, finished.usage)
        yield CompletionDone(finished)

    def estimate_tokens(self, messages: Sequence[Message]) -> int:
        """The inherited estimate, at the ratio this endpoint has been observed at.

        Every completion reports how many tokens the request became, so the
        conversion the estimate needs is arriving for free on traffic that was
        being sent anyway. Nothing is measured on purpose and no extra request
        is made.
        """

        chars, media = measure_request(messages)
        return int(chars / self._chars_per_token) + media

    def _calibrate(self, messages: Sequence[Message], usage: Usage) -> None:
        """Learn what text is worth here, from a request that was sent anyway.

        Skipped when the request carried media, because the reported total then
        includes an image whose token cost this ratio must not absorb — that is
        what `MEDIA_TOKENS` is for, and folding it in here would make the ratio
        drift with how many pictures a conversation happened to contain.

        Smoothed rather than replaced, so one odd request cannot move the
        threshold that decides when a conversation is folded, and clamped so
        that a nonsensical report cannot widen it far enough to disable folding
        altogether.
        """

        chars, media = measure_request(messages)
        reported = usage.input_tokens
        if media or not reported or chars < CALIBRATION_MIN_CHARS:
            return
        observed = chars / reported
        blended = self._chars_per_token + CALIBRATION_WEIGHT * (observed - self._chars_per_token)
        self._chars_per_token = min(max(blended, CHARS_PER_TOKEN_FLOOR), CHARS_PER_TOKEN_CEILING)

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
