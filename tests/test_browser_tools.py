"""The browser capability returns real multimodal evidence, not a verdict."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agent.runtime import Agent
from app.tools.browser import container_flags
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
    assert "title: Capability check" in (result[0].text or "")
    assert 'button "Continue" [ref=e1]' in (result[0].text or "")
    assert "console errors:\nnone" in (result[0].text or "")
    assert result[1].data is not None and len(result[1].data) > 1_000
    assert list((tmp_path / ".agent" / "browser").glob("page-*.png"))


def test_a_desktop_browser_keeps_its_own_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--no-sandbox` is what a container needs, not what a laptop should get.

    It is the only real isolation the browser has. Handing it away everywhere so
    that one environment works would make the deployed concession the default.
    """

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)

    assert container_flags() == []


def test_a_container_browser_gets_the_flags_it_cannot_start_without(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chromium as root refuses its sandbox, and 64 MB of /dev/shm crashes it.

    Both are facts about the machine, so they are read from the machine rather
    than from a setting that has to be remembered when a profile changes.
    """

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)

    assert container_flags() == ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]


def test_windows_is_never_treated_as_a_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")

    assert container_flags() == []
