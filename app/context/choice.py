"""The context size a person chose, kept in their own workspace.

A marker file, like the plan switch: it survives a restarted worker, is the
same in every interface, and the person can see it beside `AGENTS.md`. The
sizes are shares of the model's real ceiling, read from the server, so a
choice is a trade the engine can state in tokens rather than a number copied
from a document.
"""

from __future__ import annotations

from pathlib import Path

CONTEXT_CHOICE = Path(".agent") / "context"

# Share of the ceiling each size spends. `None` is the configured fraction.
SIZES: dict[str, float | None] = {"small": 0.25, "normal": None, "large": 0.95}
DEFAULT_SIZE = "normal"


def context_choice(workspace: Path | str) -> str:
    """Never raises: an unreadable or unknown marker is the default."""

    try:
        chosen = (Path(workspace) / CONTEXT_CHOICE).read_text(encoding="utf-8").strip().lower()
    except OSError:
        return DEFAULT_SIZE
    return chosen if chosen in SIZES else DEFAULT_SIZE


def set_context_choice(workspace: Path | str, size: str) -> None:
    if size not in SIZES:
        raise ValueError(f"not a context size: {size!r}")
    marker = Path(workspace) / CONTEXT_CHOICE
    if size == DEFAULT_SIZE:
        marker.unlink(missing_ok=True)
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{size}\n", encoding="utf-8")


def share(size: str, fraction: float) -> float:
    chosen = SIZES.get(size)
    return fraction if chosen is None else chosen
