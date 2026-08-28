"""Settings read from the environment.

Swapping the model or the endpoint is a configuration change, never a code
change; this is the only place that reads the environment.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseSettings):
    """How to reach the OpenAI-compatible endpoint that serves the model."""

    model_config = SettingsConfigDict(env_prefix="MODEL_", env_file=".env", extra="ignore")

    endpoint: str = "http://127.0.0.1:8000/v1"
    name: str = "gemma-4-12b-it"
    api_key: str | None = None
    # Ordinary OpenAI-compatible services use bearer auth. Modal web endpoints
    # can instead require the proxy token as two headers; keeping this explicit
    # avoids guessing from a URL or from the shape of a secret.
    auth_style: Literal["bearer", "modal_proxy"] = "bearer"
    timeout: float = 120.0
    # Version 1.5 coding profile. This is an output cap, not reserved output and
    # not the server context length; the validated server context stays 16k.
    max_tokens: int = 4096
    temperature: float = 0.0
    # Extra attempts after the first, for failures that say "later", not "no".
    retries: int = 2
    retry_backoff: float = 0.5


class TelegramSettings(BaseSettings):
    """How to reach Telegram, and who is allowed to reach the assistant."""

    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_", env_file=".env", extra="ignore"
    )

    token: str = ""
    # Telegram includes this exact value in every webhook request. It is not
    # the bot token and must be configured independently.
    webhook_secret: str = ""
    api_base: str = "https://api.telegram.org"
    # Comma-separated numeric Telegram user ids. Empty means nobody, because the
    # safe answer has to be the default: an assistant reachable by whoever finds
    # the bot spends the owner's GPU and reads the owner's memory.
    allowed_users: str = ""
    # Admit every Telegram account instead of consulting the list above. Each
    # account still gets its own conversations, memory and workspace, but they
    # share one GPU, so this is a deliberate choice and never a default.
    open_access: bool = False
    # Long-poll duration asked of Telegram. The HTTP timeout must exceed it.
    poll_timeout: int = 25
    timeout: float = 60.0

    @property
    def allowed(self) -> frozenset[int]:
        found = set()
        for part in self.allowed_users.replace(";", ",").split(","):
            part = part.strip()
            if part:
                found.add(int(part))
        return frozenset(found)


class AgentSettings(BaseSettings):
    """Where the agent stores memory, what it may read, and how much it keeps."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    database: str = "data/memory.sqlite3"
    # Where the deployed profile keeps conversations instead. Empty means the
    # SQLite file above, which is what the local profile uses and will keep
    # using: a personal machine has one process and a disk under it.
    #
    # `PostgresStore` is provider-agnostic; everything a provider needs lives in
    # this one string. For Neon that means the **pooled** endpoint — a fleet
    # that scales to zero opens and drops connections in bursts, and a direct
    # endpoint runs out of them long before the database runs out of capacity —
    # together with `sslmode=require`. It is a credential and belongs in the
    # environment or a platform secret, never in the repository.
    database_url: str = ""
    # A second database, used only to measure one against the other. It exists
    # because the deployed store's latency turned out to be dominated by the
    # distance between the worker and the database, and that claim is worth a
    # measurement rather than a map. Empty means there is nothing to compare to.
    alt_database_url: str = ""
    # Keeps this application's tables together in a database that may hold
    # other things, and gives a test a namespace of its own.
    database_schema: str = "public"
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
