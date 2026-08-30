# V2 sub-step 4.1.5 — real context capacity

**Date:** 2026-08-30
**Agent:** Claude, direct session
**Outcome:** implemented, offline suite green, the ceiling raised and live on the
deployed endpoint. The end-to-end product check is still owed — see "What is not
verified".

The plan and the arithmetic behind it, including the arithmetic that turned out
to be wrong, are in `reports/2026-08-30_v2_context_memory_plan.md`. This report
is what was built and what was measured.

## What the effective limit was

9,830 tokens: a 16,384 ceiling spent at `AGENT_CONTEXT_FRACTION` 0.6. Not 16k,
and small enough that a single turn of the 4.1 loop with a few tool results
reaches it. Raising it was the acute part; the rest of this sub-step is about
noticing the limit before rather than after crossing it.

## The boot

One deploy, one boot, three changes, all in the boot that was already owed the
NCCL fix.

```text
MAX_MODEL_LEN         16384 -> 65536
NCCL rendezvous       pinned to loopback in the image environment
max_inputs            32 -> 8
GPU_MEMORY_UTILIZATION  0.80, unchanged
kv_cache_dtype          auto, unchanged
```

Deploy took 9.4 s and rebuilt only the environment layer; the weights and the
image were untouched. The first request after it paid for the new snapshot:

```text
REQUEST TO SERVING: 299.7s
  text     200   1.55s    18 in /  25 out  stop
  image    200   2.34s   281 in /   5 out  stop
  audio    200   1.53s    95 in /  12 out  stop
```

All three modalities answered on the new revision, which matters because
multimodal profiling has broken on a configuration change before.

### What the log says

```text
non-default args: {... 'max_model_len': 65536, 'gpu_memory_utilization': 0.8 ...}
Available KV cache memory: 11.13 GiB
GPU KV cache size: 256,669 tokens
Maximum concurrency for 65,536 tokens per request: 3.92x
enable_prefix_caching=True, enable_chunked_prefill=True, kv_cache_dtype=auto
```

**The prediction was wrong, and generously so.** 1.32x concurrency was expected,
from treating KV per token as a constant derived from 16k boot logs. The real
figure is 3.92x. The same ~11 GiB held 86,664 tokens at a 16k ceiling and
256,669 at a 64k one, so that constant is a property of a configuration and not
of the model. The records that were written on it — `ROADMAP.md`,
`DECISIONS.md`, `model_app.py` and the plan report — were corrected the same
day, including the withdrawal of "128k is unreachable on an A10", which is now
an open question rather than a settled no.

**The NCCL warning storm is gone.** Every `Broken pipe` and `should dump` line
in the retained log window falls between 00:30 and 00:58, from containers of the
previous revision. There are none at or after the 01:45 boot. That closes an
item owed since 2026-08-28, which was deliberately not fixed then because it was
warning-only and a snapshot must not be rebuilt to tidy logs.

**vLLM offered a second opinion on utilization**, unprompted: CUDA graph memory
profiling means 0.80 here is equivalent to 0.7640 under the older accounting,
and 0.8360 would restore the pre-v0.21 effective pool. That is the number to
probe from if the pool is ever worth raising. It was not raised: 3.92x is more
room than 64k needs.

## The pressure check moved in front of the model call

Folding used to happen in `persist`, from the size the *previous* request
reported. Exact, and one turn late — and with one loop able to spend many steps
inside a single turn, "next turn" can be long after the conversation stopped
fitting.

`fitted` in `app/agent/graph.py` now estimates the request about to be sent,
before every model step, and folds first if it is over budget. The oversized
request is not sent at all.

The cost of moving earlier is that the size is an estimate rather than a report.
`ModelBackend.estimate_tokens` is that estimate, behind the model boundary
because the same text is a different number of tokens for a different model —
the rule that keeps tokenizers inside `app/models/` applies to estimates of one.
It is characters over a ratio, plus a fixed price per media part, plus tool-call
arguments, which is where a `write_file` hides a whole file.

It calibrates itself. Every completion reports how many tokens the request
became, so the conversion arrives free on traffic that was being sent anyway;
`_calibrate` blends it in at 0.25, ignores requests carrying media (whose
reported total includes an image this ratio must not absorb) and requests under
500 characters (mostly template overhead), and clamps the result to 1.0–6.0. The
clamp matters in one direction especially: a ratio drifting too high would make
every request look small and quietly stop folding anything.

The starting ratio is 3.0 characters per token, deliberately pessimistic — this
assistant is talked to in Russian and carries JSON and file contents, all of
which tokenize worse than English prose. The two errors are not symmetric:
overestimating folds earlier than necessary, underestimating sends a request the
server refuses.

Incidentally measured on the boot: an image plus a short question came to 281
prompt tokens, against the 320 this prices an image at. Conservative and close.

## The budget is per-person in mechanism

`Agent.budget()` takes `context_tokens` when one is set, clamped to what the
server reports, and falls back to the fraction otherwise. An `Agent` belongs to
one user, so this is already the place a chosen size lands. The clamp is why the
ceiling is asked of the server rather than configured: a stale setting, or a
choice made when the endpoint was larger, must not become a request the endpoint
refuses.

Nothing offers that choice. The Telegram command and the per-user column are
4.6a, where compaction is good enough to make a smaller budget a real trade
rather than a faster way to lose history. `AGENT_CONTEXT_TOKENS` exists in
configuration and is unset.

## What this deliberately does not do

Only stored history folds. The current turn's own messages have not been written
yet, so a turn that grew large by accumulating tool results is not what this
shortens — that is 4.6a's work, and `ContextOverflowError` remains the backstop
underneath. Message-count folding (`summarize_after`) still exists beside the
token check; removing it is also 4.6a. No pruning, no summarizer schema, no new
tables, no second threshold beside `AGENT_CONTEXT_FRACTION`.

## Checks

```text
python -m pytest -q          742 passed, 22 skipped
```

Up from 710. New: `tests/test_telegram_rate_limit.py`, 14 tests over waiting out
a `429`; `tests/test_request_size.py`, 17 tests over the measurement,
the calibration and its clamps, and the budget's precedence and clamp. Changed:
three overflow tests in `tests/test_agent_session.py` now use a budget far larger
than their conversation, so that the pre-request fold does not fire and the
server-side overflow they exist to test still arrives unannounced — which is
exactly the case an estimate cannot rule out. One test added there for the new
path: a conversation over budget folds before the request, with no refusal and
no retry in between.

## The real Telegram turns after the boot

Three, sent by the human at 02:13 and read back from the deployed telemetry:

```text
17802ec0…  02:13:01  answer_delivered  loop  7.20s  1m/0t  2889/39
63b9fcbb…  02:13:09  answer_delivered  loop  8.54s  1m/0t  2941/84
edb0ea2b…  02:13:25  answer_delivered  loop  8.37s  1m/0t  3038/93
```

**What this proves: raising the ceiling did not break the product path.** Real
messages go through the webhook, the queue, a CPU worker and the 64k endpoint
and come back in 7-8.5 s, one model call each, on the one loop. That is the
regression check the boot needed.

**What it does not prove is the rest of 4.1.5.** `assistant-control` was not
redeployed, so the container that answered these runs the pre-4.1.5 application:
no `fitted`, no estimator, no `context_tokens`. The endpoint half of this
sub-step is live; the application half exists only in the working tree.

The old code does already read the ceiling — `Agent.budget()` has always asked
`/v1/models` — so its budget went from 9,830 to 39,321 the moment the endpoint
changed. Nothing observable distinguishes that at ~3,000 input tokens, and the
budget is not recorded in telemetry, so these traces cannot confirm it either
way. That is a gap in what is measured, not a doubt about the code.

## Accepted live, 2026-08-30

`assistant-control` was deployed with the application half at 02:2x, and the
human then pushed an article at the bot. Seven turns:

| started | calls | input tokens |
|---|---|---|
| 02:25:09 | 3 model, 2 tool | 15,960 |
| 02:25:51 | 2 model, 1 tool | 17,681 |
| 02:26:31 | 1 model | 6,751 |
| 02:27:04 | 2 model, 1 tool | 17,703 |
| 02:27:57 | 1 model | 11,051 |
| 02:28:47 | 1 model | 11,754 |
| 02:29:25 | 2 model, 1 tool | 28,113 |

The largest single request was **15,699 tokens**. The budget before this
sub-step was 9,830, against a hard ceiling of 16,384 — so this conversation
would have been folded repeatedly on the way through, and the turn after it
would have met the ceiling itself.

**No `context_folded` event was recorded**, because no single request came near
39,321. That is the product outcome the sub-step existed for: the article stayed
in context whole instead of being summarized away underneath the person reading
it. The ceiling is in use, and the fold that now guards it did not need to fire.

## The defect this acceptance found

The last of those seven turns failed:

```text
telegram refused sendMessage: Too Many Requests: retry after 32
```

The model had already finished — 770 output tokens over 22.5 s — and the answer
was discarded on delivery. Seven long answers in four and a half minutes, each
written into the chat by repeated edits, is enough to be rate limited, and edits
count toward the limit.

What that cost, before the fix:

- a finished answer thrown away after it was paid for;
- the update back to `pending` with `attempts=1`, and **nothing to respawn a
  worker for it** — the control function has no retry configured, so it waits
  for the next message to arrive and be claimed behind it;
- three attempts and then abandonment, if the flood persisted.

**Corrected the same day.** This report first claimed the retry would re-run the
whole turn, model calls included, at about 24 s of GPU. It does not, and the
record says so: when the update was finally reclaimed at 02:39:15 it finished
`answer_delivered` with **0 model calls and 0 tokens**, 614.66 s after the
person sent it. The checkpointer had the completed graph, so the resume
delivered the answer that already existed rather than producing it again. The
defect is that the answer waited ten minutes for an unrelated message to arrive,
not that it was paid for twice.

That run is also a second sighting of 4.1's reading trap: a retried update keeps
its `run_id` and `started_at` is rewritten to the new claim, so the first
attempt's events render at negative offsets — here from `-568.21s`.

And Telegram had said exactly how long to wait, in a structured field, which the
client ignored.

`TelegramClient._call` now reads `parameters.retry_after`, waits it out — half a
second over, because arriving on the boundary is how a flood wait gets extended
— and tries again, at most twice, and never for a wait longer than 60 s. Nothing
else is retried: a rate limit is the one refusal that carries its own remedy,
and everything else would be guessing. `tests/test_telegram_rate_limit.py`
covers the wait, the bound on the number of holds, the refusal of an
unreasonable wait, that an ordinary refusal is not retried, and that a
nonsensical `retry_after` — including `True`, which is an `int` in Python — is
treated as an ordinary refusal rather than one second.

Not addressed, and recorded as its own queue item: the edit frequency that
provoked the limit. Streaming an answer is chatty by design, and throttling it
is a measurement rather than a one-line change.

## What is not verified

- **A fold actually firing in production.** The seven live turns went up to
  15,699 tokens in one request, which is well inside 39,321. What the new
  `fitted` path does when it does fire has only been exercised offline.
- **The rate-limit fix, live.** It is written and tested and not deployed.
- **That the application observed the new ceiling, directly.** It plainly did —
  a 15,699-token request could not have been sent under the old budget — but no
  event carries the budget itself. If that ever matters, the cheap fix is a
  field on the turn rather than a probe that wakes a GPU.
- **Restore-to-health for the new snapshot.** The 299.7 s above is snapshot
  *creation*. What a warm wake now costs will show on the next one.
- **Whether the estimate's ratio settles anywhere sensible on real traffic.** It
  starts at 3.0 and moves; nobody has watched it move.

## A note on the record

`.env.example` was unreadable and uneditable here: the agent permission rule
denying `.env.*` catches the template along with the real secret files it exists
to protect. The human renamed it to `env.example`, which the rule does not match,
so the catch-all stayed exactly as strict as it was instead of being narrowed to
an enumeration that a future `.env.something` could slip past.

The rename paid for itself immediately. `AGENT_CONTEXT_TOKENS` now sits beside
`AGENT_CONTEXT_FRACTION` rather than appended at the end, and `AGENT_TELEMETRY`,
`AGENT_TELEMETRY_DATABASE` and `AGENT_STREAM_ANSWERS` are documented at last —
`docs/OPERATIONS_MAP.md` had been carrying a note that they were missing because
"editing it was refused in the session that added them". A stale claim that the
server context is 16k went from the same file. Eleven references and the
`!.env.example` negation in `.gitignore` were updated.

`app/telemetry/backend.py` was found to be dead — `TracedBackend` was the task
lifecycle's wrapper and 4.1 deleted its only caller, leaving a module whose
docstring still describes a planner, implementer and validator that no longer
exist. Not touched here, to keep this diff readable. Flagged for its own change.
