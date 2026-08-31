"""File tools, confined to one directory.

The root is passed in, never read from the environment by the tool itself, so a
caller cannot accidentally hand the model the whole disk. Every path the model
supplies is resolved and checked against that root before anything is opened.

The granted root is the autonomy boundary: reads, writes and edits inside it do
not ask one call at a time. Resolution and confinement still apply every time.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.tools.base import Tool, ToolError

MAX_ENTRIES = 200
MAX_CHARS = 20_000


def resolve_in_root(root: Path, path: str) -> Path:
    """Resolve a model-supplied path inside the root, or refuse it.

    Resolution happens before the check, so `..` segments, absolute paths and
    symlinks that leave the root are all refused by the same comparison.
    """

    try:
        supplied = Path(path or ".")
        candidate = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
    except (OSError, RuntimeError) as error:
        detail = getattr(error, "strerror", None) or str(error) or type(error).__name__
        raise ToolError(f"path {path!r} cannot be resolved: {detail}") from error
    if candidate != root and root not in candidate.parents:
        raise ToolError(f"path {path!r} is outside the allowed root")
    return candidate


def _list_files(root: Path, path: str = ".") -> str:
    target = resolve_in_root(root, path)
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
    target = resolve_in_root(root, path)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n... truncated at {MAX_CHARS} characters"
    return text


def _write_file(root: Path, path: str, content: str) -> str:
    target = resolve_in_root(root, path)
    if target.is_dir():
        raise ToolError(f"path {path!r} is a directory")
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    verb = "overwrote" if existed else "created"
    return f"{verb} {path} ({len(content)} characters)"


def _edit_file(root: Path, path: str, old_text: str, new_text: str) -> str:
    target = resolve_in_root(root, path)
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
            description=(
                "List files and directories inside the allowed workspace root. Accepts "
                "either an absolute path inside that root or a path relative to it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute path inside the workspace root, or a path relative to "
                            "that root. Defaults to the root."
                        ),
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            run=lambda path=".": _list_files(resolved, path),
        ),
        Tool(
            name="read_file",
            description=(
                "Read a UTF-8 text file inside the allowed workspace root. Accepts either "
                "an absolute path inside that root or a path relative to it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute path inside the workspace root, or a path relative to it."
                        ),
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
                "exists. Give `path` first and `content` last. `content` is the exact "
                "bytes of the file and nothing else: never wrap it in a markdown code "
                "fence and never add ``` before or after it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute path inside the workspace root, or a path relative to it."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "The complete new contents of the file, with no markdown "
                            "fence around them."
                        ),
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            run=lambda path, content: _write_file(resolved, path, content),
        ),
        Tool(
            name="edit_file",
            description=(
                "Replace one exact, unique text fragment in an existing UTF-8 file inside "
                "the workspace."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Absolute path inside the workspace root, or a path relative to it."
                        ),
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
        ),
    ]
