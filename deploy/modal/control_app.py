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
