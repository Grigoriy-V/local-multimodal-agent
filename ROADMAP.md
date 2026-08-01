# Roadmap

**Updated:** 2026-08-01

**Project status:** Stages 1 and 2 closed, Stage 3 under way

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
  ever orphaned.
- The file tools take their allowed root as an argument and resolve every
  model-supplied path before comparing it against that root.
- The model runs outside the repository: `gemma-4-12B-it-qat-w4a16-ct` weights
  and a vLLM 0.26 server live in WSL2 `Ubuntu-22.04`, reached only over
  `http://127.0.0.1:8000/v1`. The repository declares no inference dependency.
- The fixtures carry meaning rather than bytes: three seconds of speech in wav
  and flac, and two flat images the model can name.
- `httpx` is imported only by `app/models/`, `langgraph` only by `app/agent/`,
  and no `langchain_core` type appears anywhere in `app/`.
- The Windows `.venv` holds every dependency group and the project installed
  editable.
- The full target specification is fixed in `docs/CONTRACT.md`.

## Plan

Three stages from the contract. Each states the outcome and its closing
criterion, not the method. A closed stage collapses to one line and a link.

### Stage 1 — Multimodal smoke test

Closed 2026-08-01: `reports/2026-08-01_stage1_smoke_script.md`.

### Stage 2 — Minimal LangGraph agent

Closed 2026-08-01: `reports/2026-08-01_stage2_agent.md`.

### Stage 3 — Full graph

Grow the same graph to the full flow, adding explicit state, checkpoints,
resumable sessions, context-size control, tool error handling, retry paths, and
confirmation before destructive actions.

Done: checkpoints, resumable turns, and confirmation before a destructive tool —
`reports/2026-08-01_stage3_confirmation.md`. Still open: context-size control by
tokens, and a retry path for a failing model call.

**Closes when:** the graph runs the same flows and the inference, UI, memory, and
tool layers were not rewritten to achieve it.

## Next step candidates

Maximum three. Not authorized by being listed.

1. Bound the request by tokens, not by turn count — the current window counts
   messages, so one large image can still dominate a request. The last Stage 3
   item with no answer at all.
2. Retry a model call that fails transiently, inside `ModelBackend`, so the
   graph keeps one failure mode instead of two.
3. Give the UI a thread list instead of resuming the newest thread silently, and
   show which threads are waiting on an answer.

## Out of scope

Fixed by `docs/CONTRACT.md`; changing this list is a `DECISIONS.md` entry.
Fine-tuning, multi-agent orchestration, a vector database before SQLite
retrieval works, Open WebUI as the main UI.

## Maintenance

Update only the affected facts. When a stage closes, collapse it to one line
with a link, clear the approved step, then discuss the next transition. Ideas
and deferred work go to `docs/BACKLOG.md`. Metrics and commands go to
`reports/`. Step history is not kept here.
