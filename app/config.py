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
