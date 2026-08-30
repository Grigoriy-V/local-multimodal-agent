# Decisions

This file records approved durable architectural and scope choices. It is not a
roadmap, current-state map, work log or evidence report.

Use the four canonical documents for the current product, system, code and
operations. Use `ROADMAP.md` for current work and authorization. Read a decision
when a canonical document links it, when its rationale matters, or when the
choice is being reconsidered. Measurements and implementation evidence belong
in `reports/`.

A decision is a draft until the human explicitly approves it. Every entry uses
the same fields; use `None` when it neither replaces nor is replaced by another
decision.

## 2026-08-01 — All model access goes through `ModelBackend`

Decision

Application code talks to the model through the asynchronous `ModelBackend`
contract. Provider SDKs, tokenizers and processors stay inside `app/models/`.

Why

Changing the model or its OpenAI-compatible endpoint must not require rewriting
the agent, context, memory, tools or interfaces.

Consequences

Provider-specific types and imports do not enter application domain code. Any
model-shaped estimation also belongs behind the model boundary.

Supersedes / Superseded by

None.

## 2026-08-01 — Use LangGraph without adopting LangChain message types

Decision

LangGraph owns orchestration and resumable interrupts, using the project's own
messages and state. The application does not use LangChain agents, `ToolNode`,
`create_react_agent` or `langchain_core` message classes.

Why

The prebuilt nodes require LangChain model/message types and would move the
multimodal application contract outside project control for little saved code.

Consequences

Agent graphs and tool execution remain explicit project code. A transitive
LangChain installation is not permission to import it into `app/`.

Supersedes / Superseded by

None.

## 2026-08-01 — Defer an application HTTP layer

Decision

Do not add FastAPI while every interface runs in the same process as the
application. Add an application HTTP boundary only for a separately hosted
caller.

Why

An HTTP layer with no remote consumer adds ceremony without creating a useful
boundary. Keeping interfaces thin makes that layer cheap to add when real.

Consequences

Application code cannot depend on request, response or session objects, and
business logic cannot move into interface callbacks.

Supersedes / Superseded by

Amended by `2026-08-27 — An HTTP layer requires a separately hosted caller`.

## 2026-08-01 — Start memory retrieval without a vector store

Decision

Long-term facts use text retrieval in the existing store. Embeddings and a
vector database are deferred until text retrieval works and is measured.

Why

The context and memory lifecycle must be proven before adding another storage
system and retrieval model.

Consequences

A vector database is not part of the current architecture or roadmap merely
because it may improve retrieval later.

Supersedes / Superseded by

None.

## 2026-08-01 — Conversation data is separate from checkpoints

Decision

Threads, ordered messages, rolling summaries and facts belong to the
application's `ConversationStore`. LangGraph checkpointers hold only resumable
in-flight graph state.

Why

Conversation is portable product data; checkpoint schemas are framework-owned
serialized execution state.

Consequences

History is never reconstructed from checkpoints. Deleting disposable
checkpoint state must not delete canonical conversation data.

Supersedes / Superseded by

Storage implementation details were generalized by
`2026-08-27 — One persistence contract, local and deployed implementations`.

## 2026-08-01 — Long-term facts require an explicit save decision

Decision

A fact enters long-term memory only through an explicit save action. Model
output is not harvested automatically as trusted memory.

Why

Generated claims can be wrong, and persistence makes them influence unrelated
future turns.

Consequences

Saved facts carry provenance and are scoped by user. Candidate-memory review or
narrow automatic policy would require a later approved decision.

Supersedes / Superseded by

The original single-user global retrieval scope was superseded by
`2026-08-27 — One persistence contract, local and deployed implementations`;
the explicit-save rule remains.

## 2026-08-01 — Tools declare consequence; the graph owns consent

Decision

`Tool.destructive` marks an action whose effect is not free to undo. The graph
pauses before execution and asks the user; without a resumable approval path,
the action is declined.

Why

Workspace confinement is not consent, and approval logic inside tools or UI
adapters would be inconsistent and transport-specific.

Consequences

Consequential actions cannot run before approval, and a resumed graph must not
repeat earlier tools from the same node.

Supersedes / Superseded by

The consent half is superseded by 2026-08-30, "Work inside a person's own
workspace does not ask permission". Declaring consequence in the tool and owning
the answer in the runtime still holds.

## 2026-08-01 — Token accounting comes from the model server

Decision

Actual request size comes from server usage and model limits. Any pre-request
estimate is owned by `ModelBackend`, not by a tokenizer in context code.

Why

Only the serving model can count its text and multimodal tokens correctly.

Consequences

The repository does not duplicate the serving tokenizer or treat message count
as token count. Context decisions use the configured fraction of the reported
model limit.

Supersedes / Superseded by

None.

## 2026-08-01 — Version 1 initially closed at Stage 3

Decision

Version 1 was initially limited to the Stage 3 persistent local product and the
minimum UI and workspace behavior needed to exercise it.

Why

The project needed a closeable baseline before expanding into policy and
autonomous-task work.

Consequences

This entry is historical and must not be used as current product scope.

Supersedes / Superseded by

Superseded by `2026-08-01 — Reopen Version 1 for product completion`.

## 2026-08-01 — Reopen Version 1 for product completion

Decision

Reopen Version 1 until persistent chat, bounded attachments, recoverable tool
failures, honest context overflow and a real browser/restart smoke pass as a
user experience rather than merely existing in code.

Why

Review showed that several first-pass checks proved narrower technical
properties than the closure language claimed.

Consequences

User-facing capability requires short end-to-end evidence. Historical Version
1 work is now closed; current sequencing lives only in `ROADMAP.md`.

Supersedes / Superseded by

Supersedes `2026-08-01 — Version 1 initially closed at Stage 3`.

## 2026-08-01 — No general project log

Decision

Do not maintain a `PROJECT_LOG.md`. Durable choices live here, human-readable
evidence in `reports/`, and structured task/measurement outcomes in the two
JSONL journals.

Why

Repeating one event across several logs creates agent work and conflicting
copies.

Consequences

Record each kind of information once in its owning document or journal.

Supersedes / Superseded by

None.

## 2026-08-02 — Benchmarks do not define the product agent

Decision

The production assistant is a general autonomous harness. Benchmark-specific
routes, prompts and verifiers remain evaluation artifacts and do not become
product control flow.

Why

A vertical slice can prove mechanics while still encoding one task instead of
agent autonomy.

Consequences

Users state outcomes through one ordinary interface. The agent derives the
plan, capabilities and evidence; scenario success alone is not product
acceptance.

Supersedes / Superseded by

Clarified by `2026-08-02 — One interface; the harness decides whether to act`.

## 2026-08-02 — Workspace confinement accepts absolute paths

Decision

Every path-taking tool validates against an explicit workspace root and accepts
both relative and absolute paths that resolve inside it. Ambiguous filenames
are clarified.

Why

The workspace is a permission boundary, not a demand that users translate a
known native path into an internal format.

Consequences

Absolute paths never bypass root validation, safe in-root paths are not rejected
for formatting alone, and ambiguous locations are not guessed.

Supersedes / Superseded by

None.

## 2026-08-02 — One interface; the harness decides whether to act

Decision

Every ordinary natural-language request enters one harness. The harness decides
whether to answer directly or plan, use tools, validate and repair.

Why

Tool use is part of the agent's work, not a product mode the user should have to
select.

Consequences

There is no Conversation/Agent selector, special task route or tool button
required for autonomous behavior.

Supersedes / Superseded by

Supersedes the earlier benchmark-era wording that referred to an agent mode.

## 2026-08-27 — The product becomes a deployable personal assistant

Decision

The local agent also deploys serverless for one owner and a small number of
other users, first through Telegram. Local and deployed profiles use the same
`app/`; deployment is configuration, infrastructure and adapters.

Why

The existing application boundaries were built to support another interface
and model endpoint without forking the product.

Consequences

Capabilities must work in both profiles before they are complete. Provider and
platform code stay behind adapters, and user-owned state is scoped by user.

Supersedes / Superseded by

Supersedes the earlier policy-platform/MCP definition of Version 2 as current
scope.

## 2026-08-27 — One persistence contract, local and deployed implementations

Decision

Conversation, summaries and facts use one `ConversationStore` contract. SQLite
implements it locally; PostgreSQL implements it in deployment. Both run the
same contract tests and scope data by user.

Why

SQLite preserves a zero-setup local profile, while concurrent serverless
workers require a network database rather than SQLite on a shared volume.

Consequences

Application code cannot depend on a concrete store. Cross-user data access and
SQLite as a deployed multi-writer database are excluded.

Supersedes / Superseded by

Generalizes the implementation-specific parts of
`2026-08-01 — Conversation data is separate from checkpoints` and supersedes
the original global fact scope.

## 2026-08-27 — An HTTP layer requires a separately hosted caller

Decision

Telegram and Chainlit remain in-process adapters. `app/api/` stays deferred
until a UI or consumer is hosted separately from the application.

Why

Two in-process adapters still do not create a useful network boundary.

Consequences

No application HTTP surface is built for its own sake, while application code
remains independent of interface request/session objects.

Supersedes / Superseded by

Amends `2026-08-01 — Defer an application HTTP layer` by making the trigger a
separately hosted caller rather than merely a second consumer.

## 2026-08-28 — Optimize a replacement model deployment, not the baseline

Decision

Validate model-serving optimizations under a separately named deployment. Move
the application endpoint only after backend, multimodal and interface
acceptance; retain the measured baseline as rollback until separately removed.

Why

A new identity preserves honest comparison and rollback and prevents a measured
configuration from being silently redefined.

Consequences

Experimental snapshot or startup changes do not overwrite the baseline.
Deleting the rollback deployment is a separate destructive human gate.

Supersedes / Superseded by

None.

## 2026-08-28 — Database latency is not a gate and control placement stays unpinned

Decision

Withdraw the invented 100 ms warm and 500 ms cold database closing limits.
Keep Neon in `us-east-2`, leave Modal control functions unpinned, and retain the
latency probe as an instrument rather than acceptance.

Why

After application reads were collapsed to one round trip, measurements showed
database execution was negligible and remaining delay was placement. Pinning
the whole worker cost more than the brief GPU wait it removed, while current
product delay was acceptable.

Consequences

Do not pin control or GPU functions or migrate the populated database solely to
reduce this round trip. Reconsider only with new product evidence and measured
economics.

Supersedes / Superseded by

Supersedes the provisional database-latency closing gate.

## 2026-08-29 — Observation and presentation are separate agent actions

Decision

Tools that read, render or inspect return evidence to the agent. Only an
explicit presentation action such as `send_file` makes selected content
outbound to the user.

Why

Automatically forwarding tool media makes an adapter or hidden workflow decide
what the user sees instead of the agent.

Consequences

Adapters transport explicit outbound content but do not turn arbitrary tool
results into chat messages. The agent may inspect several artifacts and choose
what, if anything, to send.

Supersedes / Superseded by

Supersedes automatic delivery of media returned by observation tools.

## 2026-08-29 — Web search, fetch and visual rendering are separate capabilities

Decision

Use Firecrawl for search leads, bounded direct HTTP for normal text fetch, and
an isolated secretless Chromium function for rendered page inspection.
Firecrawl scraping is an explicit fallback, not the normal fetch path.

Why

Search, byte fetching and JavaScript rendering have different costs, evidence
and trust boundaries. A universal sandbox is larger than the present need.

Consequences

Public page JavaScript does not run beside control-plane secrets or user
workspaces. Search results are not automatically fetched, screenshots are not
automatically sent, and direct fetch does not spend provider credit.

Supersedes / Superseded by

None.

## 2026-08-29 — Project configuration is the source; platforms receive a copy

Decision

Runtime values originate in project-owned local configuration. The deployment
receives an allow-listed copy through `tools/sync_control_secret.py`; provider
dashboards are not an authoring source.

Why

Provider-only values are hard to review, reproduce and move. An explicit allow
list also exposes exactly what leaves the machine.

Consequences

Do not copy the whole `.env` or manually create a second source of truth in a
provider console. Deployment-only values may be renamed during publication so
they cannot accidentally configure the local profile.

Supersedes / Superseded by

None.

## 2026-08-30 — Work inside a person's own workspace does not ask permission

Decision

Routine mutation inside the granted workspace root — creating, writing,
editing, replacing, removing files and directories — runs without asking. The
boundary, not the individual call, is what is authorized. Approval remains
required for actions whose effect leaves that boundary: sending or publishing
something, spending money, changing infrastructure, or touching data the person
did not put inside the workspace.

Why

The workspace is already confined per user and is the person's own directory;
asking before each write buys no safety the confinement does not already give,
and it turns autonomous work into a sequence of prompts. The desired experience
is an agent working inside an assigned directory, not one asking to save a file
it was told to write.

Consequences

`Tool.destructive` stops gating workspace tools and keeps its meaning for
boundary-crossing ones; consent policy belongs to the tool execution seam rather
than to the loop. `docs/PRODUCT.md` states the boundary rule instead of the
per-call one. The current baseline is unaffected until the runtime implements
it: today exactly two tools are marked destructive, `write_file` and
`edit_file`, and no tool deletes anything. Preparation and per-sub-step
acceptance are in `reports/2026-08-30_v2_step4_harness_preparation.md`.

Supersedes / Superseded by

Supersedes the consent half of 2026-08-01, "Tools declare consequence; the graph
owns consent". The other half stands: a tool declares consequence, and the
runtime — not the tool and not a UI adapter — owns what to do about it.

## 2026-08-30 — Same-user presentation and sandboxed work stay autonomous

Decision

Explicitly presenting a workspace file back to the same person through the
current conversation is part of fulfilling the request and does not ask for a
second approval. Effects beyond that relationship — sending to another person or
system, publishing, spending money or changing infrastructure — still require
approval.

Once a sandbox run itself has been separately authorized, shell, Python, package
installation and workspace mutation inside that restricted sandbox do not ask
for permission command by command. Starting each product-runtime sandbox worker
remains its own human gate under the current execution rules.

Why

`send_file` is already an explicit agent decision and an accepted part of the
conversation, not an accidental leak of an observation. Asking again would add
friction without changing the recipient. For generated code, isolation from
secrets and infrastructure is the useful boundary; confirming every command
inside that boundary would remove the autonomy the sandbox exists to enable.

Consequences

The 4.2 execution seam owns one policy across execution backends. `send_file`
remains non-destructive, while third-party and externally consequential tools
declare the need for approval. A later sandbox plugs into `execute`; it does not
change the loop or consent semantics. It receives a restricted workspace and no
control-plane secrets, and its worker-start gate is not implied by approval of a
surrounding roadmap step.

Supersedes / Superseded by

Clarifies the 2026-08-30 decision "Work inside a person's own workspace does not
ask permission"; it does not supersede it.

## 2026-08-30 — A control signal never travels in the conversation queue

Decision

An update whose purpose is to act on what is already running, or to be answered
instantly from storage, is delivered out of band: it skips the lease that
serializes a conversation, and skips the local profile's per-chat lock. `/stop`
is the case that matters — the rest of the model-free commands travel the same
way because they are the same kind of thing. Delivery alone is not enough: the
running turn has to look for the signal, so the loop checks at each step
boundary and the two halves ship together.

Why

The human's instruction on 2026-08-30, after sub-step 4.0 was accepted: a
cancellation or control signal must pass out of band relative to the ordinary
turn queue. Serializing a conversation is what makes two messages arrive in
order, and it is exactly wrong for a message about the conversation: `/stop`
queued behind the turn it exists to stop reaches the worker after that turn has
ended, finds nothing running, and says so. That was true of the local profile
from the day the per-chat lock existed, and 4.0 gave the deployed profile the
same flaw.

Consequences

`telegram_updates` gains a `control` column, and the claim never takes a control
row for a conversation. `turn_stops` records the sequence a stop arrived with,
because deployed the stop is answered in one container and the turn runs in
another. A stop applies to every turn that began before it and to no turn that
began after, so an unconsumed stop cannot cancel the next message. Evidence:
`reports/2026-08-30_v2_one_loop.md`.

Supersedes / Superseded by

Narrows the guarantee recorded on 2026-08-30 in
`reports/2026-08-30_v2_conversation_serialization.md`: a conversation's
*messages* are serialized, not everything a person sends it.

## 2026-08-30 — Stored history is canonical; what the model sees is a projection

Decision

The conversation as stored is lossless and is never rewritten or deleted by
anything that makes a request smaller. Summarizing, shortening a tool result or
dropping media produces a *model-visible surface* derived from that history, and
a derived surface may be rebuilt, rebuilt differently, or rebuilt by a different
model without the conversation changing. Compaction is always in place: a
`thread_id` before it is the same `thread_id` after it. Anything the product
depends on — the current goal, a pending decision, what has already been done —
lives in structured state, not only in the text of the surface, so no summarizer
has to guess it back.

Why

The one loop from 4.1 can spend many steps inside a single turn, so a turn can
now outgrow the request it is being assembled into before it ends. Every way of
making a request smaller is lossy, and the moment a lossy step is allowed to
write back to the store, the loss is permanent and the assistant's memory
becomes an artefact of whichever summarizer ran that day. Keeping the two apart
is what makes a summary safe to be wrong: it can be regenerated, and the exact
wording, error or filename is still recoverable from what was actually said.

Consequences

Folding writes a summary and the position it covers, never a deletion — which is
what `app/context/summary.py` already does, and is now a rule rather than an
implementation detail. Shortening a tool result on the surface leaves the full
result in history. Compaction gets a durable record of its own, in the memory
schema rather than in telemetry, because it is a source of what the model was
shown and not a measurement of a turn. `todo` and a pending `ask_user` are
structured state for this reason, which binds sub-steps 4.4 and 4.5.

Supersedes / Superseded by

None.

## 2026-08-30 — The engine's context ceiling is set once; context is spent by the application

Decision

`MAX_MODEL_LEN` is chosen once, as high as the measured KV pool validates, and
is not a tuning dial. How much context a turn actually uses is decided in the
application: it reads the ceiling from `/v1/models` and spends a fraction of it,
and later the context engine decides what fills that room. Changing how much
context the assistant uses must never require a deploy.

Why

The repository documented this backwards — that the ceiling "reserves KV cache
at start-up" — and the plan was nearly built on it. `GPU_MEMORY_UTILIZATION`
sizes the pool; the ceiling is only validated against it, so raising it costs no
VRAM at all. It costs concurrency, which for a handful of people is not a
constraint. What it does cost is one uncached boot, because vLLM builds the
engine with it and the GPU snapshot captures that engine — which is an argument
for setting it high once, not for leaving it low.

Consequences

The 16,384 ceiling stops being an architectural limit and becomes a value to
raise on the next `assistant-llm-v2` boot, which is already owed the NCCL fix.
The number comes from `Available KV cache memory` in a boot log, because a
ceiling the pool cannot hold is a refused boot. `AGENT_CONTEXT_FRACTION` remains
the only everyday control and stays a single threshold — a second fraction on
top of it would silently multiply. Raising the ceiling does not reduce the need
for compaction: prefill is measured dominant and superlinear, so a long context
is paid for in seconds per turn even when it fits.

Supersedes / Superseded by

None.

## 2026-08-30 — Turn stopping is a minimal steering seam

Decision

Turn stopping runs only when a model result would otherwise end the turn. Its
default is to stop. It continues the same loop only when an extension supplies
explicit structured steering. Sub-step 4.3 adds no validator model, finish tool,
text heuristic or new obligation state. The model decides whether the requested
outcome needs validation and which available observation capability to use.

HTML is only an acceptance scenario: the model may choose `inspect_page` when
visual evidence is material. PDF creation is removed from 4.3 acceptance until
the sandbox provides generic execution capable of creating it; no PDF-specific
workflow or tool is added to satisfy the test.

Why

A mandatory validator would recreate the fixed repair lifecycle and its cost,
while heuristics would move a semantic product decision out of the agent. A
small steering seam preserves one loop and leaves later structured state, such
as `todo`, a place to object to stopping without requiring that state now. The
current tools can read, render and deliver a PDF but cannot create its binary
contents, so retaining that acceptance before generic execution exists would
either be impossible or reward a benchmark-specific workaround.

Consequences

A normal final candidate settles immediately. Structured steering causes
another step in the same turn and must not become a second final answer in the
interface. A simple successful text write does not gain a validation pass.
Artifact validation is demonstrated through the model's trajectory and real
evidence, not through a universal validator. The natural-request PDF scenario
returns as sandbox acceptance and remains a generic harness test.

Supersedes / Superseded by

Refines the 4.3 acceptance proposed in
`reports/2026-08-30_v2_step4_harness_preparation.md`; no earlier durable
decision is superseded.

## 2026-08-30 — The prompt is assembled, and a person's instructions are an overlay

Decision

The system layer is assembled from parts rather than written as one paragraph.
A small stable core names no tool, no file format and no workflow. Everything
true only because a capability is wired up is generated from that wiring in
`app/capabilities.py`, and what each call does is owned by its tool schema.
The layers are ordered by how rarely each changes: core, capability guidance,
tool schemas, the person's standing instructions, the rolling summary, the
retrieved facts, the conversation.

A person has exactly one instruction file, `AGENTS.md`, at the root of their own
workspace. It is read on every turn and travels as its own message naming its
source, not concatenated into the system string. Its authority is below product
and capability policy: it shapes how work is done and can never widen what may
be done. It is not memory — nothing extracts it from conversation, there is no
database copy, and `remember_fact` never writes to it. `/agents` is a thin UI
over that same file.

Why

4.3 shipped one production lever, the text of a prompt, and hand-correcting
that text neither produced the behaviour it aimed at nor turned out to be what
had changed it. A measured comparison then found the real cause in what the
prompt could not say: the model was never told where its workspace was, and an
old instruction not to invent a location for a named file had generalised into
writing no file at all. Both are facts about the wiring, and a hand-written
paragraph cannot state them without going stale the moment a grant changes.

Ordering by stability is what a served prefix cache needs; today's per-turn
retrieved facts sit in front of the conversation and invalidate it from there
down. Fixing the order now costs nothing and means 4.6a measures a cache
rather than rebuilding this layer.

The instructions are a file in the workspace because the person already has an
assistant that can read and edit files there, and a command with its own store
would be a second set of instructions free to disagree with the first. They are
a separate message because the graph is compiled once per thread: an overlay
inside that compiled prompt would wait for a restart, which in the deployed
profile is invisible and on a personal machine simply does not work.

Consequences

A grant that withholds a tool also withholds the sentence about it, so guidance
cannot advertise what is not there. The core prompt may not name a tool, and a
test enforces it. Standing instructions cost tokens on every request and are
bounded at 8,000 bytes. `/agents` never reaches the model and is declared
model-free at the front door, arguments included, so writing them cannot wake a
GPU. Nothing is migrated: the file is new state in a directory that already
exists per person.

Supersedes / Superseded by

Supersedes the single hand-written `DEFAULT_SYSTEM_PROMPT` of every version up
to 2026-08-30, including the 4.3 correction to it. Does not change the 4.3
stopping seam.

## 2026-08-31 — The agent's plan is the state of one turn, and lives in that turn

Decision

`todo_write` gives the model a whole-list plan it owns, and the plan is the
state of **one unfinished turn**: it survives compaction, an interrupt, a resume
and a restarted worker, and it does not exist for the next thing the person
asks. It gets no table, no schema version and no store of its own. The list is
the arguments of the model's own last accepted call, inside the turn's messages,
which are checkpointed and are cleared by the `extend` reducer when a user
message begins a turn. Whole-list replacement is the only operation, items have
no identity, and at most one may be `in_progress`.

An unfinished plan is the first production extension in the turn-stopping seam.
It refuses one ending, names the open items, and offers the alternative that
costs nothing: update the list to say what actually happened.

Why

The lifetime asked for is exactly the lifetime the loop already gives its own
messages, so a second copy in a database would be a second thing to keep true
and a populated-database migration bought with nothing. Carrying a plan between
finished turns is a different product and was explicitly not wanted.

Planning is state the model decides to use, never a mode the harness switches
into: nothing classifies a request as complex, and an agent that wrote no plan
is never interrupted, so the ordinary answer still costs one model call. The
objection is capped at one per turn because a stale list must not become an
unbounded bill, and being made to be honest about the plan is an acceptable
outcome alongside being made to finish it.

Consequences

`Candidate` gains `steerings`, because a steered draft is deliberately never
appended to the turn's messages and an extension therefore cannot count its own
objections; any capped extension needs that number. `create_agent` wires the
extension while `Agent` does not, so the product finishes what it planned and
the bare mechanism still stops when the model stops. The capability brief states
what reads the list, since a tool schema cannot. `todo_write` is declared
model-free of any workspace root: it reaches nothing and is granted to every
agent, like memory.

Supersedes / Superseded by

Fills the seam left deliberately empty by 2026-08-30, "Whether a turn may end is
a seam, not a policy". Does not change what that seam does or its default.
