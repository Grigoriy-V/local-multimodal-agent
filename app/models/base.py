"""The only interface the application uses to reach a model.

Nothing outside this package may import a provider SDK, tokenizer, or processor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


class BackendError(RuntimeError):
    """The model endpoint was reached but its answer cannot be used."""


class ContextOverflowError(BackendError):
    """The endpoint refused a request because it exceeded its context window."""


@dataclass(frozen=True)
class ContentPart:
    """One piece of a message. Parts keep the order the user supplied.

    `outbound` is an explicit application action, not a property inferred by an
    interface. Observation tools return ordinary media for the model to inspect;
    a presentation tool marks only the item the agent chose to send.
    """

    kind: Literal["text", "image", "audio", "file"]
    text: str | None = None
    data: bytes | None = None
    media_type: str | None = None
    name: str | None = None
    outbound: bool = False

    def __post_init__(self) -> None:
        if self.kind == "text":
            if not self.text:
                raise ValueError("a text part requires text")
        elif not self.data or not self.media_type:
            raise ValueError(f"a {self.kind} part requires data and media_type")
        if self.kind == "file" and not self.name:
            raise ValueError("a file part requires a name")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One turn.

    An assistant turn may carry tool calls instead of content: asking for a tool
    and saying nothing is a complete answer. A tool turn carries the result and
    the `tool_call_id` it answers.
    """

    role: Role
    content: Sequence[ContentPart] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        # Callers pass lists; a checkpoint gives lists back. Normalizing here is
        # what makes a message read out of a checkpoint equal to the one put in.
        object.__setattr__(self, "content", tuple(self.content))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if not self.content and not self.tool_calls:
            raise ValueError("a message requires content or tool calls")


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


class ModelBackend(ABC):
    """A provider-agnostic model.

    Implementations own request shaping, provider message formats, tool-schema
    translation, structured output, error translation, and retries. Call sites
    must not change when the implementation changes.
    """

    @abstractmethod
    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        """Return one complete result."""

    @abstractmethod
    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield text chunks as they arrive."""

    async def warm(self) -> bool:
        """Start the model serving, without waiting for it to be ready.

        Optional because it only means anything for a backend that can be
        asleep. A deployment that scales to zero costs several seconds on the
        first request, and those seconds are worth spending in parallel with
        whatever else has to happen before the model is called.

        Implementations must not raise: a failed warm-up is a slower turn, never
        a failed one.
        """

        return False

    async def context_limit(self) -> int | None:
        """The largest request this model accepts, in tokens, or `None` if unknown.

        Asked of the backend rather than configured, because the number belongs
        to the model that is actually running: a tokenizer, or a limit, copied
        into project configuration is one that can quietly stop being true.
        """

        return None
