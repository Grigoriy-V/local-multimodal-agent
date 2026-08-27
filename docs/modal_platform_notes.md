# Modal platform notes

Verified 2026-08-27 against `modal.com/docs`: `guide/apps`, `guide/webhooks`,
`guide/scale`, `guide/cold-start`, `guide/function-invocation-methods`,
`guide/volumes`, `guide/secrets`, `guide/sandboxes`, `guide/memory-snapshots`,
`examples/vllm_inference`, `examples/vllm_throughput`.

This file records the platform facts this project's deployed profile depends on,
and the constraints that are easy to get wrong. It is not a Modal tutorial and
does not restate the documentation. Anything not listed here was not checked.
Re-verify exact numbers before depending on them; the platform changes and this
file does not update itself.

`ROADMAP.md` is the plan. This file is reference for building and coding against
it.

## Deployment shape

| Unit | What it is | Why separate |
|---|---|---|
| `assistant-control` | CPU app: Telegram webhook, worker function, LangGraph, tool routing | Deploys often; must not re-version the GPU app |
| `assistant-llm` | GPU app: vLLM behind an OpenAI-compatible HTTP server | Deploys rarely; owns the expensive image and weights |
| `assistant-sandbox` | Modal Sandboxes for ephemeral coding work | Created at runtime, not deployed |
| Postgres | External managed provider | Modal has no managed Postgres |
| Modal Volume | Model weights, vLLM compile cache, task artifacts | Write-once-read-many only |

An App "groups one or more Functions for atomic deployment and acts as a shared
namespace". Deployed apps persist until stopped; functions inside one scale
independently and an idle deployed app is not billed. Cross-app references by
name (`modal.Cls.from_name`, `modal.Function.from_name`) are used by working
code in the reference project but were not covered by the pages read here.

## Serving the model

Modal's own OpenAI-compatible vLLM example:

```python
@app.server(
    image=vllm_image, gpu=f"H200:{N_GPU}",
    scaledown_window=15 * MINUTES,
    startup_timeout=10 * MINUTES,
    volumes={"/root/.cache/huggingface": hf_cache_vol,
             "/root/.cache/vllm": vllm_cache_vol},
    port=VLLM_PORT, unauthenticated=True,
)
class Server: ...
```

Deployed URL shape: `https://<workspace>--<app>-server.<region>.modal.direct`,
serving `/v1/chat/completions`.

**Consequence for this project.** `MODEL_ENDPOINT` points at that URL and
`ModelBackend` needs no change. This is the whole reason the model interface
exists; do not add Modal-specific code to reach the model.

- `startup_timeout` is the container's own boot allowance and is unrelated to
  the client-side `MODEL_TIMEOUT`. Do not tune one expecting the other.
- `scaledown_window` is the idle-GPU dial: how long the GPU stays warm after the
  last request. Modal's example uses 15 minutes; shorter is cheaper and colder.
- `unauthenticated=True` in the example is example-grade. An open endpoint lets
  anyone spend GPU money, and worse, an unauthorized request still wakes the GPU
  before vLLM can answer 401. `@app.server` requires authentication by default,
  so the fix is to omit that argument rather than to add anything.

**Proxy auth needs no code change** (verified 2026-08-28, corrects an earlier
note here). Modal accepts proxy tokens two ways: the `Modal-Key` and
`Modal-Secret` headers, or `Authorization: Bearer <token-id>.<token-secret>`,
which the documentation calls compatible with OpenAI-style clients. The second
form is what `OpenAICompatibleBackend` already sends, so the token goes in
`MODEL_API_KEY` and nothing in `app/models/` changes. Token ids start with `wk-`
and secrets with `ws-`; create them in the dashboard or with
`modal workspace proxy-tokens`.

## Webhook and long-running work

Web endpoints: `@modal.fastapi_endpoint`, `@modal.asgi_app`, `@modal.wsgi_app`,
`@modal.web_server`. Request bodies up to 4 GiB, responses unlimited, WebSocket
messages up to 2 MiB. Rate limit 200 requests/second for new accounts with a
5-second burst multiplier; excess returns 429. Client IP is available.

**A webhook must not run the agent loop.** Telegram retries a webhook that does
not answer quickly, and this project's task lifecycle runs up to 300 seconds
across many sequential model calls. The webhook validates, persists, spawns and
returns.

`Function.spawn()` returns a `modal.FunctionCall` immediately. Spawned calls
"continue running if the calling process exits" and the result payload is stored
for 7 days. Persist `fc.object_id` and rebuild the handle later with
`modal.FunctionCall.from_id(...)`. `FunctionCall.get()` blocks by default; pass a
timeout to poll without blocking.

By contrast a synchronous `.remote()` call "will be cancelled within two minutes
after the caller hangs up" — which is why the blocking shape cannot carry this
project's work. Queue limits: synchronous max 2,000 queued and 25,000 total;
asynchronous up to 1,000,000 queued, 1,500/s versus 200/s.

**Telegram authentication is not Modal proxy auth.** Modal proxy auth expects
`Modal-Key` and `Modal-Secret` headers, which Telegram does not send; it sends
`X-Telegram-Bot-Api-Secret-Token`. The webhook therefore stays unauthenticated at
the Modal layer and verifies the Telegram secret token plus an allowed user list
inside the application.

## Sandboxes

Documented purpose matches this project's coding work directly: "secure
containers for executing untrusted user or agent code", including running
model-generated code and cloning repositories to run test suites.

```python
sb_app = modal.App.lookup("assistant-sandbox", create_if_missing=True)
sb = modal.Sandbox.create(app=sb_app, image=..., volumes=..., secrets=...)
p = sb.exec("python", "-c", "print('hello')")
sb.terminate(); sb.detach()
```

- Default maximum lifetime is 5 minutes, configurable up to 24 hours via
  `timeout`. `idle_timeout` terminates after inactivity.
- `Sandbox.from_id(object_id)` reattaches later. This is what lets one task span
  several webhook invocations; store the id with the task state.
- Volumes, Secrets and custom images are supported. For production, build the
  image once and reference it with `modal.Image.from_name(...)` instead of
  rebuilding per sandbox.
- Readiness probes (`modal.Probe.with_tcp` / `with_exec`) and `wait_until_ready()`
  exist when the sandbox must finish initializing first.
- Filesystem snapshots preserve state between sandbox instances.

**Consequence for this project.** A sandbox has no local filesystem path for the
host process. `read_file`, `write_file` and `edit_file` become a second
implementation over the sandbox API, not the same implementation with a
different root. The root-confinement rule still applies inside the sandbox.

## Storage

**Volumes are not a database.** The documentation states "last write wins",
"concurrent modifications of the same files should be avoided", and that
distributed file locking is not supported. The intended profile is
write-once-read-many. Volume v1 limits concurrent commits to five, has a hard
500,000 inode limit and degrades past ~50,000 files; v2 (beta) allows many
containers writing to *distinct* files, with last-write-wins still applying per
file.

This rules out SQLite on a Volume for the deployed profile — not as a
precaution, but by the documented semantics. Conversations, summaries, memory
and task state go to external Postgres.

Volumes are the right home for model weights, the vLLM compile cache and task
artifacts. Changes need `.commit()`; other containers need `.reload()` to see
them. Background commits happen every few seconds. A Volume appears empty during
reload, and open files prevent reloading.

**Secrets** are created from the dashboard, CLI or code (`Secret.from_name`,
`from_dict`, `from_dotenv`) and appear as environment variables. Keys up to
16,384 characters, values up to 32,768; use a Volume for anything larger. When
several secrets are attached, later ones override earlier duplicates. The
Postgres URL and the Telegram bot token belong here, never in the repository.

## Scaling and cold start

"By default, Modal Functions will scale to zero when there are no inputs to
process." Four parameters on `@app.function` / `@app.cls`:

- `scaledown_window` — idle time before shutdown; documented default 60 seconds,
  range 2–1200.
- `min_containers` — warm floor that prevents scaling to zero.
- `max_containers` — upper bound.
- `buffer_containers` — extra containers during active periods, for bursty
  traffic.

Modal boots containers in roughly one second; the rest of a cold start is the
application's own initialization. Containers are not considered warm until all
`@modal.enter` methods complete. The documented remedies are to bake weights in
ahead of time rather than downloading at boot, and to load independent files
concurrently.

**Memory snapshots do not fix weight loading.** `enable_memory_snapshot=True`
with the `@modal.enter(snap=True)` / `@modal.enter(snap=False)` split typically
gives 3–10x, and GPU state can be included via
`experimental_options={"enable_gpu_snapshot": True}`. But the documentation is
explicit: "if the majority of your initialization latency is spent loading
weights, GPU Memory Snapshots will generally not improve your cold start times."
For a 12B model that is exactly the dominant cost. Snapshots remove imports and
JIT work, not weight loading. Caveats: incompatible with multi-GPU code, can
fail with `torch.compile`, and randomness is preserved across restores.

## Re-check before relying on these

- `min_containers` default. `guide/scale` states functions scale to zero by
  default, implying 0; the `guide/cold-start` page was read as saying 1. Treat
  the default as unverified and set it explicitly.
- Cross-app `from_name` semantics and versioning behaviour, not covered by the
  pages read.
- Idle billing for containers inside `scaledown_window`.

## Regions: one is free, the other is a multiplier

Two different settings, easy to confuse because both appear as "region".

- **Routing region** (`routing_region`) — where the proxy that accepts the HTTP
  request sits. It defaults to `us-east` "for network efficiency" and is what
  appears in a deployed URL such as
  `…-server.us-east.modal.direct`. No surcharge.
- **Container region** (`compute_region`) — where the container actually runs.
  Setting it applies "a multiplier on top of our base usage pricing": **1.5x**
  for a broad region like `us`, **1.75x** for a narrow one like `us-west`.

**Consequence for this project.** Neither is set, so the GPU is scheduled
wherever capacity is cheapest and `us-east` in the URL is a default rather than
a choice. Pinning a region to shorten the network path is a bad trade here: a
turn makes a handful of sequential model calls, so a 100-150 ms round trip costs
about a second against generation time measured in seconds, while the multiplier
applies to every GPU second.

## Verified against the installed client

Checked 2026-08-28 against `modal` 1.5.4, not only the documentation.

- `@app.server` is current and accepts `image`, `gpu`, `volumes`, `port`,
  `scaledown_window`, `startup_timeout`, `min_containers`, `max_containers`,
  `unauthenticated` among others. There is no `requires_proxy_auth` parameter on
  it, because authentication is the default and `unauthenticated=True` is the
  opt-out.
- `Function.update_autoscaler(*, min_containers, max_containers,
  buffer_containers, scaledown_window)` exists, so the idle window can be
  changed on a deployed app with no redeploy. The documentation adds that a
  later deploy resets it to the decorator's value.
- A class decorated with `@app.server` registers as a **function**, not a class:
  it appears in `app.registered_functions` under its class name, and
  `modal.Cls.from_name` does not find it. Use `modal.Function.from_name`.
- Accepted `gpu=` strings: `T4, L4, A10, L40S, A100, A100-40GB, A100-80GB,
  RTX-PRO-6000, H100/H100!, H200, B200/B200+, B300`, with `:n` for several.
