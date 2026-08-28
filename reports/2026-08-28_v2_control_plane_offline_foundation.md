# V2 control plane: offline foundation

**Date:** 2026-08-28
**Scope:** approved offline work only; no database connection, webhook registration,
deployment, Telegram request, model request, sandbox or worker start.

## Result

The local and deployed profiles now select a LangGraph checkpointer through one
lifecycle. SQLite remains the local default. When `AGENT_DATABASE_URL` is set,
the same application code lazily opens `AsyncPostgresSaver`; its schema setup is
a separate explicit deployment operation and cannot happen as an import side
effect or an ordinary worker start.

The Telegram control-plane boundary is implemented without an HTTP/platform
adapter. It:

- compares Telegram's webhook secret before parsing or persisting a request;
- refuses oversized or malformed updates;
- checks the application allow list before any worker request;
- persists an admitted update before asking the platform to spawn;
- uses an atomic PostgreSQL lease so duplicate delivery or duplicate spawn does
  not process one update concurrently;
- leaves an update pending when spawn fails and returns it to pending when its
  worker fails;
- calls the existing `TelegramAdapter.handle_update` only after a worker claims
  the durable update.

The platform-specific HTTP function and spawn callback remain outside this
slice. Importing these modules starts nothing.

## Changed implementation

- `app/checkpoints.py` owns lazy SQLite/PostgreSQL saver selection and explicit
  PostgreSQL setup.
- `app/agent/runtime.py` and `app/agent/task_runtime.py` use that lifecycle;
  Telegram and Chainlit pass the configured database URL without branching.
- `ui/telegram/inbox.py` defines the durable update contract and its PostgreSQL
  leased implementation.
- `ui/telegram/webhook.py` defines validation, persistence-before-spawn and one
  worker invocation.
- `TELEGRAM_WEBHOOK_SECRET` is explicit configuration.
- the PostgreSQL dependency group includes `langgraph-checkpoint-postgres`
  3.1.2 through the lock file.

## Checks run now

- focused control-plane and affected regressions: **62 passed in 2.26 s**;
- focused new tests after the retry/deduplication correction: **9 passed in
  0.40 s**;
- full offline suite after the final code: **451 passed in 10.66 s**;
- Ruff over every changed Python module except `ui/chainlit_app.py`: clean;
- `ui/chainlit_app.py` still has its pre-existing E402 import-order exceptions
  caused by setting the Chainlit auth environment before importing Chainlit;
- `git diff --check`: clean;
- locked and imported `langgraph-checkpoint-postgres` 3.1.2 and
  `PostgresUpdateInbox` without opening a database.

## Limitations

No PostgreSQL SQL has run. The conversation-store contract, LangGraph schema
setup, inbox DDL, pooled-endpoint behaviour, reconnect behaviour and lease SQL
remain unverified against Neon. No HTTP platform adapter, Modal function,
ephemeral deployed sandbox, webhook registration or end-to-end Telegram path is
implemented or accepted here.

The untracked files under
`workspace/d992be3b-ad26-574f-89c6-ed89ea2efedd/` predate this task and were
preserved unchanged.

## Next human gate

Provide a test Neon pooled DSN as `AGENT_TEST_DATABASE_URL` and explicitly
authorize one migration/contract run. That action will create schemas/tables
and execute SQL in the external database. A later deploy, webhook registration
and every worker start each remain separate approvals.
