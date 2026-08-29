"""A model that says what the test tells it to say.

Shared by the graph and session tests so both drive the same fake, and so a
change to `ModelBackend` breaks one place rather than three.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.models import (
    Completion,
    CompletionDone,
    ContentPart,
    Message,
    ModelBackend,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)


class ScriptedBackend(ModelBackend):
    """Returns prepared completions in order, then `default` for anything else.

    `default` exists because summarization is also a model call: a test about
    conversation length should not have to script the summary it triggers.
    """

    def __init__(
        self,
        *completions: Completion | Exception,
        default: Completion | None = None,
        limit: int | None = None,
    ) -> None:
        self.completions = list(completions)
        self.default = default
        self.limit = limit
        self.requests: list[list[Message]] = []
        self.tools_seen: list[Any] = []
        self.formats_seen: list[Any] = []

    async def context_limit(self) -> int | None:
        return self.limit

    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        self.requests.append(list(messages))
        self.tools_seen.append(tools)
        self.formats_seen.append(response_format)
        if self.completions:
            result = self.completions.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        if self.default is None:
            raise AssertionError("the backend was called more times than the test scripted")
        return self.default

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """The scripted completion, delivered the way a server delivers one.

        The text arrives in pieces that concatenate back to it exactly, and the
        completion itself arrives at the end, so a test cannot pass because the
        fake was tidier than a real stream.
        """

        completion = await self.invoke(messages, tools, response_format)
        for start in range(0, len(completion.text), 8):
            yield TextDelta(completion.text[start : start + 8])
        yield CompletionDone(completion)


def says(text: str, input_tokens: int | None = None) -> Completion:
    return Completion(
        text=text, usage=Usage(input_tokens=input_tokens), finish_reason="stop"
    )


def calls(name: str, **arguments: Any) -> Completion:
    return Completion(
        text="",
        tool_calls=(ToolCall(id=f"call_{name}", name=name, arguments=arguments),),
        finish_reason="tool_calls",
    )


def user(text: str) -> Message:
    return Message(role="user", content=[ContentPart(kind="text", text=text)])


def body(message: Message) -> str:
    return " ".join(part.text or "" for part in message.content)


def prompt_text(messages: Sequence[Message]) -> str:
    return "\n".join(body(message) for message in messages)
