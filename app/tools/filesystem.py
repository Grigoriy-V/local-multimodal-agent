"""File tools, confined to one directory.

The root is passed in, never read from the environment by the tool itself, so a
caller cannot accidentally hand the model the whole disk. Every path the model
supplies is resolved and checked against that root before anything is opened.

Confinement is not consent: `write_file` stays inside the root and still asks
first, because overwriting a file the user cares about is inside the root too.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.base import Tool, ToolError

MAX_ENTRIES = 200
MAX_CHARS = 20_000


def _resolve(root: Path, path: str) -> Path:
    """Resolve a model-supplied path inside the root, or refuse it.

    Resolution happens before the check, so `..` segments, absolute paths and
    symlinks that leave the root are all refused by the same comparison.
    """

    candidate = (root / (path or ".")).resolve()
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


def filesystem_tools(root: Path) -> list[Tool]:
    """Build `list_files`, `read_file` and `write_file` confined to `root`."""

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
            },
            run=lambda path, content: _write_file(resolved, path, content),
            destructive=True,
        ),
    ]
