"""The Telegram interface: wire format, adapter, and the local polling transport.

`run` is deliberately not imported here. It is the module executed with
``python -m ui.telegram.run``, and importing it from the package would load it
twice.

Nothing else is imported eagerly either, and that is load-bearing rather than
tidy. The deployed webhook imports `ui.telegram.webhook`, which runs this file
first; while this named the adapter at module level, that one line pulled the
harness and LangGraph into a container whose whole job is to validate an update
and return 200. The names below are still importable from the package — they
are resolved on first use instead of on import.
"""

from typing import TYPE_CHECKING

# One entry per exported name: the module it actually lives in.
_HOMES = {
    "TelegramAdapter": "ui.telegram.adapter",
    "canonical_user_id": "ui.telegram.adapter",
    "current_thread": "ui.telegram.adapter",
    "TelegramClient": "ui.telegram.api",
    "TelegramError": "ui.telegram.api",
    "split_message": "ui.telegram.api",
    "read_update": "ui.telegram.wire",
}

if TYPE_CHECKING:  # The lazy path is invisible to a type checker, so name them.
    from ui.telegram.adapter import TelegramAdapter as TelegramAdapter
    from ui.telegram.adapter import canonical_user_id as canonical_user_id
    from ui.telegram.adapter import current_thread as current_thread
    from ui.telegram.api import TelegramClient as TelegramClient
    from ui.telegram.api import TelegramError as TelegramError
    from ui.telegram.api import split_message as split_message
    from ui.telegram.wire import read_update as read_update


def __getattr__(name: str) -> object:
    """Import the module that owns `name`, the first time someone asks for it."""

    home = _HOMES.get(name)
    if home is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(home), name)
    globals()[name] = value  # Asked once; found directly from here on.
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_HOMES])


__all__ = sorted(_HOMES)
