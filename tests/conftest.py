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

# This has to happen while conftest is imported, before pytest collects a test
# module that imports Chainlit. A fixture is too late: live-test parametrization
# reads the process environment during collection and would retain a DSN that
# Chainlit copied from .env even after the fixture removed it.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

# Every prefix `app/config.py` reads settings from.
SETTINGS_PREFIXES = ("MODEL_", "AGENT_", "TELEGRAM_", "WEB_")


# Deleting a variable is not enough for these two. `WebSettings` also reads the
# repository's `.env`, and both of these change *which tools exist*: a developer
# with a Firecrawl key would run a suite where the assistant has a search tool
# and CI would run one where it does not. An empty value is a real answer that
# the file cannot override, so the wiring under test is the same everywhere. A
# test that wants either of them says so itself.
NEUTRALIZED = ("WEB_FIRECRAWL_API_KEY", "WEB_RENDERER_URL")


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(SETTINGS_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    for name in NEUTRALIZED:
        monkeypatch.setenv(name, "")
