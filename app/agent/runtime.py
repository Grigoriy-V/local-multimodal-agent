"""Wiring: one call builds a working agent, another answers a turn.

This is where the backend, the store, the tools and the graph meet, so that a
consumer — Chainlit today, an HTTP layer later — holds no business logic of its
own and does not know it is talking to a graph.
"""

from __future__ import annotations

import hashlib
import re
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
from app.capabilities import (
    CHAT_DELIVERY,
    Delivery,
    capability_brief,
    capability_report,
)
from app.config import AgentSettings, ModelSettings
from app.context import Context, ContextPolicy, build_prelude
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import LOCAL_USER_ID, ConversationStore, Thread, open_store
from app.models import ContentPart, Message, ModelBackend, Usage
from app.models.openai_compatible import OpenAICompatibleBackend
from app.tools import CapabilityGrant, CapabilityRegistry, Toolbox, memory_tools

# The checkpoint holds this project's own dataclasses, so LangGraph is told
# which types it is allowed to reconstruct. Nothing else may come back out.
CHECKPOINT_TYPES = [
    ("app.models.base", "Message"),
    ("app.models.base", "ContentPart"),
    ("app.models.base", "ToolCall"),
    ("app.models.base", "Usage"),
    ("app.context.window", "Context"),
    ("app.agent.task_graph", "TaskPlan"),
    ("app.agent.task_graph", "ValidationStep"),
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
        store: ConversationStore,
        workspace: Path,
        policy: ContextPolicy | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        checkpoints: str | Path | None = None,
        context_fraction: float = 0.6,
        capability_registry: CapabilityRegistry | None = None,
        capability_grant: CapabilityGrant | None = None,
        user_id: str = LOCAL_USER_ID,
        delivery: Delivery = CHAT_DELIVERY,
    ) -> None:
        self.backend = backend
        self.store = store
        self.user_id = user_id
        self.workspace = Path(workspace).resolve()
        self.policy = policy or ContextPolicy()
        self.system_prompt = system_prompt
        self.delivery = delivery
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

    def toolbox(self, thread_id: str) -> Toolbox:
        """The tools this thread's graph is compiled with.

        Exposed because the assistant's own account of what it can do has to be
        read from here rather than described, and because a person asking the
        same question deserves the same source.
        """

        return self.capability_registry.toolbox(
            self.capability_grant,
            memory_tools(self.store, self.user_id, thread_id, self.policy.retrieved_facts),
        )

    def capabilities(self, thread_id: str) -> str:
        """What this agent can see, hear, send, read and change, for a person."""

        return capability_report(
            self.toolbox(thread_id), self.delivery, self.capability_grant.root
        )

    async def _graph(self, thread_id: str) -> CompiledStateGraph:
        if thread_id not in self._graphs:
            toolbox = self.toolbox(thread_id)
            # The model is told what it actually has, every turn. Left to its own
            # account it denies abilities it has and invents tools it does not.
            prompt = f"{self.system_prompt}\n\n{capability_brief(toolbox, self.delivery)}"
            self._graphs[thread_id] = build_agent(
                self.backend,
                toolbox,
                self.store,
                self.user_id,
                replace(self.policy, max_input_tokens=await self.budget()),
                prompt,
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
        facts = (
            self.store.search(query, self.user_id, limit=self.policy.retrieved_facts)
            if query
            else []
        )
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

        self.store.append(thread_id, messages, self.user_id)

    def threads(self) -> list[Thread]:
        return self.store.threads(self.user_id)

    async def aclose(self) -> None:
        close = getattr(self.backend, "aclose", None)
        if close is not None:
            await close()
        if self._connection is not None:
            await self._connection.close()
        self.store.close()


def text_message(text: str, role: str = "user") -> Message:
    return Message(role=role, content=[ContentPart(kind="text", text=text)])


# A directory name that cannot climb, hide or collide. Identifiers that already
# look like this are used unchanged so a workspace stays readable to a human;
# anything else is hashed, because sanitizing by substitution would let two
# different people land in one directory.
SAFE_SCOPE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def user_workspace(root: str | Path, user_id: str) -> Path:
    """The directory one person's files live in.

    The workspace is the permission boundary, and a boundary shared by several
    people is not one: the conversational file tools are rooted here, so a
    single directory would let anyone read what anyone else created. Every
    caller that turns a user into an agent goes through this function.
    """

    scope = user_id if SAFE_SCOPE.match(user_id) and user_id not in {".", ".."} else ""
    if not scope:
        scope = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    return Path(root).resolve() / scope


def create_agent(
    model_settings: ModelSettings | None = None,
    agent_settings: AgentSettings | None = None,
    user_id: str = LOCAL_USER_ID,
    delivery: Delivery = CHAT_DELIVERY,
) -> Agent:
    """Build the default agent from configuration.

    `delivery` is the caller's statement of what its interface can put in front
    of a person; it is what stops the model from denying that it can send a
    picture, so an interface that renders less has to say so here.
    """

    agent_settings = agent_settings or AgentSettings()
    policy = ContextPolicy(
        keep_recent=agent_settings.keep_recent,
        summarize_after=agent_settings.summarize_after,
        retrieved_facts=agent_settings.retrieved_facts,
    )
    # Each person gets their own root inside the configured workspace. The
    # directory the agent may touch has to exist before it is resolved, or the
    # first `list_files` fails on a machine that has simply never run it.
    Path(agent_settings.workspace).mkdir(parents=True, exist_ok=True)
    workspace = user_workspace(agent_settings.workspace, user_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return Agent(
        backend=OpenAICompatibleBackend(model_settings or ModelSettings()),
        store=open_store(agent_settings),
        workspace=workspace,
        policy=policy,
        checkpoints=agent_settings.checkpoints,
        context_fraction=agent_settings.context_fraction,
        user_id=user_id,
        delivery=delivery,
    )
