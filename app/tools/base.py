"""What a tool is, and how a set of them answers the model.

A tool is a name, a JSON-schema parameter description, and a callable that
returns text. Nothing here knows about a provider or a graph.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.models import ContentPart, Message, ToolCall


class ToolError(RuntimeError):
    """The model asked for something the tool refuses or cannot do.

    Raised, not returned: the caller decides whether the model sees it.
    """


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str]

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

    def run(self, call: ToolCall) -> Message:
        """Answer one tool call with a message the model can be shown."""

        tool = self._tools.get(call.name)
        if tool is None:
            result = f"error: unknown tool {call.name!r}; available: {', '.join(self.names)}"
        else:
            try:
                result = tool.run(**call.arguments)
            except ToolError as error:
                result = f"error: {error}"
            except TypeError as error:
                result = f"error: bad arguments for {call.name}: {error}"
        return Message(
            role="tool",
            content=[ContentPart(kind="text", text=result or "(empty)")],
            tool_call_id=call.id,
        )
