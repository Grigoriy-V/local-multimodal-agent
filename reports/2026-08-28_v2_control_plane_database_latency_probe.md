# Control-plane database latency probe

**Date:** 2026-08-28  
**Scope:** offline implementation plus Modal Secret creation; no deployment or worker run

## Result

The production context-loading path and the database latency acceptance now
share one application-level operation, `load_turn_context`. It includes the
rolling-summary read, recent-message read and fact retrieval. The production
graph and `Agent.context_prompt` both call this boundary, so the probe cannot
pass by timing a smaller, benchmark-only query.

The CPU-only Modal probe supports three deliberately separate invocations:

1. `prepare` creates an isolated representative fixture with one summary,
   eight recent messages and five matching durable facts;
2. `read` measures store construction/connection plus the complete context
   read, then five complete warm reads and judges the maximum;
3. `write` measures store construction/connection plus a complete two-message
   turn append, then five complete warm appends and judges the maximum.

Every first sample includes `open_store`, including every connection and SQL
round-trip the current implementation performs. Warm acceptance uses the
maximum observed sample, not an average or percentile. The limits are encoded
as **cold <=500 ms** and **warm max <=100 ms**. The read refuses to report a
result unless the representative fixture has the expected shape. Temporary
write threads are removed after the measurement; the isolated read fixture is
retained until explicit cleanup.

The control functions deliberately use Modal's default unpinned placement, so
no compute-region price multiplier is requested. The probe records the actual
`MODAL_REGION` with every result. The latency limits apply to that real
production placement: a remote placement is not excluded from the result and a
miss is not hidden by selecting a more favorable sample.

## Checks

- Targeted context, graph, agent-session and Modal adapter tests:
  **63 passed in 1.70 s**.
- Full offline regression after the final code: **461 passed, 1 skipped in
  16.52 s**. The skipped test is the opt-in live database acceptance.
- Ruff over every touched Python file: passed.
- `git diff --check`: passed, apart from Git's existing CRLF conversion notice.

## External actions, cost and limits

The Modal Secret `assistant-control` was created from 10 allow-listed runtime
keys. `AGENT_TEST_DATABASE_URL` and unrelated `.env` values were not copied.
The secret values were not printed or written into the repository.

No image build, deploy, Modal Function, Telegram request, model request or GPU
worker occurred. VRAM use was **0** and compute cost from this work was **0**.
No latency result exists yet, so the database performance gate remains open.

## Remaining acceptance sequence

Each item starts a distinct CPU worker and therefore needs fresh explicit
permission immediately before it runs:

1. deploy `assistant-control` (the deploy may build an image but must not invoke
   a function);
2. invoke `prepare` once;
3. after Neon has scaled to zero, invoke `read` once;
4. after Neon has scaled to zero again, invoke `write` once.

The first sample may be called database-cold only when Neon, not merely the
Modal Function, was idle. If either operation misses either limit, the control
plane stays open and the measured call sequence must be optimized before a
retry.
