"""Reading a saved document, one bounded slice at a time.

The document is already in the workspace — an attachment is saved there rather
than pasted into the turn — so this tool's job is to hand back a part of it with
its labels intact and to stop before it fills the context.

Two decisions are worth stating. The tool never returns a whole large document
in one call, because a tool result goes straight into the next request and a
model cannot decline what it has already been given. And it always says what it
did not show, so the model can ask for the rest instead of answering from a
fragment it thinks is the whole thing.
"""

from __future__ import annotations

from pathlib import Path

from app.documents import (
    DOCUMENT_MEDIA_TYPES,
    MAX_PAGES_PER_VIEW,
    PDF,
    DocumentError,
    Section,
    media_type_for,
    page_count,
    read_sections,
    render_pages,
)
from app.models import ContentPart
from app.tools.base import Tool, ToolError
from app.tools.filesystem import resolve_in_root

MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 12_000


def _render(name: str, sections: list[Section], start: int, budget: int) -> str:
    """Format from `start` until the budget runs out, and say where it stopped."""

    lines = [f"{name}: {len(sections)} section(s)"]
    used = 0
    shown = 0
    for index in range(start, len(sections)):
        section = sections[index]
        block = f"\n[{index + 1}. {section.label}]\n{section.text}"
        if used + len(block) > budget and shown:
            break
        lines.append(block[: budget - used] if used + len(block) > budget else block)
        used += len(block)
        shown += 1
    last = start + shown
    if last < len(sections):
        lines.append(
            f"\n... stopped after section {last} of {len(sections)}. Call read_document "
            f"again with from_section={last + 1} to continue."
        )
    return "\n".join(lines)


def read_document(root: Path, path: str, from_section: int = 1) -> str:
    target = resolve_in_root(root, path)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file")
    if target.stat().st_size > MAX_BYTES:
        raise ToolError(f"{target.name} is larger than the {MAX_BYTES // (1024 * 1024)} MB limit")
    media_type = media_type_for(target.name, None)
    if media_type is None:
        readable = ", ".join(sorted(DOCUMENT_MEDIA_TYPES.values()))
        raise ToolError(f"{target.name} is not a document this reads ({readable})")
    try:
        sections = read_sections(target.read_bytes(), media_type)
    except DocumentError as error:
        raise ToolError(str(error)) from error
    if from_section < 1 or from_section > len(sections):
        raise ToolError(
            f"from_section must be between 1 and {len(sections)} for {target.name}"
        )
    return _render(target.name, sections, from_section - 1, MAX_CHARS)


def view_pages(root: Path, path: str, page: int = 1, pages: int = 1) -> list[ContentPart]:
    """Hand the model a picture of a page, which is how a scan is read.

    Not OCR. The model is multimodal, so it looks at the page the way a person
    does; nothing here recognises characters and then claims to have read them.
    That keeps the failure honest — an illegible scan looks illegible instead of
    becoming confident nonsense.
    """

    target = resolve_in_root(root, path)
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file")
    if media_type_for(target.name, None) != PDF:
        raise ToolError(f"{target.name} is not a PDF, so there are no pages to look at")
    if target.stat().st_size > MAX_BYTES:
        raise ToolError(f"{target.name} is larger than the {MAX_BYTES // (1024 * 1024)} MB limit")
    wanted = max(1, min(int(pages), MAX_PAGES_PER_VIEW))
    data = target.read_bytes()
    try:
        total = page_count(data)
        rendered = render_pages(data, int(page), wanted)
    except DocumentError as error:
        raise ToolError(str(error)) from error

    numbers = ", ".join(str(number) for number, _ in rendered)
    last = rendered[-1][0]
    note = f"{target.name}: page(s) {numbers} of {total}, rendered as images."
    if last < total:
        note += f" Call view_pages again with page={last + 1} for what follows."
    parts: list[ContentPart] = [ContentPart(kind="text", text=note)]
    parts.extend(
        ContentPart(kind="image", data=image, media_type="image/png")
        for _, image in rendered
    )
    return parts


def document_tools(root: Path) -> list[Tool]:
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise ValueError(f"the tool root {root} is not a directory")
    readable = ", ".join(sorted(DOCUMENT_MEDIA_TYPES.values()))
    return [
        Tool(
            name="read_document",
            description=(
                f"Read a document saved in the workspace ({readable}). Returns numbered "
                "sections with their own labels — page numbers for a PDF, headings for "
                "Markdown and .docx — and says where it stopped so the rest can be asked "
                "for. A document a person sends is saved here rather than shown to you "
                "directly, so this is how you read one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Path inside the workspace, absolute or relative.",
                    },
                    "from_section": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "Which numbered section to start at. Defaults to the first."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            run=lambda path, from_section=1: read_document(resolved, path, from_section),
        ),
        Tool(
            name="view_pages",
            description=(
                "Look at pages of a PDF as images: for a scan or anything else with no "
                "text layer, whenever the layout itself is the question — a table, a "
                "diagram, a form — and whenever the person asks you to look at, open or "
                "show the document. You see the page directly, so read it rather than "
                f"saying you cannot. At most {MAX_PAGES_PER_VIEW} page(s) per call; ask "
                "again for the ones that follow."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Path to a PDF inside the workspace.",
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "The first page to look at, counting from one.",
                    },
                    "pages": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PAGES_PER_VIEW,
                        "description": "How many pages from there. Defaults to one.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            run=lambda path, page=1, pages=1: view_pages(resolved, path, page, pages),
        ),
    ]
