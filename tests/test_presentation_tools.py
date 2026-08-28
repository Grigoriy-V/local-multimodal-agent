from __future__ import annotations

from pathlib import Path

from app.agent.runtime import Agent
from app.memory import SqliteStore
from app.models import Completion, ToolCall
from app.tools import Toolbox
from app.tools.presentation import presentation_tools
from tests.fakes import ScriptedBackend, says, user


def test_send_file_marks_only_the_chosen_workspace_item_outbound(tmp_path: Path) -> None:
    selected = tmp_path / "chosen.png"
    selected.write_bytes(b"png")
    tools = presentation_tools(tmp_path)

    result = tools[0].run(path="chosen.png")

    assert isinstance(result, list)
    assert result[0].outbound is False
    assert result[1].outbound is True
    assert result[1].name == "chosen.png"
    assert result[1].data == b"png"


def test_send_file_remains_confined_to_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    toolbox = Toolbox(presentation_tools(workspace))

    result = toolbox.run(
        ToolCall("send", "send_file", {"path": str(outside)})
    )

    assert (result.content[0].text or "").startswith("error:")
    assert not any(part.outbound for part in result.content)


async def test_the_agent_must_explicitly_call_send_file_to_create_an_outbound(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "chosen.png").write_bytes(b"png")
    call = ToolCall("send-1", "send_file", {"path": "chosen.png"})
    backend = ScriptedBackend(
        Completion(text="", tool_calls=(call,)),
        says("I sent the image I chose."),
    )
    agent = Agent(backend, SqliteStore(tmp_path / "memory.sqlite3"), workspace)
    try:
        produced = await agent.answer("thread", user("Show me the useful result"))
    finally:
        await agent.aclose()

    tool_result = next(message for message in produced if message.role == "tool")
    assert [part.name for part in tool_result.content if part.outbound] == ["chosen.png"]
    assert produced[-1].role == "assistant"
