# V2 control plane: Neon live acceptance

**Date:** 2026-08-28
**Scope:** live PostgreSQL setup and contract acceptance on the pooled Neon
endpoint. No Telegram, Modal Function, sandbox, model or GPU worker was invoked.

## Result

The conversation store, LangGraph checkpointer and leased Telegram inbox now
run against the same Neon database and have passed live correctness acceptance.
This does not close the database stage: performance acceptance remains open.

- The parameterized `ConversationStore` contract passed against real
  PostgreSQL: **25 passed in 88.96 s** on the final run.
- The explicit migration command completed in **15.7 s** on its final run.
- A repeatable live smoke exercised inbox
  `enqueue -> claim -> retry -> claim -> complete`, rejected a duplicate spawn,
  deleted its test row and queried a missing LangGraph checkpoint:
  **1 passed in 13.34 s**.
- The final catalog inspection found application tables in `assistant` and the
  active LangGraph tables in `public`.

Credentials were loaded from the ignored local `.env`; no DSN, username,
password or secret value was printed or recorded.

## Defects found and fixed

1. On Windows, async psycopg cannot run on `ProactorEventLoop`. The explicit
   migration runner now selects `SelectorEventLoop` on Windows; Linux keeps the
   default loop.
2. `PostgresStore` used session-level `SET search_path`. The Neon pooler reused
   that state for the next client, so the first LangGraph migration created its
   tables in `assistant` and the runtime could not find `public.checkpoints`.
   Store schema selection is now transaction-local with `SET LOCAL`, and the
   upstream checkpointer normalizes its connection to `public` before setup or
   use.
3. Once `.env` contained the test DSN, Chainlit's import-time `load_dotenv`
   accidentally made the nominally offline full suite run the live contract.
   Pytest now disables implicit dotenv loading before collection. Explicit live
   wrappers still load `.env` before invoking pytest.

## Final offline checks

- full offline suite: **459 passed, 1 live test skipped in 17.84 s**;
- Ruff over every Python file changed in this slice: clean;
- `git diff --check`: clean.

## External actions, cost and limits

The run created the persistent application/checkpoint schemas and tables,
created and dropped contract-only schemas, and inserted/deleted one inbox smoke
row. Neon compute usage was short and was not measured as a billable amount.
GPU/VRAM use was **0**. No project worker, Modal container, Telegram request,
model request, image build or deploy occurred.

No result here establishes the product latency budget. Contract and smoke
durations contain many operations from the developer machine and cannot be
divided into per-query claims. A later deployed-path benchmark must time each
complete logical read or write, including all connection and SQL work, at
**<=500 ms cold** and **<=100 ms warm**. The stage remains open until both pass.

After the human explicitly approved cleanup, the four unused
`assistant.checkpoint_*` tables from the failed first migration were dropped in
one statement without `CASCADE`. A catalog read then found only the active
`public.checkpoint_*` tables. This cleanup is not recoverable, but the removed
tables contained only the failed checkpointer migration state and were never
used by the accepted runtime.

Deployment is also still blocked on `TELEGRAM_WEBHOOK_SECRET`; all other
required control-plane environment keys are present locally. Creating the Modal
Secret, building/deploying `assistant-control`, invoking each CPU worker,
registering the Telegram webhook and starting a sandbox remain separate gates.
