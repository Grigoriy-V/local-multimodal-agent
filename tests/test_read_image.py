"""A file the model reads is shown in its own kind (2026-09-04).

A chart the model had just made was the one thing it could not look at:
`read_file` decoded the PNG as text. No model, no network.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.models import ToolCall
from app.tools import ToolExecutor, Toolbox, filesystem_tools

# The smallest valid PNG: one transparent pixel.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d"
    "4944415478da63f8ffff3f0300050001ffa4c0b5f70000000049454e44ae426082"
)


def _run(tools: Toolbox, **arguments):
    executor = ToolExecutor(tools)
    prepared = executor.pre_execute(ToolCall(id="c1", name="read_file", arguments=arguments))
    return asyncio.run(executor.execute(prepared))


def test_an_image_file_is_shown_as_a_picture(tmp_path: Path) -> None:
    (tmp_path / "chart.png").write_bytes(PNG)
    tools = Toolbox(filesystem_tools(tmp_path))

    outcome = _run(tools, path="chart.png")

    assert outcome.failure is None
    kinds = [part.kind for part in outcome.content]
    assert "image" in kinds
    image = next(part for part in outcome.content if part.kind == "image")
    assert image.media_type == "image/png" and image.data == PNG
    assert "chart.png" in outcome.content[0].text


def test_a_text_file_is_still_text(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    tools = Toolbox(filesystem_tools(tmp_path))

    outcome = _run(tools, path="notes.md")

    assert [part.kind for part in outcome.content] == ["text"]
    assert "hello" in outcome.content[0].text
