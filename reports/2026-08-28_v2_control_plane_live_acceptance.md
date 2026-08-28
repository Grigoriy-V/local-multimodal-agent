# V2 control plane — the deployed adapter answers a real Telegram message

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** the chain works end to end. A message sent from the human's own
Telegram account was answered by the assistant with nothing running on the
human's machine. Polling is retired; the local poller took no part.

## The chain that ran

Telegram → `telegram_webhook` on Modal → secret-token and allow-list checked in
the application → update persisted to the Neon inbox → `process_telegram_update`
spawned as a separate CPU worker → the same `TelegramAdapter` and harness →
`assistant-llm-v2` woken from its snapshot → reply delivered to the chat.

Every part of that except the model had never run outside a test before.

## The defect the latency probe could not find

The first live message failed with:

```text
ProgrammingError: can't change 'autocommit' now: connection in transaction
status INTRANS
```

`PostgresStore` opens without autocommit. Every read issues a `SELECT` and none
of them commit, so the connection sits in an open transaction as soon as
anything is read. The single-round-trip context query turns autocommit on for
one statement, and psycopg refuses that inside a transaction.

A turn calls `current_thread()` — which lists the user's threads — before it
assembles context. So **every message failed**, not an unlucky one.

The probe passed the same code because it read context first, on a fresh
connection. One operation measured in isolation was healthy; two in the order a
turn performs them were not. That is the whole lesson: a benchmark that does not
reproduce the caller's sequence certifies nothing about the caller.

`PostgresStore._settle` now leaves the connection outside a transaction, after a
read as well as before switching autocommit. The second reason outlives the bug:
an idle-in-transaction connection holds a slot and a snapshot on a pooled
server, and this assistant is idle by design between messages.

The regression is guarded twice. The fake connection in
`tests/test_postgres_optimized_paths.py` now models transaction status and
refuses an autocommit change inside a transaction exactly as psycopg does —
verified by reverting the fix, at which point the test fails. And the contract
suite gained the real sequence, `threads()` then `turn_context()`, which runs
against both implementations.

## Latency, measured rather than felt

Three defects were found in the deployed chain and two were fixed here.

**A blocking Modal RPC inside the event loop.** Modal's own runtime warned in
production logs that `process_telegram_update.spawn(update_id)` was a
synchronous call from an async context, and suggested the fix it now uses. It is
the webhook's event loop, the one Telegram is waiting on.

**A cold start on every single message.** Both CPU functions had
`scaledown_window=2`, which is shorter than any pause between two messages, so
no container was ever reused. The window is now 15 s on the webhook and the
worker. The arithmetic is the opposite of the GPU's: a cold start costs about
three seconds of a person's attention, while holding the webhook container for a
full window costs $0.000066 and the worker $0.00026. The expensive resource here
is the person, not the CPU. The probe function keeps 2 s; it is invoked
deliberately and sits on no one's waiting path.

| webhook | duration | execution |
|---|---|---|
| before, every message | 5.05 / 4.67 / 4.75 s | 1.85 / 1.67 / 1.78 s |
| after, cold | 4.69 s | 1.70 s |
| after, warm | **306.2 ms** | **271.4 ms** |

**A warm webhook is 15x faster.** The human's own account: the first message
took about ten seconds, the second was nearly instant.

Honesty about attribution: these two fixes cannot be separated by this data. The
cold path did not move at all — 4.69 s against 4.67-5.05 s before — so the
visible win is the window, not the async spawn. What `.aio()` demonstrably did
was stop blocking the event loop and silence the warning; no isolated number is
claimed for it.

## What still costs time

| | |
|---|---|
| webhook container start | ~3.0 s |
| first execution over warm (1.70 vs 0.27 s) | ~1.4 s |
| worker cold start | not measured; structurally similar |
| GPU wake from snapshot | 5.5 s |

The 1.4 s gap is Python imports plus the first TLS handshake to Neon across the
Atlantic. `min_containers=1` on the webhook would remove roughly 4.4 s of it for
about **$11 a month** — a quarter of the GPU bill for a few seconds on the first
message of a series. Recorded as a priced option, not a recommendation.

## Two capabilities that do not survive the move

Both are consequences of execution leaving the human's machine, and neither is a
regression in the code:

- **Screenshots.** `find_chromium_browser()` looks for an installed browser. On
  Windows it found Edge, which is why browser evidence worked; `debian_slim` has
  none. `/usr/bin/chromium` is already in the search list, so the fix is
  `apt_install("chromium")` plus `--no-sandbox` and `--disable-dev-shm-usage`
  when running as root. A task whose plan asks for rendered evidence will fail
  validation until then.
- **Files between messages.** The workspace lives in the container and the next
  turn gets a different one. This is the ephemeral sandbox, deliberately
  deferred by the human.

## Checks

- offline suite: **471 passed, 1 skipped**;
- store contract against real PostgreSQL: **29 passed in 82.66 s**, including
  both new sequence tests, with per-test schemas created and dropped;
- the regression test verified in both directions — reverting `_settle` makes it
  fail;
- `ruff` on every changed file, and `git diff --check`: clean.

## External actions and cost

Three `assistant-control` deploys (25.5 s, 15.9 s and one earlier), the Telegram
webhook registered, one contract run against the test database, and the live
messages the human sent. GPU time is whatever those messages cost: one wake at
5.5 s plus inference. No GPU deploy, no snapshot rebuild, no sandbox.

`tools/telegram_webhook.py` registers, inspects and reverts the webhook;
`--delete` returns the bot to polling in one command.

## Not done

- Chromium in the control image.
- File tools over an ephemeral sandbox.
- The NCCL TCPStore warnings, which emit a stack trace every second and made the
  model app's logs unusable for diagnosis during this work — the request
  timings could not be read out of them. Their fix is owed to the next GPU
  deploy, which also carries `SCALEDOWN_WINDOW = 2`.
