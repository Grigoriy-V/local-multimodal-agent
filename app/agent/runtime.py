"""Wiring: one call builds a working agent, another answers a turn.

This is where the backend, the store, the tools and the graph meet, so that a
consumer — Chainlit today, an HTTP layer later — holds no business logic of its
own and does not know it is talking to a graph.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.graph import build_agent, latest_text
from app.config import AgentSettings, ModelSettings
from app.context import Context, ContextPolicy, build_prelude
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import MemoryStore, Thread
from app.models import ContentPart, Message, ModelBackend, Usage
from app.models.openai_compatible import OpenAICompatibleBackend
from app.tools import CapabilityGrant, CapabilityRegistry, memory_tools

# The checkpoint holds this project's own dataclasses, so LangGraph is told
# which types it is allowed to reconstruct. Nothing else may come back out.
CHECKPOINT_TYPES = [
    ("app.models.base", "Message"),
    ("app.models.base", "ContentPart"),
    ("app.models.base", "ToolCall"),
    ("app.models.base", "Usage"),
    ("app.context.window", "Context"),
    ("app.agent.task_graph", "TaskPlan"),
    ("app.agent.task_graph", "TaskGrant"),
    ("app.agent.task_graph", "ImplementationResult"),
    ("app.agent.task_graph", "CheckResult"),
    ("app.agent.task_graph", "TestReport"),
    ("app.agent.task_graph", "Evaluation"),
    ("app.agent.task_graph", "TaskOutcome"),
]


@dataclass(frozen=True)
class Fill:
    """How large the last request actually was, against what it was allowed.

    `used` is the model's own count, so images are counted the way the model
    counts them. `budget` is `None` when the model does not say how much it can
    take, in which case the size is reported and not judged.
    """

    used: int
    budget: int | None

    @property
    def fraction(self) -> float | None:
        return self.used / self.budget if self.budget else None


class Agent:
    """A model, a memory and a set of tools, answering one thread at a time.

    A graph is compiled per thread because `remember_fact` records which
    conversation saved a fact. Compiling is cheap; the alternative is a mutable
    "current thread" hidden inside the toolbox.

    Checkpoints live in their own file. The conversation is in the store and is
    the durable record; a checkpoint is the state of a turn still in flight, in
    LangGraph's schema, and deleting the file loses nothing but the ability to
    finish an interrupted turn.
    """

    def __init__(
        self,
        backend: ModelBackend,
        store: MemoryStore,
        workspace: Path,
        policy: ContextPolicy | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        checkpoints: str | Path | None = None,
        context_fraction: float = 0.6,
        capability_registry: CapabilityRegistry | None = None,
        capability_grant: CapabilityGrant | None = None,
    ) -> None:
        self.backend = backend
        self.store = store
        self.workspace = Path(workspace).resolve()
        self.policy = policy or ContextPolicy()
        self.system_prompt = system_prompt
        self.checkpoints = checkpoints
        self.context_fraction = context_fraction
        self.capability_registry = capability_registry or CapabilityRegistry(self.workspace)
        self.capability_grant = capability_grant or self.capability_registry.grant()
        self._graphs: dict[str, CompiledStateGraph] = {}
        self._connection: aiosqlite.Connection | None = None
        self._saver: AsyncSqliteSaver | None = None
        self._limit: int | None = None
        self._asked_the_limit = False
        self._usage = Usage()

    async def budget(self) -> int | None:
        """How many tokens a request may take, or `None` if the model is silent.

        Asked once. The model behind an agent does not change while it runs, and
        a limit that arrived late would not match the graphs already compiled
        with the earlier one.
        """

        if not self._asked_the_limit:
            self._limit = await self.backend.context_limit()
            self._asked_the_limit = True
        return int(self._limit * self.context_fraction) if self._limit else None

    async def fill(self) -> Fill | None:
        """How full the last request was, or `None` before there was one."""

        used = self._usage.input_tokens
        return None if used is None else Fill(used=used, budget=await self.budget())

    async def _checkpointer(self) -> AsyncSqliteSaver | None:
        """Open the checkpoint file on first use.

        Lazily, because building an agent is synchronous and opening the file is
        not; and because an agent that never runs a turn should not create one.
        """

        if self.checkpoints is None:
            return None
        if self._saver is None:
            path = Path(self.checkpoints)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(str(path))
            serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
            self._saver = AsyncSqliteSaver(self._connection, serde=serde)
            await self._saver.setup()
        return self._saver

    async def _graph(self, thread_id: str) -> CompiledStateGraph:
        if thread_id not in self._graphs:
            toolbox = self.capability_registry.toolbox(
                self.capability_grant,
                memory_tools(self.store, thread_id, self.policy.retrieved_facts),
            )
            self._graphs[thread_id] = build_agent(
                self.backend,
                toolbox,
                self.store,
                replace(self.policy, max_input_tokens=await self.budget()),
                self.system_prompt,
                await self._checkpointer(),
            )
        return self._graphs[thread_id]

    async def _run(self, thread_id: str, command: Any) -> AsyncIterator[Message]:
        """Drive the graph and yield only what the conversation gained.

        An interrupt arrives here as a patch that is not a node's messages; the
        caller learns about it from `pending`, which keeps this an iterator of
        messages rather than of two different things.
        """

        graph = await self._graph(thread_id)
        config = {"configurable": {"thread_id": thread_id}}
        async for update in graph.astream(command, config=config, stream_mode="updates"):
            for node, patch in update.items():
                if node.startswith("__") or not isinstance(patch, dict):
                    continue
                usage = patch.get("usage")
                if usage is not None:
                    self._usage = usage
                for produced in patch.get("messages") or []:
                    yield produced

    async def steps(self, thread_id: str, message: Message) -> AsyncIterator[Message]:
        """Yield each message as its node finishes, so a UI can show the work.

        The user's own message is not yielded: the caller already has it.
        """

        async for produced in self._run(thread_id, {"thread_id": thread_id, "messages": [message]}):
            yield produced

    def context_prompt(
        self,
        thread_id: str,
        messages: Sequence[Message],
        system_prompt: str | None = None,
    ) -> list[Message]:
        """Assemble the same bounded conversation layers for an internal decision."""

        summary, through = self.store.summary(thread_id)
        history = self.store.messages(thread_id, after=through - 1)
        query = latest_text(list(messages))
        facts = self.store.search(query, limit=self.policy.retrieved_facts) if query else []
        context = Context(
            prelude=build_prelude(summary, facts, system_prompt or self.system_prompt),
            history=history,
        )
        return context.prompt(messages)

    async def pending(self, thread_id: str) -> list[dict[str, Any]] | None:
        """The calls this thread is waiting on an answer for, if any.

        Survives a restart, which is the point: the question is in the
        checkpoint, not in the process that asked it.
        """

        graph = await self._graph(thread_id)
        state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        for task in state.tasks:
            for stop in task.interrupts:
                return list(stop.value)
        return None

    async def resume(self, thread_id: str, answers: dict[str, bool]) -> AsyncIterator[Message]:
        """Answer the pending question — call id to approved — and carry on."""

        async for produced in self._run(thread_id, Command(resume=answers)):
            yield produced

    async def answer(self, thread_id: str, message: Message) -> list[Message]:
        """Run one turn and return everything the agent produced for it.

        A turn that stops to ask a question ends here; the caller answers with
        `pending` and `resume`.
        """

        return [produced async for produced in self.steps(thread_id, message)]

    def history(self, thread_id: str) -> list[Message]:
        return self.store.messages(thread_id)

    def record(self, thread_id: str, messages: list[Message]) -> None:
        """Persist UI-native work that did not pass through the chat graph."""

        self.store.append(thread_id, messages)

    def threads(self) -> list[Thread]:
        return self.store.threads()

    async def aclose(self) -> None:
        close = getattr(self.backend, "aclose", None)
        if close is not None:
            await close()
        if self._connection is not None:
            await self._connection.close()
        self.store.close()


def text_message(text: str, role: str = "user") -> Message:
    return Message(role=role, content=[ContentPart(kind="text", text=text)])


def create_agent(
    model_settings: ModelSettings | None = None,
    agent_settings: AgentSettings | None = None,
) -> Agent:
    """Build the default agent from configuration."""

    agent_settings = agent_settings or AgentSettings()
    policy = ContextPolicy(
        keep_recent=agent_settings.keep_recent,
        summarize_after=agent_settings.summarize_after,
        retrieved_facts=agent_settings.retrieved_facts,
    )
    workspace = Path(agent_settings.workspace)
    # The one directory the agent may touch has to exist before it is resolved,
    # or the first `list_files` fails on a machine that has simply never run it.
    workspace.mkdir(parents=True, exist_ok=True)
    return Agent(
        backend=OpenAICompatibleBackend(model_settings or ModelSettings()),
        store=MemoryStore(agent_settings.database),
        workspace=workspace,
        policy=policy,
        checkpoints=agent_settings.checkpoints,
        context_fraction=agent_settings.context_fraction,
    )
