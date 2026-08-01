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
    # Version 1.5 coding profile. This is an output cap, not reserved output and
    # not the server context length; the validated server context stays 16k.
    max_tokens: int = 4096
    temperature: float = 0.0
    # Extra attempts after the first, for failures that say "later", not "no".
    retries: int = 2
    retry_backoff: float = 0.5


class AgentSettings(BaseSettings):
    """Where the agent stores memory, what it may read, and how much it keeps."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    database: str = "data/memory.sqlite3"
    # In-flight turns only, in LangGraph's own schema. Kept apart from the
    # database so that discarding it costs no conversation.
    checkpoints: str = "data/checkpoints.sqlite3"
    # The bounded task graph has a different state shape and lifecycle from a
    # conversational turn, so its resumable grants live in their own file.
    task_checkpoints: str = "data/task-checkpoints.sqlite3"
    # The only directory the filesystem tools may reach, created on first use.
    # It defaults to a sandbox rather than to the current directory: the default
    # should be the safe answer, and pointing the agent at real work is then a
    # deliberate act rather than the consequence of where it was started.
    workspace: str = "workspace"
    keep_recent: int = 8
    summarize_after: int = 16
    retrieved_facts: int = 5
    # The share of the model's own context a request may occupy. The limit
    # itself is read from the server, never copied here: two copies of one
    # number are one number and one lie waiting to happen. The headroom is what
    # lets the fold react to a measured overshoot instead of guessing ahead.
    context_fraction: float = 0.6
