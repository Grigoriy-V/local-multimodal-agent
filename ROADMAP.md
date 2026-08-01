# Roadmap

**Updated:** 2026-08-01

**Project status:** Version 1 reopened for product completion; stages 1 and 2
are closed and the Stage 3 functional core exists

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
- The server reports `max_model_len` and `usage.prompt_tokens`, and an
  over-budget completed request triggers a fold before the next turn. This is
  reactive accounting, not a preflight hard bound; overflow recovery remains a
  Version 1 completion item. Evidence: `reports/2026-08-01_v1.md`.
- The file tools take their allowed root as an argument and resolve every
  model-supplied path before comparing it against that root; the root defaults
  to a `workspace/` sandbox, not to the repository.
- The model runs outside the repository: `gemma-4-12B-it-qat-w4a16-ct` weights
  and a vLLM 0.26 server live in WSL2 `Ubuntu-22.04`, reached only over
  `http://127.0.0.1:8000/v1`. The repository declares no inference dependency.
- The UI can replay stored conversations, show images and audio, name an
  attachment it cannot read, and report the last measured request size. Its
  current startup button chooser is temporary; Version 1 still needs normal
  persistent chat history and product-level create, switch and resume behavior.
- `httpx` is imported only by `app/models/`, `langgraph` only by `app/agent/`,
  and no `langchain_core` type appears anywhere in `app/`. No tokenizer,
  processor or provider SDK is imported anywhere.
- The Windows `.venv` holds every dependency group and the project installed
  editable; the fixtures carry meaning rather than bytes; the full target
  specification is fixed in `docs/CONTRACT.md`.

## Plan

Three stages from the contract. Each states the outcome and its closing
criterion, not the method. A closed stage collapses to one line and a link.

### Stage 1 — Multimodal smoke test

Closed 2026-08-01: `reports/2026-08-01_stage1_smoke_script.md`.

### Stage 2 — Minimal LangGraph agent

Closed 2026-08-01: `reports/2026-08-01_stage2_agent.md`.

### Stage 3 — Full graph / Version 1 product completion

The functional core was delivered 2026-08-01 in two parts: checkpoints,
resumable turns and confirmation —
`reports/2026-08-01_stage3_confirmation.md`; then the first Version 1 pass —
`reports/2026-08-01_v1.md`. Version 1 was reopened after product review.

Version 1 closes only when all of these hold together:

- normal persistent chat history supports create, switch, resume and restart
  without losing the existing conversations;
- the upload control accepts only supported inputs at explicit safe sizes, and
  unsupported or oversized input never becomes an empty model turn;
- expected tool and filesystem failures return readable tool results instead of
  terminating the graph;
- context overflow causes one bounded recovery attempt or a clear refusal, while
  the existing rolling-summary behavior remains intact;
- the complete experience passes offline regression checks and a real
  browser/restart product smoke against the local endpoint.

### Version 2 — Policy-governed tool platform (deferred)

Version 2 is not authorized yet. Its short direction is: a durable policy and
grant system for tools; policy-governed capabilities including targeted edits
and documents; an MCP surface for stronger external models; and tracing,
statistics and evaluation for the graph and tool system. Detailed deferred
direction lives in `docs/BACKLOG.md`.

## Next step candidates

Maximum three. Not authorized by being listed.

1. Finish Version 1 product completion, beginning with native persistent chat
   history. Each implementation step still requires separate human approval.

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
