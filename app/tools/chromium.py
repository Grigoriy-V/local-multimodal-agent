"""Starting a headless browser and talking to it, without deciding what for.

Two capabilities need a real browser: inspecting a local HTML artifact and
looking at a public web page. They differ in what they allow the page to do —
one blocks the network entirely, the other exists to reach it — and in nothing
else. Keeping the process, the DevTools handshake and the CDP session here means
a fix to the fragile part is a fix in both, and neither module has to remember
which flags a container cannot start without.

Nothing here navigates anywhere. The caller opens the page, because the caller
is the one that knows what the page is allowed to be.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

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


class CdpSession:
    """One page, driven over the DevTools protocol.

    Events that arrive while a call is outstanding are not discarded: console
    errors are what make a broken page look broken instead of empty, and a
    paused request is a decision this session has to make before the page can
    continue.
    """

    def __init__(
        self,
        websocket: Any,
        allow: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.websocket = websocket
        self.next_id = 1
        self.console_errors: list[str] = []
        self.refused: list[str] = []
        self._allow = allow

    def _take_id(self) -> int:
        """Every message takes its id here.

        One counter, one rule. Interception previously incremented first and
        sent second, which handed a later `call` the same id an intercepted
        request was still owed a reply for — so a page's evidence arrived as the
        acknowledgement of a `Fetch.continueRequest`, and every rendered page
        came back with no text and no title. Found by rendering a real page,
        which is the only place a screenshot and an empty transcript disagree.
        """

        taken = self.next_id
        self.next_id += 1
        return taken

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a command without waiting for its answer.

        Used from inside the receive loop, where waiting for a reply would mean
        waiting on the loop that is not running. The reply arrives later as an
        unmatched message and is ignored, which is correct: a paused request has
        exactly one right answer and nothing depends on its acknowledgement.
        """

        await self.websocket.send(
            json.dumps({"id": self._take_id(), "method": method, "params": params})
        )

    async def _decide(self, params: dict[str, Any]) -> None:
        """Let one intercepted request through, or fail it.

        This is where the browser stops being a hole in the destination policy.
        `Page.navigate` checks the address the caller asked for and nothing
        else: the page's own redirects, its fetches and every subresource are
        requests the browser makes on its own, and one of them pointing at
        169.254.169.254 is a page reading the container it is being viewed in.
        """

        identifier = params.get("requestId")
        url = str(params.get("request", {}).get("url", ""))
        if identifier is None or self._allow is None:
            # No policy means interception was never enabled, so this event is
            # not ours to answer. Answering it anyway would be this session
            # letting a request through on a page whose rule is "no network".
            return
        if await self._allow(url):
            await self._notify("Fetch.continueRequest", {"requestId": identifier})
            return
        self.refused.append(url)
        await self._notify(
            "Fetch.failRequest", {"requestId": identifier, "errorReason": "AccessDenied"}
        )

    async def _event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Fetch.requestPaused":
            await self._decide(params)
        elif method == "Runtime.exceptionThrown":
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

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 5.0
    ) -> dict[str, Any]:
        request_id = self._take_id()
        await self.websocket.send(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=timeout))
            if message.get("id") != request_id:
                await self._event(message)
                continue
            if "error" in message:
                detail = message["error"].get("message", message["error"])
                raise RuntimeError(f"{method}: {detail}")
            return message.get("result", {})

    async def evaluate(self, expression: str, timeout: float = 5.0) -> Any:
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout,
        )
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise RuntimeError(str(remote.get("description", "browser evaluation failed")))
        return remote.get("value")

    async def viewport(self, width: int, height: int) -> None:
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )

    async def wait_for_load(self, attempts: int = 50, pause: float = 0.05) -> bool:
        for _ in range(attempts):
            if await self.evaluate("document.readyState") == "complete":
                return True
            await asyncio.sleep(pause)
        return False

    async def screenshot(self, timeout: float = 15.0) -> str:
        result = await self.call(
            "Page.captureScreenshot", {"format": "png", "fromSurface": True}, timeout
        )
        return str(result["data"])


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


@contextlib.asynccontextmanager
async def open_page(
    browser: Path | None = None,
    extra_flags: Sequence[str] = (),
    max_message_bytes: int = 8 * 1024 * 1024,
    allow: Callable[[str], Awaitable[bool]] | None = None,
) -> AsyncIterator[tuple[CdpSession, str]]:
    """Start a private browser, open one blank page, and always close both.

    The profile is a temporary directory, so nothing survives the call: no
    cookies, no history, no cache carried from one page to the next. That is a
    privacy property as much as a hygiene one — two pages the assistant looks at
    for two different people never share a session.

    `allow` is asked about every request the browser makes, once interception is
    enabled. A caller that passes nothing gets no interception, which is right
    for a page that has already been forbidden the network entirely.
    """

    executable = Path(browser).resolve() if browser else find_chromium_browser()
    if executable is None or not executable.is_file():
        raise RuntimeError("no installed Chrome/Edge browser was found")

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
                *extra_flags,
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            name = await _wait_for_debugger(port, process)
            page = await asyncio.to_thread(_read_json, f"http://127.0.0.1:{port}/json/new", "PUT")
            async with connect(
                str(page["webSocketDebuggerUrl"]),
                open_timeout=5,
                max_size=max_message_bytes,
            ) as websocket:
                session = CdpSession(websocket, allow)
                for domain in ("Runtime.enable", "Page.enable", "Log.enable", "Network.enable"):
                    await session.call(domain)
                if allow is not None:
                    # Every request, not only documents: a subresource is a
                    # request to an address just as much as a navigation is.
                    await session.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
                yield session, name
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 3)
