"""Explicitly present a workspace file to the person.

Observation and presentation are separate actions. Reading, rendering or
inspecting a file gives evidence to the agent; only this tool marks a concrete
item as outbound. Interfaces translate that mark to their own transport.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app.attachments import MEDIA_KINDS
from app.models import ContentPart
from app.tools.base import Tool, ToolError
from app.tools.filesystem import NOT_A_FILE, NOT_FOUND, TOO_LARGE, resolve_in_root

MAX_OUTBOUND_BYTES = 50 * 1024 * 1024

# The one failure that is this family's own: there is nothing to deliver.
EMPTY = "presentation.empty"


def send_file(root: Path, path: str) -> list[ContentPart]:
    """Return one explicit outbound item selected from the granted workspace."""

    target = resolve_in_root(root, path)
    if not target.exists():
        raise ToolError(f"path {path!r} does not exist", code=NOT_FOUND)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file", code=NOT_A_FILE)
    size = target.stat().st_size
    if size == 0:
        raise ToolError(f"{target.name} is empty", code=EMPTY)
    if size > MAX_OUTBOUND_BYTES:
        raise ToolError(
            f"{target.name} is larger than the {MAX_OUTBOUND_BYTES // (1024 * 1024)} MB "
            "delivery limit",
            code=TOO_LARGE,
        )
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    kind = MEDIA_KINDS.get(media_type, "file")
    return [
        ContentPart(
            kind="text",
            text=f"Selected {target.name} for delivery to the person.",
        ),
        ContentPart(
            kind=kind,
            data=target.read_bytes(),
            media_type=media_type,
            name=target.name,
            outbound=True,
        ),
    ]


def presentation_tools(root: Path) -> list[Tool]:
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise ValueError(f"the tool root {root} is not a directory")
    return [
        Tool(
            name="send_file",
            description=(
                "Explicitly send one file from the workspace to the person after you "
                "decide it should be presented. Reading, view_pages and inspect_page "
                "only give evidence to you and never send it automatically. Use the exact "
                "workspace path returned by those tools, or another file you deliberately "
                "choose. This is a presentation action, not a way to inspect the file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Absolute or relative path inside the workspace.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            run=lambda path: send_file(resolved, path),
        )
    ]
