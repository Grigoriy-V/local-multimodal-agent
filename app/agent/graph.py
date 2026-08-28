"""The agent: load context, ask the model, run tools, persist.

Four nodes and one conditional edge. The state holds the project's own `Message`
objects — a framework's message classes are not adopted as the domain language,
so multimodal content stays in a format this repository controls.

Nothing here knows which model answers, where the tools read from, or where the
conversation is stored; all three are arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.context import Context, ContextPolicy, fold_older_messages, load_turn_context
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import ConversationStore
from app.models import (
    Completion,
    ContentPart,
    ContextOverflowError,
    Message,
    ModelBackend,
    ToolCall,
    Usage,
)
from app.tools import Toolbox


def extend(current: list[Message], incoming: list[Message]) -> list[Message]:
    """Append, except that a user message starts a new turn.

    With a checkpointer the state outlives the turn, so something has to mark
    where one ends, or the next turn would inherit the last one's messages and
    store and send them twice. A user message is that mark: no node produces
    one, so it can only be the beginning of a turn.
    """

    if incoming and incoming[0].role == "user":
        return list(incoming)
    return [*current, *incoming]


@dataclass
class AgentState:
    """One turn.

    `messages` are the turn's own messages and the only ones ever stored;
    `context` is assembled per turn and deliberately not persisted. `usage` is
    what the model reported for the last request of the turn, which is how the
    request's real size reaches both the fold and the user interface.
    """

    thread_id: str = "default"
    messages: Annotated[list[Message], extend] = field(default_factory=list)
    context: Context = field(default_factory=Context)
    usage: Usage = field(default_factory=Usage)


def assistant_message(completion: Completion) -> Message:
    """Turn a completion into the assistant turn that produced it.

    A turn that only calls tools has no content, which is why `Message` accepts
    tool calls in place of content.
    """

    parts = [ContentPart(kind="text", text=completion.text)] if completion.text else []
    return Message(role="assistant", content=parts, tool_calls=completion.tool_calls)


def describe_call(call: ToolCall) -> dict[str, Any]:
    """What the user is shown when asked to approve a call."""

    return {"id": call.id, "name": call.name, "arguments": call.arguments}


def declined(call: ToolCall) -> Message:
    """A refusal, phrased as a tool result so the model can react to it.

    The model is told not to retry, because a second identical request would be
    a second question to a user who has already said no.
    """

    return Message(
        role="tool",
        content=[
            ContentPart(
                kind="text",
                text=f"error: the user declined the call to {call.name}; do not try it again",
            )
        ],
        tool_call_id=call.id,
    )


def context_refusal() -> Message:
    """A completed assistant turn when even one bounded recovery cannot fit."""

    return Message(
        role="assistant",
        content=[
            ContentPart(
                kind="text",
                text=(
                    "I cannot process this request because it is too large for the model's "
                    "context window. Shorten it or start a new conversation."
                ),
            )
        ],
    )


def latest_text(messages: list[Message]) -> str:
    """The newest user text, which is what memory retrieval searches on."""

    for message in reversed(messages):
        if message.role == "user":
            return " ".join(part.text or "" for part in message.content).strip()
    return ""


def build_agent(
    backend: ModelBackend,
    toolbox: Toolbox,
    store: ConversationStore,
    user_id: str,
    policy: ContextPolicy | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the graph. The loop's only exit is an answer without tool calls.

    Runaway loops are bounded by LangGraph's own recursion limit rather than by
    a counter here.

    With a `checkpointer`, a turn that stops to ask a question — or dies — can be
    resumed from where it stopped. Without one the graph still runs; it just
    cannot stop and come back, so a destructive call has nowhere to wait and is
    refused rather than run unasked.
    """

    policy = policy or ContextPolicy()
    schemas = toolbox.schemas() or None

    def assemble_context(state: AgentState) -> Context:
        query = latest_text(state.messages)
        return load_turn_context(
            store,
            state.thread_id,
            user_id,
            query,
            policy.retrieved_facts,
            system_prompt,
        )

    def load(state: AgentState) -> dict[str, Context]:
        return {"context": assemble_context(state)}

    async def call_model(state: AgentState) -> dict[str, Any]:
        try:
            completion = await backend.invoke(state.context.prompt(state.messages), tools=schemas)
        except ContextOverflowError:
            try:
                folded = await fold_older_messages(
                    backend, store, state.thread_id, policy, force=True
                )
            except ContextOverflowError:
                folded = None
            if folded is None:
                return {"messages": [context_refusal()], "usage": Usage()}

            recovered = assemble_context(state)
            try:
                completion = await backend.invoke(
                    recovered.prompt(state.messages), tools=schemas
                )
            except ContextOverflowError:
                return {
                    "context": recovered,
                    "messages": [context_refusal()],
                    "usage": Usage(),
                }
            return {
                "context": recovered,
                "messages": [assistant_message(completion)],
                "usage": completion.usage,
            }
        return {"messages": [assistant_message(completion)], "usage": completion.usage}

    async def run_tools(state: AgentState) -> dict[str, list[Message]]:
        calls = state.messages[-1].tool_calls
        # Invalid calls go straight back to the model as tool errors. Asking a
        # user to approve a call that cannot run is both noisy and misleading.
        risky = [
            call
            for call in calls
            if toolbox.destructive(call.name) and toolbox.validation_error(call) is None
        ]
        allowed = dict.fromkeys((call.id for call in calls), True)
        if risky and checkpointer is None:
            allowed.update(dict.fromkeys((call.id for call in risky), False))
        elif risky:
            # One question for the whole batch, asked before any tool has run:
            # resuming restarts this node from the top, and a tool that ran
            # before the pause would run a second time.
            answers = interrupt([describe_call(call) for call in risky])
            allowed.update({call.id: bool(answers.get(call.id)) for call in risky})
        messages = []
        for call in calls:
            messages.append(
                await toolbox.run_async(call) if allowed[call.id] else declined(call)
            )
        return {"messages": messages}

    async def persist(state: AgentState) -> None:
        store.append(state.thread_id, state.messages, user_id)
        await fold_older_messages(
            backend, store, state.thread_id, policy, state.usage.input_tokens
        )

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
    return graph.compile(checkpointer=checkpointer)
