# V2 control plane: CPU platform adapter

**Date:** 2026-08-28
**Scope:** queue 1 work that cannot wake or call the GPU endpoint. No deployment,
database connection, Telegram request, sandbox or worker start was performed.

## Result

The Modal adapter for `assistant-control` is written and registered offline as
two independently scaling CPU functions:

- `telegram_webhook` is an unauthenticated-at-Modal HTTP endpoint because
  Telegram cannot send Modal proxy credentials. The existing application core
  verifies Telegram's secret and allow list, persists the update and returns.
- `process_telegram_update` claims the durable PostgreSQL lease and invokes the
  existing `TelegramAdapter`. The webhook calls it with `spawn`, never with a
  blocking remote call.

Both functions explicitly scale to zero. Importing the module invokes neither.
The deployment image is resolved from `uv.lock` and copies only `app/` and
`ui/`; it does not copy `.env`, data, reports or a human workspace. The model
App is not imported or redeployed.

Database setup now has one explicit local command that migrates the conversation
store, LangGraph checkpoints and Telegram inbox in order:

```powershell
.venv\Scripts\python.exe -m tools.setup_control_plane
```

Ordinary application or worker startup still runs no migration.

## Checks run now

- focused control-plane tests: **16 passed in 0.37 s**;
- full offline suite: **458 passed in 10.51 s**;
- Ruff on all files introduced by this slice: clean;
- imported the Modal module and observed exactly
  `process_telegram_update` and `telegram_webhook` registered, without invoking
  either function;
- `git diff --check`: clean;
- queried Modal Secret names only: the result was empty. No secret values were
  requested or exposed.

## External actions and cost

One read-only Modal API request listed secret names. No database, Telegram or
model request was made. No image was built, no App was deployed, no worker or
sandbox started and no GPU endpoint was contacted. Measured VRAM use is **0**;
external compute cost from this work is **0**.

## Remaining limits and gates

Live database acceptance is blocked because neither `AGENT_TEST_DATABASE_URL`
nor `AGENT_DATABASE_URL` exists locally, and Modal currently has no Secrets.
The production control secret must contain at least the pooled PostgreSQL DSN,
Telegram token, webhook secret, allow list and existing model endpoint/auth
configuration.

After credentials exist, the separate remaining actions are:

1. run the live PostgreSQL contract and explicit migrations (external SQL, no
   project worker and no GPU);
2. build/deploy `assistant-control` (external mutation; may build/start CPU
   infrastructure, but does not redeploy `assistant-llm-v2`);
3. invoke one named CPU webhook/worker acceptance action; an ordinary message
   can call the model, so a GPU-free acceptance must use a command such as
   `/can` and verify the model endpoint received no request;
4. implement and accept the ephemeral sandbox path, with each sandbox start
   separately authorized;
5. register the Telegram webhook, which retires polling and is its own external
   mutation.
