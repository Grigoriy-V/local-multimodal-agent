# Serving vLLM on Modal: cold start and throughput

Reference for tuning `deploy/modal/model_app.py`. It records what the platform
and vLLM documentation actually say, which of it is applied, and what is still
untried — so the next change is a decision rather than a guess.

Measurements and the failure history are in
[`reports/2026-08-28_v2_step3a_model_endpoint.md`](../reports/2026-08-28_v2_step3a_model_endpoint.md).
Platform facts that are not specific to vLLM are in
[`modal_platform_notes.md`](modal_platform_notes.md). `ROADMAP.md` is the plan;
this file is neither.

## What is being optimized

A wake measured **189 s** from request to ready, split by a timestamp in
`@modal.enter` and vLLM's own log:

| Stage | Time | What addresses it |
|---|---|---|
| Container scheduling, image pull, Python start | 14.6 s | nothing — already small |
| Subprocess start, torch and vLLM imports | 77 s | memory snapshot |
| Weight load and CUDA init | 32 s | GPU snapshot |
| Engine init: profiling, KV cache, CUDA graphs | 58 s | GPU snapshot, or `--enforce-eager` |
| Route registration | 5 s | — |

The image is 8% of the wake. Rebuilding it would have been wasted work; the
target is everything vLLM does after the container exists.

Separately, generation measured **~13 tok/s** on an A10 for a short answer.

## Sources

Modal:

- [examples/vllm_inference](https://modal.com/docs/examples/vllm_inference) —
  the OpenAI-compatible server: `@app.server`, the CUDA devel base image,
  `--revision` pinning, `@modal.exit()`, and the `FAST_BOOT` switch with the
  rule for choosing it. Its health check treats 503 as "keep waiting", which is
  the documented client contract for a Server.
- [examples/ministral3_inference](https://modal.com/docs/examples/ministral3_inference) —
  the same server plus GPU snapshots. This is the template for the current
  implementation.
- [examples/vllm_throughput](https://modal.com/docs/examples/vllm_throughput) —
  in-process `vllm.LLM` with a warmup request. Not used: the snapshot template
  keeps the subprocess.
- [guide/memory-snapshot](https://modal.com/docs/guide/memory-snapshot) —
  `snap=True` vs `snap=False`, `experimental_options={"enable_gpu_snapshot": True}`,
  the `torch.compile` conflict and `TORCHINDUCTOR_COMPILE_THREADS=1`.
- [guide/high-performance-llm-inference](https://modal.com/docs/guide/high-performance-llm-inference) —
  Volumes read at 1-2 GB/s, so roughly a second per gigabyte of weights; skip
  compilation at startup, or snapshot around it.
- [guide/cold-start](https://modal.com/docs/guide/cold-start) — pre-download
  weights, move work into `enter`, `scaledown_window`, `min_containers`.
- [guide/custom-container](https://modal.com/docs/guide/custom-container) —
  images are cached per layer, per `Image` method call, and breaking one layer
  cascades. Frequently-changing layers go last.
- [guide/servers](https://modal.com/docs/guide/servers) — a Server with no
  container answers 503 and does not queue, unlike Function inputs.
- [pricing](https://modal.com/pricing) — Volume storage $0.09/GiB/month with
  1 TiB free; an idle scaled-to-zero app has no compute cost.

vLLM and the model:

- [gemma4_mm.py](https://raw.githubusercontent.com/vllm-project/vllm/v0.28.0/vllm/model_executor/models/gemma4_mm.py) —
  `get_dummy_mm_data` reads `processor.feature_extractor.fft_length` only when
  audio is the profiled modality. See the report for why that matters.
- [google/gemma-4-12B-it-qat-w4a16-ct](https://huggingface.co/google/gemma-4-12B-it-qat-w4a16-ct) —
  the served checkpoint, 10.3 GB, one shard, not gated.
- [google/gemma-4-12B-it-qat-q4_0-unquantized-assistant](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-unquantized-assistant) —
  a draft model for speculative decoding, not gated. Untried.

## Applied

- **GPU memory snapshot.** `@app.cls` with `enable_memory_snapshot=True` and
  `experimental_options={"enable_gpu_snapshot": True}`. `@modal.enter(snap=True)`
  starts vLLM, warms it with three real requests so compilation and graph
  capture happen there, then calls `/sleep`; `@modal.enter(snap=False)` calls
  `/wake_up`. Sleep moves GPU memory into CPU memory, which is what gives the
  snapshot something to capture.
- **`--enable-sleep-mode`** and **`VLLM_SERVER_DEV_MODE=1`**, without which
  `/sleep` and `/wake_up` do not exist.
- **`TORCHINDUCTOR_COMPILE_THREADS=1`**, the documented mitigation for
  `torch.compile` failing snapshot creation.
- **The subprocess is kept.** A GPU snapshot captures the container, so vLLM
  does not need rebuilding in-process and no vLLM internals are imported.
- **CUDA devel base image with `.entrypoint([])`** to clear the base image's own
  entrypoint, and `add_python` because CUDA images ship without Python. A
  `debian_slim` build left `vllm._C` missing.
- **Layer order**: `uv_pip_install` before `.env(...)`, so editing an
  environment variable rebuilds only the last layer. Redeploys measured 3-9 s.
- **Weights preloaded** into a Volume by a CPU function, so GPU time is never
  spent downloading.

## Not applied, and why

- **`FAST_BOOT` / `--enforce-eager`.** The vLLM example's rule is to set it
  `True` for a service that frequently scales from zero, which describes this
  one. It is `False` because the snapshot pays for compilation once instead of
  per wake. **If GPU snapshots do not work, this becomes required rather than
  optional.**
- **Speculative decoding.** The vLLM example runs a draft model through
  `--speculative-config`, and Google publishes one for this family. It targets
  the 13 tok/s, not the cold start, and it costs VRAM: 8.28 GiB of weights and
  10 GiB of KV cache already sit in 22 GiB, so the cache would shrink. Separate
  change, separate measurement.
- **`--async-scheduling`.** Present in the example, not carried over. Throughput,
  not cold start.
- **`min_containers`.** Removes cold starts entirely and costs about $26/day.
  Contradicts the reason for deploying this way.
- **Raising `--max-model-len`.** vLLM reports room for 11.6 GiB of KV cache
  against 10.03 GiB in use at 16384 tokens, so the ceiling can rise a long way.
  Unrelated to cold start.

## Carried without justification

`VLLM_USE_V2_MODEL_RUNNER=0` and `VLLM_USE_FLASHINFER_SAMPLER=0` come from the
validated local configuration. The 2026-08-01 report calls both WSL-specific
workarounds — missing UVA and missing `nvcc` — and explicitly "none of them
model-related", so they are probably unnecessary on Modal. Remove them one at a
time against a measurement, not together.

## Expectations to hold this to

Modal documents 2-10x from snapshots and notes the benefit appears **after a
handful of cold starts, usually fewer than five**. A single wake after a deploy
proves nothing. GPU snapshots are alpha; if they fail, a CPU-only snapshot still
removes the 77 s of imports, which would be roughly 110 s rather than 189 s.
