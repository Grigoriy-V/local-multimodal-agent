# V2 step 3b — `assistant-llm-v2` boots, snapshots and serves

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** the snapshot path works end to end. The measurement that step 3b
exists for — a **restored cold start** — has not been taken yet.

Supersedes nothing. The failed first attempt and its diagnosis are in
`reports/2026-08-28_v2_step3b_first_boot_failure.md`; this is the run after the
fix.

## Change under test

One variable against the failed attempt: an explicit
`--gpu-memory-utilization 0.80`, down from the default 0.92 that vLLM reported
in force. Everything else is unchanged.

## Result: the whole sequence completed

```
Available KV cache memory: 11.06 GiB
Free memory on device (21.83/22.06 GiB) on startup.
  Desired GPU memory utilization is (0.8, 17.65 GiB).
  Actual usage is 8.28 GiB for weight, 1.02 GiB for peak activation,
  -3.58 GiB for non-torch memory, and 0.68 GiB for CUDAGraph memory.
Graph capturing finished in 15 secs, took 0.68 GiB
Application startup complete.
start: healthy after 170.2s
Using sleep-mode backend: cumem
CuMemAllocator: sleep freed 19.51 GiB memory in total, of which 8.39 GiB is
  backed up in CPU and the rest 11.12 GiB is discarded directly.
Sleep mode freed 20.53 GiB memory, 1.15 GiB memory is still in use.
It took 2.744157 seconds to fall asleep.
Snapshot created. Restoring Function from memory snapshot.
It took 1.003154 seconds to wake up tags {'weights', 'kv_cache'}.
resume: healthy after 0.0s
```

The `-3.58 GiB for non-torch memory` is the cumem allocator's accounting, and it
is what made the default utilization overshoot physical memory on the previous
attempt.

## Measurements

| | Value | Baseline for comparison |
|---|---|---|
| KV cache | **11.06 GiB**, 16384 tokens safe | 10.03 GiB |
| vLLM start to healthy | **170.2 s** | ~172 s server start |
| Fall asleep | **2.74 s** | n/a — no sleep mode |
| Snapshot content | 8.39 GiB backed up to CPU; 11.12 GiB KV discarded | n/a |
| Wake from snapshot | **1.00 s** | n/a |
| `resume` to healthy | **0.0 s** | n/a |
| `/v1/models` warm | HTTP 200, **0.88 s** | n/a |
| Chat completion warm | HTTP 200, **1.31 s**, 18 in / 25 out, `stop` | 1.8-2.4 s for 24 out |

vLLM also reported room to grow: `--kv-cache-memory=16402457088` (15.28 GiB)
would fully use the card. 0.80 was chosen as the cautious end and can be raised.

## What this does and does not prove

**Proved.** Sleep mode, CPU+GPU snapshot creation and snapshot restore all work
for Gemma 4 12B on an A10. Modal logged `Snapshot created. Restoring Function
from memory snapshot.` — creation and restore, not inferred from latency. The
restored engine woke in 1.00 s and answered correctly.

**Not proved.** The number step 3b is about: how long a request takes when the
App has scaled to zero and Modal must restore the snapshot from cold. The 1.00 s
wake above happened inside the container that had just created the snapshot,
with everything already resident. A genuine restored cold start includes
container scheduling, image availability and reading the snapshot back, none of
which are in that figure. **No cold-start claim may be made from this report.**

## The 303, explained enough to stop misreading it

Both invocations returned `HTTP 303` after almost exactly 150.7 s (150.73 and
150.78). It is not an error and not the failure signal: on the first attempt the
303 arrived at 150 s while vLLM did not die until 212 s. It is what Modal's edge
answers while a container is still coming up. Once warm, the same request
returned 200 in 0.88 s.

Consequence for measurement: **a plain `curl` cannot measure request-to-ready**,
because it is answered before readiness. Cold-start timing must come from the
container logs, or from a client that follows the redirect.

## Defect found and fixed on the way

`deploy/modal/autoscale.py` did not work against this App. `@app.cls` registers
a class, and the 1.5 client rejects both
`Function.from_name(app, "Server.serve")` (`Invalid Function name`) and reaching
the method off an instance (`Cannot call .update_autoscaler() on a method`). The
working form is `modal.Cls.from_name(app, "Server")()`. Fixed, and the rejected
spellings are recorded in the file so they are not retried.

## Cost control

After the warm measurements the idle window was cut from 600 s to 60 s with
`autoscale.py`, so the GPU drops shortly after the last request rather than
holding an idle A10 for ten minutes. This is an experiment setting; the next
deploy restores `SCALEDOWN_WINDOW = 600`.

## State

- `assistant-llm-v2`: deployed, snapshot created, idle window temporarily 60 s.
- `assistant-llm`: deployed, zero containers, still serving `MODEL_ENDPOINT`.
  Untouched.
- `MODEL_ENDPOINT` unchanged. Nothing in `app/` changed.

## Next

1. Let it scale to zero, then invoke and measure the restored cold start from
   the container log. At least two, because Modal may build several
   worker-type-specific snapshots.
2. Verify image and audio against the restored endpoint.
3. Test whether a joined proxy token works as a bearer token on `.modal.run`,
   which is what decides whether `OpenAICompatibleBackend` needs a change.
