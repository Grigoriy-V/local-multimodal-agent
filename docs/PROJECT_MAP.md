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
          ├─> interface adapter ─────> Agent
Chainlit ─┘                           │
                                     ├─ Context engine
                                     ├─ ConversationStore
                                     ├─ LangGraph checkpoints
                                     ├─ CapabilityRegistry / Toolbox
                                     └─ TurnBudget / StopRequests
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
- pauses before tools that require approval through LangGraph `interrupt()`;
- lets tool errors return to the model for recovery;
- persists the completed turn to `ConversationStore`;
- folds older conversation into a rolling summary.

`app/agent/runtime.py` owns `Agent`, which wires together backend, store, context policy, workspace, capability grant and checkpointer. One `Agent` belongs to one user; a graph is compiled per conversation thread.

### One loop, bounded and stoppable

There is one route. An ordinary request enters the graph above and normally
leaves it when the model answers without asking for a tool. Before that ordinary
exit, `app/agent/stopping.py` provides one typed extension seam: the default
accepts the answer immediately, while explicit structured `Steering` carries a
candidate and an instruction into one more model step. The candidate stays out
of conversation persistence and finished-message delivery; an interface that
already showed its streamed text receives `AnswerWithdrawn` and removes the
preview.

The product wires one extension into that seam: `app/agent/todo.py`, which can
refuse an ending while the agent's own `todo_write` plan still has open items
and by default refuses none (`DECISIONS.md` 2026-09-03). The plan is
not stored anywhere of its own — it is the arguments of the model's own last
accepted call, inside the turn's messages, so it is checkpointed with the turn
and cleared by the `extend` reducer when the next user message begins one. That
gives it the lifetime of one unfinished turn: it survives an interrupt, a resume
and a restarted worker, and never reaches the next thing the person asks.
Nothing chooses between two lifecycles, and no second lifecycle exists:
the router and the bounded plan/implement/test/evaluate task path were removed
in roadmap sub-step 4.1.

Three things bound one turn, and they are the reason the single loop is allowed
to be autonomous.

```text
user request
   ↓
load context ─> model ─> tools ─> model ─> … ─> persist
                  ▲        │
                  └────────┘
        each pass is one step, and before each batch of tools:
          has the person asked to stop?   -> stop, and say so
          is the budget spent?            -> no more work; a delivery (send_file) still
                                             goes; answer with what you have
```

- `app/agent/graph.py` owns `TurnBudget` (steps, tool calls, wall seconds) and
  enforces both checks in the `tools` node — before any tool runs and before
  anyone is asked to approve one. A crossed limit is not an error: no further
  tool runs, and the model is asked once more, without tools, for the answer
  the person is owed. So a ceiling of N steps costs at most N + 1 model calls.
- `app/agent/stop.py` owns `StopRequests`: where "stop what is running" is
  recorded. `MemoryStopRequests` for the local profile, which is one process;
  `PostgresStopRequests` for the deployed one, where `/stop` is answered in one
  container and the turn it ends runs in another.
- A stop carries the sequence number its update arrived with, and applies to
  every turn that began before it. That is what stops an unconsumed stop from
  cancelling the next message.
- `TurnStopping` is asked only for a result that would otherwise end an ordinary
  turn and only while another step still fits the turn budget. It is not asked
  for tool-call completions, the final budget answer, a user stop or a context
  refusal. Its default performs no validation and spends no extra model call;
  policy belongs to an injected structured extension, not to HTML/PDF/tool-name
  heuristics in the graph.

Time is accumulated by the nodes rather than measured from the turn's start, so
a turn that waited an hour for an approval is not over budget the moment it is
answered.

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

How much of the model's window a request may occupy is `Agent.budget()`: the limit read from the server, spent at `AGENT_CONTEXT_FRACTION`, or a chosen `AGENT_CONTEXT_TOKENS` clamped to that limit. The budget belongs to one user, because an `Agent` does; no interface offers the choice yet.

The size of the request about to be sent is estimated before every model step (`fitted` in `app/agent/graph.py`), and a conversation over budget is folded before it is sent rather than after the endpoint refuses it. Size is the trigger; a message count (`summarize_after`, 60) is the fallback for a server that reports no window. How much is folded follows from how far over budget the request is: the oldest exchanges go one at a time until enough is freed, and the last `keep_turns` exchanges (two) always stay verbatim — inside one long tool turn, the newest two steps instead (2026-09-04). The summarizer reads the same shortened surface the model reads, never whole tool results, and a fold that fails leaves the turn and its answer as they are. The estimate lives behind the model boundary (`ModelBackend.estimate_tokens`) and calibrates itself from the token counts completions already report. Only stored history folds; shortening the current turn's own accumulated tool results is not implemented, and `ContextOverflowError` remains the backstop under all of it.

What the summary and the stubs stand for stays reachable. Stored history is canonical and never rewritten; the model gets back to it through two tools of its own (`app/tools/history.py`): `search_history` finds a stored message by its words, within this person's conversations only, and `read_history` returns it by position as it was said, in pages. A shortened result's stub names its position, and the summary says the exact words behind it are kept. Nothing is injected: the model asks, and the trace shows that it did.

### Durable conversation and facts

`app/memory/base.py` defines `ConversationStore`.

The store owns:

- thread ownership;
- ordered messages;
- rolling summaries;
- long-term facts;
- per-turn context records;
- full-text search over stored messages (`search_messages`), scoped to one owner.

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
in-flight turn                 -> conversation checkpointer
"stop what is running"         -> StopRequests (memory, or turn_stops)
```

Locally checkpoints use SQLite. Deployed checkpoints use PostgreSQL so a later CPU worker can resume work started by another container.

A turn a worker died in is taken up, not restarted (4.7, 2026-09-04).
`Agent.unfinished` reads the checkpoint for a next node with nobody asking a
question; `Agent.resume_interrupted_events` continues it. A death inside the
`tools` node is the one case with something unknown: every call of that step
gets a result before the graph moves on — a `replay_safe` tool (reading) is
run now, anything else is answered `interrupted`, "whether it ran is unknown",
and the model decides what to check. The harness never runs a side effect
twice on its own. `persist` is idempotent, so a death after the store was
written does not store the turn twice. The Telegram adapter takes a turn up
only when the update it holds is the message that turn began with; any other
message starts afresh.

## Capability and tool system

### Tool primitive

`app/tools/base.py` owns:

- `Tool`: name, description, JSON-schema parameters, callable,
  `requires_approval` for an external effect the person must say yes to, and
  an optional `timeout_seconds`;
- `ToolError(message, code, detail)`: the one way a tool fails. A tool returns
  content on success and raises this on failure; it never returns a failure as
  text;
- `Toolbox`: the model-visible tools, name resolution against the allowlist,
  schema coercion and validation, and the one-line signature a refused call
  is answered with.

`app/tools/execution.py` owns the one agent-runtime lifecycle around that
toolbox: `pre_execute -> execute -> post_execute`. It resolves the name, reads
and coerces the arguments, validates, applies the approval policy, runs the
tool under its timeout, turns every exception into a typed `ToolFailure(code,
message, detail)`, bounds the content, sanitizes the failure text, records the
reason in telemetry and projects the outcome into the tool `Message`. The graph
may pause a prepared batch for an answer, but does not implement a second
execution path.

A tool failure is a tool result the model reads, so it can recover rather than
losing the turn. The typed failure rides on the message as `Message.failure`,
which is checkpointed with the turn and is the only thing the loop's repeat
guard, the plan reader, `/check` and both interfaces ask; the `error:` wording
in the text is what the model reads and is not a protocol. Stored history
carries the text projection until the schema-3 migration adds the column.
`BaseException` alone propagates, because a stop must be able to stop.

A tool whose result is a workspace item says in the result how it reaches
the person, as the call to make (`handover` in `app/tools/base.py`); the
decision stays the model's. `DECISIONS.md` 2026-09-03.

Commands run through one tool, `run_command`, behind a one-method `Runner`
the registry owns and the profile chooses (`app/tools/shell.py`). Locally it
is a process in the person's workspace with the agent's own environment
withheld; deployed it is the `run_command` Function beside the renderer
(`deploy/modal/control_app.py`): the same layers plus a developer's base
tools, the workspaces Volume, no secret, a disposable container. What a
command installs lives in the workspace, which is what survives between
turns in both profiles; when the workspace has a `.venv`, that is the
`python` and `pip` on a command's `PATH`, and locally one is made on first
use. The worker commits the Volume before a command and reloads after it,
the Function the other way round, so the two containers see one workspace
within a turn. On Windows a command runs under a write-restricted token and
the operating system refuses every write outside the workspace
(`app/tools/shell_windows.py`). A conversation runs in `full` mode, where
everything inside the workspace is autonomous, or `careful`, where the tools
that change it ask first (`app/agent/mode.py`). `DECISIONS.md` 2026-09-04.

A call whose arguments could not be read as a JSON object still reaches the
loop, with the text kept on `ToolCall.raw_arguments`, and is refused as one
`bad_arguments` result with the tool's signature; the request is not failed.
Failure codes: the runtime's `unknown_tool`, `bad_arguments`, `declined`,
`not_run`, `timeout`, `internal`, `failed`, and a family's own (`fs.*`,
`doc.*`, `browser.*`, `web.*`, `memory.*`, `todo.*`, `presentation.*`).
`docs/v2_tool_system.md` is the contract.

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

The model's capability description is generated separately in `app/capabilities.py` from what is actually wired: toolbox, admitted input types, interface delivery and the granted workspace root.

### The prompt is assembled, not written

Since 2026-08-30 the system layer is built from parts ordered by how rarely
each changes, which is also the order a served prefix cache needs:

```text
stable core            app/context/window.py    DEFAULT_SYSTEM_PROMPT, names no tool; ends with WORKING_METHOD, the method any model is asked to work by
capability guidance    app/capabilities.py      generated from the wired toolbox
tool schemas           the toolbox              sent beside the messages
standing instructions  app/instructions.py      AGENTS.md, one per person
rolling summary        the store                changes when a conversation folds
retrieved facts        the store                changes every turn
history and turn       the store                the conversation itself
```

`AGENTS.md` lives at the root of the person's own workspace, is read again on
every turn — so an edit applies to the next message without a redeploy — and
travels as its own framed message naming its source. It is an overlay on the
prompt with authority below product and capability policy: it can shape how
work is done and can never widen what may be done. It is not memory, holds no
database copy, and `remember_fact` never writes to it. `/agents` in Telegram is
a thin UI over that same file.

### Filesystem

`app/tools/filesystem.py` owns the current workspace filesystem tools:

- `list_files`
- `read_file`
- `write_file`
- `edit_file`

All paths resolve through `resolve_in_root()`. Absolute paths are accepted only
if they remain inside the granted root. Reads, writes and edits inside that
root are autonomous. Tools whose effects cross the same-person conversation
boundary declare that they require approval, and the execution seam enforces it.

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

Observation tools do not send their media automatically. `send_file` selects one workspace item, or several in one call, and marks each `ContentPart` as `outbound=True`; adapters transport that explicit outbound action, and Telegram delivers several items of one kind as one album.

This distinction applies to document previews and web screenshots as well as ordinary files.

### Browser session and local inspection

`app/tools/chromium.py` owns the browser process, the CDP session and
`BrowserSession`: one page with the whole operation set — `open`, `snapshot`,
`screenshot`, `evaluate`, `console`, `navigate`, `click`, `type`, `press`,
`select`. A snapshot is the page as a bounded outline in which every
interactive element carries a `ref`; actions take refs, never selectors, and
a ref from an older snapshot is refused as `browser.stale_ref`. The trust
boundary is a property of the session: `open_browser(offline=True)` confines
navigation to the document; `serve=serve_directory(root)` answers requests
for the root's own files; `allow=policy` is asked about every other request,
and without it every other request fails. A session has exactly one of
the two.

`app/tools/browser.py` exposes observation only. `inspect_page` opens a
local HTML artifact in an offline session that serves the workspace's own
files at `http://artifact.local/`, lets the page reach public addresses under
the same policy as `view_web_page` and refuses private ones, so the page has
an origin, storage, its sibling files and its CDN resources; it returns the
structure with refs, the visible text, console errors, the requests that were
refused and a screenshot.
No click, type or navigate tool exists in this version. `render_locally` in
`app/web.py` drives the same session with the public request policy.

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
- dispatches `/new`, `/chats`, `/can`, `/check`, `/stop`, `/plan`, `/mode`,
  `/context`, `/compact` and help commands;
- passes ordinary messages to the `Agent`, with the update id as the turn's
  sequence so a later `/stop` can be told from an earlier one;
- renders the consent question, the transient tool status and the step it
  belongs to;
- transports only explicitly outbound tool media;
- displays model-declared tool calls as concise status lines.

`ui/telegram/api.py` owns direct Telegram Bot API calls.

`ui/telegram/wire.py` owns minimal raw-update parsing, the `needs_model()` predicate and `travels_out_of_band()`, which is what marks an update as control. It intentionally imports only the standard library to keep webhook cold start independent of the agent stack.

#### Local Telegram profile

`ui/telegram/run.py` uses long polling. Different chats run concurrently; updates from the same chat are serialized with per-chat locks — except control updates, which are handled beside the lock rather than behind it, because `/stop` waiting for the turn it stops is not a stop.

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

`ui/telegram/inbox.py` owns the PostgreSQL leased inbox. It deduplicates by Telegram `update_id` and leases by conversation: a claim takes the oldest unfinished update of the conversation that woke it, and refuses while another of that conversation's updates is still running. A per-conversation advisory lock makes the refusal hold across containers. The conversation is named by the webhook when the row is written; a row queued before the column existed is still claimed on its own.

A lease is shorter than the worker container's life (`LEASE_SECONDS` 590 against a 600 s timeout), so a killed container's row is claimable the moment the platform re-invokes the same update or the next message arrives. An update claimed three times and never finished is given up on at the fourth claim, with a message to the person; the count is read at the claim because a dead worker cannot return its update to the queue itself.

The update worker keeps its conversation until nothing is left, so a burst is answered in order by one warm container. Past a drain window it hands the rest to a fresh worker rather than risk its own timeout.

Not yet decided: whether an image and the question that follows it are one intent. Coalescing would change what a turn is, and every recorded number counts turns. `ROADMAP.md` 4.0 owns it.

### Chainlit

`ui/chainlit_app.py` is the local Chainlit adapter and `ui/chainlit_history.py` connects Chainlit history to the application's store.

It uses the same `Agent` core and the same explicit outbound-media rule. Chainlit's stop button records a `StopRequests` entry for the running turn rather than cancelling a coroutine; the session counts its own sequence, since it has no update ids to take one from.

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
- 65,536-token server context limit, raised from 16,384 on 2026-08-30;
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
| "Stop what is running" | `StopRequests`: memory, or `turn_stops` | yes |
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

A tool declares `requires_approval` for an effect beyond the workspace. The ordinary agent graph pauses via durable LangGraph interrupt before running it.

### Public web

Direct fetch checks destinations before connection and on redirects. Browser viewing validates requests and runs public page JavaScript in a separate deployed renderer that holds no control-plane secret, database URL or user volume.

### Provider/model output

Model output, tool output, documents and web content are data. They do not acquire authority by appearing inside a tool result or page.

## Current implementation edges worth knowing

These are facts useful when reading the code; `ROADMAP.md` decides whether/when they change.

- There is one route and one loop. The router's second full-context model call per message is gone, as is the bounded task lifecycle it selected.
- A turn is bounded by `TurnBudget` and can be ended by `StopRequests`; both are enforced in the graph's `tools` node, so a turn that never calls a tool is never checked and costs neither.
- The deployed Telegram inbox leases by conversation and marks control updates so they skip that lease. The `control` column is created by `tools/setup_control_plane.py`, as is `turn_stops`; until both have run against a database, the deployed behaviour is the old one.
- Every turn that reaches the model carries one `run_id` from ingress to delivery, and its model calls, tool calls, tokens, first token, first visible response and outcome are recorded. `tools/show_run.py` reads one back, lists failed and unfinished turns, and derives GPU time and cost at read time.
- `tools/show_run.py` renders the loop's steps from `loop_step` events, and names the limit or the stop that ended a turn early.
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
  this project's agent runtime without turning the one loop into a collection
  of special-case modes.

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
