"""Tools, and the boundary they are not allowed to cross.

The confinement tests are the point: a path-taking tool handed to a model is the
one place where a wrong answer becomes a wrong file read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import ToolCall
from app.tools import Tool, Toolbox, ToolError, filesystem_tools


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "notes.txt").write_text("kept inside", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.txt").write_text("deeper", encoding="utf-8")
    return tmp_path


def tools(root: Path) -> dict[str, Tool]:
    return {tool.name: tool for tool in filesystem_tools(root)}


# --- confinement -------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["..", "../secret.txt", "sub/../../secret.txt", "C:/Windows/win.ini", "/etc/passwd"],
)
def test_paths_outside_the_root_are_refused(workspace: Path, path: str) -> None:
    (workspace.parent / "secret.txt").write_text("must not be read", encoding="utf-8")

    with pytest.raises(ToolError, match="outside the allowed root"):
        tools(workspace)["read_file"].run(path=path)


def test_a_root_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        filesystem_tools(target)


# --- reading -----------------------------------------------------------------


def test_read_file_returns_the_text(workspace: Path) -> None:
    assert tools(workspace)["read_file"].run(path="notes.txt") == "kept inside"


def test_read_file_reaches_a_subdirectory(workspace: Path) -> None:
    assert tools(workspace)["read_file"].run(path="sub/deep.txt") == "deeper"


def test_read_file_on_a_directory_is_refused(workspace: Path) -> None:
    with pytest.raises(ToolError, match="not a file"):
        tools(workspace)["read_file"].run(path="sub")


def test_list_files_marks_directories(workspace: Path) -> None:
    listing = tools(workspace)["list_files"].run().splitlines()

    assert listing == ["notes.txt", "sub/"]


def test_list_files_defaults_to_the_root(workspace: Path) -> None:
    assert tools(workspace)["list_files"].run() == tools(workspace)["list_files"].run(path=".")


def test_list_files_on_a_file_is_refused(workspace: Path) -> None:
    with pytest.raises(ToolError, match="not a directory"):
        tools(workspace)["list_files"].run(path="notes.txt")


# --- the toolbox -------------------------------------------------------------


def toolbox(workspace: Path) -> Toolbox:
    return Toolbox(filesystem_tools(workspace))


def test_schemas_describe_every_tool(workspace: Path) -> None:
    schemas = toolbox(workspace).schemas()

    assert [schema["function"]["name"] for schema in schemas] == ["list_files", "read_file"]
    assert schemas[1]["function"]["parameters"]["required"] == ["path"]
    assert all(schema["type"] == "function" for schema in schemas)


def test_a_call_becomes_a_tool_message_carrying_its_id(workspace: Path) -> None:
    call = ToolCall(id="call_1", name="read_file", arguments={"path": "notes.txt"})

    message = toolbox(workspace).run(call)

    assert message.role == "tool"
    assert message.tool_call_id == "call_1"
    assert message.content[0].text == "kept inside"


def test_a_refused_path_reaches_the_model_instead_of_raising(workspace: Path) -> None:
    call = ToolCall(id="call_1", name="read_file", arguments={"path": "../secret.txt"})

    message = toolbox(workspace).run(call)

    assert message.content[0].text.startswith("error: path")
    assert message.tool_call_id == "call_1"


def test_an_unknown_tool_is_reported_with_the_available_names(workspace: Path) -> None:
    call = ToolCall(id="call_1", name="rm_rf", arguments={})

    text = toolbox(workspace).run(call).content[0].text

    assert "unknown tool 'rm_rf'" in text
    assert "read_file" in text


def test_wrong_arguments_are_reported_rather_than_crashing(workspace: Path) -> None:
    call = ToolCall(id="call_1", name="read_file", arguments={"filename": "notes.txt"})

    text = toolbox(workspace).run(call).content[0].text

    assert text.startswith("error: bad arguments for read_file")


def test_an_empty_result_still_produces_content(workspace: Path) -> None:
    box = Toolbox([Tool(name="quiet", description="", parameters={}, run=lambda: "")])

    message = box.run(ToolCall(id="call_1", name="quiet", arguments={}))

    assert message.content[0].text == "(empty)"
