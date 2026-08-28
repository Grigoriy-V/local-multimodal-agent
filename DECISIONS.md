# Decisions

Architecture and scope decisions only. Not a work log, not a task ledger, not a
place for results.

This file preserves rationale and history. `ROADMAP.md` is the only source of
current product direction, state, order and approved work, and wins every
conflict. Read only the relevant decision when `ROADMAP.md` links it or when an
architectural choice is explicitly being reconsidered.

Write an entry when a choice constrains future work: a component selected or
rejected, a boundary moved, an invariant introduced or dropped. Do not write one
for a completed task, a metric, or a bug fix — those belong in `reports/` and the
journals.

Format: date, title, the decision, why, and what it rules out.

## 2026-08-01: All model access goes through `ModelBackend`

**Decision.** The application talks to one async interface with `invoke` and
`stream`. Only `app/models/` may import a provider SDK, tokenizer, or processor.

**Why.** Replacing Gemma 4 12B IT with Gemma E4B, Qwen, or another
OpenAI-compatible model must be a configuration change, not an agent rewrite.

**Rules out.** Importing model internals from `app/agent/`, `app/context/`,
`app/memory/`, `app/tools/`, `app/api/`, or `ui/`.

## 2026-08-01: LangGraph from the first agent; LangChain is dropped

**Decision.** There is no LangChain stage. The first agent is a minimal
LangGraph graph, and Stage 3 grows that same graph instead of migrating to it.
LangGraph's core is used — `StateGraph`, checkpointers, `interrupt` — but not its
prebuilt `create_react_agent` or `ToolNode`.

**Why.** LangChain was in the plan for a fast first result, and the human's
learning interest is LangGraph, not LangChain. Measured on 2026-08-01 against
langgraph 1.2.10: the core graph runs on the project's own dataclasses, keeps
state across a checkpointer, and closes a tool loop without any LangChain type.
The prebuilts do not: `create_react_agent` requires a `BaseChatModel`, and
`ToolNode` rejects anything but a `langchain_core` message with
`NotImplementedError: Unsupported message type`. Adopting them would mean
adopting `langchain_core` messages as the project's own message type, which puts
image and audio content back into a format the project does not control — the
exact risk `ModelBackend` exists to prevent. The tool loop they would save is
roughly sixty lines.

**Rules out.** `create_react_agent`, `ToolNode`, and any use of
`langchain_core` message classes in graph state or in `app/`. `langchain-core`
still arrives as a transitive dependency of `langgraph`; being installed is not
permission to import it.

## 2026-08-01: FastAPI is deferred, not abandoned

**Decision.** Stage 2 has no HTTP layer. Chainlit calls the agent as a Python
module. FastAPI is added when a consumer other than Chainlit exists.

**Why.** The end goal is a deployable product, so the API boundary is real — but
in Stage 2 it would have exactly one caller and would be a layer built for its
own sake. The cost of adding it later is low provided the agent never assumes it
is called over HTTP.

**Rules out.** Business logic in Chainlit callbacks, and any agent code that
depends on a request, response, or session object.

## 2026-08-01: SQLite-only memory before any vector store

**Decision.** Long-term facts live in SQLite; initial retrieval uses full-text
search. Embeddings are deferred.

**Why.** The basic four-layer context system must be shown to work before
retrieval quality is optimized.

**Rules out.** Adding a vector database as part of Stage 2.

## 2026-08-01: The conversation lives in the project's own SQLite

**Decision.** Threads, messages, the rolling summary, and facts are owned by
`app/memory/store.py`. The LangGraph checkpointer records in-flight turn state
only — it is not where the conversation is kept — and lives in its own file, so
discarding it costs no conversation.

**Why.** The conversation is the product's data: it must be readable, queryable
and portable without LangGraph, and it must survive a framework change. A
checkpointer's schema is LangGraph's, versioned by LangGraph, and holds serialized
graph state rather than a message history anything else can use.

**Rules out.** Reconstructing history from a checkpointer, and any storage of
conversation content outside `MemoryStore`.

## 2026-08-01: Facts are global and only ever saved by an explicit tool call

**Decision.** A long-term fact enters the store only when the model calls
`remember_fact`. The thread is recorded as provenance, but retrieval is global:
a fact saved in one conversation is visible in every later one.

**Why.** The project invariant forbids storing model-generated facts as trusted
memory without an explicit save decision, so nothing may be harvested from an
answer automatically. Global visibility is the point of long-term memory — a
fact scoped to its own thread is indistinguishable from the transcript.

**Rules out.** Inferring facts from model output, and per-thread fact isolation.

## 2026-08-01: A tool declares that it is destructive; the graph decides consent

**Decision.** `Tool.destructive` marks a tool whose effect is not free to undo.
The graph asks the user before running one, through a single `interrupt` raised
before any tool in the batch has run. Where a checkpointer is absent there is
nowhere to wait, and the call is declined rather than run.

**Why.** Confinement is not consent: `write_file` stays inside the workspace and
can still destroy work that matters. Putting the flag on the tool and the asking
in the graph means a new destructive tool inherits the behaviour by setting one
field, and a tool never has to know that a user interface exists. Asking before
anything runs is not a preference — a resumed node restarts from the top, so a
tool that ran before the pause would run twice.

**Rules out.** A destructive tool that runs without an explicit answer, consent
logic inside a tool or inside Chainlit, and per-tool interrupts interleaved with
tool execution.

## 2026-08-01: Token accounting comes from the server, not from a local tokenizer

**Decision.** The size of a request is measured by the model server. The actual
size of the last request is `usage.prompt_tokens` from its response; the ceiling
is `max_model_len` read from `/v1/models`. The repository configures only the
fraction of that ceiling a request may occupy. Any estimate needed before
sending lives behind `ModelBackend` with the rest of model-shaped knowledge.

**Why.** A tokenizer is part of a model. Loading one in `app/context/` would make
swapping the model a code change in the context layer, which is what
`ModelBackend` exists to prevent — and it would also be wrong, because a local
text tokenizer cannot count image tokens, and images are the reason the bound is
needed at all. The server already holds the only tokenizer that matches what is
running, and reports both numbers for free.

**Rules out.** A tokenizer dependency in the repository, a `max_model_len`
duplicated in project configuration, and any context decision that assumes a
message count approximates a token count.

## 2026-08-01: Version 1 is the closed Stage 3 and nothing more

**Decision.** Version 1 is the then-current Stage 3 completed, plus what is
needed to exercise it by hand: a token-bounded request with its fill shown, a
retry inside `ModelBackend`, a thread list in the UI, images and audio rendered in
answers, one fixed workspace, and an explicit refusal for a file type the agent
cannot accept. The workspace is a single hardcoded sandbox; asking the user to
grant a directory is not part of it.

**Why.** The agent already runs, so the risk is not that version 1 is too small
but that it never closes. Granting a directory is a scope grant that must be
stored, revoked and survive a restart — half of a policy engine — and building
it piecemeal now would make the policy work in version 2 harder, not easier.

**Rules out.** Document ingestion, video, an `edit_file` tool, run tracing, an
MCP server, an evaluation harness, and runtime workspace selection as version 1
work. All are recorded in `docs/BACKLOG.md`.

## 2026-08-01: Version 1 is reopened for product completion

**Decision.** The earlier Version 1 closure is superseded. Its functional core
and evidence remain valid, but Version 1 closes only against the then-current
product acceptance criteria: normal persistent chat history,
bounded and honest attachment handling, tool failures that remain inside the
turn, recoverable or clearly refused context overflow, and an end-to-end
browser/restart smoke without regressions to the existing agent.

Version 2 remains deferred. `ROADMAP.md` holds its short direction;
`docs/BACKLOG.md` holds the truthful detail for that possible later stage but is
neither a contract nor authorization to begin it.

**Why.** Product review found that several first-pass checks proved a narrower
property than the closure language claimed: startup action buttons were not a
normal chat history, reactive token measurement was not a preflight hard bound,
and expected operating-system tool failures were not covered by the tool error
boundary. Reopening preserves the working foundation while correcting those
gaps before scope expands.

**Rules out.** Starting Version 2 before Version 1 closes again, treating the
technical presence of a user-facing feature as product acceptance, and choosing
the storage implementation for native Chainlit history in this documentation
step.

## 2026-08-01: No PROJECT_LOG; this file plus the journals replace it

**Decision.** There is no `PROJECT_LOG.md`. Decisions live here, measured
outcomes live in `reports/ml_work.jsonl` and `reports/`, task outcomes live in
`reports/agent_tasks.jsonl`.

**Why.** In an earlier project a single event was written to four places, which
multiplied agent work and created four points of divergence.

**Rules out.** Restating a result in more than one place.

## 2026-08-02: Benchmark workflows do not define the product agent

**Decision.** Version 1.5 is a general autonomous harness. Every ordinary
request enters one harness, which decides whether to answer directly or
continue into a task loop; the model derives criteria and chooses governed
capabilities. Browser and filesystem operations are capabilities, not
user-invoked workflows. The Snake-specific verifier and the native `preview`
and scripted `task` routes built during the first vertical slice are retained
only as historical evaluation code and evidence, disconnected from Chainlit
and from the application task runtime. The implementation record is in
`reports/2026-08-01_v15_step1.md` through
`reports/2026-08-02_v15_step9.md`.

**Why.** The vertical slice proved that planning, grants, editing, retry and a
browser probe can work together, but it encoded one benchmark into production
control flow. A user should state the outcome and approve scope; the agent must
decide which tools and evidence the task needs.

**Rules out.** Per-tool UI buttons such as `preview`, special prompt contracts
such as `/task`, filename-specific production verifiers, and accepting a
benchmark pass as product acceptance.

## 2026-08-02: Workspace confinement accepts absolute paths

**Decision.** Every path-taking tool continues to resolve and validate paths
against an explicit workspace root. Within that boundary it accepts both an
absolute path and a path relative to the root. If the user gives only a filename
and its directory is not already established, the agent asks for the location.

**Why.** The sandbox is a permission boundary, not a requirement that humans
translate a known Windows path into an internal relative form.

**Rules out.** Rejecting safe absolute workspace paths merely because they are
absolute, guessing a directory for an ambiguous filename, and allowing an
absolute path to bypass root validation.

## 2026-08-02: One interface; the harness decides whether to act

**Decision.** Every ordinary natural-language request enters one general
harness. The harness decides whether to answer directly or to plan, use tools,
validate and repair. There is no user-selected conversational versus agent
mode. This supersedes the `in agent mode` wording in the earlier benchmark
workflow decision.

**Why.** Tool use is part of the model's work, not a separate product selected
by the user. A mode switch exposes an implementation split and makes the user
decide what the agent is supposed to infer.

**Rules out.** A `Conversation` / `Agent` selector, separate user-facing entry
paths for answers and tasks, and requiring a slash command or tool control to
obtain autonomous behavior.

## 2026-08-27: The product becomes a deployable personal assistant

**Decision.** The project's scope widens from a single-user local agent to a
personal assistant that also deploys serverless for a small number of people,
first over Telegram. It continues in this repository, and the deployment target
becomes a configuration axis: the local and deployed profiles run the same
`app/`. The GPU model server remains outside the repository, reached over
`MODEL_ENDPOINT` only. Direction and its open points are in
`docs/personal_assistant_direction.md`.

**Why.** Most of `app/` transfers unchanged, and the adapter boundary was built
for exactly this substitution — proving it by starting a second repository
would refute the invariant at the moment of its first real test. Keeping the
local profile preserves a working system to develop against without cloud cost.

**Rules out.** A separate assistant repository, a Modal-specific fork of `app/`,
provider or platform imports outside their adapter, and treating a capability
that works in only one profile as finished. It also retires the earlier
Version 2 direction — a policy-governed tool platform with an MCP surface — as
the current plan; that material stays in `docs/BACKLOG.md`.

## 2026-08-27: One persistence contract, two implementations

**Decision.** Conversations, summaries and memory move behind one store
contract. SQLite implements it for the local profile; a networked database
implements it for the deployed profile, because an idle application must cost
nothing and SQLite on a network volume is not safe for concurrent writers. One
shared contract test suite runs against both. Conversations, summaries and
memory become scoped by user.

**Why.** The engine differs only in full-text search and the connection layer;
ordinary SQL carries over. Keeping SQLite locally preserves zero-setup runs and
the offline, temporary-database test rule that a database-server-only design
would break. Facts are global today by design, which becomes a leak between
people as soon as a second user exists.

**Rules out.** A concrete store class as a type in application code, SQLite on
a network volume in the deployed profile, an always-on container kept alive to
own a database file, a second implementation without shared contract tests, and
any unscoped fact or thread query once more than one person uses the system.

## 2026-08-27: The HTTP layer waits for a separately hosted caller

**Decision.** `app/api/` stays deferred even though a consumer other than
Chainlit now exists. Telegram runs in the same process, so the trigger recorded
in the earlier FastAPI decision is amended: the condition is a UI hosted apart
from the application, not merely a second consumer.

**Why.** The reason that decision existed was to avoid a layer built for its own
sake. Two in-process adapters do not create one. What has to be preserved is the
property that makes the layer cheap later, and that property is a discipline,
not a module.

**Rules out.** Building an HTTP surface with no separately hosted caller, and
any code in `app/` that depends on a request, response or session object.

## 2026-08-28: Optimize the model endpoint as a replacement, not an overwrite

**Decision.** The measured `assistant-llm` deployment remains the baseline while
a separately named Modal App validates the production model-server shape:
protected OpenAI-compatible vLLM, preloaded immutable weights, CPU+GPU memory
snapshots around vLLM sleep/wake, explicit `min_containers=0` and
`max_containers=1`, and a 30-second idle window. The application
switches `MODEL_ENDPOINT` only after the replacement passes backend,
multimodal and Telegram acceptance.

**Why.** The baseline proved compatibility and scale-to-zero but wakes in about
three minutes. Its checkpoint reads in under seven seconds; repeatable vLLM
imports/configuration, profiling, compilation and CUDA graph capture dominate,
so image surgery and weight relocation target the wrong stage. A new identity
preserves honest comparison, rollback and the rule that a measured configuration
is not silently redefined.

The idle window was initially ten minutes while a wake still appeared to cost
roughly three minutes. After a restored cold start measured 25 seconds, the
human chose 30 seconds to prioritize scale-to-zero and avoid paying for idle GPU
time while a private user reads or steps away. This is a product default, not a
claim that 30 seconds is universally optimal; observed traffic may justify a
later measured change.

**Rules out.** Redeploying experimental snapshot code over the baseline,
unbounded GPU replicas, a positive warm-container floor, declaring success from
one cold invocation, changing several performance variables in one run, and
deleting the baseline as part of replacement deployment.

## 2026-08-28: Database latency is not a gate, and the region stays unpinned

**Decision.** The control plane's `<=100 ms` warm and `<=500 ms` cold database
limits are withdrawn as a closing gate. Modal placement stays unpinned, the
database stays in Neon `us-east-2`, and the measured cross-region latency of
roughly 110 ms per round trip is accepted as current behaviour. The probe,
the `compare` operation and the second database configuration are kept as
instruments, not as acceptance criteria.

**Why.** The gate was written before there was a number, and every number that
arrived afterwards argued against it.

The first correction was real and is kept: one application-level read used to
cost four to five sequential round trips plus a migration check on every store
opening. Collapsing it to a single round trip took the warm maximum from
961.7 ms to one round trip exactly — four of five samples within 0.4 ms of
109.4 ms. Beyond that the code has nothing left to give, because the database
itself spends 0.6 ms on the query.

An A/B then measured both databases from one container to control for
placement, which is unpinned and had already landed on two different
continents. Co-located: **2.1-3.4 ms**. Across the Atlantic: **98.7-196.9 ms**.
So the database is placed correctly and the worker is not — and migrating the
database to Europe, which the earlier evidence appeared to argue for, would
have turned a passing result into a failing one.

What settled it was costing both options instead of assuming:

- **Latency costs money only where something waits with the meter running.**
  That is the one to three database calls that fall between two model calls
  while the GPU is warm and idle. At 110 ms each that is 0.1-0.3 s of warm GPU,
  about **$0.00006** per message.
- **Pinning costs 1.75x on the worker's whole lifetime**, and the worker is
  alive for the entire message because it waits on the model — 20-25 s. That is
  about **$0.00033** per message.

Pinning is therefore four to eight times more expensive than the latency it
removes. At a hundred messages a day the whole argument is worth about a dollar
a month, against roughly $46 of GPU for the same messages. Neither figure is
worth a decision, so the decision is made on product grounds instead: current
delays are acceptable to the human, and nothing about them is load-bearing.

The same arithmetic points at what does matter. A 30-second idle window costs
about **$0.0092** per message — more than half the GPU bill — and the router
spends a second full-context request on every message. Both are already queued
under measurement and economics, and both are worth roughly thirty times more
than this entire question.

**Rules out.** Pinning `region=` on the control functions to buy latency;
migrating the production database on the strength of a measurement whose worker
placement was not controlled; treating a latency limit invented before
measurement as acceptance; and pinning the GPU app, where a 1.75x multiplier
would be real money and 110 ms would disappear into a multi-second inference
anyway.

## 2026-08-29: Observing and presenting are separate agent actions

**Decision.** A tool that reads, renders or inspects something returns evidence
to the agent and does not automatically put that evidence in front of the user.
The agent decides which capabilities to use and whether, what and when to send.
Presenting a chosen workspace file or media item is a separate, general agent
capability. An interface adapter only translates an explicit outbound action to
its transport; it never turns an arbitrary tool result into product behaviour.

Ordinary non-destructive work inside the granted workspace does not require a
special user mode or per-tool approval. The workspace remains the permission
boundary, while the model is free to read, look, compare, reason and choose its
next tool within it.

**Why.** Automatically forwarding every image returned by `view_pages` or
`inspect_page` makes the adapter decide what the user sees. Prompting the model
to trigger that hidden workflow does not restore agency; it only disguises the
workflow as a tool choice. Separating perception from presentation lets the
same harness inspect several candidates, reason about them and send only the
result it actually chose, independently of Telegram or another interface.

**Rules out.** Automatic delivery of arbitrary tool media, interface-specific
send decisions inside an adapter, prompt rules that hard-code a tool sequence
for a product request, and describing a capable workspace agent as unable to
look at or present files it can actually handle.

## 2026-08-29: Web search, fetch and visual rendering are separate capabilities

**Decision.** Firecrawl is used for search only on the normal path.
`fetch_page` is the application's own bounded direct HTTP tool and does not
spend provider credit. `view_web_page` is the application's own Chromium
renderer, executed in a dedicated secretless CPU function with neither control
credentials nor a workspace volume. It returns evidence to the agent; showing
its screenshot remains a separate `send_file` decision. Firecrawl scrape is an
explicit fallback for pages the direct fetch or datacenter browser cannot read.

A general-purpose Modal Sandbox is not part of this capability. Fetching bytes
does not execute page JavaScript and stays in the existing worker behind public
destination, redirect, time, type and size bounds. Arbitrary page rendering is
isolated because the existing deployed browser runs as root with
`--no-sandbox` in the same container as application secrets.

**Why.** Search, fetching readable content and looking at a rendered page have
different costs and failure modes. One provider API for all three would spend
credits and disclose every fetched URL unnecessarily. A universal execution
sandbox would add a mechanism larger than the product need. A small secretless
renderer preserves full visual capability while keeping untrusted page code
away from the control plane and the person's persistent files.

**Rules out.** Firecrawl as the default fetch path, automatically scraping all
search results, enabling arbitrary external URLs in the credential-bearing
update worker, mounting the person's workspace into the renderer, and building
a general-purpose sandbox before another capability requires one.
