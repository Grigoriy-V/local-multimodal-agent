# Roadmap

**Updated:** 2026-08-01

**Project status:** Stage 1 closed, Stage 2 started — the tool loop closes

**Current approved step:** none

This is the canonical roadmap. Listing something here does not authorize work.
The human approves one step before implementation begins.

## Current state

Maximum ten bullets. When full, replace a stale fact — do not append.

- The repository contains documents, the package skeleton, the `ModelBackend`
  interface, an OpenAI-compatible backend on `httpx`, settings, an environment
  doctor, the Stage 1 smoke runner, the work-log tool, the filesystem tools, and
  the minimal agent graph.
- The tool loop closes: `Message` carries the assistant's own tool calls, and a
  two-node graph — model, tools — ran a real two-iteration cycle against the
  endpoint in 3.8 s.
- `list_files` and `read_file` take their allowed root as an argument and
  resolve every model-supplied path before comparing it against that root.
- The model runs outside the repository: `gemma-4-12B-it-qat-w4a16-ct` weights
  and a vLLM 0.26 server live in WSL2 `Ubuntu-22.04`, reached only over
  `http://127.0.0.1:8000/v1`. The repository declares no inference dependency.
- Every Stage 1 contract item is exercised by repository code and passes; see
  `reports/2026-08-01_stage1_smoke_script.md`.
- The fixtures carry meaning rather than bytes: three seconds of speech in wav
  and flac, and two flat images the model can name.
- Only `app/models/` may import a transport or provider library; importing the
  interface package does not pull in `httpx`.
- The Windows `.venv` holds the test tools, the `app` and `agent` dependency
  groups, and the project installed editable.
- The full target specification is fixed in `docs/CONTRACT.md`.

## Plan

Three stages from the contract. Each states the outcome and its closing
criterion, not the method. A closed stage collapses to one line and a link.

### Stage 1 — Multimodal smoke test

Closed 2026-08-01: `reports/2026-08-01_stage1_smoke_script.md`.

### Stage 2 — Minimal LangGraph agent

A small graph — model, tools, model — with `list_files`, `read_file`,
`remember_fact`, and `search_memory`, four context layers, SQLite persistence,
and Chainlit exposing tool calls and intermediate steps.

**Closes when:** conversations survive a restart, a fact saved in one session is
retrieved in a later one, older context is summarized rather than grown, and
integration tests cover the agent.

### Stage 3 — Full graph

Grow the same graph to the full flow, adding explicit state, checkpoints,
resumable sessions, context-size control, tool error handling, retry paths, and
confirmation before destructive actions.

**Closes when:** the graph runs the same flows and the inference, UI, memory, and
tool layers were not rewritten to achieve it.

## Next step candidates

Maximum three. Not authorized by being listed.

1. Build the SQLite layer — threads, messages, and facts — so there is something
   for a conversation to survive into, plus `remember_fact` and `search_memory`
   on top of it.
2. Put Chainlit in front of the graph, showing tool calls and intermediate
   steps. Makes the agent usable by hand; adds nothing the closing criteria ask
   for.

## Out of scope

Fixed by `docs/CONTRACT.md`; changing this list is a `DECISIONS.md` entry.
Fine-tuning, multi-agent orchestration, a vector database before SQLite
retrieval works, Open WebUI as the main UI.

## Maintenance

Update only the affected facts. When a stage closes, collapse it to one line
with a link, clear the approved step, then discuss the next transition. Ideas
and deferred work go to `docs/BACKLOG.md`. Metrics and commands go to
`reports/`. Step history is not kept here.
