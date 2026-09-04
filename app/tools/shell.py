"""Running a command in the workspace: one tool, one runner behind it.

`run_command` is the one tool; Python, `pip`, `node`, `git` are commands it
runs, not tools of their own. Where a command runs is the `Runner`'s business
and differs by profile: on the person's own machine it is a process in the
workspace with a reduced environment (`LocalRunner`); deployed it will be a
container beside the renderer that holds no secret. The tool, the result the
model reads and the codes are the same in both.

What a command gets: the workspace as its working directory and its home, and
an environment reduced to what a shell needs. Nothing from the process that
started the agent — no `.env` value, no token — is passed on. What survives a
command is whatever it wrote into the workspace; that is where a virtual
environment goes, and the brief says so.

A non-zero exit is a result, not a failure (`docs/v2_tool_system.md`, "Failure
is not the same as an unwanted result"). The failures are the runner's own: the
command did not finish in time and was killed, or could not be started at all.
`DECISIONS.md` 2026-09-04.
"""

from __future__ import annotations

import asyncio
import os
import platform
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .base import Tool, ToolError

# The family's own codes.
COMMAND_TIMEOUT = "shell.timeout"
COMMAND_NOT_STARTED = "shell.not_started"

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
# What the model reads back of a command's output: below the executor's own
# 32k backstop, with the tail kept because a build says what failed at the end.
MAX_OUTPUT_CHARS = 16_000
TAIL_CHARS = 4_000

# What a shell needs and nothing else. `HOME` and its Windows twin point into
# the workspace so that what a command installs "for the user" lands where the
# workspace keeps it. `SYSTEMROOT` and `COMSPEC` are what `cmd` itself needs to
# start on Windows; `TEMP`/`TMP` so tools that write temporary files work.
_PASSED = ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")


@dataclass(frozen=True)
class Finished:
    """What one command came to."""

    exit_code: int
    output: str
    cut: bool
    seconds: float
    # A container that was created for this command, so nothing installed by
    # an earlier one is present. Never true on the person's own machine.
    fresh: bool = False


class Runner(Protocol):
    """Where a command runs. One method; the profile chooses the implementation."""

    # Said once in the brief, so the model knows which shell it is writing for.
    where: str

    async def run(self, command: str, cwd: Path, timeout: float) -> Finished: ...


def command_environment(workspace: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a command gets: what a shell needs, home in the workspace."""

    source = os.environ if source is None else source
    env = {name: source[name] for name in _PASSED if name in source}
    env["HOME"] = str(workspace)
    env["USERPROFILE"] = str(workspace)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NO_COLOR"] = "1"
    env.setdefault("LANG", "C.UTF-8")
    return env


def bounded(text: str, limit: int = MAX_OUTPUT_CHARS, tail: int = TAIL_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = text[: limit - tail]
    return f"{head}\n… [{len(text) - limit} characters left out] …\n{text[-tail:]}", True


def _kill_tree(process: subprocess.Popen) -> None:
    """Stop the command and everything it started."""

    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
                timeout=10,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


class LocalRunner:
    """A process on this machine, in the workspace, with a reduced environment.

    The person's own machine is where Claude Code and Codex run their commands
    on Windows too, with the person as the boundary; this does the same and
    withholds the agent's own environment. The shell is the platform's: `cmd`
    on Windows, `/bin/sh` elsewhere, which is what `shell=True` means.
    """

    def __init__(self) -> None:
        system = platform.system() or "this machine"
        shell = "cmd" if sys.platform == "win32" else "sh"
        self.where = f"on this machine ({system}), through {shell}"

    async def run(self, command: str, cwd: Path, timeout: float) -> Finished:
        started = time.monotonic()
        try:
            process = subprocess.Popen(  # noqa: S602 - the command is the point
                command,
                shell=True,
                cwd=str(cwd),
                env=command_environment(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=sys.platform != "win32",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                ),
            )
        except OSError as error:
            raise ToolError(
                f"the command could not be started: {error.strerror or error}",
                code=COMMAND_NOT_STARTED,
            ) from error
        try:
            raw, _ = await asyncio.to_thread(process.communicate, None, timeout)
        except subprocess.TimeoutExpired as error:
            _kill_tree(process)
            partial = (error.output or b"").decode("utf-8", errors="replace")
            tail, _ = bounded(partial, TAIL_CHARS, TAIL_CHARS // 2)
            raise ToolError(
                f"the command did not finish within {timeout:g} seconds and was killed",
                code=COMMAND_TIMEOUT,
                detail=tail.strip() or None,
            ) from None
        except BaseException:
            # A stop, or the interpreter going down: the command must not
            # outlive the turn that asked for it.
            _kill_tree(process)
            raise
        output, cut = bounded((raw or b"").decode("utf-8", errors="replace"))
        return Finished(
            exit_code=process.returncode,
            output=output,
            cut=cut,
            seconds=time.monotonic() - started,
        )


def describe(finished: Finished) -> str:
    """What the model reads: the exit code first, then what the command said."""

    lines = [f"exit code: {finished.exit_code}   ({finished.seconds:.1f} s)"]
    if finished.fresh:
        lines.append(
            "new environment: nothing installed by earlier commands is present; "
            "what is in the workspace is."
        )
    if finished.cut:
        lines.append("output (cut in the middle; the beginning and the end are kept):")
    else:
        lines.append("output:")
    lines.append(finished.output.strip() or "(no output)")
    return "\n".join(lines)


def shell_tools(root: Path, runner: Runner) -> list[Tool]:
    resolved = Path(root).resolve()

    async def run_command(command: str, timeout_seconds: int = DEFAULT_TIMEOUT) -> str:
        limit = max(1, min(int(timeout_seconds), MAX_TIMEOUT))
        return describe(await runner.run(str(command), resolved, float(limit)))

    return [
        Tool(
            name="run_command",
            description=(
                "Run one shell command in your workspace and read its exit code and "
                "output. Python, pip, node, npm, git and the like are commands here. A "
                "non-zero exit code is a result to read, not an error of the tool. "
                f"`timeout_seconds` (default {DEFAULT_TIMEOUT}, at most {MAX_TIMEOUT}) "
                "kills the command if it runs longer. The command cannot read from the "
                "terminal, so pass answers on the command line or with flags."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command line, as for the shell."},
                    "timeout_seconds": {
                        "type": "integer",
                        "description": f"Seconds before the command is killed; default {DEFAULT_TIMEOUT}.",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            run=run_command,
            mutates=True,
            # The executor's own deadline, above the longest the tool allows, so
            # a runner that hangs is still stopped.
            timeout_seconds=MAX_TIMEOUT + 30,
        ),
    ]
