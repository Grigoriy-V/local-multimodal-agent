"""Point Telegram at the deployed webhook, or take it back to polling.

Registering is a mode switch, not an addition: Telegram refuses `getUpdates`
while a webhook is set, so `ui/telegram/run.py` stops working the moment this
succeeds and works again the moment `--delete` runs. That is the whole reason
this is a named tool with two directions rather than a curl line in a report.

The secret token is what makes the endpoint safe to leave unauthenticated:
Telegram sends it as a header on every delivery and the application refuses
anything else. It is read from `.env` and never printed.

    .venv\\Scripts\\python.exe tools/telegram_webhook.py --url https://...
    .venv\\Scripts\\python.exe tools/telegram_webhook.py            # show status
    .venv\\Scripts\\python.exe tools/telegram_webhook.py --delete   # back to polling
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from app.config import TelegramSettings


def call(settings: TelegramSettings, method: str, payload: dict[str, object]) -> dict:
    request = urllib.request.Request(
        f"{settings.api_base.rstrip('/')}/bot{settings.token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="the deployed webhook endpoint")
    parser.add_argument("--delete", action="store_true", help="return to polling")
    arguments = parser.parse_args()

    settings = TelegramSettings()
    if not settings.token:
        print("TELEGRAM_TOKEN is not configured")
        return 1

    if arguments.delete:
        body = call(settings, "deleteWebhook", {"drop_pending_updates": False})
        print(f"deleteWebhook: ok={body.get('ok')}")
    elif arguments.url:
        if not settings.webhook_secret:
            print("TELEGRAM_WEBHOOK_SECRET is not configured; refusing to register")
            return 1
        body = call(
            settings,
            "setWebhook",
            {
                "url": arguments.url,
                "secret_token": settings.webhook_secret,
                "allowed_updates": ["message", "callback_query"],
                "max_connections": 8,
            },
        )
        print(f"setWebhook: ok={body.get('ok')} {body.get('description', '')}")

    info = call(settings, "getWebhookInfo", {}).get("result", {})
    # Everything here is operational state, not a credential. The secret is
    # never returned by Telegram and is never printed by this tool.
    for key in (
        "url",
        "pending_update_count",
        "max_connections",
        "last_error_date",
        "last_error_message",
    ):
        if key in info:
            print(f"  {key}: {info[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
