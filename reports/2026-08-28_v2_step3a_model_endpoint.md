# Version 2 step 3a — model endpoint on Modal

**Date:** 2026-08-28
**Result:** working. Gemma 4 12B serves an OpenAI-compatible API on a Modal A10,
answers through the application's own `ModelBackend` with no code change, and
scales to zero when idle. Cold start and idle-to-answer are measured below and
are poor; optimizing them is later work.

## What is deployed

`deploy/modal/model_app.py` is one Modal app, `assistant-llm`, with three units
of deliberately different cost:

- `fetch_weights` — CPU only, fills the weights Volume once.
- `preflight` — CPU only, reproduces known startup failures before a GPU starts.
- `Server` — `@app.server` on an A10 running vLLM's own OpenAI-compatible
  server unmodified.

URL: `https://grigoriy-v--assistant-llm-server.us-east.modal.direct`, serving
`/v1`. Nothing in `app/` changed; nothing in `deploy/` imports `app/` and
nothing in `app/` imports `modal`.

## Measurements

| | Value |
|---|---|
| First boot, empty compile cache | init engine **127 s** (compilation 78 s); **~196 s** container start to listening |
| Idle to answer, warm compile cache | **201 s** total: 197 s wake + 3.7 s answer |
| Second boot engine init | **62 s** (compilation **17.7 s**) |
| Weights load | 6.9 s, 8.28 GiB |
| Answer latency, warm | 1.8-2.4 s for 24 output tokens (~13 tok/s) |
| KV cache | 10.03 GiB in use; vLLM offers 11.6 GiB to fully use the card |
| Device memory | 22.06 GiB free on an A10; 8.28 weights + 1.02 activation + 0.68 CUDA graphs |

The Volume-backed compile cache works — compilation fell from 78 s to 17.7 s —
but it is not where the time goes. Of a 197 s wake, roughly 135 s precedes
engine init: container scheduling, pulling a large CUDA image, and imports.
That is the target for any future optimization, not the compilation.

Scale to zero is confirmed by the wake measurement itself: 86 consecutive 503
responses while no container existed, then a healthy boot.

`max_model_len` stays at 16384 while the card reports ~10 GiB of KV cache, so
the ceiling can be raised substantially. Doing so is a cheap redeploy and should
follow a decision, not this report.

## The failure that dominated this step, and its real cause

The server crash-looped, then failed twice more, across roughly 15 cents of
avoidable A10 time. The cause was one dictionary entry of mine.

vLLM profiles the single modality with the largest feature size. The validated
local launch script passes `--limit-mm-per-prompt '{"image":4,"audio":1}'` and
says nothing about video, so video keeps its non-zero default and is what gets
profiled: `profiled with 1 video items` in the working local log. Copying the
shape from Modal's example — which disables every modality — I wrote
`{"image":4,"audio":1,"video":0}`. Video left the running, audio became the
largest, and vLLM entered the audio dummy-input path, which reads
`processor.feature_extractor.fft_length`. This checkpoint's extractor has no FFT
attribute at all, because the architecture projects raw waveforms.

The Modal log then read `profiled with 3 audio items` where the local log read
`profiled with 1 video items`. That one line is the whole diagnosis.

Everything built on top of that was wrong: a hunt through seven `transformers`
releases, a conclusion that no version could satisfy vLLM, and a proposal to
ship with audio disabled. Audio was never broken.

### Process failures worth keeping

1. **Pinned vLLM but not `transformers`.** The first crash-loop came from a
   transitive upgrade to 5.16.1 breaking `head_dim` parsing. The pin was
   defended as preserving run identity while the thing that broke was unpinned.
2. **Diagnosed by assumption.** 503 responses were read as "loading weights"
   from the tail of a log; the traceback was in the part not read. A 900-second
   polling loop was started on that basis.
3. **Claimed to read logs, then polled HTTP.** The second failed run was watched
   through `/health` status codes only, while the error had been in the log for
   minutes.
4. **Improvised instead of reading the reference.** Modal's vLLM example and
   this repository's own `2026-08-01_gemma4_endpoint_smoke.md` were both
   available from the start. The report contains the working versions, the
   working flags, and the cold-start figures that several GPU runs were spent
   rediscovering.
5. **Looked for the working environment in the wrong place.** `/root/venvs/vllm`
   and `/root/models` in WSL were intact the whole time; only the user's home
   directory was checked, despite the report naming `/root/serve_gemma4.sh`.

The countermeasure that worked is `preflight`: both known failures reproduce on
a CPU container for cents, and it now also asserts that `MM_LIMITS` does not
name `video`.

## Configuration, and why each part of it

Copied from the environment that served this checkpoint successfully, with
departures made one at a time:

- `vllm==0.26.0`, `transformers==5.14.1` — the versions in `/root/venvs/vllm`.
- `--limit-mm-per-prompt {"image": 4, "audio": 1}` — exactly the working value,
  `video` deliberately absent.
- `--revision` pinned to the snapshot in the Volume.
- CUDA devel base image, from Modal's example; a `debian_slim` build left
  `vllm._C` missing.
- `@modal.exit()` terminating vLLM, from the same example.

Still carried but unexamined: `VLLM_USE_V2_MODEL_RUNNER=0` and
`VLLM_USE_FLASHINFER_SAMPLER=0`. The 2026-08-01 report calls these WSL-specific
workarounds for missing UVA and missing `nvcc`, "none of them model-related", so
they are probably unnecessary on Modal. They stay until they can be removed one
at a time against a measurement.

## Access

The endpoint requires Modal proxy auth. `@app.server` authenticates by default
and `unauthenticated=True` is deliberately absent, so an unauthorized request is
refused at the edge and **never wakes the GPU** — verified: HTTP 401
`proxy auth required` in 0.83 s. Running vLLM's `--api-key` instead would pay
for a cold start before answering 401.

Modal also accepts a proxy token as `Authorization: Bearer <id>.<secret>`, which
is what `OpenAICompatibleBackend` already sends. The change to `app/models/`
that this project's notes predicted was not needed.

## Parameters, sorted by what they cost to change

| Change | Cost |
|---|---|
| `MODEL_MAX_TOKENS`, `AGENT_CONTEXT_FRACTION` | none — `.env` |
| Idle window | seconds — `autoscale.py`, no deploy |
| `MAX_MODEL_LEN`, GPU type | seconds — deploy, no image rebuild, weights stay |
| vLLM version, weights | minutes — image rebuild or Volume refill |

Measured: `modal deploy` took 3-9 s when only arguments changed.
`Function.update_autoscaler(scaledown_window=…)` changes the idle window with no
deploy at all, and a later deploy resets it to `SCALEDOWN_WINDOW`.

## Checks

- `preflight` on CPU: `head_dim: OK (head_size=512)`, `mm limits: OK`. PASS.
- Unauthenticated request: HTTP 401 at the edge in 0.83 s, no container started.
- `/v1/models` through the application backend: `gemma-4-12b-it`,
  `max_model_len=16384`, read by the existing `context_limit()`.
- A completion through `OpenAICompatibleBackend`, unmodified: 38 in / 24 out,
  `finish_reason: stop`, correct Russian answer.
- Offline suite unaffected: **383 passed**. `ruff check deploy/` clean.

## Cost

Weights download, several image builds, and roughly 12 minutes of A10 across
five boots, most of it spent on failures that CPU checks would have caught.
Under one dollar in total.

## Not done

- **Audio and images are not exercised end to end.** Audio is enabled and the
  profiling path that crashes when it is misconfigured now runs clean, but no
  audio or image request has been sent to the deployed endpoint.
- Step 2 is not yet accepted: no conversation has gone through Telegram against
  this endpoint.
- Cold start is measured, not addressed. `FAST_BOOT` / `--enforce-eager` and
  memory snapshots are untried.
- The two WSL environment variables are still carried without justification.
- The 2026-08-01 report's run identity omits the `transformers` version, which
  is what made both failures hard to place. Future run identities should record
  it.
- Nothing was committed.
