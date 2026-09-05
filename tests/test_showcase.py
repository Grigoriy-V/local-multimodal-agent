"""A stored conversation renders as a page with its media (2026-09-05).

The evidence of what the assistant does is in the database; this turns one
thread into Markdown with the picture beside it. No model, no network.
"""

from __future__ import annotations

from pathlib import Path

from app.memory import SqliteStore
from app.models import ContentPart, Message, ToolCall
from tools.showcase import render_thread

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d"
    "4944415478da63f8ffff3f0300050001ffa4c0b5f70000000049454e44ae426082"
)


def test_a_thread_renders_with_its_calls_results_and_picture(tmp_path: Path) -> None:
    messages = [
        Message(role="user", content=[ContentPart(kind="text", text="draw it and send it")]),
        Message(role="assistant", tool_calls=(ToolCall(id="c1", name="read_file", arguments={"path": "chart.png"}),)),
        Message(
            role="tool",
            tool_call_id="c1",
            content=[
                ContentPart(kind="text", text="chart.png: an image"),
                ContentPart(kind="image", data=PNG, media_type="image/png", name="chart.png"),
            ],
        ),
        Message(role="assistant", content=[ContentPart(kind="text", text="south, 45")]),
    ]
    with SqliteStore(str(tmp_path / "c.db")) as store:
        store.append("t", messages, "someone")
        stored = store.messages("t")

    page = "\n".join(render_thread("t", stored, tmp_path))

    assert "**Person:** draw it and send it" in page
    assert "`read_file`" in page and "- path: `chart.png`" in page
    assert "chart.png: an image" in page
    assert "![chart.png](t-chart-" in page
    assert "> south, 45" in page
    [picture] = tmp_path.glob("t-chart-*.png")
    assert picture.read_bytes() == PNG
