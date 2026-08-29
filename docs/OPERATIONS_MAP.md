# Operations Map

This document maps the **current operational surface** of `local-multimodal-agent`: configuration, deployment, secrets, migrations, Telegram mode, runtime controls, storage and diagnostics.

It is a navigation/ownership document, not a deployment history. `ROADMAP.md` owns current work; `reports/` owns measurements and acceptance evidence; `AGENTS.md` owns permission and execution rules for coding agents.
`DECISIONS.md` explains approved durable operational choices. Read the relevant
entry when changing such a choice; this map remains the source for the current
operational surface and commands.

Never put secret values into repository documents, command examples, reports or chat output.

## Operational topology

```text
                         Modal

Telegram
   │
   ▼
assistant-control
   ├─ telegram_webhook          small CPU ingress
   ├─ process_telegram_update   CPU agent worker
   ├─ render_web_page           isolated CPU browser
   ├─ self_test                 runtime capability diagnostic
   └─ measure_database_latency  DB diagnostic
          │
          ├────────────> Neon/PostgreSQL
          │               conversations / facts / checkpoints / inbox
          │
          ├────────────> Modal Volume: assistant-workspaces
          │               per-user workspace directories
          │
          └────────────> assistant-llm-v2
                           A10 / vLLM / scale-to-zero
                           HF cache + vLLM cache Volumes
```

The CPU control plane and GPU model are separately deployed apps. Deploying `assistant-control` does not redeploy the model app.

## Configuration ownership

### Application settings

**Owner:** `app/config.py`

All normal application environment configuration belongs to one of these settings classes:

| Prefix | Class | Purpose |
|---|---|---|
| `MODEL_` | `ModelSettings` | model endpoint, model name, auth, timeouts/generation |
| `AGENT_` | `AgentSettings` | DB/store, checkpoints, workspace, context policy |
| `TELEGRAM_` | `TelegramSettings` | Bot API, webhook secret, access policy |
| `WEB_` | `WebSettings` | search, direct fetch, renderer/browser configuration |

Local example/defaults: `.env.example`.

Application code should not invent a second environment-loading path when the value belongs in one of these classes.

## Local configuration and deployed secret

### Local source

The project's local configuration is `.env` (not committed). `.env.example` documents names and safe defaults/placeholders.

### Deployed control-plane secret synchronization

**Existing owner: `tools/sync_control_secret.py`.**

Run from repository root:

```text
.venv\Scripts\python.exe tools/sync_control_secret.py
```

The script:

- reads local `.env`;
- publishes only an explicit allow-list;
- prints key names, never values;
- creates/replaces Modal Secret `assistant-control` using `--force`;
- intentionally does not copy the whole `.env`;
- supports source-name -> deployed-name translation.

Current allow-listed families include Telegram credentials/access configuration, deployed database settings, model endpoint/auth settings, and web search/renderer settings.

Important translation:

```text
local .env name:      DEPLOY_WEB_RENDERER_URL
published env name:   WEB_RENDERER_URL
```

This prevents the local profile from accidentally sending every `view_web_page` call to the deployed renderer.

**Do not create a new secret-sync script or type values manually into the provider as a new source of truth before inspecting this owner.**

## PostgreSQL/control-plane setup

**Owner:** `tools/setup_control_plane.py`.

Purpose: explicit trusted migration/setup for the deployed control plane.

It prepares:

```text
ConversationStore/PostgresStore schema
LangGraph PostgreSQL checkpoint tables
Telegram `telegram_updates` inbox table
```

The normal runtime intentionally does not run these migrations on each request.

Store schema version is **2** in both implementations (`PRAGMA user_version` for
SQLite, the `schema_version` row for PostgreSQL). Version 2 adds the `user_state`
table, which records which conversation each person is in. The step from 1 to 2
is additive: re-running the schema is the whole migration and no conversation is
touched, so no reset is needed to adopt it.

Resetting a store is a separate destructive operation and stays behind the human
gate for deleting or migrating a populated database. There is no application
path to it: `PostgresStore.drop_schema` refuses `public`, and the local file is
deleted by hand. Nothing about the local or deployed store is reset from a
worker starting up.

Primary configuration comes from `AgentSettings` / `AGENT_DATABASE_URL`.

The script also has an `--alternate` path for the configured alternate database used by latency comparison work.

## Telegram operating mode

Telegram supports two transport modes that are mutually exclusive from Telegram's perspective.

### Bot profile and native command menu

**Owner:** `tools/telegram_profile.py`.

Preview the intended description and `/new`, `/chats`, `/can`, `/stop`, `/help`
menu without contacting Telegram:

```text
.venv\Scripts\python.exe tools/telegram_profile.py
```

Publish them only after the human authorizes the external mutation:

```text
.venv\Scripts\python.exe tools/telegram_profile.py --publish
```

The tool reads `TELEGRAM_TOKEN` from settings. `/check` remains a working typed
diagnostic but is intentionally absent from the native product menu.

### Deployed webhook

**Registration/status owner:** `tools/telegram_webhook.py`.

Examples from repository root:

```text
# inspect current webhook status
.venv\Scripts\python.exe tools/telegram_webhook.py

# point Telegram at a deployed webhook
.venv\Scripts\python.exe tools/telegram_webhook.py --url <deployed-webhook-url>

# remove webhook and return to polling
.venv\Scripts\python.exe tools/telegram_webhook.py --delete
```

The tool reads `TELEGRAM_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` from settings and does not print the secret.

The webhook itself is `telegram_webhook` in `deploy/modal/control_app.py` and delegates to the transport-neutral core in `ui/telegram/webhook.py`.

### Local polling

Entry point:

```text
python -m ui.telegram.run
```

`ui/telegram/run.py` uses the same `TelegramAdapter` as deployment. It serializes updates from the same chat locally and allows different chats to run concurrently.

If a Telegram webhook is registered, Telegram refuses normal `getUpdates` polling until the webhook is deleted.

## Modal control-plane deployment

**Owner:** `deploy/modal/control_app.py`.

App name:

```text
assistant-control
```

The file defines three image shapes:

```text
control_image  -> dependencies + source; no Chromium
agent_image    -> Chromium/fonts + source; deployed agent worker
render_image   -> Chromium/fonts + source; isolated page renderer
```

Heavy dependencies/browser are layered below copied source so source-only changes can reuse earlier image layers.

### Main functions

#### `telegram_webhook`

Purpose: fast HTTP ingress.

Current resource shape in code:

```text
CPU: 0.25
memory: 512 MiB
min containers: 0
max containers: 20
scaledown window: 60 s
timeout: 30 s
```

It validates Telegram admission, persists the update, starts a worker and asks the model to wake in parallel when needed.

The webhook deliberately uses `control_image`, not `agent_image`, so it does not carry/import the browser/agent stack on its critical path.

#### `process_telegram_update`

Purpose: claim one durable update and run the full application turn.

Current resource shape:

```text
CPU: 1
memory: 2048 MiB
min containers: 0
max containers: 8
scaledown window: 60 s
timeout: 600 s
```

It mounts the persistent workspace Volume, reloads before a turn and commits after the turn.

#### `render_web_page`

Purpose: execute public page JavaScript in a separate trust boundary.

Current resource shape:

```text
CPU: 1
memory: 2048 MiB
min containers: 0
max containers: 4
scaledown window: 20 s
timeout: 180 s
proxy authentication: required
```

Critical isolation properties in code:

- no `assistant-control` secret;
- no database URL from the control secret;
- no user workspace volume;
- public URL is checked again in the renderer;
- response returns rendered text/screenshot/console/refusal evidence to the caller.

#### `self_test`

Runs the assistant's real capability probes in the deployed environment.

Default is free. Optional arguments can add:

```text
include_model=True   -> model/GPU probe
include_credit=True  -> provider-credit search probe
```

A deploy is not the same as an invocation; invoking this function can start containers and, depending on options, external paid resources.

#### `measure_database_latency`

Diagnostic for representative production read/write behavior and optional primary/alternate comparison. It is not application request handling.

## Modal model deployment

**Owner:** `deploy/modal/model_app.py`.

App name:

```text
assistant-llm-v2
```

Current model/server constants in code include:

```text
checkpoint: google/gemma-4-12B-it-qat-w4a16-ct
served name: gemma-4-12b-it
vLLM: 0.26.0
transformers: 5.14.1
GPU: A10
max model length: 16384
GPU memory utilization: 0.80
multimodal per-prompt limits: image=4, audio=1
min containers: 0
max containers: 1
scaledown window default: 12 s
concurrent inputs per GPU container: 32
```

The model endpoint requires Modal proxy authentication at the edge.

### Model functions

#### `fetch_weights`

CPU-only weight-cache population.

Use it when the pinned checkpoint is not already present in the HF cache Volume. It avoids downloading model weights while GPU billing is active.

#### `preflight`

CPU-only check for known vLLM/transformers/model-config startup failures. It is intended to catch known configuration regressions before paying for a GPU boot.

#### `Server`

The GPU class. It starts vLLM, performs warmup, sleeps it before snapshot, restores from CPU+GPU snapshot, wakes it, and serves the OpenAI-compatible endpoint.

Persistent deployment storage:

```text
assistant-hf-cache    -> model weights
assistant-vllm-cache  -> vLLM compile/cache
```

Neither is canonical conversation/user data.

## GPU scaledown without deploy

**Owner:** `deploy/modal/autoscale.py`.

Examples:

```text
python deploy/modal/autoscale.py
python deploy/modal/autoscale.py --window 300
```

This updates the running Modal class autoscaler without rebuilding images or redeploying the app.

Important behavior: a later `model_app.py` deploy resets the setting to the `SCALEDOWN_WINDOW` constant in that file. Persistent policy changes therefore belong in code after measurement; `autoscale.py` is the experiment/control surface.

## Storage ownership

### Local profile

```text
conversation/memory        AGENT_DATABASE -> SQLite file
ordinary checkpoints       AGENT_CHECKPOINTS -> SQLite file
task checkpoints           AGENT_TASK_CHECKPOINTS/default task checkpoint file
workspace                  AGENT_WORKSPACE -> local directory
```

Exact defaults live in `AgentSettings` and `.env.example`.

### Deployed profile

```text
Neon/PostgreSQL
  ├─ conversations/messages/summaries/facts
  ├─ LangGraph checkpoint tables
  └─ telegram_updates durable inbox

Modal Volume assistant-workspaces
  └─ /workspaces/<canonical-user>/...

Modal Volumes
  ├─ assistant-hf-cache
  └─ assistant-vllm-cache
```

The deployed CPU worker may disappear between turns. Durable product state must therefore be in these stores rather than process memory.

## Web operational configuration

Current web capability has three distinct operational paths:

```text
search_web     -> Firecrawl provider
fetch_page     -> direct outbound HTTP from agent worker
view_web_page  -> configured renderer endpoint in deployment
```

Relevant settings:

```text
WEB_FIRECRAWL_API_KEY
WEB_FIRECRAWL_ENDPOINT
WEB_FALLBACK_USER_AGENT
WEB_LOCAL_BROWSER
WEB_RENDERER_URL          # deployed runtime name
WEB_RENDERER_KEY
```

Local `.env` intentionally uses `DEPLOY_WEB_RENDERER_URL` for the deployed renderer address; the secret sync tool renames it during publishing.

The deployed `agent_image` sets `WEB_LOCAL_BROWSER=0`. If renderer configuration is missing, public browser viewing should fail instead of silently running page JavaScript in the worker that holds secrets.

## Diagnostics and checks

### `/can`

User-facing claim generated from current runtime wiring. It does not call the model.

Owner path:

```text
app/capabilities.py -> capability_report()
ui/telegram/adapter.py -> /can dispatch
```

### `/check`

Runs actual capability probes from the current runtime. Telegram's normal `/check` uses free probes and does not wake the GPU.

Owner paths:

```text
app/preflight.py
app/agent/runtime.py -> Agent.selftest()
ui/telegram/adapter.py
```

Deployed `self_test` in `control_app.py` exists for the same question inside the actual container and can optionally include GPU/provider-credit checks.

### Local doctor

`python scripts/doctor.py`

Use for environment-level local diagnostics before inventing one-off checks.

### Model wake measurement

`scripts/measure_endpoint_wake.py` owns the dedicated endpoint wake measurement workflow.

### Broad smoke/live scripts

`scripts/smoke_test.py`, `scripts/stage3_live.py`, and `scripts/v1_live.py` are existing runners. Some reflect earlier project stages; inspect their exact scope before treating them as current product acceptance.

## Work/evidence logging

**Owner:** `tools/work_log.py`.

Append-only journals:

```text
reports/agent_tasks.jsonl
reports/ml_work.jsonl
```

The tool captures repository metadata (branch, HEAD, changed files) when appending. Use it rather than hand-editing JSONL if a journal entry is required by `AGENTS.md`.

Human-readable implementation evidence belongs in `reports/` rather than in the four stable project maps.

## Common operational tasks: find the owner first

| Need | Existing owner |
|---|---|
| Add/change env setting | `app/config.py` + `.env.example` |
| Publish control secret from `.env` | `tools/sync_control_secret.py` |
| Create/migrate deployed DB/checkpoints/inbox | `tools/setup_control_plane.py` |
| Register/remove/show Telegram webhook | `tools/telegram_webhook.py` |
| Preview/publish Telegram profile and command menu | `tools/telegram_profile.py` |
| Deploy CPU control plane | `deploy/modal/control_app.py` |
| Deploy model server | `deploy/modal/model_app.py` |
| Change current GPU idle window without deploy | `deploy/modal/autoscale.py` |
| Diagnose deployed capabilities | `control_app.py::self_test` |
| Diagnose local install | `scripts/doctor.py` |
| Measure endpoint wake | `scripts/measure_endpoint_wake.py` |
| Record/search agent/ML work journal | `tools/work_log.py` |

## Operations invariants

- Treat `.env` as the local configuration source; publish a reviewed allow-list, not the whole file.
- Do not print or store secret values in reports or shell command strings.
- Do not run application DB migrations implicitly on normal serverless request paths.
- Do not conflate deploying a function with invoking it; invocation can start billable resources.
- Keep public page JavaScript away from control-plane secrets in the deployed profile.
- Keep the model app independent from the application code; their runtime contract is the configured OpenAI-compatible endpoint.
- Keep local/deployed differences behind settings, stores and deployment adapters rather than branching `app/`.
- Check `tools/`, `scripts/` and `deploy/` before adding an operational helper: many correct owners are intentionally not imported by the application.
