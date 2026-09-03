"""A general, sandboxed browser capability for local HTML artifacts.

The model chooses this tool like any other capability. It is not a verifier and
contains no task-specific acceptance logic: it returns page evidence — the
structure with refs, the visible text, console errors and a screenshot — for
the model to judge.

The page is driven through `BrowserSession` in `chromium.py`, the one API every
browser capability uses. What is decided here is what this page is allowed to
be: a local file, opened as a document in an offline session, with every network
scheme blocked. Only observation is exposed in this version; the session
already carries the actions, and a tool that exposes one later changes nothing
here.
"""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from app.models import ContentPart
from app.tools.base import Tool, ToolError
from app.tools.chromium import (
    LOAD_FAILED,
    MAX_SNAPSHOT_CHARS,
    MAX_VISIBLE_TEXT,
    REFUSED,
    STALE_REF,
    UNAVAILABLE,
    BrowserError,
    BrowserSession,
    container_flags,
    find_chromium_browser,
    open_browser,
)
from app.tools.documents import UNSUPPORTED
from app.tools.filesystem import NOT_A_FILE, NOT_FOUND, TOO_LARGE, resolve_in_root

MAX_HTML_BYTES = 2 * 1024 * 1024

__all__ = [
    "LOAD_FAILED",
    "MAX_HTML_BYTES",
    "MAX_SNAPSHOT_CHARS",
    "MAX_VISIBLE_TEXT",
    "REFUSED",
    "STALE_REF",
    "UNAVAILABLE",
    "browser_tools",
    "container_flags",
    "find_chromium_browser",
    "inspect_local_page",
    "page_report",
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


def _local_document(root: Path, path: str) -> Path:
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
    return target


def page_report(
    *,
    title: str,
    browser: str,
    structure: str,
    truncated: bool,
    text: str,
    console_errors: list[str],
    screenshot: str,
) -> str:
    """What the model reads about a page, as text it can quote from.

    Sections, not JSON: the structure and the visible text are multi-line, and
    a JSON string of them is one long escaped line the model has to unpick.
    """

    errors = "\n".join(f"- {line}" for line in console_errors) if console_errors else "none"
    cut = " (cut; the page has more)" if truncated else ""
    return (
        f"title: {title or '(none)'}\n"
        f"browser: {browser}\n"
        f"network: external network and file URLs blocked\n"
        f"screenshot: {screenshot}\n"
        f"\nconsole errors:\n{errors}\n"
        f"\nstructure{cut}; an interactive element carries a ref:\n{structure or '(empty page)'}\n"
        f"\nvisible text:\n{text or '(none)'}\n"
    )


async def observe(session: BrowserSession, artifact: Path) -> tuple[str, bytes]:
    """Everything a look at the page yields: the report text and the PNG.

    Kept apart from opening so a later tool that acts on the page and then
    looks again reports the same way.
    """

    snapshot = await session.snapshot(MAX_SNAPSHOT_CHARS)
    text = await session.visible_text(MAX_VISIBLE_TEXT)
    title = await session.title()
    image = await asyncio.to_thread(write_png, artifact, await session.screenshot())
    # One more evaluation drains console events that arrived after the last
    # call, which is where a script's late error would otherwise hide.
    await session.evaluate("0")
    return (
        page_report(
            title=title,
            browser=session.browser_name,
            structure=snapshot.text,
            truncated=snapshot.truncated,
            text=text,
            console_errors=session.console(),
            screenshot=artifact.as_posix(),
        ),
        image,
    )


async def inspect_local_page(
    root: Path, path: str, browser: Path | None = None
) -> list[ContentPart]:
    """Open one self-contained local HTML file and return multimodal evidence."""

    target = _local_document(root, path)
    artifact = root / ".agent" / "browser" / f"{target.stem}-{secrets.token_hex(4)}.png"
    try:
        async with open_browser(browser, offline=True) as session:
            await session.open(document=target.read_text(encoding="utf-8", errors="replace"))
            report, image = await observe(session, artifact)
    except BrowserError as error:
        raise ToolError(str(error), code=error.code, detail=error.detail) from error
    report = report.replace(artifact.as_posix(), artifact.relative_to(root).as_posix(), 1)
    return [
        ContentPart(kind="text", text=report),
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
                "real browser. Returns the page structure with a ref on every interactive "
                "element, the visible text, console errors and a screenshot for visual "
                "inspection. External network and file URLs are blocked; use view_web_page "
                "for a page on the internet."
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
