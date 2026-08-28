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
    .uv_sync(
        ".",
        groups=["app", "agent", "postgres", "deploy"],
        frozen=True,
        extra_options="--no-install-project",
    )
    .add_local_dir("app", "/root/project/app", copy=True)
    .add_local_dir("ui", "/root/project/ui", copy=True)
    .add_local_file(
        "deploy/modal/control_app.py", "/root/project/control_app.py", copy=True
    )
    .env({"PYTHONPATH": "/root/project"})
)

# Load the webhook's modules in the container's global scope. `Image.imports` is
# what makes that safe: the block runs only inside the container, so importing
# this file locally to deploy it stays as cheap as before. The function bodies
# below still import what they use, which after this is a dictionary lookup —
# they are left that way so each function still reads as a list of what it
# depends on.
#
# Only the webhook's path is here, deliberately. Importing the agent stack would
# put it in every webhook container too, and that import is exactly what this
# function's cold start was paying for: 1.67-3.86 s of execution before the
# stack was moved out of reach, 0.34-0.46 s after.
#
# The worker keeps its imports inside itself until its own cold start has been
# measured rather than assumed.
with control_image.imports():
    from fastapi.responses import JSONResponse  # noqa: F401

    from app.config import AgentSettings, TelegramSettings  # noqa: F401
    from ui.telegram.inbox import PostgresUpdateInbox  # noqa: F401
    from ui.telegram.webhook import TelegramWebhook  # noqa: F401


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
    # 15 s, not the platform floor. The arithmetic here is the opposite of the
    # GPU's: a cold start costs about three seconds of someone's attention,
    # while holding this container costs $0.00026 for the whole window. The
    # expensive resource is the person waiting, not the CPU.
    # 60 s, matching the webhook, so a conversation stays warm as one thing
    # rather than in halves. Measured from the platform's own startup column:
    # a cold worker costs 3.23 s of scheduling plus 1.71 s of first-execution
    # work — imports, graph construction, first connection — for 4.93 s over a
    # warm one, which is the largest CPU number in the chain.
    #
    # This container is dearer to hold than the webhook: a full core with 2 GiB
    # is $0.0000175 a second, so a minute costs $0.00105 against the webhook's
    # $0.00026. At a hundred wakes a day that is about $3 a month, against the
    # roughly $46 of GPU it sits in front of.
    scaledown_window=60,
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
    timeout=180,
    include_source=False,
)
async def self_test(include_model: bool = False) -> str:
    """Try every capability here, in the environment the assistant runs in.

    The point is the environment, not the code: the offline suite already covers
    the logic, and every failure this catches — a missing browser, a store that
    breaks on the second call, tables in the wrong schema — is invisible until
    something runs inside a deployed container.

    Free by default. `include_model` adds one completion, which wakes the GPU,
    so it is a separate decision every time it is made.
    """

    from app.agent.runtime import create_agent
    from app.config import AgentSettings
    from ui.telegram.adapter import DELIVERY

    telegram, _ = _settings()
    owner = "deployed-self-test"
    agent = create_agent(
        agent_settings=AgentSettings(), user_id=owner, delivery=DELIVERY
    )
    try:
        costs = ("free", "gpu") if include_model else ("free",)
        return await agent.selftest(f"self-test-{owner}", costs)
    finally:
        await agent.aclose()


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
def measure_database_latency(
    operation: str, warm_runs: int = 5, database: str = "primary"
) -> dict[str, object]:
    """Measure one complete production read or write without touching the model.

    ``prepare`` creates a representative isolated read fixture. A later
    ``read`` or ``write`` invocation must happen only after Neon is known to be
    idle if its first sample is to count as database-cold acceptance.

    ``database`` selects between the deployed database and a second one
    configured as ``AGENT_ALT_DATABASE_URL``. ``compare`` measures the warm read
    against both **inside one invocation**, which is the only way to get an
    honest answer: placement is unpinned, so two separate calls can run in two
    regions and the difference between them would not be the difference between
    the databases. A DSN is never passed as an argument — it would then appear
    in the platform's own call records — so the choice is a name and the values
    stay in the secret.
    """

    import os
    import time
    import uuid

    from app.config import AgentSettings
    from app.context import load_turn_context
    from app.context.window import DEFAULT_SYSTEM_PROMPT
    from app.memory import ConversationStore, open_store
    from app.models import ContentPart, Message

    if operation not in {"prepare", "read", "write", "compare"}:
        raise ValueError("operation must be prepare, read, write or compare")
    if not 1 <= warm_runs <= 20:
        raise ValueError("warm_runs must be between 1 and 20")
    if database not in {"primary", "alternate"}:
        raise ValueError("database must be primary or alternate")

    configured = AgentSettings()

    def profile(name: str) -> AgentSettings:
        url = configured.database_url if name == "primary" else configured.alt_database_url
        if not url:
            key = "AGENT_DATABASE_URL" if name == "primary" else "AGENT_ALT_DATABASE_URL"
            raise RuntimeError(f"{key} is not configured")
        return configured.model_copy(update={"database_url": url})

    settings = profile(database)

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

    def sample(chosen: AgentSettings, run_once) -> dict[str, object]:
        started = time.perf_counter()
        store = open_store(chosen)
        try:
            shape = run_once(store)
            cold_ms = (time.perf_counter() - started) * 1000
            warm_ms = []
            for _ in range(warm_runs):
                warm_started = time.perf_counter()
                shape = run_once(store)
                warm_ms.append((time.perf_counter() - warm_started) * 1000)
        finally:
            for thread_id in created_threads:
                store.delete_thread(thread_id)
            created_threads.clear()
            store.close()
        return {
            "cold_ms": round(cold_ms, 3),
            "warm_ms": [round(value, 3) for value in warm_ms],
            "warm_max_ms": round(max(warm_ms), 3),
            "warm_min_ms": round(min(warm_ms), 3),
            "shape": shape,
        }

    if operation == "compare":
        # One container, one region, back to back. The only thing that differs
        # between the two results is where the database is.
        return {
            "operation": operation,
            "region": os.environ.get("MODAL_REGION", "unknown"),
            "primary": sample(profile("primary"), read_once),
            "alternate": sample(profile("alternate"), read_once),
        }

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
            "database": database,
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


_waker: object | None = None


async def _warm() -> bool:
    """Start the model waking while the update worker is still being scheduled.

    The webhook decides *whether* to call this — it knows whether the update
    needs a model at all — and this decides *how*, which is the platform's
    business and not the transport's.

    The backend is kept for the life of the container so that a second message
    reuses the connection instead of paying another TLS handshake to wake a
    model that is already awake. If the client is ever unusable — a different
    event loop, a closed pool — `warm` returns False and the turn is the one we
    had before this existed, which is why nothing here re-raises.
    """

    global _waker

    from app.config import ModelSettings
    from app.models.openai_compatible import OpenAICompatibleBackend

    if _waker is None:
        _waker = OpenAICompatibleBackend(ModelSettings())
    return await _waker.warm()


async def _spawn(update_id: int) -> None:
    # ``spawn`` returns immediately and the durable inbox owns the retry state.
    # The async form matters here rather than being a style preference: the
    # blocking one is a synchronous RPC to Modal's control plane made from
    # inside the event loop, and it stalled the webhook that Telegram is
    # waiting on. Modal's own runtime warned about it in production logs.
    await process_telegram_update.spawn.aio(update_id)


@app.function(
    image=control_image,
    secrets=[control_secret],
    cpu=0.25,
    memory=512,
    min_containers=0,
    max_containers=20,
    # 60 s, and the reasoning is the opposite of the GPU's. What is left of this
    # function's cold start is ~3.5 s of Modal scheduling that no code removes —
    # measured, after both the imports and a memory snapshot were tried against
    # it. The only remaining lever is not being cold, and here that is nearly
    # free: a quarter-core with 512 MiB costs $0.0000044 a second, so holding the
    # window open for a full minute after the last update costs $0.00026. A
    # hundred wakes a day is under a dollar a month.
    #
    # A minute is chosen against how people actually type: it covers reading a
    # reply and answering it, which is the case that was paying 3.5 s at 15 s.
    scaledown_window=60,
    timeout=30,
    include_source=False,
    # No `enable_memory_snapshot`. It was tried here and measured over nine cold
    # starts, and the numbers said to take it out:
    #
    #     before snapshots      mean 5.36 s   execution 1.67-3.86 s
    #     snapshot creation     mean 8.56 s   6 of the 9 cold starts
    #     snapshot restore      mean 4.06 s   execution 0.34-0.46 s
    #
    # A restore is only about a second better than no snapshot, and subtracting
    # execution shows why: the container itself still takes ~3.5 s either way.
    # Restoring skips the initialization, not the scheduling — and the
    # initialization had already been removed by keeping the agent stack out of
    # this function's imports. The two are substitutes, and the free one won.
    # What is left is spent creating snapshots that a later cold start may not
    # even land on, because a snapshot only restores onto the worker type that
    # made it and placement here is unpinned.
    #
    # Reconsider only for a function with real init to capture. This one has none
    # left, which is the point.
)
@modal.fastapi_endpoint(method="POST", docs=False, requires_proxy_auth=False)
async def telegram_webhook(request: Request):
    """Translate one HTTP request into the transport-neutral webhook core."""

    from fastapi.responses import JSONResponse

    from ui.telegram.inbox import PostgresUpdateInbox
    from ui.telegram.webhook import TelegramWebhook

    telegram, agent = _settings()
    inbox = PostgresUpdateInbox(agent.database_url, agent.database_schema)
    accepted = await TelegramWebhook(telegram, inbox, _spawn, warm=_warm).accept(
        request.headers,
        await request.body(),
    )
    return JSONResponse({"detail": accepted.detail}, status_code=accepted.status)
