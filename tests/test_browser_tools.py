"""The browser capability returns real multimodal evidence, not a verdict."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.runtime import Agent
from app.memory import SqliteStore
from app.models import ContentPart, ToolCall
from app.tools import (
    BROWSER_INSPECT,
    Capability,
    CapabilityRegistry,
    Tool,
    Toolbox,
    browser_tools,
    find_chromium_browser,
    inspect_local_page,
)
from tests.fakes import ScriptedBackend, calls, says, user


async def test_browser_tool_returns_text_and_screenshot_to_the_model(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<title>Page</title><p>Hello</p>", encoding="utf-8")
    seen: list[tuple[Path, str]] = []

    async def inspect(root: Path, path: str, _browser: Path | None):
        seen.append((root, path))
        return [
            ContentPart(kind="text", text='{"title": "Page"}'),
            ContentPart(kind="image", data=b"png", media_type="image/png"),
        ]

    box = Toolbox(browser_tools(tmp_path, inspector=inspect))
    result = await box.run_async(ToolCall("browser", "inspect_page", {"path": str(page)}))

    assert seen == [(tmp_path.resolve(), str(page))]
    assert [part.kind for part in result.content] == ["text", "image"]
    assert result.content[1].data == b"png"


async def test_browser_tool_refuses_a_path_outside_its_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")

    result = await Toolbox(browser_tools(root)).run_async(
        ToolCall("browser", "inspect_page", {"path": str(outside)})
    )

    assert result.content[0].text is not None
    assert "outside the allowed root" in result.content[0].text


async def test_browser_screenshot_reaches_the_next_model_call(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def inspect_page(path: str):
        assert path == "page.html"
        return [
            ContentPart(kind="text", text="page loaded"),
            ContentPart(kind="image", data=b"screenshot", media_type="image/png"),
        ]

    registry = CapabilityRegistry(
        workspace,
        (Capability(BROWSER_INSPECT, lambda _root: [Tool(
            name="inspect_page",
            description="inspect",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            run=inspect_page,
        )]),),
    )
    backend = ScriptedBackend(calls("inspect_page", path="page.html"), says("Looks good."))
    agent = Agent(
        backend,
        SqliteStore(tmp_path / "memory.sqlite3"),
        workspace,
        capability_registry=registry,
        capability_grant=registry.grant(capabilities=(BROWSER_INSPECT,)),
    )

    await agent.answer("thread", user("Inspect page.html"))

    tool_result = backend.requests[1][-1]
    assert tool_result.role == "tool"
    assert [part.kind for part in tool_result.content] == ["text", "image"]
    assert tool_result.content[1].data == b"screenshot"
    await agent.aclose()


@pytest.mark.skipif(find_chromium_browser() is None, reason="Chrome/Edge is unavailable")
async def test_real_browser_inspects_a_general_local_page(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text(
        "<title>Capability check</title><main><button>Continue</button></main>",
        encoding="utf-8",
    )

    result = await inspect_local_page(tmp_path, str(page))

    assert [part.kind for part in result] == ["text", "image"]
    assert '"title": "Capability check"' in (result[0].text or "")
    assert '"buttons": 1' in (result[0].text or "")
    assert result[1].data is not None and len(result[1].data) > 1_000
    assert list((tmp_path / ".agent" / "browser").glob("page-*.png"))
