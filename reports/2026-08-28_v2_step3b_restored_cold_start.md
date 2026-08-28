# V2 step 3b — first restored cold start, and an audio regression

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** the snapshot delivers the intended speedup. One modality regressed
and is fixed but unverified; a second restored wake is still required before any
cold-start acceptance.

Builds on `reports/2026-08-28_v2_step3b_snapshot_boot.md`, which created the
snapshot but only measured a warm-container wake, not a genuine cold one.

## What was measured

`scripts/measure_endpoint_wake.py --auth bearer` against `assistant-llm-v2`
after `modal container list` had already confirmed zero active containers —
this run is a real restored cold start, not a warm re-check.

| | This run | Baseline (`assistant-llm`) |
|---|---|---|
| Request-to-serving | **25.0 s** | 189-201 s |
| Text, warm | 200, 1.67 s, 15.0 tok/s | 1.8-2.4 s, ~13 tok/s |
| Image, warm | 200, 3.81 s, correctly identified a red circle | not exercised in 3a |
| Audio, warm | **500: `Please install vllm[audio] for audio support`** | worked (2026-08-01 local smoke) |
| Bearer token on `.modal.run` | **accepted** | established on `.modal.direct` only |

25.0 s is roughly an 8x reduction against the unsnapshotted baseline, which is
the number step 3b exists to produce. **One restored wake is not two**; Modal
may build several worker-type-specific snapshots, so this is not yet an
acceptance-grade result on its own.

The bearer-token question from `docs/modal_platform_notes.md` is answered: a
proxy token joined by a period works as an ordinary bearer token on this
`.modal.run` endpoint, the same as it did on the baseline's `.modal.direct` one.
`OpenAICompatibleBackend` needs no change to reach either shape.

## The audio regression

Root cause, found immediately rather than guessed at: `deploy/modal/model_app.py`
installed plain `vllm==0.26.0`. `reports/2026-08-01_gemma4_endpoint_smoke.md`
already recorded, from the local WSL server, that this binds a placeholder audio
module at import time and that installing `av`/`scipy`/`soundfile`/`soxr`
separately does not fix it — only the `vllm[audio]` extra does, and only if
present before the server starts.

This is not a new defect introduced by the snapshot work. The baseline
`assistant-llm` has the same plain `vllm==0.26.0` install and was never sent an
audio request during step 3a or since — its own report lists it as untested.
The image inherited the omission; nothing regressed relative to a working
baseline configuration, because that configuration was never exercised.

**Fix applied:** `vllm[audio]==0.26.0"`, one line in `deploy/modal/model_app.py`.
**Not yet verified.** It requires a redeploy and another paid boot to confirm,
and that boot doubles as the second restored-wake measurement step 3b already
needs.

## State

- `assistant-llm-v2`: deployed with the audio fix applied but not deployed or
  invoked since. Idle window still the temporary 60 s from the previous session.
- `assistant-llm`: deployed, zero containers, still serving `MODEL_ENDPOINT`.
  Untouched, and its own audio support remains unverified on Modal — only the
  2026-08-01 local WSL run confirmed it.
- No change to `app/`, `MODEL_ENDPOINT`, or anything Telegram-facing.

## Next

1. Redeploy `assistant-llm-v2` with the audio fix. Free, no container starts.
2. Let it scale to zero (60 s window), then run the second restored-wake
   measurement, this time with `--auth headers` to also confirm the two-header
   form still works. Verify audio succeeds this time.
3. Only after two consistent restored-wake numbers does step 3b have
   acceptance-grade evidence. Restore `SCALEDOWN_WINDOW = 600` at the next
   deploy meant to stay up.
