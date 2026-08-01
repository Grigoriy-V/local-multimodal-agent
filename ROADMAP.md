# Roadmap

**Updated:** 2026-08-01

**Project status:** Version 1 closed; Version 1.5 steps 1 through 4 closed

**Current approved step:** none

This is the canonical roadmap. Listing something here does not authorize work.
The human approves one step before implementation begins.

## Current state

Maximum ten bullets. When full, replace a stale fact — do not append.

- The conversational agent remains a four-node graph — `load`, `model`,
  `tools`, `persist` — with six tools, four context layers, SQLite and Chainlit.
  A separate bounded task graph now owns the explicit
  `task -> plan -> implement -> test -> evaluate -> retry/finalize` lifecycle.
  Its model adapter produces structured plans and executes filesystem calls only
  through the active task grant, returning exact tool results to the model.
  Evidence: `reports/2026-08-01_stage2_agent.md` and
  `reports/2026-08-01_v15_step2.md` through
  `reports/2026-08-01_v15_step4.md`.
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

### Version 1.5 — Agent task harness and native product controls

Version 1.5 first proves the agent loop on one concrete vertical slice: the
agent must create, repair and verify a working HTML Snake inside its sandbox.
Graph and harness correctness come before UI polish. Detailed boundaries and
later ideas live in `docs/BACKLOG.md`; listing these steps does not authorize
their implementation.

Milestone A — autonomous Snake task:

1. Closed 2026-08-01: added atomic sandboxed exact single-match `edit_file`,
   JSON-schema validation before confirmation, and the measured
   `MODEL_MAX_TOKENS=4096` coding profile while retaining the validated 16k
   server context. Evidence: `reports/2026-08-01_v15_step1.md`.
2. Closed 2026-08-01: added explicit task state and graph routes for
   `task -> plan -> implement -> test -> evaluate -> retry/finalize`, structured
   plans and acceptance criteria, and hard iteration, tool-call and time
   budgets. Evidence: `reports/2026-08-01_v15_step2.md`.
3. Closed 2026-08-01: added a checkpointed task-scoped grant. After planning,
   one explicit approval permits `write_file` and `edit_file` only in the
   declared sandbox subdirectory for that run; the grant survives a SQLite
   checkpoint and is revoked on completion or refusal. Evidence:
   `reports/2026-08-01_v15_step3.md`.
4. Closed 2026-08-01: connected a model-agnostic `ModelTaskWorker` to the task
   graph. It starts each attempt from a real grant-root listing, creates through
   `write_file`, repairs through `read_file` plus `edit_file`, feeds exact tool
   failures back to the model and prevents over-budget calls from running.
   Evidence: `reports/2026-08-01_v15_step4.md`.
5. Add a deterministic web verifier for file presence, HTML structure,
   JavaScript syntax and required game controls; return one structured test
   report to `evaluate`.
6. Route a failed report back to implementation while budget remains, otherwise
   finalize honestly with the artifact and failures; never claim success from
   plausible code alone.
7. Add the browser verifier and preview: load the page, collect console errors,
   prove canvas rendering and time-based movement, exercise keyboard input and
   expose the final artifact through the UI.
8. Close Milestone A with offline graph tests and one live Gemma product task
   that creates Snake, corrects a seeded or observed failure, passes both
   verifier layers and survives the required confirmation/checkpoint flow.

Milestone B — product capabilities on the working harness:

9. Reconcile temporary and canonical chat IDs, then add useful native Chainlit
   commands, settings and task status through thin UI adapters.
10. Load applicable workspace `AGENTS.md` instructions without expanding the
    sandbox, grants or tool permissions.
11. Make SQLite memory inspectable and editable, with candidate memories kept
    separate from user-approved committed memory.
12. Run the complete regression and browser/restart product smoke for all
    retained Version 1.5 capabilities.

Closing criterion: the bounded graph completes or clearly stops representative
sandbox tasks; the live Snake task passes deterministic and browser checks; and
the retained instruction, native UI, chat and memory behavior works through the
actual product without silent state or permission changes.

### Version 2 — Policy-governed tool platform (deferred)

Version 2 is not authorized yet. Its short direction is: a durable policy and
grant system for tools; policy-governed documents and future capabilities; an
MCP surface for stronger external models; and tracing,
statistics and evaluation for the graph and tool system. Detailed deferred
direction lives in `docs/BACKLOG.md`.

Provisional plan:

1. Define one durable policy predicate and inspectable grant lifecycle shared
   by every UI, model and tool call.
2. Put document ingestion and later capabilities behind that policy boundary.
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

1. Approve and implement Version 1.5 step 5: a deterministic web verifier for
   file presence, HTML structure, JavaScript syntax and required game controls.

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
