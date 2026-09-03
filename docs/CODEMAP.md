# Code Map

This document is the low-cost navigation index for `local-multimodal-agent`.
Its purpose is to help a developer or coding agent find the **existing owner** of a behavior before reading broad parts of the repository or creating a second implementation.

It is not an architecture history and not a roadmap. Current work is in `ROADMAP.md`; product invariants are in `docs/PRODUCT.md`; the conceptual system map is in `docs/PROJECT_MAP.md`; operations are in `docs/OPERATIONS_MAP.md`.
Approved durable rationale is in `DECISIONS.md`. Consult the relevant entry
after locating the owner when a boundary is being changed or reconsidered;
do not use the decision history as a substitute for the current code map.

## Rule for exploration

> **Find the existing owner before creating another owner.**

Before adding a new script, service, registry, storage path, deployment entry point, browser launcher, secret writer, tool abstraction, message type or UI workflow:

1. find the intent in this map;
2. inspect the listed owner file and related symbols;
3. search the repository for the named symbols / environment keys;
4. inspect the closest tests;
5. only then decide whether a new owner is actually required.

This is particularly important for `tools/`, `scripts/` and `deploy/`: operational functionality may not be reachable by following imports from `app/`.

## First files to read by task

| Intent | Primary owner | Read next / search terms |
|---|---|---|
| Understand product principle | `docs/PRODUCT.md` | `ROADMAP.md`, `AGENTS.md` |
| Understand current architecture | `docs/PROJECT_MAP.md` | this file |
| Understand current task/order | `ROADMAP.md` | linked reports |
| Understand why a durable boundary exists | `DECISIONS.md` | the current owner in this map, linked evidence |
| Change environment/config | `app/config.py` | `env.example`, `ModelSettings`, `AgentSettings`, `TelegramSettings`, `WebSettings` |
| Change the agent loop | `app/agent/graph.py` | `build_agent`, `AgentState`, `interrupt`, `tests/test_agent_graph.py` |
| Change what one turn may spend | `app/agent/graph.py` | `TurnBudget`, `exceeded`, `BUDGET_EXHAUSTED`, `tests/test_turn_bounds.py` |
| Change when a repeating failed call ends a turn | `app/agent/graph.py` | `failed_before`, `MAX_IDENTICAL_FAILURES`, `REPEATED_FAILURE`, `ENDING`, `tests/test_repeated_failure.py` |
| Change how a running turn is stopped | `app/agent/stop.py` | `StopRequests`, `MemoryStopRequests`, `PostgresStopRequests`, `asked_to_stop` |
| Change whether a model result ends the turn | `app/agent/stopping.py` | `TurnStopping`, `Candidate`, `Steering`, `Steered`, `STOP_ON_ANSWER`, `settled`, `carried`, `tests/test_turn_stopping.py` |
| Change the agent's own plan for a turn | `app/tools/todo.py` | `todo_write`, `normalise`, `current`, `unfinished`, `tests/test_todo.py` |
| Change what an unfinished plan does to an ending | `app/agent/todo.py` | `FinishesItsOwnList`, `INSTRUCTION`, `Candidate.steerings` |
| Change how much a plan is encouraged | `app/capabilities.py`, `app/tools/todo.py` | `_planning_lines`, `DESCRIPTION` — wording only; nothing classifies a request |
| Change what the person sees of the plan | `ui/telegram/adapter.py` | `plan_lines`, `PLAN_MARKS`, `ToolActivity.plan`, `ToolActivity.show` |
| Change which updates skip the conversation queue | `ui/telegram/wire.py` | `travels_out_of_band`, `needs_model`, `InboxJob.control` |
| Change agent wiring/context/tools | `app/agent/runtime.py` | `Agent`, `create_agent`, `toolbox`, `_graph` |
| Change how an answer streams as it is written | `app/agent/graph.py`, `ui/telegram/adapter.py` | `complete`, `ASSISTANT_DELTA`, `AssistantDelta`, `MessageProduced`, `AnswerWithdrawn`, `AnswerPreview`, `StreamedCompletion` |
| Change model-agnostic message types | `app/models/base.py` | `Message`, `ContentPart`, `ToolCall`, `ModelBackend` |
| Change OpenAI/vLLM request translation | `app/models/openai_compatible.py` | `OpenAICompatibleBackend`, `build_messages`, `parse_completion` |
| Reproduce or fix the served Gemma 4 tool parser | `tools/gemma4_parser.py` | `vendored_args`, `fixed_args`, `extract_calls`, `parse_arguments`, `CorruptArguments`, `tests/test_gemma4_parser.py` |
| Change the stable prompt core (names no tool) | `app/context/window.py` | `DEFAULT_SYSTEM_PROMPT` |
| Change prompt layer order / context replay | `app/context/window.py` | `build_prelude`, `facts_layer`, `Context`, `ContextPolicy` |
| Change what is shortened on the model-visible surface | `app/context/window.py` | `Context.surface`, `Surface`, `shortened`, `within_media_budget` |
| Change the person's context size choice | `app/context/choice.py`, `app/agent/runtime.py` | `context_choice`, `set_context_choice`, `Agent.budget`, `Agent.context_report`, `Agent.compact` |
| Read or write a person's standing instructions | `app/instructions.py` | `AGENTS.md`, `read_instructions`, `write_instructions`, `instruction_message` |
| Change context folding/summary | `app/context/summary.py`, `app/context/persistence.py` | `fold_older_messages`, `load_turn_context` |
| Change when a conversation is folded | `app/agent/graph.py` | `fitted`, `context_folded` |
| Estimate how large a request is | `app/models/base.py`, `app/models/openai_compatible.py` | `estimate_tokens`, `measure_request`, `CHARS_PER_TOKEN`, `MEDIA_TOKENS`, `_calibrate` |
| Change how much context a request may use | `app/agent/runtime.py`, `app/config.py` | `Agent.budget`, `context_fraction`, `context_tokens` |
| Change conversation/memory contract | `app/memory/base.py` | `ConversationStore`, `TurnContextRecords` |
| Measure a turn: identity, timings, counts, outcome | `app/telemetry/` | `TurnTrace`, `Telemetry`, `TurnRun`, `TraceEvent`, `NO_TRACE`, `RUN_ID` |
| Change where turn telemetry is stored | `app/telemetry/open.py` | `open_telemetry`, `SqliteTelemetry`, `PostgresTelemetry` |
| Read a measured turn back | `app/telemetry/inspect.py`, `tools/show_run.py` | `render_run`, `render_listing`, `recent_runs` |
| Read the loop's steps back | `app/telemetry/inspect.py` | `steps`, `step_section`, `loop_step` |
| Read the model server's engine metrics | `app/telemetry/vllm.py` | `parse_metrics`, `discover`, `restarted`, `summarize` |
| Measure prefill, decode and prefix cache | `tools/vllm_baseline.py` | `plan`, `measure`, `report` |
| Compare one system prompt against another | `tools/prompt_scenarios.py` | `SCENARIOS`, `select`, `run_one`, `render`, `--dry-run` |
| Estimate GPU seconds and cost of a turn | `app/telemetry/cost.py` | `gpu_cost`, `IDLE_WINDOW_SECONDS`, `A10_USD_PER_SECOND` |
| Reach the model endpoint's auth headers | `app/models/openai_compatible.py` | `auth_headers` |
| Change SQLite persistence | `app/memory/store.py` | `SqliteStore` |
| Change deployed PostgreSQL persistence | `app/memory/postgres.py` | `PostgresStore`, `turn_context`, `append` |
| Change store selection | `app/memory/open.py` | `open_store` |
| Change graph checkpoints | `app/checkpoints.py` | `CheckpointHandle`, `setup_postgres_checkpoints` |
| Add/change a tool primitive or execution lifecycle | `app/tools/base.py`, `app/tools/execution.py` | `Tool`, `ToolError`, `Toolbox`, `ToolExecutor`, `pre_execute`, `execute`, `post_execute`, `project`, `tests/test_tool_outcomes.py` |
| Add a failure code, or read one | `app/models/base.py`, `app/tools/base.py`, each family module | `ToolFailure`, `Message.failure`, `UNKNOWN_TOOL` … `FAILED`, a family's own constants |
| Add/change a capability/grant | `app/tools/capabilities.py` | `CapabilityRegistry`, `CapabilityGrant`, `DEFAULT_CAPABILITIES` |
| Change what assistant says it can do, or assemble its system message | `app/capabilities.py` | `system_message`, `capability_brief`, `capability_report`, `tool_inventory` |
| Change filesystem tools/path scope | `app/tools/filesystem.py` | `resolve_in_root`, `filesystem_tools` |
| Change attachment admission | `app/attachments.py` | `admit_uploads`, `load_attachments`, limits |
| Change document parsing/rendering | `app/documents.py` | `read_sections`, `render_pages`, `media_type_for` |
| Change document model tools | `app/tools/documents.py` | `read_document`, `view_pages`, `document_tools` |
| Change explicit file delivery | `app/tools/presentation.py` | `send_file`, `presentation_tools`, `outbound=True` |
| Change local HTML inspection or what it reports | `app/tools/browser.py` | `inspect_page`, `page_report`, `observe`, `browser_tools` |
| Change the browser session, its snapshot or an action | `app/tools/chromium.py` | `BrowserSession`, `open_browser`, `format_snapshot`, `_SNAPSHOT`, `tests/test_browser_session.py` |
| Change Chromium/CDP internals | `app/tools/chromium.py` | browser launch, `CdpSession`, request policy |
| Change public web security/networking | `app/web.py` | `check_destination`, `fetch_page`, `render_page`, `render_locally` |
| Change model-facing web tools | `app/tools/web.py` | `search_web`, `fetch_page`, `view_web_page`, tool builders |
| Change Telegram behavior | `ui/telegram/adapter.py` | `TelegramAdapter`, `_on_message`, `_deliver`, `_on_callback` |
| Change which conversation a person is in | `ui/telegram/adapter.py`, `app/memory/base.py` | `current_thread`, `new_thread`, `_choose_conversation`, `active_thread`, `set_active_thread` |
| Change Telegram raw update parsing | `ui/telegram/wire.py` | `Incoming`, `read_update`, `needs_model` |
| Change Telegram Markdown rendering | `ui/telegram/markdown.py` | `render`, `balanced` |
| Change Telegram Bot API transport/presentation primitives | `ui/telegram/api.py` | `TelegramClient`, `Formatted`, `PRODUCT_COMMANDS` |
| Change how a Telegram rate limit is handled | `ui/telegram/api.py` | `retry_after`, `MAX_RETRY_AFTER_SECONDS`, `MAX_RATE_LIMIT_HOLDS`, `_call` |
| Change deployed webhook handoff | `ui/telegram/webhook.py` | `TelegramWebhook`, `TelegramUpdateWorker` |
| Change deployed Telegram inbox | `ui/telegram/inbox.py` | `PostgresUpdateInbox`, `UpdateInbox` |
| Change local Telegram polling | `ui/telegram/run.py` | `PollingBot`, per-chat locks |
| Change Chainlit adapter | `ui/chainlit_app.py` | `render`, `create_runtime_with_stops`, `to_message` |
| Change Chainlit persisted history | `ui/chainlit_history.py` | `MemoryStoreDataLayer` |
| Change deployed CPU control plane | `deploy/modal/control_app.py` | `telegram_webhook`, `process_telegram_update`, `render_web_page`, images |
| Change model deployment | `deploy/modal/model_app.py` | `Server`, `fetch_weights`, `preflight`, `SCALEDOWN_WINDOW` |
| Change running GPU idle window without deploy | `deploy/modal/autoscale.py` | `update_autoscaler` |
| **Synchronize deployed control-plane secrets** | **`tools/sync_control_secret.py`** | **`ALLOWED`, `assistant-control`, `DEPLOY_WEB_RENDERER_URL`** |
| Run deployed DB/checkpoint/inbox migrations | `tools/setup_control_plane.py` | `setup_control_plane`, `--alternate` |
| Register/delete/check Telegram webhook | `tools/telegram_webhook.py` | `setWebhook`, `deleteWebhook`, `getWebhookInfo` |
| Preview/publish Telegram bot profile and command menu | `tools/telegram_profile.py` | `--publish`, `PRODUCT_COMMANDS`, bot descriptions |
| Append/search work journals | `tools/work_log.py` | `reports/agent_tasks.jsonl`, `reports/ml_work.jsonl` |
| Diagnose local installation | `scripts/doctor.py` | diagnostics |
| Measure model endpoint wake | `scripts/measure_endpoint_wake.py` | wake measurement |
| Run the live loop acceptance (wakes the GPU) | `scripts/loop_live.py` | scenarios A–E, `Turn`, PASS/FAIL per check, exit code |
| Run broad smoke/live legacy checks | `scripts/smoke_test.py`, `scripts/stage3_live.py`, `scripts/v1_live.py` | historical stage runners |
| Migrate local workspace data | `scripts/migrate_workspace.py` | migration logic |

## Repository shape

```text
app/                 application domain and runtime
  agent/             the agent loop, its wiring, its budget, its stop and its
                     turn-stopping seam
  context/           prompt context and compaction
  memory/            conversation/fact store contract + implementations
  telemetry/         turn records, traces and the recorder handed to the app
  models/            model contract + OpenAI-compatible adapter
  tools/             tool/capability implementations
  api/               currently empty stub
  attachments.py     input admission
  capabilities.py    truthful runtime capability description
  checkpoints.py     LangGraph saver lifecycle
  config.py          all environment settings
  documents.py       document parsers/rendering primitives
  web.py             public-web networking/security/render routing

deploy/modal/         Modal CPU/GPU deployment code and autoscale tool
ui/                   Chainlit and Telegram adapters
  telegram/           Bot API, adapter, webhook, inbox, wire format, polling
tools/                operational repository tools (important: inspect directly)
scripts/              diagnostics, migrations, smoke/measurement runners
tests/                offline contract/unit/integration tests
reports/              evidence, implementation reports and append-only journals
docs/                 stable product/project/code/operations maps
ROADMAP.md             current state/order/approved work
AGENTS.md              working rules for coding agents
```

## Core ownership details

### `app/config.py` is the environment owner

Do not scatter `os.environ` reads through application code.

Current settings families:

```text
MODEL_*      -> ModelSettings
AGENT_*      -> AgentSettings
TELEGRAM_*   -> TelegramSettings
WEB_*        -> WebSettings
```

`env.example` documents local names and defaults.

A deployed variable may intentionally use a different source name locally. Example: `DEPLOY_WEB_RENDERER_URL` in `.env` is published as `WEB_RENDERER_URL` by `tools/sync_control_secret.py` so the local profile does not accidentally use the deployed renderer.

### `app/models/base.py` is the model domain owner

Do not add provider-specific messages, tokenizers or processors to agent/context/tool code.

Search symbols:

```text
ModelBackend
Message
ContentPart
ToolCall
Completion
Usage
```

`ContentPart.outbound` means an explicit presentation action has already been chosen. It is not evidence for a later model request.

### `app/agent/runtime.py` is the main application wiring seam

If a feature is present in tools but absent from the agent, inspect `Agent.toolbox()`, `CapabilityRegistry`, the current `CapabilityGrant` and delivery filtering here before adding a second wiring path.

Useful symbols:

```text
Agent
create_agent
user_workspace
CHECKPOINT_TYPES
toolbox
capabilities
selftest
```

### `app/tools/capabilities.py` versus `app/capabilities.py`

These files have related names but different jobs:

```text
app/tools/capabilities.py
  permission/wiring side
  Capability / CapabilityGrant / CapabilityRegistry
  turns grants into Toolboxes

app/capabilities.py
  truth/reporting side
  reads actual Toolbox + admission + delivery
  builds model capability brief and /can report
```

Do not merge these concepts by accident.

### Tool ownership

```text
base.py          Tool / Toolbox contract, ToolError, runtime failure codes, coercion
execution.py     pre_execute / execute / post_execute lifecycle, bounds, sanitizing, projection
filesystem.py    list/read/write/edit workspace files
documents.py     read_document / view_pages
presentation.py  send_file (explicit outbound action)
browser.py       inspect_page for local/self-contained HTML (observation only)
chromium.py      Chrome/Edge launch, CDP session, BrowserSession with snapshot/refs/actions
web.py           search_web / fetch_page / view_web_page wrappers
memory.py        remember_fact / search_memory
todo.py          todo_write, and the plan folded back out of a turn
```

If a new tool needs an existing execution primitive, extend/reuse the primitive rather than cloning it under a new tool name.

### Web ownership is intentionally split

```text
app/tools/web.py    model-facing Tool definitions + workspace screenshot artifacts
app/web.py          URL validation, DNS/IP policy, fetch/search/render transport
app/tools/chromium.py
                    browser process / CDP mechanics / BrowserSession
```

Do not add another URL validator or Chromium launcher without checking these three owners.

### Document ownership is intentionally split

```text
app/attachments.py     decide whether upload becomes media input or saved document
app/documents.py       parse/render document bytes
app/tools/documents.py expose bounded read/view actions to the model
app/tools/presentation.py
                       explicitly send a chosen saved/rendered file
```

### Telegram ownership is intentionally split

```text
wire.py       raw Telegram JSON -> minimal Incoming; model-free predicate;
              canonical identity and the conversation a turn is serialized by
markdown.py   ordinary Markdown -> safe Telegram HTML/plain blocks
api.py        Bot API network calls + Telegram presentation primitives
adapter.py    Incoming <-> application + chat presentation/activity state
inbox.py      durable deployed update queue, leased per conversation
webhook.py    validate/admit/spawn/worker core
run.py        local long-poll driver
```

If changing deployed webhook latency, do not move agent imports into `wire.py`; that module's standard-library-only boundary is deliberate and tested.

### Deployment ownership

`deploy/modal/control_app.py` owns only deployed CPU/platform wiring. It should call the same app/UI code rather than reimplementing agent behavior.

`deploy/modal/model_app.py` owns only the model-serving deployment. `app/` does not import it.

## Existing operational owners — check before inventing scripts

This section exists because operational tools are easy to miss when exploring by imports.

### Secrets

**Owner:** `tools/sync_control_secret.py`

Purpose: copy an explicit allow-list from local `.env` into Modal Secret `assistant-control`, replacing the secret atomically with `--force`.

Search terms:

```text
sync_control_secret
SECRET_NAME
ALLOWED
DEPLOY_WEB_RENDERER_URL
WEB_RENDERER_URL
assistant-control
```

Do **not** create another Modal secret synchronization mechanism before inspecting this file.

### Control-plane migrations

**Owner:** `tools/setup_control_plane.py`

Creates/migrates:

- conversation store schema;
- PostgreSQL LangGraph checkpoint tables;
- Telegram durable inbox.

The runtime does not silently run these migrations on each request.

### Telegram webhook registration

**Owner:** `tools/telegram_webhook.py`

This switches Telegram between webhook delivery and long polling and reports webhook status.

### Telegram bot profile

**Owner:** `tools/telegram_profile.py`

Without arguments it previews the bot description, short description and native
command menu. `--publish` sends them to Telegram and is therefore an explicit
external mutation rather than adapter startup behavior.

### GPU autoscaling experiment

**Owner:** `deploy/modal/autoscale.py`

Changes the running Modal class `scaledown_window` without a redeploy. A later model-app deploy resets the value to `SCALEDOWN_WINDOW` in `model_app.py`.

### Work journals

**Owner:** `tools/work_log.py`

Writes/searches:

```text
reports/agent_tasks.jsonl
reports/ml_work.jsonl
```

Prefer the tool over manually editing append-only journal JSON.

## Test discovery map

The suite is broad; start with the test named after the owner you are changing rather than running repository search from scratch.

Common families include:

```text
tests/test_agent_graph.py
tests/test_agent_session.py
tests/test_attachments.py
tests/test_browser_session.py
tests/test_browser_tools.py
tests/test_capabilities.py
```

Additional tests exist for persistence/store contracts, Telegram, documents, web tools, model endpoint/deployment, turn bounds, checkpoints and operational behavior. When changing a symbol, search `tests/` for the symbol or public tool name and run the focused file first, then the full offline suite.

Useful searches:

```text
rg "CapabilityRegistry|capability_brief" tests
rg "send_file|outbound" tests
rg "view_pages|read_document" tests
rg "search_web|fetch_page|view_web_page" tests
rg "PostgresStore|ConversationStore" tests
rg "TelegramWebhook|PostgresUpdateInbox" tests
rg "TurnBudget|StopRequests" tests
rg "OpenAICompatibleBackend|build_messages" tests
```

There is currently no mechanical import-graph test for the model/domain layer
boundary. Add one when a second backend or a broad layer refactor makes that
regression likely; until then, use the owner rules above and a focused static
import audit rather than adding a permanent test for a hypothetical change.

## Known traps for code exploration

### Operational code is not on the app import graph

`tools/sync_control_secret.py`, `tools/setup_control_plane.py`, `tools/telegram_webhook.py` and `deploy/modal/autoscale.py` may be the correct owner even though nothing in `app/` imports them.

Always scan `tools/`, `scripts/` and `deploy/` when the request is operational.

### A capability name is not necessarily a tool name

Examples:

```text
capability: presentation.files -> tool: send_file
capability: documents.read     -> tools: read_document, view_pages
capability: web.view           -> tool: view_web_page
```

Do not tell the model to call capability names.

### Telemetry is not conversation persistence

`app/telemetry/` is a separate contract with separate tables on purpose.
Conversations are the product's content and belong to the person; telemetry is
operational evidence about the machine, holds no message text, and can be
deleted without a user noticing. Do not add telemetry methods to
`ConversationStore`, and do not put conversation content into a trace.

A turn's identity is a `run_id` string generated at ingress and carried in
LangGraph's `configurable` beside `thread_id`; the live recorder is looked up
from it through `Telemetry.trace()`. Never put the recorder itself into graph
state or configuration — it is not serializable and a checkpoint would try.

Code that asks for an unknown run gets `NO_TRACE`, which records nothing, so
every path without telemetry keeps working unchanged.

Objects built once and reused for every turn — `TracedBackend` — hold no run
identity. They take a `Callable[[], TurnTrace]` and ask `resolve()` for the
current turn when something happens, which keeps one source for that answer in
the runtime that started the turn.

Two counts of tools exist and mean different things. `AgentState.tool_calls` is
what the turn has spent against its budget; `TurnRun.tool_calls` is what
actually executed, counted where it executed. They agree today because a
refused call is not counted against either, and they are still not the same
question.

### Conversation store is not checkpoint state

If the requirement is durable chat/memory, start in `app/memory/`.
If it is resumable in-flight LangGraph state, start in `app/checkpoints.py` and `app/agent/graph.py`.

### Observation media is not delivery

`view_pages`, `inspect_page` and `view_web_page` can return images to the model. The user receives only content explicitly marked outbound by presentation logic.

### Both profiles serialize a conversation, by different means

`ui/telegram/run.py` holds a per-chat lock in one process. `PostgresUpdateInbox` leases a conversation in the database, which is where it has to be: the deployed workers are separate containers with nothing in common but the database. Change the claim in `_claim_conversation` and you are changing the ordering guarantee, not an implementation detail.

### Chainlit and Telegram attachment paths differ today

Telegram uses `admit_uploads()` and saves supported documents into the user workspace. Chainlit currently uses `load_attachments()` and therefore follows the direct-media admission path. Inspect this before claiming upload parity or adding a second document parser.

### A control signal is not an ordinary update

`/stop` and the storage-answered commands are marked `control` at the front
door and skip the conversation's lease entirely — in the deployed queue by the
column, locally by being handled beside the per-chat lock. Delivering them
faster is only half of it: what ends a running turn is the loop reading
`StopRequests` at its next step, which is why the two live in one sub-step and
not one of them alone.

## Cheap exploration recipe

For an unfamiliar change:

```text
1. Read PRODUCT.md only if the product intent is unclear.
2. Find the intent row in CODEMAP.md.
3. Open the primary owner file.
4. Search the named symbols and environment keys.
5. Read the directly related test(s).
6. Read PROJECT_MAP.md only when the change crosses boundaries.
7. Read OPERATIONS_MAP.md when the change touches deployment/config/secrets/state.
8. Read ROADMAP.md before treating proposed future work as approved.
9. Read the relevant DECISIONS.md entry before changing a durable boundary.
10. Use reports only for evidence/history relevant to the exact question.
```

The goal is not to avoid repository exploration; it is to start exploration at the correct ownership boundary.
