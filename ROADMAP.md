# Roadmap

**Updated:** 2026-08-01

**Project status:** foundation created, Stage 1 not started

**Current approved step:** none

This is the canonical roadmap. Listing something here does not authorize work.
The human approves one step before implementation begins.

## Current state

Maximum ten bullets. When full, replace a stale fact — do not append.

- The repository contains documents, the package skeleton, the `ModelBackend`
  interface, an environment doctor, and the work-log tool.
- No dependency has been installed, no model downloaded, and no vLLM server run.
- The full target specification is fixed in `docs/CONTRACT.md`.

## Plan

Three stages from the contract. Each states the outcome and its closing
criterion, not the method. A closed stage collapses to one line and a link.

### Stage 1 — Multimodal smoke test

Prove that the chosen model runs locally and answers text, image, multi-image,
and short-audio requests through an OpenAI-compatible endpoint, with streaming,
a system prompt, structured JSON output, and one test tool call.

**Closes when:** a script independent of the final UI exercises all of the above
and records latency, VRAM, and failures.

### Stage 2 — LangChain agent

A minimal agent with `list_files`, `read_file`, `remember_fact`, and
`search_memory`, four context layers, SQLite persistence, and Chainlit exposing
tool calls and intermediate steps.

**Closes when:** conversations survive a restart, a fact saved in one session is
retrieved in a later one, older context is summarized rather than grown, and
integration tests cover the agent.

### Stage 3 — LangGraph migration

Replace implicit orchestration with an explicit graph adding state, checkpoints,
resumable sessions, context-size control, tool error handling, retry paths, and
confirmation before destructive actions.

**Closes when:** the graph runs the same flows and the inference, UI, memory, and
tool layers were not rewritten to achieve it.

## Next step candidates

Maximum three. Not authorized by being listed.

1. Install the locked dependencies and run the environment doctor.
2. Decide how the vLLM server is launched and where the model weights live.
3. Fix the exact contents and pass/fail criteria of the Stage 1 smoke test.

## Out of scope

Fixed by `docs/CONTRACT.md`; changing this list is a `DECISIONS.md` entry.
Fine-tuning, multi-agent orchestration, a vector database before SQLite
retrieval works, Open WebUI as the main UI.

## Maintenance

Update only the affected facts. When a stage closes, collapse it to one line
with a link, clear the approved step, then discuss the next transition. Ideas
and deferred work go to `docs/BACKLOG.md`. Metrics and commands go to
`reports/`. Step history is not kept here.
