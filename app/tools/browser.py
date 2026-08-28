"""A general, sandboxed browser capability for local HTML artifacts.

The model chooses this tool like any other capability. It is not a verifier and
contains no task-specific acceptance logic: it returns page evidence (visible
text, console errors, element counts and a screenshot) for the model to judge.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

from app.models import ContentPart
from app.tools.base import Tool, ToolError
from app.tools.filesystem import resolve_in_root

MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_VISIBLE_TEXT = 8_000


def find_chromium_browser() -> Path | None:
    """Find an installed Chromium browser without downloading anything."""

    for name in ("msedge", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    candidates = (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path("/usr/bin/microsoft-edge"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    )
    return next((path.resolve() for path in candidates if path.is_file()), None)


def container_flags() -> list[str]:
    """The launch flags a browser needs to start at all inside a container.

    Chromium refuses to run its own sandbox as root, and a container's default
    `/dev/shm` is 64 MB, which is where a renderer crashes rather than fails
    honestly. Both are container facts, so they are decided by looking at the
    machine rather than by a setting someone has to remember to turn on.

    They are dropped on a normal desktop deliberately. `--no-sandbox` is the
    concession that buys the container a browser at all; giving it up where it
    is not needed would be trading away the only isolation the browser has.
    """

    if os.name == "nt" or getattr(os, "geteuid", None) is None or os.geteuid() != 0:
        return []
    return ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _read_json(url: str, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("browser returned a non-object DevTools response")
    return payload


class _CdpSession:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self.next_id = 1
        self.console_errors: list[str] = []

    def _event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exception = details.get("exception", {})
            self.console_errors.append(
                str(exception.get("description") or details.get("text") or "JavaScript error")
            )
        elif method == "Runtime.consoleAPICalled" and params.get("type") in {"error", "assert"}:
            values = [
                item.get("value", item.get("description", ""))
                for item in params.get("args", [])
            ]
            self.console_errors.append(" ".join(str(value) for value in values).strip())
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error":
                self.console_errors.append(str(entry.get("text", "browser log error")))

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        await self.websocket.send(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=5))
            if message.get("id") != request_id:
                self._event(message)
                continue
            if "error" in message:
                detail = message["error"].get("message", message["error"])
                raise RuntimeError(f"{method}: {detail}")
            return message.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise RuntimeError(str(remote.get("description", "browser evaluation failed")))
        return remote.get("value")


async def _wait_for_debugger(port: int, process: subprocess.Popen[bytes]) -> str:
    url = f"http://127.0.0.1:{port}/json/version"
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(f"browser exited before DevTools was ready ({process.returncode})")
        try:
            payload = await asyncio.to_thread(_read_json, url)
            return str(payload["Browser"])
        except (OSError, KeyError, RuntimeError):
            await asyncio.sleep(0.05)
    raise RuntimeError("browser DevTools endpoint did not become ready")


def _write_png(path: Path, encoded: str) -> bytes:
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
    if not target.is_file():
        raise ToolError(f"path {path!r} is not a file")
    if target.suffix.lower() not in {".html", ".htm"}:
        raise ToolError("inspect_page accepts only .html and .htm files")
    if target.stat().st_size > MAX_HTML_BYTES:
        raise ToolError(f"HTML file exceeds the {MAX_HTML_BYTES}-byte browser limit")
    executable = Path(browser).resolve() if browser else find_chromium_browser()
    if executable is None or not executable.is_file():
        raise ToolError("no installed Chrome/Edge browser was found")

    artifact = root / ".agent" / "browser" / f"{target.stem}-{secrets.token_hex(4)}.png"
    document = base64.b64encode(target.read_bytes()).decode("ascii")
    document_url = f"data:text/html;charset=utf-8;base64,{document}"
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="local-agent-browser-") as profile:
        process = subprocess.Popen(
            [
                str(executable),
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-extensions",
                "--disable-sync",
                "--metrics-recording-only",
                *container_flags(),
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            browser_name = await _wait_for_debugger(port, process)
            page = await asyncio.to_thread(
                _read_json, f"http://127.0.0.1:{port}/json/new", "PUT"
            )
            async with connect(
                str(page["webSocketDebuggerUrl"]),
                open_timeout=5,
                max_size=8 * 1024 * 1024,
            ) as websocket:
                session = _CdpSession(websocket)
                for domain in ("Runtime.enable", "Page.enable", "Log.enable", "Network.enable"):
                    await session.call(domain)
                await session.call(
                    "Network.setBlockedURLs",
                    {"urls": ["http://*", "https://*", "file://*", "ftp://*"]},
                )
                await session.call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 900, "height": 700, "deviceScaleFactor": 1, "mobile": False},
                )
                navigation = await session.call("Page.navigate", {"url": document_url})
                if navigation.get("errorText"):
                    raise ToolError(str(navigation["errorText"]))
                for _ in range(50):
                    if await session.evaluate("document.readyState") == "complete":
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise ToolError("page did not finish loading")
                await asyncio.sleep(0.2)
                evidence = await session.evaluate(_PAGE_EVIDENCE)
                screenshot = await session.call(
                    "Page.captureScreenshot", {"format": "png", "fromSurface": True}
                )
                image = await asyncio.to_thread(_write_png, artifact, str(screenshot["data"]))
                await session.evaluate("0")
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 3)

    relative_artifact = artifact.relative_to(root).as_posix()
    report = {
        **(evidence if isinstance(evidence, dict) else {}),
        "browser": browser_name,
        "console_errors": list(dict.fromkeys(session.console_errors)),
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
                "screenshot for visual inspection. External network and file URLs are blocked."
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
