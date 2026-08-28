"""Modal CPU control plane for the deployed Telegram adapter.

Deploying this module never redeploys the model app. The unauthenticated HTTP
function verifies Telegram's own secret and allow list, persists the update,
spawns a separate CPU function and returns immediately. Only that worker calls
the existing transport-neutral ``TelegramAdapter``.

No function is invoked by importing this module. Database migrations are an
explicit local operation through ``tools/setup_control_plane.py``.
"""

import modal
from fastapi import Request

APP_NAME = "assistant-control"
SECRET_NAME = "assistant-control"

app = modal.App(APP_NAME)
control_secret = modal.Secret.from_name(SECRET_NAME)

# Build only from the lock file and copy only application source. In particular,
# never copy the repository's .env, data, reports or human workspaces into an
# image layer.
control_image = (
    modal.Image.debian_slim(python_version="3.12")
    .add_local_file("pyproject.toml", "/root/project/pyproject.toml", copy=True)
    .add_local_file("uv.lock", "/root/project/uv.lock", copy=True)
    .uv_sync(
        "/root/project",
        groups=["app", "agent", "postgres", "deploy"],
        frozen=True,
        extra_options="--no-install-project",
    )
    .add_local_dir("app", "/root/project/app", copy=True)
    .add_local_dir("ui", "/root/project/ui", copy=True)
    .env({"PYTHONPATH": "/root/project"})
)


def _settings() -> tuple[object, object]:
    from app.config import AgentSettings, TelegramSettings

    telegram = TelegramSettings()
    agent = AgentSettings()
    if not telegram.token:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")
    if not telegram.webhook_secret:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is not configured")
    if not telegram.allowed and not telegram.open_access:
        raise RuntimeError("no Telegram account is allowed")
    if not agent.database_url:
        raise RuntimeError("AGENT_DATABASE_URL is not configured")
    return telegram, agent


@app.function(
    image=control_image,
    secrets=[control_secret],
    cpu=1.0,
    memory=2048,
    min_containers=0,
    max_containers=8,
    scaledown_window=2,
    timeout=600,
    include_source=False,
)
async def process_telegram_update(update_id: int) -> bool:
    """Claim and process one durable update in a separate CPU worker."""

    from ui.telegram.adapter import TelegramAdapter
    from ui.telegram.api import TelegramClient
    from ui.telegram.inbox import PostgresUpdateInbox
    from ui.telegram.webhook import TelegramUpdateWorker

    telegram, agent = _settings()
    client = TelegramClient(telegram)
    adapter = TelegramAdapter(client, telegram, agent)
    inbox = PostgresUpdateInbox(agent.database_url, agent.database_schema)
    try:
        return await TelegramUpdateWorker(inbox, adapter).run(update_id)
    finally:
        await adapter.aclose()
        await client.aclose()


@app.function(
    image=control_image,
    secrets=[control_secret],
    cpu=0.25,
    memory=512,
    min_containers=0,
    max_containers=1,
    scaledown_window=2,
    timeout=120,
    include_source=False,
)
def measure_database_latency(operation: str, warm_runs: int = 5) -> dict[str, object]:
    """Measure one complete production read or write without touching the model.

    ``prepare`` creates a representative isolated read fixture. A later
    ``read`` or ``write`` invocation must happen only after Neon is known to be
    idle if its first sample is to count as database-cold acceptance.
    """

    import os
    import time
    import uuid

    from app.config import AgentSettings
    from app.context import load_turn_context
    from app.context.window import DEFAULT_SYSTEM_PROMPT
    from app.memory import ConversationStore, open_store
    from app.models import ContentPart, Message

    if operation not in {"prepare", "read", "write"}:
        raise ValueError("operation must be prepare, read or write")
    if not 1 <= warm_runs <= 20:
        raise ValueError("warm_runs must be between 1 and 20")

    settings = AgentSettings()
    if not settings.database_url:
        raise RuntimeError("AGENT_DATABASE_URL is not configured")

    owner = "database-latency-benchmark-v1"
    fixture = "database-latency-read-fixture-v1"

    def message(role: str, value: str) -> Message:
        return Message(role=role, content=[ContentPart(kind="text", text=value)])

    if operation == "prepare":
        store = open_store(settings)
        try:
            existing_owner = store.thread_owner(fixture)
            if existing_owner not in {None, owner}:
                raise RuntimeError("latency fixture id belongs to another owner")
            if store.message_count(fixture) == 0:
                turns = []
                for index in range(4):
                    turns.extend(
                        [
                            message("user", f"latencyfixture question {index}"),
                            message("assistant", f"latencyfixture answer {index}"),
                        ]
                    )
                store.append(fixture, turns, owner)
                store.set_summary(fixture, "Representative earlier conversation.", 0)
            saved = set(store.facts(owner))
            for index in range(5):
                fact = f"latencyfixture durable fact {index}"
                if fact not in saved:
                    store.remember(fact, owner, fixture)
            return {"operation": operation, "fixture": "ready"}
        finally:
            store.close()

    query = "latencyfixture current question"

    def read_once(store: ConversationStore) -> dict[str, int]:
        context = load_turn_context(
            store, fixture, owner, query, 5, DEFAULT_SYSTEM_PROMPT
        )
        shape = {"history": len(context.history), "prelude": len(context.prelude)}
        if shape != {"history": 8, "prelude": 3}:
            raise RuntimeError("representative read fixture is absent or incomplete")
        return shape

    created_threads: list[str] = []

    def write_once(store: ConversationStore) -> dict[str, int]:
        thread_id = f"database-latency-write-{uuid.uuid4().hex}"
        created_threads.append(thread_id)
        count = store.append(
            thread_id,
            [message("user", "benchmark question"), message("assistant", "benchmark answer")],
            owner,
        )
        return {"messages": count}

    run_once = read_once if operation == "read" else write_once
    started = time.perf_counter()
    store = open_store(settings)
    try:
        shape = run_once(store)
        cold_ms = (time.perf_counter() - started) * 1000
        warm_ms = []
        for _ in range(warm_runs):
            warm_started = time.perf_counter()
            shape = run_once(store)
            warm_ms.append((time.perf_counter() - warm_started) * 1000)
        return {
            "operation": operation,
            "cold_ms": round(cold_ms, 3),
            "warm_ms": [round(value, 3) for value in warm_ms],
            "warm_max_ms": round(max(warm_ms), 3),
            "cold_pass": cold_ms <= 500,
            "warm_pass": max(warm_ms) <= 100,
            "shape": shape,
            "region": os.environ.get("MODAL_REGION", "unknown"),
        }
    finally:
        for thread_id in created_threads:
            store.delete_thread(thread_id)
        store.close()


async def _spawn(update_id: int) -> None:
    # ``spawn`` returns immediately and the durable inbox owns the retry state.
    process_telegram_update.spawn(update_id)


@app.function(
    image=control_image,
    secrets=[control_secret],
    cpu=0.25,
    memory=512,
    min_containers=0,
    max_containers=20,
    scaledown_window=2,
    timeout=30,
    include_source=False,
)
@modal.fastapi_endpoint(method="POST", docs=False, requires_proxy_auth=False)
async def telegram_webhook(request: Request):
    """Translate one HTTP request into the transport-neutral webhook core."""

    from fastapi.responses import JSONResponse

    from ui.telegram.inbox import PostgresUpdateInbox
    from ui.telegram.webhook import TelegramWebhook

    telegram, agent = _settings()
    inbox = PostgresUpdateInbox(agent.database_url, agent.database_schema)
    accepted = await TelegramWebhook(telegram, inbox, _spawn).accept(
        request.headers,
        await request.body(),
    )
    return JSONResponse({"detail": accepted.detail}, status_code=accepted.status)
