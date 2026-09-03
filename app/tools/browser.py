"""A general, sandboxed browser capability for local HTML artifacts.

The model chooses this tool like any other capability. It is not a verifier and
contains no task-specific acceptance logic: it returns page evidence (visible
text, console errors, element counts and a screenshot) for the model to judge.

The browser process itself lives in `chromium.py`, shared with the web-viewing
capability. What is decided here is what this page is allowed to be: a local
file, loaded as data, with every network scheme blocked.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from app.models import ContentPart
from app.tools.base import Tool, ToolError
from app.tools.documents import UNSUPPORTED
from app.tools.filesystem import NOT_A_FILE, NOT_FOUND, TOO_LARGE, resolve_in_root
from app.tools.chromium import (
    MAX_VISIBLE_TEXT,
    container_flags,
    find_chromium_browser,
    open_page,
)

MAX_HTML_BYTES = 2 * 1024 * 1024

# The family's codes: no browser to open, and a page the browser could not show.
UNAVAILABLE = "browser.unavailable"
LOAD_FAILED = "browser.load_failed"

__all__ = [
    "MAX_HTML_BYTES",
    "MAX_VISIBLE_TEXT",
    "browser_tools",
    "container_flags",
    "find_chromium_browser",
    "inspect_local_page",
    "write_png",
]


def write_png(path: Path, encoded: str) -> bytes:
    """Save a base64 screenshot into the workspace without a torn file."""

    data = base64.b64decode(encoded)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return data


_PAGE_EVIDENCE = f"""
(() => ({{
  title: document.title,
  url: location.href,
  ready_state: document.readyState,
  visible_text: (document.body?.innerText || '').slice(0, {MAX_VISIBLE_TEXT}),
  links: document.querySelectorAll('a').length,
  buttons: document.querySelectorAll('button').length,
  inputs: document.querySelectorAll('input, textarea, select').length,
  images: document.querySelectorAll('img').length,
  canvases: document.querySelectorAll('canvas').length,
  viewport: {{width: innerWidth, height: innerHeight}}
}}))()
"""


async def inspect_local_page(
    root: Path, path: str, browser: Path | None = None
) -> list[ContentPart]:
    """Open one self-contained local HTML file and return multimodal evidence."""

    target = resolve_in_root(root, path)
    if not target.exists():
        raise ToolError(f"path {path!r} does not exist", code=NOT_FOUND)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file", code=NOT_A_FILE)
    if target.suffix.lower() not in {".html", ".htm"}:
        raise ToolError("inspect_page accepts only .html and .htm files", code=UNSUPPORTED)
    if target.stat().st_size > MAX_HTML_BYTES:
        raise ToolError(
            f"HTML file exceeds the {MAX_HTML_BYTES}-byte browser limit", code=TOO_LARGE
        )

    artifact = root / ".agent" / "browser" / f"{target.stem}-{secrets.token_hex(4)}.png"
    document = base64.b64encode(target.read_bytes()).decode("ascii")
    document_url = f"data:text/html;charset=utf-8;base64,{document}"

    try:
        async with open_page(browser) as (session, browser_name):
            await session.call(
                "Network.setBlockedURLs",
                {"urls": ["http://*", "https://*", "file://*", "ftp://*"]},
            )
            await session.viewport(900, 700)
            navigation = await session.call("Page.navigate", {"url": document_url})
            if navigation.get("errorText"):
                raise ToolError(
                    "the page could not be opened",
                    code=LOAD_FAILED,
                    detail=str(navigation["errorText"]),
                )
            if not await session.wait_for_load():
                raise ToolError("page did not finish loading", code=LOAD_FAILED)
            await asyncio.sleep(0.2)
            evidence: Any = await session.evaluate(_PAGE_EVIDENCE)
            image = await asyncio.to_thread(write_png, artifact, await session.screenshot())
            await session.evaluate("0")
            console_errors = list(dict.fromkeys(session.console_errors))
    except RuntimeError as error:
        # `chromium.py` raises one kind for both "no browser here" and "the
        # browser broke"; which it was is the only thing the model needs.
        code = UNAVAILABLE if "no installed" in str(error) else LOAD_FAILED
        raise ToolError(str(error), code=code) from error

    relative_artifact = artifact.relative_to(root).as_posix()
    report = {
        **(evidence if isinstance(evidence, dict) else {}),
        "browser": browser_name,
        "console_errors": console_errors,
        "screenshot": relative_artifact,
        "network_policy": "external network and file URLs blocked",
    }
    return [
        ContentPart(kind="text", text=json.dumps(report, ensure_ascii=False, indent=2)),
        ContentPart(kind="image", data=image, media_type="image/png"),
    ]


def browser_tools(
    root: Path,
    browser: Path | None = None,
    inspector: Any = inspect_local_page,
) -> list[Tool]:
    """Build the model-selected browser capability for one allowed root."""

    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise ValueError(f"the tool root {root} is not a directory")
    return [
        Tool(
            name="inspect_page",
            description=(
                "Open a self-contained local HTML file inside the allowed workspace in a "
                "real browser. Returns visible text, page structure, console errors and a "
                "screenshot for visual inspection. External network and file URLs are blocked; "
                "use view_web_page for a page on the internet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Absolute .html/.htm path inside the workspace, or a path relative "
                            "to that workspace."
                        ),
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            run=lambda path: inspector(resolved, path, browser),
        )
    ]
