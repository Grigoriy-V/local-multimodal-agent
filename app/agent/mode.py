"""Two ways a conversation may run: `full`, or `careful`.

In `full`, the default, everything inside the workspace runs without a
question — reading, writing, running a command — and only effects beyond it
(another person, another system, money, infrastructure) ask first. In
`careful`, the tools that change the workspace ask too, through the same
approval path. Claude Code's permission modes, in one flag: a tool declares
that it `mutates`, and the toolbox reads the mode when it decides what needs a
yes. Nothing else in the loop knows the mode exists.

Kept the way the plan switch is kept: a marker in the person's workspace, read
when the next turn's toolbox is built, so a change takes effect from the next
message and is the same in every interface. `DECISIONS.md` 2026-09-04.
"""

from __future__ import annotations

from pathlib import Path

CAREFUL_SWITCH = Path(".agent") / "careful.on"
MODES = ("full", "careful")


def careful_enabled(workspace: Path | str) -> bool:
    """Never raises: an unreadable marker is the default, `full`."""

    try:
        return (Path(workspace) / CAREFUL_SWITCH).is_file()
    except OSError:
        return False


def current_mode(workspace: Path | str) -> str:
    return "careful" if careful_enabled(workspace) else "full"


def set_mode(workspace: Path | str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; one of {', '.join(MODES)}")
    marker = Path(workspace) / CAREFUL_SWITCH
    if mode == "full":
        marker.unlink(missing_ok=True)
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "careful mode: tools that change the workspace ask first; /mode full turns it off\n",
        encoding="utf-8",
    )
