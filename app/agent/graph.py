"""The agent: load context, ask the model, run tools, persist.

Four nodes and two conditional edges — one asking whether the model wants a
tool, one asking whether the turn is still allowed to run. The state holds the
project's own `Message` objects — a framework's message classes are not adopted as the domain language,
so multimodal content stays in a format this repository controls.

Nothing here knows which model answers, where the tools read from, or where the
conversation is stored; all three are arguments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter, interrupt

from app.agent.stop import NO_STOPS, StopRequests
from app.context import Context, ContextPolicy, fold_older_messages, load_turn_context
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import ConversationStore
from app.models import (
    BackendError,
    Completion,
    ContentPart,
    ContextOverflowError,
    Message,
    ModelBackend,
    TextDelta,
    ToolCall,
    Usage,
)
from app.telemetry import NO_TRACE, Telemetry, TurnTrace
from app.tools import ToolExecutor, Toolbox

# The key a text delta travels under on LangGraph's custom stream channel. The
# channel carries anything, so the runtime and the graph have to agree on one
# name; nothing else in this project writes to it.
ASSISTANT_DELTA = "assistant_delta"

# The turn identity travels beside `thread_id` in LangGraph's own configurable
# dictionary. A string, never the recorder itself: this value is carried in
# checkpoint metadata and log lines, and neither may hold a live object.
RUN_ID = "run_id"


def run_id_of(config: RunnableConfig | None) -> str | None:
    if not config:
        return None
    return (config.get("configurable") or {}).get(RUN_ID)


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


@dataclass(frozen=True)
class TurnBudget:
    """What one turn may spend before it has to stop and say so.

    The loop's only other bound is LangGraph's recursion limit, which is a
    guard against a graph that cannot terminate rather than a ceiling on what
    an autonomous turn costs. This is the ceiling: a model that keeps finding
    one more thing to check spends a GPU at roughly $0.0003 a second, and
    nothing else stands between it and the bill.

    Time is accumulated by the nodes rather than measured from the turn's
    start, so a turn that waited an hour for someone to approve a call is not
    over budget the moment they answer.

    Every limit bounds the *work*: when one is crossed no further tool runs,
    and the model is asked once more, without tools, for the answer the person
    is owed. So a ceiling of N steps costs at most N + 1 model calls.
    """

    max_steps: int = 12
    max_tool_calls: int = 24
    max_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if self.max_tool_calls < 0:
            raise ValueError("max_tool_calls cannot be negative")
        if self.max_seconds <= 0:
            raise ValueError("max_seconds must be positive")


# Why a turn stopped short of the model deciding it was finished. Empty is the
# ordinary case: nothing stopped it.
BUDGET_EXHAUSTED = "budget"
STOP_REQUESTED = "stopped"


@dataclass
class AgentState:
    """One turn.

    `messages` are the turn's own messages and the only ones ever stored;
    `context` is assembled per turn and deliberately not persisted. `usage` is
    what the model reported for the last request of the turn, which is how the
    request's real size reaches both the fold and the user interface.

    The counters are the turn's own spend, and `sequence` is the number the
    request arrived with — what a stop is compared against. All of them are
    reset by the caller when a turn begins, because with a checkpointer this
    state outlives the turn and an inherited counter would exhaust the next
    turn's budget before it ran.
    """

    thread_id: str = "default"
    messages: Annotated[list[Message], extend] = field(default_factory=list)
    context: Context = field(default_factory=Context)
    usage: Usage = field(default_factory=Usage)
    sequence: int = 0
    steps: int = 0
    tool_calls: int = 0
    spent_seconds: float = 0.0
    stopping: str = ""


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


def halted(call: ToolCall, reason: str) -> Message:
    """A call that was not run, phrased as a tool result the model can read.

    The same shape as `declined`, and for the same reason: the model asked for
    something, and the honest answer to it is a result, not silence.
    """

    return Message(
        role="tool",
        content=[ContentPart(kind="text", text=f"error: {reason}")],
        tool_call_id=call.id,
    )


BUDGET_REASON = (
    "this turn has reached the limit of what it may spend; no further tools "
    "will run, so answer now with what you already have"
)
STOP_REASON = "the user asked to stop; this call was not run"
# What the person is told when the model spent its last request asking for one
# more tool rather than answering.
BUDGET_ANSWER = (
    "I stopped here: this turn reached the limit of what it is allowed to spend."
)


def stopped_message() -> Message:
    """The completed assistant turn after a person asked for it to end.

    Written here rather than by the model: someone who asked for the work to
    stop is not asking for one more model call to tell them it stopped.
    """

    return Message(
        role="assistant",
        content=[ContentPart(kind="text", text="Stopped at your request.")],
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
    stream_answers: bool = True,
    telemetry: Telemetry | None = None,
    budget: TurnBudget | None = None,
    stops: StopRequests = NO_STOPS,
) -> CompiledStateGraph:
    """Compile the graph. This is the loop, and there is only one of it.

    A turn ends in one of four ways: the model answers without asking for a
    tool, the person asks it to stop, it reaches its budget, or the request
    cannot be made to fit. The first is the ordinary one; the other three are
    the reason this loop is allowed to be autonomous.

    With a `checkpointer`, a turn that stops to ask a question — or dies — can be
    resumed from where it stopped. Without one the graph still runs; it just
    cannot stop and come back, so a destructive call has nowhere to wait and is
    refused rather than run unasked.

    `stops` is asked at each step boundary and never at the start: a turn that
    has not run anything yet has nothing to stop, and in the deployed profile
    the question costs a round trip to the control plane.
    """

    policy = policy or ContextPolicy()
    limits = budget or TurnBudget()
    schemas = toolbox.schemas() or None

    def trace_of(config: RunnableConfig | None) -> TurnTrace:
        """The recorder for the turn this invocation belongs to, if any.

        Looked up rather than captured: the graph is compiled once per thread
        and reused, while a trace belongs to one turn.
        """

        if telemetry is None:
            return NO_TRACE
        return telemetry.trace(run_id_of(config))

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

    async def complete(
        prompt: list[Message],
        writer: StreamWriter,
        trace: TurnTrace,
        tools: list[dict[str, Any]] | None,
    ) -> Completion:
        """One model call, streamed or not, with the same result either way.

        Streaming is how the answer becomes visible while it is being written;
        it must not change what the graph does with it. The events carry the
        whole completion, so tool calls, usage and the finish reason survive the
        stream and the rest of this node cannot tell which path it took.
        """

        with trace.model("answer") as measured:
            if not stream_answers:
                # No first-token boundary exists on this path, and inventing one
                # would report a TTFT equal to the whole call.
                completion = await backend.invoke(prompt, tools=tools)
                measured.done(completion)
                return completion
            completion = None
            seen_text = False
            async for event in backend.stream(prompt, tools=tools):
                if isinstance(event, TextDelta):
                    if not seen_text:
                        seen_text = True
                        measured.first_token()
                    # Presentation only. Nothing on this channel is ever persisted.
                    writer({ASSISTANT_DELTA: event.text})
                else:
                    completion = event.completion
            if completion is None:
                raise BackendError("the model stream ended without a completion")
            measured.done(completion)
            return completion

    async def call_model(
        state: AgentState, config: RunnableConfig, writer: StreamWriter
    ) -> dict[str, Any]:
        started = time.monotonic()
        patch = await _ask(state, config, writer)
        # One step is one model call and whatever it decided to do next, which
        # is the unit a budget and a reader of the trace both care about.
        patch["steps"] = state.steps + 1
        patch["spent_seconds"] = state.spent_seconds + (time.monotonic() - started)
        return patch

    async def _ask(
        state: AgentState, config: RunnableConfig, writer: StreamWriter
    ) -> dict[str, Any]:
        trace = trace_of(config)
        trace.event(
            "loop_step",
            step=state.steps + 1,
            tool_calls=state.tool_calls,
            spent_ms=int(state.spent_seconds * 1000),
            stopping=state.stopping or None,
        )
        # A turn that has spent its budget still gets to answer, and is offered
        # no tools while it does: the alternative is to keep asking a model that
        # keeps calling tools whether it would like to stop now.
        offered = None if state.stopping == BUDGET_EXHAUSTED else schemas

        def produced(completion: Completion) -> Message:
            """What the model wrote, and only that, once the turn is ending.

            A model offered no tools can still ask for one, and a stored
            assistant message whose tool calls have no results is a history the
            next request cannot be built from.
            """

            message = assistant_message(completion)
            if offered is None and message.tool_calls:
                if not message.content:
                    # It asked for another tool instead of answering. Saying so
                    # is better than an empty bubble, and better than a lie.
                    return Message(
                        role="assistant",
                        content=[ContentPart(kind="text", text=BUDGET_ANSWER)],
                    )
                return Message(role="assistant", content=message.content)
            return message

        prepared = await fitted(state, trace)
        try:
            completion = await complete(
                prepared.prompt(state.messages), writer, trace, offered
            )
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
                completion = await complete(
                    recovered.prompt(state.messages), writer, trace, offered
                )
            except ContextOverflowError:
                return {
                    "context": recovered,
                    "messages": [context_refusal()],
                    "usage": Usage(),
                }
            return {
                "context": recovered,
                "messages": [produced(completion)],
                "usage": completion.usage,
            }
        return {
            "context": prepared,
            "messages": [produced(completion)],
            "usage": completion.usage,
        }

    async def fitted(state: AgentState, trace: TurnTrace) -> Context:
        """Fold before asking, if what is about to be sent is already too big.

        The fold used to happen in `persist`, from the size the *previous*
        request reported. That was exact and one turn late: the request that
        overshot was still sent, and with one loop able to spend many steps
        inside a single turn, "next turn" can be a long way past the point where
        the conversation stopped fitting.

        Measuring here means the oversized request is not sent at all. The cost
        is that the size is an estimate rather than a report — see
        `ModelBackend.estimate_tokens` — and the fraction of the window the
        application spends is what makes that trade safe.

        Only stored history folds. The current turn's own messages have not been
        written yet, so a turn that grew large by accumulating tool results is
        not what this shortens; shortening those is 4.6a's work, and until then
        `ContextOverflowError` remains the backstop underneath this.
        """

        if policy.max_input_tokens is None:
            return state.context
        estimated = backend.estimate_tokens(state.context.prompt(state.messages))
        if estimated <= policy.max_input_tokens:
            return state.context
        folded = await fold_older_messages(
            backend, store, state.thread_id, policy, force=True
        )
        if folded is None:
            # Nothing left to fold: the size is the current turn, not the
            # history behind it. Send it and let the overflow path answer.
            return state.context
        context = assemble_context(state)
        trace.event(
            "context_folded",
            estimated=estimated,
            budget=policy.max_input_tokens,
            now=backend.estimate_tokens(context.prompt(state.messages)),
        )
        return context

    async def asked_to_stop(state: AgentState) -> bool:
        """Whether the person has asked for this turn to end. Never raises.

        A control channel that could fail a turn would be worse than not having
        one: the turn this is protecting is the expensive half of the product.
        """

        try:
            return await stops.requested(user_id, state.sequence)
        except Exception:  # noqa: BLE001 - a stop that cannot be read is not a stop
            return False

    def exceeded(state: AgentState, incoming: int) -> str:
        """Which limit the next batch of tools would cross, if any."""

        if state.steps >= limits.max_steps:
            return "steps"
        if state.tool_calls + incoming > limits.max_tool_calls:
            return "tool_calls"
        if state.spent_seconds >= limits.max_seconds:
            return "seconds"
        return ""

    async def run_tools(
        state: AgentState, config: RunnableConfig
    ) -> dict[str, Any]:
        started = time.monotonic()
        trace = trace_of(config)
        calls = state.messages[-1].tool_calls

        # Both checks happen before anything runs, and before anyone is asked to
        # approve anything: a person who has already said stop should not then
        # be shown a consent question, and a turn out of budget should not spend
        # its last seconds waiting for an answer to one.
        if await asked_to_stop(state):
            trace.event("turn_stopped", step=state.steps, tool_calls=state.tool_calls)
            return {
                "messages": [
                    *(halted(call, STOP_REASON) for call in calls),
                    stopped_message(),
                ],
                "stopping": STOP_REQUESTED,
            }
        limit = exceeded(state, len(calls))
        if limit:
            trace.event(
                "turn_budget_exhausted",
                limit=limit,
                step=state.steps,
                tool_calls=state.tool_calls,
                spent_ms=int(state.spent_seconds * 1000),
            )
            return {
                "messages": [halted(call, BUDGET_REASON) for call in calls],
                "stopping": BUDGET_EXHAUSTED,
            }

        executor = ToolExecutor(toolbox, trace)
        prepared = [executor.pre_execute(call) for call in calls]
        # Invalid calls go straight back to the model as tool errors. Asking a
        # user to approve a call that cannot run is both noisy and misleading.
        risky = [item for item in prepared if item.approval_required]
        allowed = dict.fromkeys((call.id for call in calls), True)
        if risky and checkpointer is None:
            allowed.update(dict.fromkeys((item.call.id for item in risky), False))
        elif risky:
            # One question for the whole batch, asked before any tool has run:
            # resuming restarts this node from the top, and a tool that ran
            # before the pause would run a second time.
            trace.event("approval_requested", calls=[item.call.name for item in risky])
            answers = interrupt([describe_call(item.call) for item in risky])
            allowed.update(
                {item.call.id: bool(answers.get(item.call.id)) for item in risky}
            )
            trace.event(
                "approval_resumed",
                approved=[
                    item.call.name for item in risky if allowed[item.call.id]
                ],
            )
        messages = []
        spent = 0
        for item in prepared:
            call = item.call
            if not allowed[call.id]:
                # Never run, so never counted as a tool call the turn spent.
                trace.event("tool_failed", tool=call.name, status="declined")
                messages.append(declined(call))
                continue
            result = await executor.run(item)
            spent += 1
            messages.append(result)
        return {
            "messages": messages,
            "tool_calls": state.tool_calls + spent,
            "spent_seconds": state.spent_seconds + (time.monotonic() - started),
        }

    async def persist(state: AgentState, config: RunnableConfig) -> None:
        with trace_of(config).step("persist"):
            store.append(state.thread_id, state.messages, user_id)
            await fold_older_messages(
                backend, store, state.thread_id, policy, state.usage.input_tokens
            )

    def after_model(state: AgentState) -> str:
        if state.stopping == BUDGET_EXHAUSTED:
            # The answer written without tools is the end of the turn, whatever
            # the model asked for while writing it.
            return "persist"
        return "tools" if state.messages[-1].tool_calls else "persist"

    def after_tools(state: AgentState) -> str:
        # A turn the person stopped does not get another model call to say so.
        return "persist" if state.stopping == STOP_REQUESTED else "model"

    graph = StateGraph(AgentState)
    graph.add_node("load", load)
    graph.add_node("model", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("persist", persist)
    graph.add_edge(START, "load")
    graph.add_edge("load", "model")
    graph.add_conditional_edges("model", after_model, {"tools": "tools", "persist": "persist"})
    graph.add_conditional_edges("tools", after_tools, {"model": "model", "persist": "persist"})
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=checkpointer)
