"""What a tool is, and how a set of them answers the model.

A tool is a name, a JSON-schema parameter description, and a callable that
returns text. Nothing here knows about a provider or a graph.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.models import ContentPart, Message, ToolCall


class ToolError(RuntimeError):
    """The model asked for something the tool refuses or cannot do.

    Raised, not returned: the caller decides whether the model sees it.
    """


@dataclass(frozen=True)
class Tool:
    """`destructive` marks a tool that changes something outside the agent.

    The flag says nothing about how consent is obtained — that is the graph's
    business. A tool only declares that running it is not free to undo.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str | Sequence[ContentPart] | Awaitable[str | Sequence[ContentPart]]]
    destructive: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Toolbox:
    """The tools one agent may use.

    A failing tool is not a failing turn. Every error becomes a tool result the
    model can read and correct itself against, because the alternative — killing
    the run — loses the conversation over a mistyped path.
    """

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def destructive(self, name: str) -> bool:
        """Whether this call needs consent before it runs.

        An unknown name is not destructive: it never runs, it only produces the
        error that tells the model the tool does not exist.
        """

        tool = self._tools.get(name)
        return tool is not None and tool.destructive

    def validation_error(self, call: ToolCall) -> str | None:
        """Return a readable JSON-schema error without executing the tool.

        Tool schemas in this project deliberately use a small JSON-schema
        subset. Keeping the check here makes the schema shown to the model the
        same contract enforced before consent and execution.
        """

        tool = self._tools.get(call.name)
        if tool is None:
            return None
        schema = tool.parameters
        arguments = call.arguments
        if schema.get("type") == "object" and not isinstance(arguments, dict):
            return "arguments must be an object"

        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in arguments]
        if missing:
            return f"missing required argument(s): {', '.join(missing)}"

        if schema.get("additionalProperties") is False:
            unexpected = [name for name in arguments if name not in properties]
            if unexpected:
                return f"unexpected argument(s): {', '.join(unexpected)}"

        json_types = {
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
        }
        for name, value in arguments.items():
            expected = properties.get(name, {}).get("type")
            if expected in json_types and not json_types[expected](value):
                return f"argument {name!r} must be {expected}"
            minimum = properties.get(name, {}).get("minLength")
            if minimum is not None and isinstance(value, str) and len(value) < minimum:
                return f"argument {name!r} must contain at least {minimum} character(s)"
        return None

    def _prepare(self, call: ToolCall) -> tuple[Tool | None, Message | None]:
        tool = self._tools.get(call.name)
        if tool is None:
            return None, self._message(
                call, f"error: unknown tool {call.name!r}; available: {', '.join(self.names)}"
            )
        validation_error = self.validation_error(call)
        if validation_error:
            return None, self._message(
                call, f"error: bad arguments for {call.name}: {validation_error}"
            )
        return tool, None

    @staticmethod
    def _message(call: ToolCall, result: str | Sequence[ContentPart]) -> Message:
        if isinstance(result, str):
            content = [ContentPart(kind="text", text=result or "(empty)")]
        else:
            content = list(result) or [ContentPart(kind="text", text="(empty)")]
        return Message(
            role="tool",
            content=content,
            tool_call_id=call.id,
        )

    @staticmethod
    def _failure(call: ToolCall, error: Exception) -> Message:
        if isinstance(error, ToolError):
            result = f"error: {error}"
        elif isinstance(error, TypeError):
            result = f"error: bad arguments for {call.name}: {error}"
        else:
            detail = getattr(error, "strerror", None) or str(error) or type(error).__name__
            result = f"error: {call.name} failed: {detail}"
        return Toolbox._message(call, result)

    def run(self, call: ToolCall) -> Message:
        """Run a synchronous tool and return the message shown to the model."""

        tool, refused = self._prepare(call)
        if refused is not None:
            return refused
        try:
            result = tool.run(**call.arguments)  # type: ignore[union-attr]
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if close is not None:
                    close()
                raise RuntimeError(f"tool {call.name!r} is async; use Toolbox.run_async")
            return self._message(call, result)
        except (ToolError, TypeError, OSError) as error:
            return self._failure(call, error)

    async def run_async(self, call: ToolCall) -> Message:
        """Run either a synchronous or asynchronous tool."""

        tool, refused = self._prepare(call)
        if refused is not None:
            return refused
        try:
            result = tool.run(**call.arguments)  # type: ignore[union-attr]
            if inspect.isawaitable(result):
                result = await result
            return self._message(call, result)
        except (ToolError, TypeError, OSError) as error:
            return self._failure(call, error)
