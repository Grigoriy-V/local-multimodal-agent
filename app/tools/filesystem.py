"""File tools, confined to one directory.

The root is passed in, never read from the environment by the tool itself, so a
caller cannot accidentally hand the model the whole disk. Every path the model
supplies is resolved and checked against that root before anything is opened.

Confinement is not consent: `write_file` stays inside the root and still asks
first, because overwriting a file the user cares about is inside the root too.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.tools.base import Tool, ToolError

MAX_ENTRIES = 200
MAX_CHARS = 20_000


def _resolve(root: Path, path: str) -> Path:
    """Resolve a model-supplied path inside the root, or refuse it.

    Resolution happens before the check, so `..` segments, absolute paths and
    symlinks that leave the root are all refused by the same comparison.
    """

    try:
        candidate = (root / (path or ".")).resolve()
    except (OSError, RuntimeError) as error:
        detail = getattr(error, "strerror", None) or str(error) or type(error).__name__
        raise ToolError(f"path {path!r} cannot be resolved: {detail}") from error
    if candidate != root and root not in candidate.parents:
        raise ToolError(f"path {path!r} is outside the allowed root")
    return candidate


def _list_files(root: Path, path: str = ".") -> str:
    target = _resolve(root, path)
    if not target.is_dir():
        raise ToolError(f"path {path!r} is not a directory")
    entries = sorted(
        f"{entry.name}/" if entry.is_dir() else entry.name for entry in target.iterdir()
    )
    if not entries:
        return f"{path}: empty"
    shown = entries[:MAX_ENTRIES]
    listing = "\n".join(shown)
    if len(entries) > len(shown):
        listing += f"\n... {len(entries) - len(shown)} more entries"
    return listing


def _read_file(root: Path, path: str) -> str:
    target = _resolve(root, path)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n... truncated at {MAX_CHARS} characters"
    return text


def _write_file(root: Path, path: str, content: str) -> str:
    target = _resolve(root, path)
    if target.is_dir():
        raise ToolError(f"path {path!r} is a directory")
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    verb = "overwrote" if existed else "created"
    return f"{verb} {path} ({len(content)} characters)"


def _edit_file(root: Path, path: str, old_text: str, new_text: str) -> str:
    target = _resolve(root, path)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file")
    if not old_text:
        raise ToolError("old_text cannot be empty")

    current = target.read_text(encoding="utf-8")
    matches = current.count(old_text)
    if matches != 1:
        raise ToolError(
            f"old_text must occur exactly once in {path!r}; found {matches} matches"
        )
    updated = current.replace(old_text, new_text, 1)

    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, delete=False
        ) as output:
            temporary = output.name
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return f"edited {path} (replaced 1 match; {len(updated)} characters)"


def filesystem_tools(root: Path) -> list[Tool]:
    """Build the filesystem tools confined to `root`."""

    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise ValueError(f"the tool root {root} is not a directory")

    return [
        Tool(
            name="list_files",
            description="List the files and directories at a path inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace root. Defaults to the root.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            run=lambda path=".": _list_files(resolved, path),
        ),
        Tool(
            name="read_file",
            description="Read a UTF-8 text file inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace root.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            run=lambda path: _read_file(resolved, path),
        ),
        Tool(
            name="write_file",
            description=(
                "Write a UTF-8 text file inside the workspace, replacing it if it already "
                "exists. The user is asked to approve the write before it happens."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete new contents of the file.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            run=lambda path, content: _write_file(resolved, path, content),
            destructive=True,
        ),
        Tool(
            name="edit_file",
            description=(
                "Replace one exact, unique text fragment in an existing UTF-8 file inside "
                "the workspace. The user is asked to approve the edit before it happens."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Path relative to the workspace root.",
                    },
                    "old_text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Exact text that must occur once in the file.",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text; may be empty to delete the match.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            run=lambda path, old_text, new_text: _edit_file(
                resolved, path, old_text, new_text
            ),
            destructive=True,
        ),
    ]
