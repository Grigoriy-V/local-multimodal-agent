"""Publish the bot's own product surface: its description and command menu.

Telegram keeps these on its side, not in this repository, so they are a
deployment action rather than a code path — and one that a person has to take
deliberately, which is why this is a tool and not something the adapter does on
startup. Running it changes what every user of the bot sees.

The text itself lives in `ui/telegram/api.py`, next to the adapter that answers
those commands, so the menu and the behaviour cannot drift apart. This file
only sends it.

    .venv\\Scripts\\python.exe tools/telegram_profile.py            # show intent
    .venv\\Scripts\\python.exe tools/telegram_profile.py --publish  # apply it
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import TelegramSettings
from ui.telegram.api import (
    BOT_DESCRIPTION,
    BOT_SHORT_DESCRIPTION,
    PRODUCT_COMMANDS,
    TelegramClient,
    TelegramError,
)


async def publish(settings: TelegramSettings) -> None:
    client = TelegramClient(settings)
    try:
        await client.set_my_commands(PRODUCT_COMMANDS)
        await client.set_my_description(BOT_DESCRIPTION)
        await client.set_my_short_description(BOT_SHORT_DESCRIPTION)
    finally:
        await client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="send the description and command menu to Telegram",
    )
    arguments = parser.parse_args()

    print("Description:")
    print(f"  {BOT_DESCRIPTION}")
    print("Short description:")
    print(f"  {BOT_SHORT_DESCRIPTION}")
    print("Command menu:")
    for entry in PRODUCT_COMMANDS:
        print(f"  /{entry.command} — {entry.description}")

    if not arguments.publish:
        print("\nNothing was sent. Re-run with --publish to apply this.")
        return 0

    settings = TelegramSettings()
    if not settings.token:
        print("TELEGRAM_TOKEN is not configured")
        return 1
    try:
        asyncio.run(publish(settings))
    except TelegramError as error:
        print(f"telegram refused the update: {error}")
        return 1
    print("\nPublished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
