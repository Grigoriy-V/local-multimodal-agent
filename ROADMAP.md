# Roadmap

**Updated:** 2026-08-01

**Project status:** Version 1 closed; Version 1.5 is a provisional direction
under discussion

**Current approved step:** none

This is the canonical roadmap. Listing something here does not authorize work.
The human approves one step before implementation begins.

## Current state

Maximum ten bullets. When full, replace a stale fact — do not append.

- A working agent exists: a four-node graph — `load`, `model`, `tools`,
  `persist` — with the four contract tools, four context layers, SQLite
  persistence, and Chainlit in front. Evidence:
  `reports/2026-08-01_stage2_agent.md`.
- The conversation lives in the project's own SQLite; the checkpointer has its
  own file and holds only turns still in flight. Facts are global across threads
  and saved only when the model calls `remember_fact`.
- `write_file` cannot run until the user answers. The turn stops at the call,
  the question survives the process, and a refusal comes back to the model as a
  tool result. Evidence: `reports/2026-08-01_stage3_confirmation.md`.
- Older turns leave the verbatim window only once the rolling summary covers
  them, and a cut only lands at the start of a user turn, so no tool result is
  ever orphaned. Two things fold: too many messages, or a request measured over
  budget.
- The server reports `max_model_len` and `usage.prompt_tokens`. In addition to
  normal reactive folding, a typed context overflow now forces one fold and one
  retry; an unfittable request ends as a stored readable refusal. Evidence:
  `reports/2026-08-01_v1.md` and `reports/2026-08-01_v1_resilience.md`.
- The file tools take their allowed root as an argument and resolve every
  model-supplied path before comparing it against that root; the root defaults
  to a `workspace/` sandbox, not to the repository.
- The model runs outside the repository: `gemma-4-12B-it-qat-w4a16-ct` weights
  and a vLLM 0.26 server live in WSL2 `Ubuntu-22.04`, reached only over
  `http://127.0.0.1:8000/v1`. The repository declares no inference dependency.
- Chainlit reads its native sidebar and resumed threads from the canonical
  conversation SQLite. Its upload control and the UI-independent admission
  boundary now share explicit media and size limits, and a refused batch never
  starts a model turn. Evidence: `reports/2026-08-01_v1_chat_history.md` and
  `reports/2026-08-01_v1_uploads.md`.
- `httpx` is imported only by `app/models/`, `langgraph` only by `app/agent/`,
  and no `langchain_core` type appears anywhere in `app/`. No tokenizer,
  processor or provider SDK is imported anywhere.
- The Windows `.venv` holds every dependency group and the project installed
  editable; the fixtures carry meaning rather than bytes; the full target
  specification is fixed in `docs/CONTRACT.md`.

## Plan

Each open major stage or version keeps a compact outcome, ordered plan and
closing criterion, so the work remaining is visible independently of the next
step candidate. A closed stage collapses to one line and an evidence link.

### Stage 1 — Multimodal smoke test

Closed 2026-08-01: `reports/2026-08-01_stage1_smoke_script.md`.

### Stage 2 — Minimal LangGraph agent

Closed 2026-08-01: `reports/2026-08-01_stage2_agent.md`.

### Stage 3 — Full graph / Version 1 product completion

Closed 2026-08-01: `reports/2026-08-01_v1_product_smoke.md`.

### Version 1.5 — Native product controls and learning harness (provisional)

Version 1.5 is a provisional direction, not an authorized or finalized stage.
After Version 1 closes, it should prioritize learning and strengthening the
graph and harness over visual polish: native Chainlit controls and commands,
workspace instruction loading, inspectable memory, and a bounded
task-to-implementation-to-test loop. Details and unresolved decisions live in
`docs/BACKLOG.md`.

Provisional plan:

1. Harden tool-call and chat lifecycle behavior: validate calls before asking
   for confirmation, recover from correctable argument errors, and remove
   temporary/duplicate thread artifacts without losing canonical history.
2. Load applicable workspace `AGENTS.md` instructions without expanding the
   sandbox or tool permissions.
3. Add only useful native Chainlit controls and commands through thin UI
   adapters; defer custom frontend work.
4. Make SQLite memory inspectable and editable, with candidate memories kept
   separate from user-approved committed memory.
5. Evolve the graph into a bounded task, implementation, test and evaluation
   loop with explicit budgets and policy-approved verifiers.
6. Close with regression and product tasks that prove creation, verification,
   recovery and restart behavior end to end, including the HTML Snake case.

Closing criterion: the final Version 1.5 scope is approved, every retained plan
item works through the actual UI, and the bounded graph can complete or clearly
stop representative sandbox tasks without silent state or permission changes.

### Version 2 — Policy-governed tool platform (deferred)

Version 2 is not authorized yet. Its short direction is: a durable policy and
grant system for tools; policy-governed capabilities including targeted edits
and documents; an MCP surface for stronger external models; and tracing,
statistics and evaluation for the graph and tool system. Detailed deferred
direction lives in `docs/BACKLOG.md`.

Provisional plan:

1. Define one durable policy predicate and inspectable grant lifecycle shared
   by every UI, model and tool call.
2. Add targeted edits and document ingestion behind that policy boundary.
3. Expose policy-governed tools and memory through MCP.
4. Evaluate Codex app-server integration without nesting incompatible agent
   loops or placing subscription credentials in the repository.
5. Add tracing and comparable statistics for model, graph, policy and tool
   decisions.
6. Build reproducible evaluations for tool choice, policy compliance, memory
   retrieval and graph regressions.

Closing criterion: external capable models can use the same governed tools and
memory, and recorded evaluations demonstrate that policy, observability and
regression behavior hold across supported interfaces.

## Next step candidates

Maximum three. Not authorized by being listed.

1. Review and finalize the provisional Version 1.5 scope and order, then approve
   its first implementation step.

## Out of scope

Fixed by `docs/CONTRACT.md`; changing this list is a `DECISIONS.md` entry.
Fine-tuning, multi-agent orchestration, a vector database before SQLite
retrieval works, Open WebUI as the main UI.

## Maintenance

Update only the affected facts. When a stage closes, collapse it to one line
with a link, clear the approved step, then discuss the next transition. Keep the
short current direction here; `docs/BACKLOG.md` is the source of truth for
detailed deferred or possible later direction, but is not authorization or a
contract. Metrics and commands go to `reports/`. Step history is not kept here.
