# V2 step 3b — real Telegram turn through the optimized endpoint

**Outcome:** passed. Step 3b is closed.

## User path

The local Telegram polling adapter was started with process-level overrides:

```text
MODEL_ENDPOINT=https://grigoriy-v--assistant-llm-v2-server-serve.modal.run/v1
MODEL_AUTH_STYLE=modal_proxy
```

The persistent `.env` was not changed. The human sent one ordinary Telegram
message and confirmed receiving the model's reply. Terminating the controlling
shell cell left the `uv` child process tree alive, so the two exact Python
polling PIDs were identified by their `-m ui.telegram.run` command line and
stopped explicitly. A final process check returned
`PYTHON_TELEGRAM_POLLERS=0`.

This is the first retained product evidence for the complete path:

```text
Telegram -> TelegramAdapter -> shared harness -> OpenAICompatibleBackend
-> Modal proxy headers -> assistant-llm-v2 -> Gemma 4 12B -> Telegram
```

## Modal evidence

Exactly one restored A10 container, `ta-01M130YYH0AT2HH3NNJRXN4VMR`, handled
the turn:

- `08:50:17+07:00` — `Restoring Function from memory snapshot.`;
- vLLM wake itself took **0.951 s**;
- `resume: healthy after 0.0s`;
- the harness made two successful completion calls, its normal decision plus
  answer path:
  - first: HTTP 200, **17.8 s** external duration, **3.74 s** execution;
  - second: HTTP 200, **1.66 s** duration, **1.55 s** execution;
- `08:51:20+07:00` — API-server shutdown began;
- the subsequent read-only `modal container list --json` returned `[]`.

No new snapshot was created. The existing NCCL TCPStore warning repeated as
expected and did not affect either response. Its deferred fix remains scheduled
for the next independently necessary deployment, not a warning-only rebuild.

## Acceptance

- real Telegram input: passed;
- real model reply visible to the human in Telegram: passed;
- v2 two-header application auth: passed;
- existing snapshot reused: passed;
- scale-to-zero: passed;
- polling stopped after the authorized turn: passed after explicit child-process
  cleanup.

The exact per-run dollar charge is not exposed in the route logs and remains a
Modal Billing observation rather than an inferred number. One A10 container
was active for roughly 63 seconds from restore log to shutdown log.

## Remaining product work

Step 3b is closed. Step 2 still needs one bounded work request through Telegram,
including the existing capability-approval interaction and its final result.
At the time of this live acceptance, the persistent local `.env` still pointed
to the original deployment; only the process-level override used v2. The
post-acceptance promotion below supersedes that configuration state.

## Post-acceptance promotion

After reviewing this evidence, the human selected `assistant-llm-v2` as the
primary deployment. The persistent local profile now targets its `/v1` endpoint
with `MODEL_AUTH_STYLE=modal_proxy`. The original App remains deployed only for
rollback/reference; this configuration change did not start a worker or create
a new snapshot.

## Billing observation

Modal Billing reports cost by App in hourly buckets, not by individual HTTP
request. For 08:00-08:59 local time, all `assistant-llm-v2` activity cost
`$0.20093184`, but that bucket includes earlier controls as well as this Telegram
test. Using the observed roughly 63-second container lifetime and the current
A10 rate, this test is estimated at about `$0.0207` including CPU and memory.
That estimate is not an exact per-request charge.
