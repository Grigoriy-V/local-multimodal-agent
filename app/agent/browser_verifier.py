"""Behavioral verification of a sandboxed HTML artifact in a real browser.

The verifier launches an already installed Chromium browser in an isolated
temporary profile and controls it through the DevTools protocol. It never uses
an application-specific browser API and never navigates away from the granted
local artifact.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

from app.agent.task_graph import (
    CheckResult,
    ImplementationResult,
    TaskContext,
    TestReport,
)
from app.agent.web_verifier import WebVerifier


@dataclass(frozen=True)
class BrowserProbeResult:
    loaded: bool
    console_errors: tuple[str, ...]
    canvas_present: bool
    canvas_rendered: bool
    moved: bool
    keyboard_received: bool
    preview_written: bool
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "console_errors", tuple(self.console_errors))


def find_chromium_browser() -> Path | None:
    """Find a local Chrome/Edge executable without downloading a browser."""

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
            text = exception.get("description") or details.get("text") or "JavaScript exception"
            self.console_errors.append(str(text))
        elif method == "Runtime.consoleAPICalled" and params.get("type") in {
            "error",
            "assert",
        }:
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
                raise RuntimeError(f"{method}: {message['error'].get('message', message['error'])}")
            return message.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise RuntimeError(str(remote.get("description", "browser evaluation failed")))
        return remote.get("value")


_PROBE_SCRIPT = r"""
(() => {
  const canvas = document.querySelector('canvas');
  if (!canvas) return {present: false, rendered: false, fingerprint: null, keys: []};
  const context = canvas.getContext('2d');
  if (!context || canvas.width < 1 || canvas.height < 1) {
    return {
      present: true, rendered: false, fingerprint: null,
      keys: window.__agentProbe?.keys || []
    };
  }
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let hash = 2166136261;
  let nonTransparent = 0;
  const colors = new Set();
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2], a = pixels[i + 3];
    if (a) nonTransparent += 1;
    if (colors.size < 8) colors.add(`${r},${g},${b},${a}`);
    hash ^= r; hash = Math.imul(hash, 16777619);
    hash ^= g; hash = Math.imul(hash, 16777619);
    hash ^= b; hash = Math.imul(hash, 16777619);
    hash ^= a; hash = Math.imul(hash, 16777619);
  }
  return {
    present: true,
    rendered: nonTransparent > 0 && colors.size > 1,
    fingerprint: hash >>> 0,
    keys: window.__agentProbe?.keys || []
  };
})()
"""


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


def _write_preview(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(base64.b64decode(encoded))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


async def probe_browser(
    html: Path, preview: Path, browser: Path
) -> BrowserProbeResult:
    """Load, exercise and capture one local HTML artifact."""

    port = _free_port()
    document = base64.b64encode(html.read_bytes()).decode("ascii")
    document_url = f"data:text/html;charset=utf-8;base64,{document}"
    with tempfile.TemporaryDirectory(prefix="local-agent-browser-") as profile:
        process = subprocess.Popen(
            [
                str(browser),
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-extensions",
                "--disable-sync",
                "--metrics-recording-only",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            browser_name = await _wait_for_debugger(port, process)
            target = await asyncio.to_thread(
                _read_json, f"http://127.0.0.1:{port}/json/new", "PUT"
            )
            websocket_url = str(target["webSocketDebuggerUrl"])
            async with connect(
                websocket_url, open_timeout=5, max_size=4 * 1024 * 1024
            ) as websocket:
                session = _CdpSession(websocket)
                await session.call("Runtime.enable")
                await session.call("Page.enable")
                await session.call("Log.enable")
                await session.call("Network.enable")
                await session.call(
                    "Network.setBlockedURLs",
                    {"urls": ["http://*", "https://*", "file://*", "ftp://*"]},
                )
                await session.call(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": (
                            "window.__agentProbe = {keys: []};"
                            "window.addEventListener('keydown', event => "
                            "window.__agentProbe.keys.push(event.key), true);"
                        )
                    },
                )
                await session.call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 900, "height": 700, "deviceScaleFactor": 1, "mobile": False},
                )
                navigation = await session.call("Page.navigate", {"url": document_url})
                if navigation.get("errorText"):
                    raise RuntimeError(str(navigation["errorText"]))
                for _ in range(50):
                    if await session.evaluate("document.readyState") == "complete":
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise RuntimeError("page did not finish loading")

                await asyncio.sleep(0.12)
                before = await session.evaluate(_PROBE_SCRIPT)
                await session.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "key": "ArrowRight",
                        "code": "ArrowRight",
                        "windowsVirtualKeyCode": 39,
                        "nativeVirtualKeyCode": 39,
                    },
                )
                await session.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "key": "ArrowRight",
                        "code": "ArrowRight",
                        "windowsVirtualKeyCode": 39,
                        "nativeVirtualKeyCode": 39,
                    },
                )
                await asyncio.sleep(0.15)
                after_key = await session.evaluate(_PROBE_SCRIPT)
                await asyncio.sleep(0.15)
                after_time = await session.evaluate(_PROBE_SCRIPT)
                screenshot = await session.call(
                    "Page.captureScreenshot", {"format": "png", "fromSurface": True}
                )
                await asyncio.to_thread(_write_preview, preview, str(screenshot["data"]))
                await session.evaluate("0")  # drain console events before reporting

                fingerprints = (
                    before.get("fingerprint"),
                    after_key.get("fingerprint"),
                    after_time.get("fingerprint"),
                )
                moved = len(set(fingerprints)) > 1 and None not in fingerprints
                keys = after_time.get("keys", [])
                return BrowserProbeResult(
                    loaded=True,
                    console_errors=tuple(dict.fromkeys(session.console_errors)),
                    canvas_present=bool(after_time.get("present")),
                    canvas_rendered=bool(after_time.get("rendered")),
                    moved=moved,
                    keyboard_received="ArrowRight" in keys,
                    preview_written=preview.is_file() and preview.stat().st_size > 0,
                    detail=browser_name,
                )
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 3)


class BrowserVerifier:
    """Convert a real browser probe into task-graph checks and a preview artifact."""

    def __init__(
        self,
        workspace: Path,
        target: str = "snake.html",
        preview: str = "snake-preview.png",
        browser: Path | None = None,
        probe: Any = probe_browser,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.target = self._relative(target)
        self.preview = self._relative(preview)
        self.browser = Path(browser).resolve() if browser else find_chromium_browser()
        self.probe = probe

    @staticmethod
    def _relative(value: str) -> Path:
        path = Path(value)
        if not value.strip() or path.is_absolute() or ".." in path.parts:
            raise ValueError("browser verifier paths must be relative to the task grant")
        return path

    async def __call__(
        self, context: TaskContext, _implementation: ImplementationResult
    ) -> TestReport:
        if not context.grant.allows("browser_verify"):
            raise PermissionError("task grant does not allow browser verification")
        root = context.grant.root(self.workspace)
        target = (root / self.target).resolve()
        preview = (root / self.preview).resolve()
        if root not in target.parents or root not in preview.parents:
            raise PermissionError("browser verifier path is outside the task grant")
        if not target.is_file():
            return self._failed("HTML artifact is unavailable")
        if self.browser is None or not self.browser.is_file():
            return self._failed("no installed Chrome/Edge browser was found")
        try:
            result = await self.probe(target, preview, self.browser)
        except Exception as error:
            return self._failed(f"browser probe failed: {error}")

        console_detail = (
            "; ".join(result.console_errors) if result.console_errors else "no console errors"
        )
        checks = (
            CheckResult("browser_load", result.loaded, result.detail or "page loaded"),
            CheckResult("browser_console", not result.console_errors, console_detail),
            CheckResult(
                "canvas_rendering",
                result.canvas_present and result.canvas_rendered,
                "canvas contains multiple rendered colors"
                if result.canvas_rendered
                else "canvas was missing or visually blank",
            ),
            CheckResult(
                "time_movement",
                result.moved,
                "canvas changed across timed frames"
                if result.moved
                else "canvas did not change across timed frames",
            ),
            CheckResult(
                "keyboard_input",
                result.keyboard_received,
                "page received ArrowRight"
                if result.keyboard_received
                else "page did not receive ArrowRight",
            ),
            CheckResult(
                "preview",
                result.preview_written,
                self.preview.as_posix()
                if result.preview_written
                else "browser did not write a preview",
            ),
        )
        artifacts = (self.preview.as_posix(),) if result.preview_written else ()
        return TestReport(checks, artifacts=artifacts)

    @staticmethod
    def _failed(detail: str) -> TestReport:
        return TestReport(
            (
                CheckResult("browser_load", False, detail),
                CheckResult("browser_console", False, "browser did not load the page"),
                CheckResult("canvas_rendering", False, "browser did not load the page"),
                CheckResult("time_movement", False, "browser did not load the page"),
                CheckResult("keyboard_input", False, "browser did not load the page"),
                CheckResult("preview", False, "browser did not load the page"),
            )
        )


class LayeredWebVerifier:
    """Run the cheap static gate before launching the behavioral browser gate."""

    def __init__(
        self,
        workspace: Path,
        target: str = "snake.html",
        preview: str = "snake-preview.png",
        browser: Path | None = None,
        browser_probe: Any = probe_browser,
    ) -> None:
        self.static = WebVerifier(workspace, target=target)
        self.browser = BrowserVerifier(
            workspace,
            target=target,
            preview=preview,
            browser=browser,
            probe=browser_probe,
        )

    async def __call__(
        self, context: TaskContext, implementation: ImplementationResult
    ) -> TestReport:
        static = await self.static(context, implementation)
        if not static.passed:
            return static
        behavioral = await self.browser(context, implementation)
        return TestReport(
            (*static.checks, *behavioral.checks), artifacts=behavioral.artifacts
        )
