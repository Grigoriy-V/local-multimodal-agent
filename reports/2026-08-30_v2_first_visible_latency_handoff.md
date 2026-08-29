# Latency to the first visible word — handoff, not started

**Date:** 2026-08-30
**Status:** recorded, not approved, not begun.
**Origin:** the human's question — are we losing time on badly optimized CPU
workers?
**Related:** `reports/2026-08-29_v2_turn_telemetry_implementation.md`,
`reports/2026-08-29_v2_gpu_baseline_measured.md`.

## The question

Not a sum of CPU and GPU seconds, which answers cost. The critical path from the
message arriving to the first text the person can read, split into inference and
everything else, with the parallelism accounted for.

For one nearly warm turn we have `request → first visible = 2.245 s`, of which
router 0.966 s, answer TTFT 0.586 s, queue wait 0.241 s. The remainder cannot
honestly be called infrastructure: the Telegram preview waits for 24 characters
(`PREVIEW_START_CHARS`, `ui/telegram/adapter.py`), so it also contains initial
decode and the `sendMessage` round trip. The true warm overhead is probably a
few hundred milliseconds and is not measured.

## What already exists

Three of the five spans are in the trace today.

- **Arrival** is `queued_ms`, and it is computed by the **database's** clock
  (`CURRENT_TIMESTAMP - created_at` in the inbox claim), not by comparing two
  containers. Keep it that way: the webhook and the worker are different
  machines, and comparing their timestamps directly measures skew.
- **Model TTFT** is `model_first_token`, with its duration inside the call.
- **Delivery finished** is effectively `telegram_preview_started`, because
  `visible()` is called after `_send()` returns, so the round trip is already
  inside it.

## What is actually missing

**One event**, plus one name for a gap.

- `preview_threshold_reached`, emitted before `_send()`. It separates the two
  things now fused between the first token and the first visible word: decoding
  the 24th character, and the Telegram round trip.
- A name for the span between the inbox claim and the first model call — harness
  construction and loading conversation context from the database. It was 0.78 s
  in a live turn, and it is the only part of "before the model" this project
  controls directly.

Everything else in the proposed list is arithmetic over offsets the timeline
already records:

```text
infra before model   = model_started        - turn_started   + queued_ms
model TTFT           = model_first_token    - model_started
initial decode       = threshold_reached    - model_first_token
Telegram delivery    = preview_started      - threshold_reached
                     = time to first visible
```

## The caveat that matters more than the decomposition

Warm and cold turns must not be averaged, and nothing currently separates them.

| | warm | cold |
|---|---|---|
| queue wait | 0.24 s | 6.5 s |
| router call | 0.97 s | 5.14 s |

The 5.14 s router is not CPU. At the measured prefill rate, 1,730 tokens cost
about 0.7 s, so roughly 4.4 s of it was the GPU waking. On a cold path the order
is GPU wake, then worker cold start, then the router, and a few hundred
milliseconds of warm overhead is invisible inside it. On a warm path the router
dominates, and queue item 5 removes the router entirely.

So this work needs a cheap marker for **whether a turn paid for a wake**.
Otherwise an average over ten turns is an average over two different worlds and
any improvement drowns in the variance. The worker's cold start is already
proxied by `queued_ms`; a GPU wake is proxied by nothing.

## An honest boundary to state up front

The leg from the person pressing send to the webhook receiving the update cannot
be measured. Telegram's `message.date` has one-second resolution, which is
useless against a budget of a few hundred milliseconds. The metric is therefore
**"from webhook receipt to first visible"**, and should be named that way rather
than implying it covers the person's whole wait.

## What the existing data already says about the original question

On the warm path CPU is not the problem: 0.24 s of queue and about 0.8 s of
context loading, against roughly 1.0 s spent on one extra model call that the
product does not need. On the cold path the cost is real but it is the price of
scale-to-zero, which was chosen deliberately — not a badly optimized worker.

The decomposition is worth doing not to find a culprit but to give queue item 5
a "before" number its change can be measured against.

## Proposed acceptance, if this is ever approved

One warm turn and one cold turn, each rendered by `tools/show_run.py`, where the
four spans add up to the measured time to first visible within the resolution of
the timestamps, and the cold turn is identifiable as cold from the row alone.
