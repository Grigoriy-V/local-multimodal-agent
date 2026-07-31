"""The only interface the application uses to reach a model.

Nothing outside this package may import a provider SDK, tokenizer, or processor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ContentPart:
    """One piece of a message. Parts keep the order the user supplied."""

    kind: Literal["text", "image", "audio"]
    text: str | None = None
    data: bytes | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "text":
            if not self.text:
                raise ValueError("a text part requires text")
        elif not self.data or not self.media_type:
            raise ValueError(f"a {self.kind} part requires data and media_type")


@dataclass(frozen=True)
class Message:
    role: Role
    content: Sequence[ContentPart]
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("a message requires at least one content part")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


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
