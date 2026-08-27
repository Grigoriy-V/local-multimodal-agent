"""The Telegram interface: wire format, adapter, and the local polling transport.

`run` is deliberately not imported here. It is the module executed with
``python -m ui.telegram.run``, and importing it from the package would load it
twice.
"""

from ui.telegram.adapter import TelegramAdapter, canonical_user_id, current_thread, read_update
from ui.telegram.api import TelegramClient, TelegramError, split_message

__all__ = [
    "TelegramAdapter",
    "TelegramClient",
    "TelegramError",
    "canonical_user_id",
    "current_thread",
    "read_update",
    "split_message",
]
