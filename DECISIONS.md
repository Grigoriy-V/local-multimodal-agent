# Decisions

Architecture and scope decisions only. Not a work log, not a task ledger, not a
place for results.

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
`app/memory/store.py`. A LangGraph checkpointer, when Stage 3 adds one, records
in-flight turn state only — it is not where the conversation is kept.

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

**Why.** The contract forbids storing model-generated facts as trusted memory
without an explicit save decision, so nothing may be harvested from an answer
automatically. Global visibility is the point of long-term memory — a fact scoped
to its own thread is indistinguishable from the transcript.

**Rules out.** Inferring facts from model output, and per-thread fact isolation.

## 2026-08-01: No PROJECT_LOG; this file plus the journals replace it

**Decision.** There is no `PROJECT_LOG.md`. Decisions live here, measured
outcomes live in `reports/ml_work.jsonl` and `reports/`, task outcomes live in
`reports/agent_tasks.jsonl`.

**Why.** In an earlier project a single event was written to four places, which
multiplied agent work and created four points of divergence.

**Rules out.** Restating a result in more than one place.
