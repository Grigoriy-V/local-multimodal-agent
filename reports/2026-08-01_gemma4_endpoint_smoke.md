# Gemma 4 12B IT endpoint smoke

**Date:** 2026-08-01
**Run identity:** vllm-0.26.0 / gemma-4-12B-it-qat-w4a16-ct / V1 model runner / flashinfer sampler off

## Configuration

- model and quantization: `google/gemma-4-12B-it-qat-w4a16-ct`, compressed-tensors
  `pack-quantized` w4a16 QAT. Only the text stack is 4-bit; `embed_audio.*`,
  `embed_vision.*` and `lm_head` are in the quantization `ignore` list.
- endpoint: `http://127.0.0.1:8000/v1`, OpenAI-compatible, served from WSL2
  `Ubuntu-22.04`, reached from Windows over localhost forwarding.
- request shape: direct HTTP, no repository code involved. Requests issued from
  the server-side venv; the model was never imported in process.
- relevant settings:
  `--max-model-len 16384 --limit-mm-per-prompt '{"image":4,"audio":1}'
  --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4`,
  plus `VLLM_USE_V2_MODEL_RUNNER=0`, `VLLM_USE_FLASHINFER_SAMPLER=0`,
  `CUDA_HOME=<venv>/nvidia/cu13`. Launch script: `/root/serve_gemma4.sh` in WSL.

## Result

Contract items from `docs/CONTRACT.md`, Stage 1.

| Item | Verdict | Latency | Evidence |
|---|---|---|---|
| loads and fits in 24 GB | PASS | load 5.3 s, compile 34.7 s | 8.28 GiB weights, 11.79 GiB KV cache |
| text chat | PASS | 1.13 s | 20 in / 8 out, `finish_reason: stop` |
| system prompt | PASS | — | two-sentence limit obeyed |
| streaming | PASS | TTFT 0.39 s, total 0.97 s | 36 delta chunks |
| single image | PASS | 1.22 s | 224x224 red circle described correctly |
| multiple images | PASS | 0.85 s | both images distinguished in one message |
| short audio | PASS | 0.38 s | 3 s synthetic signal, 73 audio tokens |
| speech audio | PASS | 1.19 s | 8.68 s FLAC transcribed verbatim, language and tone correct |
| one tool call | PASS | 0.72 s | `get_weather{"city":"Tbilisi","unit":"celsius"}`, `finish_reason: tool_calls` |
| structured JSON | PASS | 1.57 s | `json_schema` + `strict`, schema satisfied exactly |

| Metric | Value |
|---|---|
| peak VRAM | not measurable via `nvidia-smi`; see Observations |
| weights in VRAM | 8.28 GiB |
| KV cache | 11.79 GiB = 92,403 tokens |
| cold start | ~130 s first run, ~70 s with the torch.compile cache warm |
| failures | none after the three fixes below |

## Observations

Three WSL-specific blockers, none of them model-related:

1. `RuntimeError: UVA is not available`. vLLM forces `pin_memory=False` under WSL
   because NVIDIA does not support pinned memory there, and the V2 GPU model
   runner introduced in 0.26 hard-requires UVA. Fixed with
   `VLLM_USE_V2_MODEL_RUNNER=0`, falling back to the V1 runner.
2. `Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist`.
   FlashInfer JIT-compiles its sampling module. Fixed with
   `VLLM_USE_FLASHINFER_SAMPLER=0`, plus `CUDA_HOME` pointed at the pip-installed
   `nvidia/cu13` so any other JIT path still works.
3. Audio returned `Please install vllm[audio]`. Installing `av`, `scipy`,
   `soundfile`, `soxr` is not enough on its own: the server binds the placeholder
   module at startup and must be restarted.

`--limit-mm-per-prompt` takes JSON in 0.26, not `key=value`.

**Peak VRAM cannot be read from `nvidia-smi`.** vLLM reserves
`gpu_memory_utilization` (0.9 = 23.9 GiB of 24 GiB) as one block at startup and
never returns it, so the driver always reports a nearly full card. Real
consumption has to be taken from vLLM's own startup log. Any future VRAM metric
must state which of the two it is.

92,403 tokens of KV cache against `--max-model-len 16384` leaves roughly 5.6x
concurrency, so the context limit can be raised if a task needs it.

## Limitations

- Speech is strong, synthetic audio is not. An 8.68 s stereo 24 kHz FLAC of
  English speech (215 audio tokens) was transcribed verbatim, and speaker,
  language and tone were identified correctly. Synthetic signals are a different
  story: a frequency sweep was described correctly, but a pure 440 Hz sine was
  consistently called "a person is laughing" at `temperature=0`. Treat the audio
  path as speech-oriented and do not extrapolate to non-speech sound.
- **The repository has no speech fixture.** The sample used came from the user's
  own material outside the repository and was deliberately not copied in; the
  committed fixtures (`pixel.png` 70 B, `tone.wav` 20 ms) test transport only.
- All timings are single-shot on an idle card, with no concurrency and no
  repetition. They are order-of-magnitude figures, not benchmarks.
- The image results used a generated fixture, not the repository one.

## Next gate

Human decision on Stage 1 implementation. Nothing in the repository was changed
by this run beyond this report and the journal records.
