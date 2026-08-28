"""Publish the control plane's runtime configuration as a Modal Secret.

The allow list below is the point of this file. A deployment needs a handful of
values from the developer's `.env`, and the failure everyone reaches for is
copying the file wholesale — which would put the test database URL, local paths
and anything else that ever lands there into a platform secret. Naming the keys
makes that impossible by accident and reviewable on sight.

Values are never printed, never written into a shell string and never recorded.
The command is built as an argument list, so nothing passes through a shell, and
the only output is key names.

    .venv\\Scripts\\python.exe tools/sync_control_secret.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SECRET_NAME = "assistant-control"

# What the deployed control plane reads. Local paths are excluded because a
# Windows path means nothing in a Linux container, and `AGENT_TEST_DATABASE_URL`
# is excluded because a deployment must never be able to reach the database the
# test suite creates and drops schemas in.
ALLOWED = (
    "TELEGRAM_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_ALLOWED_USERS",
    "AGENT_DATABASE_URL",
    "AGENT_DATABASE_SCHEMA",
    # Only for measuring one database against another; see the latency report.
    "AGENT_ALT_DATABASE_URL",
    "MODEL_ENDPOINT",
    "MODEL_NAME",
    "MODEL_API_KEY",
    "MODEL_AUTH_STYLE",
)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    source = Path(".env")
    if not source.is_file():
        print("no .env in the working directory")
        return 1

    values = read_env(source)
    present = [key for key in ALLOWED if values.get(key)]
    missing = [key for key in ALLOWED if not values.get(key)]

    print(f"publishing {len(present)} keys to the {SECRET_NAME} secret:")
    for key in present:
        print(f"  + {key}")
    for key in missing:
        print(f"  - {key} (absent from .env, not published)")

    if not present:
        print("nothing to publish")
        return 1

    command = [
        sys.executable,
        "-m",
        "modal",
        "secret",
        "create",
        SECRET_NAME,
        *(f"{key}={values[key]}" for key in present),
        "--force",
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
