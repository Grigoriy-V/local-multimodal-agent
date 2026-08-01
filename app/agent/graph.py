"""The agent: load context, ask the model, run tools, persist.

Four nodes and one conditional edge. The state holds the project's own `Message`
objects — a framework's message classes are not adopted as the domain language,
so multimodal content stays in a format this repository controls.

Nothing here knows which model answers, where the tools read from, or where the
conversation is stored; all three are arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from operator import add
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.context import Context, ContextPolicy, build_prelude, fold_older_messages
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import MemoryStore
from app.models import Completion, ContentPart, Message, ModelBackend
from app.tools import Toolbox


@dataclass
class AgentState:
    """One turn.

    `messages` are the turn's own messages and the only ones ever stored;
    `context` is assembled per turn and deliberately not persisted.
    """

    thread_id: str = "default"
    messages: Annotated[list[Message], add] = field(default_factory=list)
    context: Context = field(default_factory=Context)


def assistant_message(completion: Completion) -> Message:
    """Turn a completion into the assistant turn that produced it.

    A turn that only calls tools has no content, which is why `Message` accepts
    tool calls in place of content.
    """

    parts = [ContentPart(kind="text", text=completion.text)] if completion.text else []
    return Message(role="assistant", content=parts, tool_calls=completion.tool_calls)


def latest_text(messages: list[Message]) -> str:
    """The newest user text, which is what memory retrieval searches on."""

    for message in reversed(messages):
        if message.role == "user":
            return " ".join(part.text or "" for part in message.content).strip()
    return ""


def build_agent(
    backend: ModelBackend,
    toolbox: Toolbox,
    store: MemoryStore,
    policy: ContextPolicy | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> CompiledStateGraph:
    """Compile the graph. The loop's only exit is an answer without tool calls.

    Runaway loops are bounded by LangGraph's own recursion limit rather than by
    a counter here.
    """

    policy = policy or ContextPolicy()
    schemas = toolbox.schemas() or None

    def load(state: AgentState) -> dict[str, Context]:
        summary, through = store.summary(state.thread_id)
        history = store.messages(state.thread_id, after=through - 1)
        query = latest_text(state.messages)
        facts = store.search(query, limit=policy.retrieved_facts) if query else []
        return {
            "context": Context(
                prelude=build_prelude(summary, facts, system_prompt),
                history=history,
            )
        }

    async def call_model(state: AgentState) -> dict[str, list[Message]]:
        completion = await backend.invoke(state.context.prompt(state.messages), tools=schemas)
        return {"messages": [assistant_message(completion)]}

    async def run_tools(state: AgentState) -> dict[str, list[Message]]:
        return {"messages": [toolbox.run(call) for call in state.messages[-1].tool_calls]}

    async def persist(state: AgentState) -> None:
        store.append(state.thread_id, state.messages)
        await fold_older_messages(backend, store, state.thread_id, policy)

    def has_tool_calls(state: AgentState) -> str:
        return "tools" if state.messages[-1].tool_calls else "persist"

    graph = StateGraph(AgentState)
    graph.add_node("load", load)
    graph.add_node("model", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("persist", persist)
    graph.add_edge(START, "load")
    graph.add_edge("load", "model")
    graph.add_conditional_edges("model", has_tool_calls, {"tools": "tools", "persist": "persist"})
    graph.add_edge("tools", "model")
    graph.add_edge("persist", END)
    return graph.compile()
