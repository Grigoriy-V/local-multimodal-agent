"""Wiring: one call builds a working agent, another answers a turn.

This is where the backend, the store, the tools and the graph meet, so that a
consumer — Chainlit today, an HTTP layer later — holds no business logic of its
own and does not know it is talking to a graph.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import build_agent
from app.config import AgentSettings, ModelSettings
from app.context import ContextPolicy
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import MemoryStore
from app.models import ContentPart, Message, ModelBackend
from app.models.openai_compatible import OpenAICompatibleBackend
from app.tools import Toolbox, filesystem_tools, memory_tools


class Agent:
    """A model, a memory and a set of tools, answering one thread at a time.

    A graph is compiled per thread because `remember_fact` records which
    conversation saved a fact. Compiling is cheap; the alternative is a mutable
    "current thread" hidden inside the toolbox.
    """

    def __init__(
        self,
        backend: ModelBackend,
        store: MemoryStore,
        workspace: Path,
        policy: ContextPolicy | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.backend = backend
        self.store = store
        self.workspace = Path(workspace).resolve()
        self.policy = policy or ContextPolicy()
        self.system_prompt = system_prompt
        self._graphs: dict[str, CompiledStateGraph] = {}

    def _graph(self, thread_id: str) -> CompiledStateGraph:
        if thread_id not in self._graphs:
            toolbox = Toolbox(
                [
                    *filesystem_tools(self.workspace),
                    *memory_tools(self.store, thread_id, self.policy.retrieved_facts),
                ]
            )
            self._graphs[thread_id] = build_agent(
                self.backend, toolbox, self.store, self.policy, self.system_prompt
            )
        return self._graphs[thread_id]

    async def steps(self, thread_id: str, message: Message) -> AsyncIterator[Message]:
        """Yield each message as its node finishes, so a UI can show the work.

        The user's own message is not yielded: the caller already has it.
        """

        stream = self._graph(thread_id).astream(
            {"thread_id": thread_id, "messages": [message]}, stream_mode="updates"
        )
        async for update in stream:
            for patch in update.values():
                for produced in (patch or {}).get("messages", []):
                    yield produced

    async def answer(self, thread_id: str, message: Message) -> list[Message]:
        """Run one turn and return everything the agent produced for it."""

        return [produced async for produced in self.steps(thread_id, message)]

    def history(self, thread_id: str) -> list[Message]:
        return self.store.messages(thread_id)

    def threads(self) -> list[str]:
        return self.store.threads()

    async def aclose(self) -> None:
        close = getattr(self.backend, "aclose", None)
        if close is not None:
            await close()
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
    return Agent(
        backend=OpenAICompatibleBackend(model_settings or ModelSettings()),
        store=MemoryStore(agent_settings.database),
        workspace=Path(agent_settings.workspace),
        policy=policy,
    )
