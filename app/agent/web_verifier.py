"""Deterministic checks for a self-contained browser game artifact.

The verifier reads only the target file inside the active task grant. JavaScript
is parsed by ``node --check`` and is never executed; behavioral browser checks
belong to a later verifier layer.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path

from app.agent.task_graph import (
    CheckResult,
    ImplementationResult,
    TaskContext,
    TestReport,
)

SyntaxChecker = Callable[[str], CheckResult]

_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _ArtifactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_html_doctype = False
        self.tags: list[str] = []
        self.canvases: list[dict[str, str | None]] = []
        self.inline_scripts: list[str] = []
        self.external_scripts: list[str] = []
        self.errors: list[str] = []
        self._stack: list[str] = []
        self._script: list[str] | None = None

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() == "doctype html":
            self.has_html_doctype = True

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        attributes = {name.lower(): value for name, value in attrs}
        self.tags.append(tag)
        if tag == "canvas":
            self.canvases.append(attributes)
        if tag == "script":
            source = attributes.get("src")
            if source:
                self.external_scripts.append(source)
                self._script = None
            else:
                self._script = []
        if tag not in _VOID_TAGS:
            self._stack.append(tag)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._script is not None:
            self.inline_scripts.append("".join(self._script))
            self._script = None
        if not self._stack:
            self.errors.append(f"unexpected closing </{tag}>")
            return
        expected = self._stack.pop()
        if expected != tag:
            self.errors.append(f"expected </{expected}> before </{tag}>")

    def finish(self) -> None:
        self.close()
        if self._stack:
            self.errors.append(
                "unclosed tags: " + ", ".join(f"<{tag}>" for tag in self._stack)
            )


def node_javascript_syntax(
    source: str, executable: str | None = None
) -> CheckResult:
    """Parse JavaScript without executing it."""

    command = executable or shutil.which("node")
    if not command:
        return CheckResult(
            "javascript_syntax",
            False,
            "Node.js is unavailable; cannot parse JavaScript safely",
        )
    try:
        completed = subprocess.run(
            [command, "--check", "-"],
            input=source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckResult(
            "javascript_syntax", False, f"Node.js syntax check failed to run: {error}"
        )
    if completed.returncode == 0:
        return CheckResult(
            "javascript_syntax", True, "Node.js parsed all inline JavaScript"
        )
    detail = (completed.stderr or completed.stdout).strip().replace("\r", "")
    return CheckResult(
        "javascript_syntax",
        False,
        f"Node.js rejected inline JavaScript: {detail[:500]}",
    )


def _html_structure(parser: _ArtifactParser) -> CheckResult:
    missing: list[str] = []
    if not parser.has_html_doctype:
        missing.append("<!DOCTYPE html>")
    for tag in ("html", "head", "body"):
        if tag not in parser.tags:
            missing.append(f"<{tag}>")
    if not parser.canvases:
        missing.append("<canvas>")
    if not parser.inline_scripts:
        missing.append("inline <script>")
    if parser.external_scripts:
        missing.append("external <script src> is not allowed")
    problems = [*missing, *parser.errors]
    if problems:
        return CheckResult(
            "html_structure", False, "missing or malformed: " + "; ".join(problems)
        )
    return CheckResult(
        "html_structure", True, "standalone document has head, body, canvas and inline script"
    )


def _game_controls(source: str) -> CheckResult:
    missing: list[str] = []
    if not re.search(r"getContext\s*\(\s*['\"]2d['\"]\s*\)", source):
        missing.append("2D canvas context")
    if not re.search(
        r"(?:addEventListener\s*\(\s*['\"]keydown['\"]|\.onkeydown\s*=)",
        source,
    ):
        missing.append("keydown handler")
    directions = {
        "left": ("ArrowLeft", "37"),
        "up": ("ArrowUp", "38"),
        "right": ("ArrowRight", "39"),
        "down": ("ArrowDown", "40"),
    }
    for name, (key_name, key_code) in directions.items():
        if key_name not in source and not re.search(rf"\b{key_code}\b", source):
            missing.append(f"{name} arrow")
    if not re.search(
        r"\b(?:setInterval|setTimeout|requestAnimationFrame)\s*\(", source
    ):
        missing.append("game loop")
    if missing:
        return CheckResult(
            "game_controls", False, "missing signals: " + ", ".join(missing)
        )
    return CheckResult(
        "game_controls",
        True,
        "2D canvas, keydown, four arrow directions and a game loop are present",
    )


class WebVerifier:
    """Return the stable four-check report consumed by the task graph."""

    def __init__(
        self,
        workspace: Path,
        target: str = "snake.html",
        syntax_checker: SyntaxChecker = node_javascript_syntax,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        requested = Path(target)
        if not target.strip() or requested.is_absolute() or ".." in requested.parts:
            raise ValueError("web verifier target must be a relative path inside the grant")
        self.target = requested
        self.syntax_checker = syntax_checker

    async def __call__(
        self, context: TaskContext, _implementation: ImplementationResult
    ) -> TestReport:
        root = context.grant.root(self.workspace)
        target = (root / self.target).resolve()
        if target != root and root not in target.parents:
            raise PermissionError("web verifier target is outside the task grant")
        if not target.is_file():
            absent = f"{self.target.as_posix()} does not exist inside the task grant"
            return TestReport(
                (
                    CheckResult("file_presence", False, absent),
                    CheckResult("html_structure", False, "file is unavailable"),
                    CheckResult("javascript_syntax", False, "file is unavailable"),
                    CheckResult("game_controls", False, "file is unavailable"),
                )
            )

        try:
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            return TestReport(
                (
                    CheckResult("file_presence", True, target.name),
                    CheckResult("html_structure", False, f"cannot read UTF-8 HTML: {error}"),
                    CheckResult("javascript_syntax", False, "HTML is unreadable"),
                    CheckResult("game_controls", False, "HTML is unreadable"),
                )
            )

        parser = _ArtifactParser()
        try:
            parser.feed(source)
            parser.finish()
        except Exception as error:  # HTMLParser can surface malformed declarations.
            parser.errors.append(str(error))
        html_check = _html_structure(parser)
        javascript = "\n;\n".join(parser.inline_scripts)
        if javascript.strip():
            syntax_check = await asyncio.to_thread(self.syntax_checker, javascript)
        else:
            syntax_check = CheckResult(
                "javascript_syntax", False, "no inline JavaScript to parse"
            )
        return TestReport(
            (
                CheckResult("file_presence", True, f"found {target.name}"),
                html_check,
                syntax_check,
                _game_controls(javascript),
            )
        )
