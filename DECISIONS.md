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
