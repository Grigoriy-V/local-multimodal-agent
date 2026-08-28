"""Keep the offline suite independent of whoever is running it.

Importing `chainlit` calls `load_dotenv`, which copies the developer's `.env`
into `os.environ`. From that point on a test's `_env_file=None` no longer
isolates anything: the values arrive as real environment variables instead, and
the suite starts passing or failing according to the local machine's
configuration rather than the code. That happened for real — pointing the local
profile at the Modal endpoint with `MODEL_AUTH_STYLE=modal_proxy` broke thirteen
wire-format tests that never touch authentication.

Clearing the application's own prefixes before every test removes the coupling
without forbidding the import.
"""

from __future__ import annotations

import os

import pytest

# Every prefix `app/config.py` reads settings from.
SETTINGS_PREFIXES = ("MODEL_", "AGENT_", "TELEGRAM_")


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(SETTINGS_PREFIXES):
            monkeypatch.delenv(name, raising=False)
