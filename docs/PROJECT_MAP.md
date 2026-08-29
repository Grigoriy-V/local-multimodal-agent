# Project Map

This is the conceptual map of the **current implementation** of `local-multimodal-agent`.
It explains components, ownership and runtime flows. It is not a roadmap or architecture history.

For implementation navigation use `docs/CODEMAP.md`. For deployment commands and configuration use `docs/OPERATIONS_MAP.md`. Current work lives in `ROADMAP.md`; evidence lives in `reports/`.
`DECISIONS.md` explains approved durable choices behind these boundaries. Read
only the relevant entry when its rationale matters or the choice is being
reconsidered; this map describes the current system.

## System at a glance

```text
                        ┌──────────────────────────┐
                        │      Model endpoint      │
                        │ OpenAI-compatible vLLM   │
                        │ assistant-llm-v2 / A10   │
                        └────────────┬─────────────┘
                                     │ ModelBackend
                                     │
Telegram ─┐                           ▼
          ├─> interface adapter ─> GeneralHarness / Agent
Chainlit ─┘                           │
                                     ├─ Context engine
                                     ├─ ConversationStore
                                     ├─ LangGraph checkpoints
                                     ├─ CapabilityRegistry / Toolbox
                                     └─ bounded TaskRuntime
                                              │
              ┌───────────────────────────────┼──────────────────────────────┐
              ▼                               ▼                              ▼
          workspace                       public web                    memory/store
   files / docs / artifacts       search / fetch / browser view      SQLite / PostgreSQL
              │                               │
              │                         isolated renderer
              │                         for page JavaScript
              ▼
     explicit presentation
          `send_file`
```

The application core is under `app/`. Interfaces are under `ui/`. Modal deployment is under `deploy/modal/`. Operational scripts are under `tools/` and `scripts/`.

## Domain boundaries

### Application messages and model boundary

`app/models/base.py` owns the canonical domain types:

- `ContentPart`
- `ToolCall`
- `Message`
- `Usage`
- `Completion`
- `ModelBackend`

Application code speaks these types rather than provider SDK types or LangChain message classes.

`app/models/openai_compatible.py` is the current provider-wire adapter. It translates the project's messages, multimodal parts, tools and structured output to/from an OpenAI-compatible HTTP endpoint.

The deployed model server is infrastructure in `deploy/modal/model_app.py`; `app/` reaches it only through `MODEL_ENDPOINT` and `ModelBackend`.

### Agent runtime

The ordinary conversational loop is in `app/agent/graph.py`:

```text
START
  ↓
load context
  ↓
model
  ↓
┌─ no tool calls ───────────────> persist ─> END
│
└─ tool calls ─> tools ─> model ─> ...
```

The graph:

- assembles bounded context;
- calls the configured `ModelBackend`;
- validates and runs tools;
- pauses before destructive tools through LangGraph `interrupt()`;
- lets tool errors return to the model for recovery;
- persists the completed turn to `ConversationStore`;
- folds older conversation into a rolling summary.

`app/agent/runtime.py` owns `Agent`, which wires together backend, store, context policy, workspace, capability grant and checkpointer. One `Agent` belongs to one user; a graph is compiled per conversation thread.

### General harness and bounded tasks

`app/agent/harness.py` owns `GeneralHarness`.

Current behavior has two internal branches:

```text
user request
   ↓
structured router model call
   ├─ answer ─> ordinary Agent graph
   └─ act    ─> bounded TaskRuntime
```

The user does not choose this branch. It is internal implementation.

The task path is separate from the ordinary conversational graph:

```text
task
 → plan
 → authorize workspace grant
 → implement
 → validate real evidence
 → evaluate
 → repair if needed
 → finalize
```

Key owners:

- `app/agent/task_graph.py` — durable lifecycle and budgets;
- `app/agent/task_runtime.py` — start/resume/view/cancel API and task checkpointer;
- `app/agent/task_worker.py` — model planner + implementation loop;
- `app/agent/task_validator.py` — model-driven evidence collection and criterion evaluation.

Current task-loop capability is narrower than the ordinary assistant: implementation is built around filesystem read/write, while validation currently admits filesystem read and local browser inspection. This is a current implementation constraint, not a general statement about what the conversational agent can do.

## Context and memory

### Turn context

`app/context/window.py` defines the model prompt shape.

The current context is assembled from:

1. the stable system prompt;
2. a rolling summary of older conversation;
3. saved long-term facts relevant to the user;
4. recent conversation history;
5. the new turn.

The effective system prompt also receives a generated capability brief based on the actual toolbox and delivery interface.

Media replay is bounded (`image` and `audio` budgets). Explicit outbound media is not replayed as fresh visual/audio evidence; it becomes a textual placeholder in later context.

### Durable conversation and facts

`app/memory/base.py` defines `ConversationStore`.

The store owns:

- thread ownership;
- ordered messages;
- rolling summaries;
- long-term facts;
- per-turn context records.

Implementations:

```text
local profile     -> SqliteStore   (`app/memory/store.py`)
deployed profile  -> PostgresStore (`app/memory/postgres.py`, currently Neon)
```

`app/memory/open.py` selects the implementation from configuration.

User scope is part of the store contract. Cross-conversation operations require an explicit owner; a thread is permanently associated with one owner.

### Checkpoints are not conversation history

`app/checkpoints.py` owns LangGraph checkpoint lifecycle.

Checkpoints store resumable in-flight graph state. They are deliberately separate from canonical conversation history.

```text
conversation / summary / facts -> ConversationStore
ordinary in-flight turn        -> conversation checkpointer
task lifecycle                 -> task checkpointer
```

Locally checkpoints use SQLite. Deployed checkpoints use PostgreSQL so a later CPU worker can resume work started by another container.

## Capability and tool system

### Tool primitive

`app/tools/base.py` owns:

- `Tool`: name, description, JSON-schema parameters, callable, destructive flag;
- `Toolbox`: actual model-visible tools, validation and execution.

A tool failure is normally returned as a tool result so the model can recover rather than losing the whole turn.

### Capability layer

`app/tools/capabilities.py` owns the current capability registry and scoped grants.

Current capability names:

```text
filesystem.read
filesystem.write
browser.inspect
documents.read
presentation.files
web.search
web.fetch
web.view
```

A `CapabilityGrant` has a workspace root and a set of capability names. `CapabilityRegistry` turns the grant into the actual `Toolbox`.

The model's capability description is generated separately in `app/capabilities.py` from what is actually wired: toolbox, admitted input types and interface delivery.

### Filesystem

`app/tools/filesystem.py` owns the current workspace filesystem tools:

- `list_files`
- `read_file`
- `write_file`
- `edit_file`

All paths resolve through `resolve_in_root()`. Absolute paths are accepted only if they remain inside the granted root. Writes/edits are destructive and therefore require approval in the ordinary agent graph.

### Attachments and documents

`app/attachments.py` is the UI-independent admission policy.

For Telegram:

```text
image/audio upload -> model ContentPart
supported document -> saved into user's workspace -> turn receives its exact saved name
```

Document internals are split:

- `app/documents.py` — format detection, structured extraction and PDF rendering;
- `app/tools/documents.py` — `read_document` and `view_pages` model tools.

`read_document` returns bounded labelled sections rather than dumping a whole document into context. `view_pages` renders PDF pages to PNG for multimodal inspection and saves previews under `.agent/documents/`.

Current formats in this subsystem include PDF, DOCX, TXT, Markdown and CSV.

### Observation versus presentation

`app/tools/presentation.py` owns `send_file`.

Observation tools do not send their media automatically. `send_file` selects one workspace item and marks its `ContentPart` as `outbound=True`; adapters transport that explicit outbound action.

This distinction applies to document previews and web screenshots as well as ordinary files.

### Local browser inspection

`app/tools/browser.py` inspects self-contained local HTML artifacts. It uses the shared Chromium/CDP implementation in `app/tools/chromium.py` and blocks network access for this local-artifact capability.

### Public web

Public web is deliberately three capabilities:

```text
search_web     -> ranked leads via Firecrawl; provider credit; does not read pages
fetch_page     -> bounded direct HTTP page text; no page JavaScript
view_web_page  -> real browser; rendered text + screenshot; page JavaScript executes
```

`app/tools/web.py` defines the model-facing tools.

`app/web.py` owns destination validation, direct fetch, Firecrawl client and browser-render routing. It checks public destinations, limits redirects/time/body size and treats returned web content as untrusted data.

The deployed browser renderer is isolated from control-plane secrets and user workspaces; see Deployment below.

## Interfaces

### Telegram

`ui/telegram/adapter.py` is the main Telegram/application adapter.

It owns transport translation, not agent policy:

- maps Telegram account identity to canonical application user id;
- finds/creates the current application thread;
- downloads uploads and passes them through app admission;
- dispatches `/new`, `/can`, `/check`, `/stop` and help commands;
- passes ordinary messages to `GeneralHarness`;
- renders task approvals/progress/results;
- transports only explicitly outbound tool media;
- displays model-declared tool calls as concise status lines.

`ui/telegram/api.py` owns direct Telegram Bot API calls.

`ui/telegram/wire.py` owns minimal raw-update parsing and the `needs_model()` predicate. It intentionally imports only the standard library to keep webhook cold start independent of the agent stack.

#### Local Telegram profile

`ui/telegram/run.py` uses long polling. Different chats run concurrently; updates from the same chat are serialized with per-chat locks.

#### Deployed Telegram profile

`ui/telegram/webhook.py` separates HTTP acceptance from agent work:

```text
Telegram request
  ↓
validate secret + account
  ↓
persist update in durable inbox
  ↓
spawn CPU update worker
  ↓
return HTTP 200
```

The model wake is requested in parallel with durable admission for updates that need the model.

`ui/telegram/inbox.py` owns the PostgreSQL leased inbox. It deduplicates and leases by Telegram `update_id`.

**Known current correctness debt:** distinct updates belonging to the same deployed conversation are not yet serialized by this inbox. The local polling path does serialize a chat. `ROADMAP.md` owns the planned correction.

### Chainlit

`ui/chainlit_app.py` is the local Chainlit adapter and `ui/chainlit_history.py` connects Chainlit history to the application's store.

It uses the same `Agent` / `GeneralHarness` core and the same explicit outbound-media rule.

Current asymmetry: Chainlit upload admission still goes through `load_attachments()`, which accepts direct image/audio media rather than the Telegram `admit_uploads()` document-save path. Documents already present in the workspace can still be handled by application tools, but document upload parity should not be inferred from Telegram behavior.

## Deployment

### Control plane: `assistant-control`

`deploy/modal/control_app.py` owns the deployed CPU application.

Images are layered so heavy dependencies and Chromium are below frequently changing source code.

Main functions:

```text
telegram_webhook
    small CPU ingress
    no browser
    validates + queues + wakes model + spawns worker

process_telegram_update
    CPU agent worker
    secrets + persistent workspace volume
    runs TelegramAdapter / application harness

render_web_page
    isolated browser CPU endpoint
    no control secret
    no database URL
    no user workspace volume
    proxy authenticated

self_test
    executes runtime capability probes in the deployed environment

measure_database_latency
    diagnostic only
```

The deployed workspace is Modal Volume `assistant-workspaces` mounted at `/workspaces`. `user_workspace()` creates a separate directory per canonical user inside that root. The worker reloads the volume before a turn and commits it after the turn.

### Model plane: `assistant-llm-v2`

`deploy/modal/model_app.py` owns the current Modal vLLM deployment.

Current shape:

- Gemma 4 12B QAT checkpoint;
- OpenAI-compatible vLLM server;
- A10 GPU;
- 16,384-token server context limit;
- image/audio multimodal limits;
- scale-to-zero;
- CPU+GPU memory snapshots around a warmed sleeping vLLM process;
- proxy-authenticated endpoint;
- model weights and vLLM cache on separate Modal Volumes.

`fetch_weights()` downloads weights on CPU. `preflight()` checks known model/config startup failures without paying for GPU time. `Server` owns the GPU process.

The application and model deployment have no Python import dependency on each other; the contract is the OpenAI-compatible HTTP endpoint configured by `MODEL_*` settings.

## Storage and state ownership

| State | Current owner | Durable? |
|---|---|---:|
| Conversation messages | `ConversationStore` | yes |
| Rolling conversation summary | `ConversationStore` | yes |
| Long-term facts | `ConversationStore` | yes |
| In-flight conversational graph | LangGraph checkpointer | resumable |
| In-flight bounded task | task LangGraph checkpointer | resumable |
| Telegram accepted update / retry lease | PostgreSQL Telegram inbox | yes |
| Turn identity (`run_id`), generated at ingress | Telegram inbox row / polling loop | yes |
| Turn summary and trace | `TelemetryStore` (`turn_runs`, `trace_events`) | yes |
| In-flight turn recorder | `Telemetry` in the worker process | no |
| User files / document previews / web screenshots (deployed) | per-user dir on `assistant-workspaces` Volume | yes |
| Model weights | Modal HF cache Volume | yes |
| vLLM compile/cache | Modal vLLM cache Volume | yes |
| GPU KV/runtime state | model container | no canonical product state |
| Interface-specific transient state | adapter/container | no |

## Trust boundaries

### User scope

Conversation/memory operations are scoped by canonical user id. Workspace paths are rooted inside a per-user directory.

### Workspace scope

Filesystem/document/presentation tools cannot resolve paths outside their granted root.

### Consequential actions

The current tool primitive marks destructive actions. The ordinary agent graph pauses via durable LangGraph interrupt before running them.

### Public web

Direct fetch checks destinations before connection and on redirects. Browser viewing validates requests and runs public page JavaScript in a separate deployed renderer that holds no control-plane secret, database URL or user volume.

### Provider/model output

Model output, tool output, documents and web content are data. They do not acquire authority by appearing inside a tool result or page.

## Current implementation edges worth knowing

These are facts useful when reading the code; `ROADMAP.md` decides whether/when they change.

- `GeneralHarness` currently spends a separate structured model call to choose `answer` versus `act`.
- The bounded task implementation/validation toolbox is narrower than the ordinary assistant toolbox.
- The deployed Telegram inbox leases by `update_id`, not by conversation, so same-thread concurrency is not yet solved.
- Every turn that reaches the model carries one `run_id` from ingress to delivery, and its model calls, tool calls, tokens, first token, first visible response and outcome are recorded. What is missing is the reading half: there is no `show run <run_id>` inspector yet, and no GPU-time or derived-cost attribution.
- The bounded task path reports the model calls it spends through a wrapped backend rather than per stage, so an act turn's totals are honest while its internal stage detail is still coarse.
- Chainlit document-upload admission is not yet the same as Telegram document admission.
- `Capability.build` currently receives a local `Path`; remote execution/sandbox abstraction is not yet a first-class provider boundary.
- `app/api/` exists as an empty stub; no separately hosted application API is currently used.

## Architectural references

The long-term goal is not merely to add more tools to a chatbot. The project
should grow toward the functional maturity of a production-grade agent harness:
one coherent runtime that can reliably manage tools, evidence, permissions,
sessions, long-running work, recovery, memory, sandboxed execution, subagents
and multiple interfaces without turning those capabilities into hard-coded
workflows.

The projects below are architectural references, not dependencies,
specifications, or implementations to copy mechanically. They are useful
because they already solve classes of problems this project is expected to
encounter as it matures. When changing a corresponding boundary here, inspect
how these systems solve the same problem and borrow the underlying pattern only
when it fits this product.

- **[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)** —
  reference for harness architecture itself: replaceable capability/plugin
  seams, a common agent loop, structured session events, tool/runtime
  separation, workflows, skills and subagents built around the same core rather
  than as unrelated execution systems. It is especially useful when evolving
  this project's agent runtime without turning `GeneralHarness` into a
  collection of special-case modes.

- **[OpenCode](https://github.com/anomalyco/opencode)** — reference for a mature
  headless agent core: sessions as first-class runtime objects, tool and plugin
  hooks, permission boundaries, child-agent/session patterns, event-driven
  observability and multiple clients around one underlying agent service. It is
  especially useful for permissions, inspectable execution, subagents and
  keeping UI concerns outside the core runtime.

- **[OpenClaw](https://github.com/openclaw/openclaw)** — reference for the
  personal-assistant side of a mature harness: session routing,
  messaging-channel integration, persistent agent workspaces, tool/skill
  execution, browser control, multi-agent isolation and a dedicated control
  plane around the agent runtime. It is especially relevant because this
  project is also a persistent personal assistant rather than only a coding
  agent or one-shot task runner.

These references define a **maturity target, not an architecture target**. The
objective is to reach comparable functional properties while preserving this
project's own product principles and existing boundaries where they remain
sound. A feature should not be copied because another harness has it; the
reference becomes relevant when this project encounters the same underlying
problem.
