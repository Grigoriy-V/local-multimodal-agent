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

## 2026-08-01: SQLite-only memory before any vector store

**Decision.** Long-term facts live in SQLite; initial retrieval uses full-text
search. Embeddings are deferred.

**Why.** The basic four-layer context system must be shown to work before
retrieval quality is optimized.

**Rules out.** Adding a vector database as part of Stage 2.

## 2026-08-01: No PROJECT_LOG; this file plus the journals replace it

**Decision.** There is no `PROJECT_LOG.md`. Decisions live here, measured
outcomes live in `reports/ml_work.jsonl` and `reports/`, task outcomes live in
`reports/agent_tasks.jsonl`.

**Why.** In an earlier project a single event was written to four places, which
multiplied agent work and created four points of divergence.

**Rules out.** Restating a result in more than one place.
