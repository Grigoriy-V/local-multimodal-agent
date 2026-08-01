"""The minimal agent: ask the model, run what it asked for, ask again.

Two nodes and one conditional edge. The state holds the project's own `Message`
objects — a framework's message classes are not adopted as the domain language,
so multimodal content stays in a format this repository controls.

Nothing here knows which model answers or where the tools read from; both are
constructor arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from operator import add
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.models import Completion, ContentPart, Message, ModelBackend
from app.tools import Toolbox


@dataclass
class AgentState:
    """Everything the graph carries. Nodes append; nothing rewrites history."""

    messages: Annotated[list[Message], add] = field(default_factory=list)


def assistant_message(completion: Completion) -> Message:
    """Turn a completion into the assistant turn that produced it.

    A turn that only calls tools has no content, which is why `Message` accepts
    tool calls in place of content.
    """

    parts = [ContentPart(kind="text", text=completion.text)] if completion.text else []
    return Message(role="assistant", content=parts, tool_calls=completion.tool_calls)


def build_agent(backend: ModelBackend, toolbox: Toolbox) -> CompiledStateGraph:
    """Compile the graph. The loop's only exit is an answer without tool calls.

    Runaway loops are bounded by LangGraph's own recursion limit rather than by
    a counter here.
    """

    schemas = toolbox.schemas() or None

    async def call_model(state: AgentState) -> dict[str, list[Message]]:
        completion = await backend.invoke(state.messages, tools=schemas)
        return {"messages": [assistant_message(completion)]}

    async def run_tools(state: AgentState) -> dict[str, list[Message]]:
        return {"messages": [toolbox.run(call) for call in state.messages[-1].tool_calls]}

    def has_tool_calls(state: AgentState) -> str:
        return "tools" if state.messages[-1].tool_calls else END

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_node("tools", run_tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", has_tool_calls, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile()
