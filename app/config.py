"""Settings read from the environment.

Swapping the model or the endpoint is a configuration change, never a code
change; this is the only place that reads the environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseSettings):
    """How to reach the OpenAI-compatible endpoint that serves the model."""

    model_config = SettingsConfigDict(env_prefix="MODEL_", env_file=".env", extra="ignore")

    endpoint: str = "http://127.0.0.1:8000/v1"
    name: str = "gemma-4-12b-it"
    api_key: str | None = None
    timeout: float = 120.0
    max_tokens: int = 512
    temperature: float = 0.0


class AgentSettings(BaseSettings):
    """Where the agent stores memory, what it may read, and how much it keeps."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    database: str = "data/memory.sqlite3"
    # The only directory the filesystem tools may reach. Widening it is a
    # deliberate act, which is why it is configuration and not a default guess.
    workspace: str = "."
    keep_recent: int = 8
    summarize_after: int = 16
    retrieved_facts: int = 5
