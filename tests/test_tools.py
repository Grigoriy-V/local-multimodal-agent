"""Tools, and the boundary they are not allowed to cross.

The confinement tests are the point: a path-taking tool handed to a model is the
one place where a wrong answer becomes a wrong file read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import ToolCall
from app.tools import Tool, Toolbox, ToolError, filesystem_tools, tool_failed


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
@pytest.mark.parametrize("name", ["read_file", "write_file", "edit_file"])
def test_paths_outside_the_root_are_refused(workspace: Path, name: str, path: str) -> None:
    escapee = workspace.parent / "secret.txt"
    escapee.write_text("must not be touched", encoding="utf-8")
    arguments = {"path": path}
    if name == "write_file":
        arguments["content"] = "overwritten"
    elif name == "edit_file":
        arguments.update(old_text="inside", new_text="outside")

    with pytest.raises(ToolError, match="outside the allowed root"):
        tools(workspace)[name].run(**arguments)

    assert escapee.read_text(encoding="utf-8") == "must not be touched"


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


def test_read_file_accepts_an_absolute_path_inside_the_root(workspace: Path) -> None:
    target = workspace / "sub" / "deep.txt"

    assert tools(workspace)["read_file"].run(path=str(target.resolve())) == "deeper"


def test_list_files_accepts_the_absolute_workspace_root(workspace: Path) -> None:
    listing = tools(workspace)["list_files"].run(path=str(workspace.resolve()))

    assert listing.splitlines() == ["notes.txt", "sub/"]


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


# --- writing -----------------------------------------------------------------


def test_write_file_creates_a_file(workspace: Path) -> None:
    result = tools(workspace)["write_file"].run(path="fresh.txt", content="hello")

    assert (workspace / "fresh.txt").read_text(encoding="utf-8") == "hello"
    assert result == "created fresh.txt (5 characters)"


def test_write_file_accepts_an_absolute_path_inside_the_root(workspace: Path) -> None:
    target = workspace / "absolute.txt"

    tools(workspace)["write_file"].run(path=str(target.resolve()), content="hello")

    assert target.read_text(encoding="utf-8") == "hello"


def test_write_file_says_when_it_replaced_something(workspace: Path) -> None:
    result = tools(workspace)["write_file"].run(path="notes.txt", content="replaced")

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "replaced"
    assert result.startswith("overwrote")


def test_write_file_makes_the_directories_it_needs(workspace: Path) -> None:
    tools(workspace)["write_file"].run(path="a/b/c.txt", content="deep")

    assert (workspace / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "deep"


def test_write_file_on_a_directory_is_refused(workspace: Path) -> None:
    with pytest.raises(ToolError, match="is a directory"):
        tools(workspace)["write_file"].run(path="sub", content="x")


def test_edit_file_replaces_one_exact_match(workspace: Path) -> None:
    result = tools(workspace)["edit_file"].run(
        path="notes.txt", old_text="kept", new_text="stayed"
    )

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "stayed inside"
    assert result == "edited notes.txt (replaced 1 match; 13 characters)"


@pytest.mark.parametrize("text", ["absent", "e"])
def test_edit_file_refuses_non_unique_matches(workspace: Path, text: str) -> None:
    before = (workspace / "notes.txt").read_text(encoding="utf-8")

    with pytest.raises(ToolError, match="must occur exactly once"):
        tools(workspace)["edit_file"].run(path="notes.txt", old_text=text, new_text="x")

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == before


def test_edit_file_refuses_an_empty_match(workspace: Path) -> None:
    with pytest.raises(ToolError, match="cannot be empty"):
        tools(workspace)["edit_file"].run(path="notes.txt", old_text="", new_text="x")


def test_edit_file_on_a_missing_file_is_refused(workspace: Path) -> None:
    with pytest.raises(ToolError, match="is not a file"):
        tools(workspace)["edit_file"].run(
            path="missing.txt", old_text="old", new_text="new"
        )


def test_edit_file_leaves_the_original_when_atomic_replace_fails(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = (workspace / "notes.txt").read_text(encoding="utf-8")

    def fail_replace(source: str, destination: Path) -> None:
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr("app.tools.filesystem.os.replace", fail_replace)
    with pytest.raises(PermissionError, match="permission denied"):
        tools(workspace)["edit_file"].run(
            path="notes.txt", old_text="kept", new_text="changed"
        )

    assert (workspace / "notes.txt").read_text(encoding="utf-8") == before
    assert sorted(path.name for path in workspace.iterdir()) == ["notes.txt", "sub"]


def test_workspace_write_and_edit_are_autonomous(workspace: Path) -> None:
    box = toolbox(workspace)

    assert [name for name in box.names if box.requires_approval(name)] == []


def test_an_unknown_tool_is_not_destructive(workspace: Path) -> None:
    # It never runs, so there is nothing to ask about — it only produces the
    # error that tells the model the tool does not exist.
    assert toolbox(workspace).destructive("rm") is False


# --- the toolbox -------------------------------------------------------------


def toolbox(workspace: Path) -> Toolbox:
    return Toolbox(filesystem_tools(workspace))


def test_schemas_describe_every_tool(workspace: Path) -> None:
    schemas = toolbox(workspace).schemas()

    assert [schema["function"]["name"] for schema in schemas] == [
        "list_files",
        "read_file",
        "write_file",
        "edit_file",
    ]
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


def test_schema_rejects_wrong_types_and_unexpected_arguments(workspace: Path) -> None:
    wrong_type = ToolCall(id="a", name="read_file", arguments={"path": 3})
    extra = ToolCall(
        id="b", name="write_file", arguments={"path": "x", "content": "y", "force": True}
    )

    assert "argument 'path' must be string" in toolbox(workspace).run(wrong_type).content[0].text
    assert "unexpected argument(s): force" in toolbox(workspace).run(extra).content[0].text


def test_an_empty_result_still_produces_content(workspace: Path) -> None:
    box = Toolbox([Tool(name="quiet", description="", parameters={}, run=lambda: "")])

    message = box.run(ToolCall(id="call_1", name="quiet", arguments={}))

    assert message.content[0].text == "(empty)"


def test_an_operating_system_failure_becomes_a_readable_tool_result() -> None:
    def denied() -> str:
        raise PermissionError(13, "permission denied")

    box = Toolbox([Tool(name="blocked", description="", parameters={}, run=denied)])

    text = box.run(ToolCall(id="call_1", name="blocked", arguments={})).content[0].text

    assert text == "error: blocked failed: permission denied"


def test_a_programming_error_is_not_hidden_as_a_tool_result() -> None:
    def broken() -> str:
        raise ValueError("bug")

    box = Toolbox([Tool(name="broken", description="", parameters={}, run=broken)])

    with pytest.raises(ValueError, match="bug"):
        box.run(ToolCall(id="call_1", name="broken", arguments={}))


def test_every_way_a_call_can_fail_is_recognisable_as_a_failure() -> None:
    """Telemetry asks the toolbox whether a result went wrong, not a string.

    A tool failure is a message the model reads rather than an exception, so
    `tool_failed` is the only signal there is. If a failure path ever stops
    matching it, a failing tool starts being counted as a successful one.
    """

    def denied() -> str:
        raise PermissionError(13, "permission denied")

    def refused() -> str:
        raise ToolError("that path is outside the workspace")

    box = Toolbox(
        [
            Tool(name="blocked", description="", parameters={}, run=denied),
            Tool(name="refuses", description="", parameters={}, run=refused),
            Tool(
                name="strict",
                description="",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                run=lambda path: path,
            ),
            Tool(name="fine", description="", parameters={}, run=lambda: "all good"),
        ]
    )
    failures = [
        ToolCall(id="c1", name="blocked", arguments={}),
        ToolCall(id="c2", name="refuses", arguments={}),
        ToolCall(id="c3", name="strict", arguments={}),  # missing argument
        ToolCall(id="c4", name="absent", arguments={}),  # unknown tool
    ]

    assert all(tool_failed(box.run(call)) for call in failures)
    assert not tool_failed(box.run(ToolCall(id="c5", name="fine", arguments={})))
