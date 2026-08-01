"""The tool loop, closed offline.

A scripted backend replaces the model, so these tests answer one question: does
what the model asked for come back to it, and does the loop end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from app.agent.graph import build_agent
from app.models import Completion, ContentPart, Message, ModelBackend, ToolCall
from app.tools import Toolbox, filesystem_tools


class ScriptedBackend(ModelBackend):
    """Returns the next prepared completion and records what it was sent."""

    def __init__(self, *completions: Completion) -> None:
        self.completions = list(completions)
        self.requests: list[list[Message]] = []
        self.tools_seen: list[Any] = []

    async def invoke(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        self.requests.append(list(messages))
        self.tools_seen.append(tools)
        return self.completions.pop(0)

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        yield (await self.invoke(messages, tools, response_format)).text


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "notes.txt").write_text("the answer is 42", encoding="utf-8")
    return tmp_path


def ask(text: str) -> dict[str, list[Message]]:
    return {"messages": [Message(role="user", content=[ContentPart(kind="text", text=text)])]}


def calls(name: str, **arguments: Any) -> Completion:
    return Completion(
        text="",
        tool_calls=(ToolCall(id=f"call_{name}", name=name, arguments=arguments),),
        finish_reason="tool_calls",
    )


async def test_a_call_tool_answer_cycle_closes(workspace: Path) -> None:
    backend = ScriptedBackend(calls("read_file", path="notes.txt"), Completion(text="42"))
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    result = await agent.ainvoke(ask("What does notes.txt say?"))

    assert [message.role for message in result["messages"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result["messages"][-1].content[0].text == "42"


async def test_the_tool_result_is_what_the_second_request_carries(workspace: Path) -> None:
    backend = ScriptedBackend(calls("read_file", path="notes.txt"), Completion(text="42"))
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    await agent.ainvoke(ask("What does notes.txt say?"))

    second = backend.requests[1]
    assert second[1].tool_calls[0].name == "read_file"
    assert second[2].role == "tool"
    assert second[2].tool_call_id == "call_read_file"
    assert second[2].content[0].text == "the answer is 42"


async def test_an_answer_without_tool_calls_ends_the_graph(workspace: Path) -> None:
    backend = ScriptedBackend(Completion(text="no tool needed"))
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    result = await agent.ainvoke(ask("Say hello."))

    assert len(backend.requests) == 1
    assert [message.role for message in result["messages"]] == ["user", "assistant"]


async def test_the_loop_runs_more_than_once(workspace: Path) -> None:
    backend = ScriptedBackend(
        calls("list_files"),
        calls("read_file", path="notes.txt"),
        Completion(text="42"),
    )
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    result = await agent.ainvoke(ask("Find the answer."))

    assert len(backend.requests) == 3
    assert [message.role for message in result["messages"]].count("tool") == 2


async def test_several_calls_in_one_turn_each_get_a_result(workspace: Path) -> None:
    both = Completion(
        text="",
        tool_calls=(
            ToolCall(id="a", name="list_files", arguments={}),
            ToolCall(id="b", name="read_file", arguments={"path": "notes.txt"}),
        ),
    )
    backend = ScriptedBackend(both, Completion(text="done"))
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    result = await agent.ainvoke(ask("Look around and read."))

    tool_messages = [message for message in result["messages"] if message.role == "tool"]
    assert [message.tool_call_id for message in tool_messages] == ["a", "b"]


async def test_a_failing_tool_goes_back_to_the_model(workspace: Path) -> None:
    backend = ScriptedBackend(calls("read_file", path="../secret.txt"), Completion(text="sorry"))
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    result = await agent.ainvoke(ask("Read the secret."))

    assert result["messages"][2].content[0].text.startswith("error:")
    assert result["messages"][-1].content[0].text == "sorry"


async def test_the_tool_schemas_are_sent_on_every_request(workspace: Path) -> None:
    backend = ScriptedBackend(calls("list_files"), Completion(text="done"))
    agent = build_agent(backend, Toolbox(filesystem_tools(workspace)))

    await agent.ainvoke(ask("Look around."))

    names = [[tool["function"]["name"] for tool in seen] for seen in backend.tools_seen]
    assert names == [["list_files", "read_file"], ["list_files", "read_file"]]


async def test_an_agent_without_tools_sends_none(workspace: Path) -> None:
    backend = ScriptedBackend(Completion(text="hello"))
    agent = build_agent(backend, Toolbox())

    await agent.ainvoke(ask("Say hello."))

    assert backend.tools_seen == [None]
