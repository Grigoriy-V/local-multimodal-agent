# A second model: Qwen3.8-27B in FP8 on an L40S

**Date:** 2026-09-05
**Status:** built and deployed as `assistant-llm-qwen`; the first boot was
refused by vLLM's own memory check (§5) and the App is stopped. The next
boot needs the human's choice between a higher utilization and a lower
ceiling (§5). The live scenarios on it, and the choice of which model the
assistant uses, are separate gates (`ROADMAP.md` item 9).

## 1. What was asked

The human wanted a second model beside Gemma 4 12B and named Qwen3.8-27B
(released 2026-08-14, after this assistant's knowledge; read from its model
card and `config.json`). The questions, in order: does it fit an A10 at 64k
with a quantized cache; 128k; on an L40S; 262k; which quantization; whether a
second App is the right shape; whether the A100-40GB is worth it for speed;
what the cold start does to the cache. This report keeps the arithmetic those
answers rested on, so the boot log can be read against it.

## 2. The model, as far as memory is concerned

From `Qwen/Qwen3.8-27B/config.json`: 64 layers, `full_attention_interval: 4`
— 16 layers of full attention with 24 query heads, 4 KV heads at 256, and 48
layers of Gated DeltaNet (16 key heads, 48 value heads at 128) whose state is
fixed per sequence. Vision encoder of 27 layers at 1152. Vocabulary 248,320
over a 5120 hidden size, so the embeddings and the head are about 5 GB in
bf16 and stay bf16 in every quantization. Native context 262,144.

KV per token, full-attention layers only:

```text
2 × 16 layers × 4 heads × 256 × 2 bytes = 65,536 bytes = 64 KB   (bf16)
                                                        32 KB   (fp8)
```

Gemma 4 12B, for comparison, measured about 44 KB per token at the 64k
ceiling with its sliding-window layers saturated. Qwen3-8B, the model named
for this comparison on 2026-08-30, is 144 KB: every layer full attention.
The linear-attention state is about 150 MB per sequence in fp32 and does
not grow.

## 3. What fits where

Pool = card × utilization; weights include the vision tower.

| Card, utilization | Pool | Weights | Left for KV | 64k bf16 (4 GiB) | 128k bf16 (8 GiB) | 262k bf16 (16 GiB) |
|---|---|---|---|---|---|---|
| A10 24 GB, 0.80 | ~17.9 GiB | int4 ~15 | ~2.5 | no | no | no |
| A10 24 GB, 0.90 | ~20 GiB | int4 ~15 | ~5 | barely | fp8 KV only, no margin | no |
| A100 40 GB, 0.80 | ~30 GiB | FP8 ~26 | ~4 | barely | no | no |
| A100 40 GB, 0.80 | ~30 GiB | int4 ~15 | ~15 | yes | yes | fp8 KV only |
| **L40S 48 GB, 0.86** | **~38.7 GiB** | **FP8 ~26** | **~12.5** | **3x** | **1.5x** | fp8 KV only |
| L40S 48 GB, 0.80 | ~36 GiB | int4 ~15 | ~21 | yes | yes | yes, barely |

bf16 weights (~54 GB) and the official FP8 (~27.8 GB) do not fit an A10 at
all. So on the A10, 128k with this model needs int4 weights, a quantized
cache and 0.90 at once; the human declined that, and the earlier plan's
reasoning for the Gemma card applies (utilization 0.92 produced an OOM,
`reports/2026-08-30_v2_context_memory_plan.md`).

**Why the L40S over the A100-40GB.** The A100 has 1.8× the memory bandwidth,
which is decode speed, but it is Ampere: no FP8 tensor cores, so FP8 weights
are unpacked to bf16 for every matmul and prefill is slower, while the L40S
runs them as FP8. With FP8 weights the A100 holds 64k barely and 128k not at
all. Decode is not what this product waits on — a turn is five to ten short
calls over a large prefix — so prefill and the wake matter more. The two cost
about the same per hour on Modal (~$1.95 vs ~$2.10).

**Why not 262k.** Possible on the L40S only with the cache in fp8 (8 GiB for
one sequence, one at a time), a quantization on top of the FP8 weights with
no `kv_scale` in the checkpoint, and a prefill of two to three minutes to
the first token. The ceiling is insurance, not a working mode, and
`AGENT_CONTEXT_FRACTION` spends below it regardless. 128k in bf16 leaves
everything unquantized and keeps room.

## 4. Which quantization

Published measurements, all text-only, none with tool calls or images:

- Quesma, 2026-08, llama.cpp GGUF: Terminal-Bench 2.1 (89 agentic coding
  tasks) BF16 ~76%, Q4_K_M ~75%, UD-Q2_K_XL ~73%, 1-bit at chance; GPQA and
  IFBench show no measurable loss down to 2-bit. Four bits hold on this model.
- NVIDIA forum, DGX Spark, vLLM 0.27.1: NVFP4 29–34% faster output than FP8.
  NVFP4 is a Blackwell format; the L40S is Ada and has no path for it.
- Qwen's card for the FP8: fine-grained block-128 e4m3, "nearly identical"
  to the original.

What exists for vLLM on Ada: the official FP8 (`Qwen/Qwen3.8-27B-FP8`, 77
shards, 27.8 GB, 3.08 GB of it bf16); `RedHatAI/Qwen3.8-27B-INT4` (W4A16
g128, the format the Gemma App already serves); two single-author AWQ and
AutoRound builds; NVFP4 builds that do not apply. GGUF is llama.cpp's and was
not considered for vLLM with a hybrid architecture.

Chosen: the official FP8, because its quality is the publisher's and FP8 is
a hardware path on this card. RedHat's INT4 is the alternative if decode
speed turns out to matter, or if 262k in bf16 is ever wanted; it would be
decided by the same live scenarios, not by the tables above.

## 5. What was built, and the first boot

`deploy/modal/model_app_qwen.py`: App `assistant-llm-qwen`, importing the
readiness wait, sleep, wake, warmup, image, Volumes and timeouts from
`model_app.py` (`_warmup` took a served-name parameter for it). Its own:
checkpoint and revision `017b9c7a`, served name `qwen3.8-27b`, `L40S`,
131,072 ceiling, utilization 0.86 (the human's number), KV `auto`,
`--default-chat-template-kwargs {"reasoning_effort": "low"}`, parsers
`qwen3_xml` and `qwen3` (vLLM 0.26.0 has both; the template writes
`<tool_call><function=…><parameter=…>`), `image=4, video=0`, a 32 GiB
container memory request for sleep level 1. Offline: five identity tests
in `tests/test_model_endpoint.py`; the suite passes (1089).

**Thinking at `low`** is a first setting, not a finding: the template
defaults to `xhigh`, which would reason at length before each of a turn's
calls. The reasoning parser separates the block and the client reads
`content` alone, as with Gemma. A vLLM issue (#42021, 0.18) reported tool
calls landing in `content` with thinking on for Qwen3.5 under `qwen3_coder`
and `hermes`; whether 0.26.0 with `qwen3_xml` has it is the first thing the
live scenarios will show.

`preflight` on CPU, vLLM 0.26.0 / transformers 5.14.1: resolved
`Qwen3_5ForConditionalGeneration`, `max_model_len 131072`, PASS.
`fetch_weights` on CPU: see below.

### The first boot, refused

One wake request at 09:57 UTC; Modal started a container four times in
13 minutes (each start ends in the same error, and Modal restarts a
container whose enter hook raises), until the App was stopped by hand at
10:12. About 13 L40S-minutes, ~$0.45. The wake request itself came back
after 753.6 s with a 303. The log of every attempt says the same thing:

```text
Checkpoint size: 28.75 GiB
Model loading took 28.51 GiB memory and 14-24 seconds     (Volume, 9P)
torch.compile took 57 s (first attempt), 15 s from cache afterwards
Initial profiling/warmup run took 57 s
Encoder cache: budget 16384 tokens, profiled with 1 image
Estimated CUDA graph memory: 1.11 GiB
Available KV cache memory: 7.04 GiB
--gpu-memory-utilization=0.8600 is equivalent to 0.8351 without CUDA graph
  memory profiling; to keep the same effective KV cache, increase to 0.8849
ValueError: To serve at least one request with the model's max seq len
  (131072), 8.18 GiB KV cache is needed, which is larger than the available
  KV cache memory (7.04 GiB). Based on the available memory, the estimated
  maximum model length is 112896.
```

What the arithmetic of §3 got wrong, by the log: the weights are 28.5 GiB
resident, not ~26 (the bf16 embeddings, head and tower are 3.08 GB on
disk and the FP8 blocks carry their scales), and the profiling run,
encoder cache and CUDA graphs take about 2.7 GiB beside them. The
per-token figure was right: 8.18 GiB for 131,072 tokens is 65.4 KB, the
64 KB of §2. Two ways to a boot that vLLM accepts, both the human's to
choose, because 0.86 was their number and 128k was the target:

| | Pool | KV available | 131,072 needs | Fits |
|---|---|---|---|---|
| 0.86, ceiling 131,072 | ~38.3 GiB | 7.04 GiB | 8.18 GiB | no — this boot |
| 0.86, ceiling 98,304 (96k) | ~38.3 GiB | 7.04 GiB | 6.14 GiB | yes, 1.15x |
| 0.86, ceiling 112,896 | ~38.3 GiB | 7.04 GiB | 7.04 GiB | yes, 1.0x, vLLM's own number |
| 0.90, ceiling 131,072 | ~40.1 GiB | ~8.8 GiB | 8.18 GiB | yes, ~1.07x, ~0.6 GiB to spare |

0.90 is where the first App's OOM lived on the A10 (0.92 there, under the
same cumem allocator); on a 48 GB card the overshoot is a smaller share,
and vLLM's own accounting says 0.8849 is the value that reproduces the
pool 0.86 meant before graph profiling was counted. 96k at 0.86 keeps the
margin and gives up a quarter of the ceiling that no turn has yet used.
Either is one boot, ~4 minutes of L40S, and a refused boot restarts until
stopped, so the stop is part of the procedure: watch the log, not the
request.

## 6. The cache and the cold start, for the record

Asked separately: the KV cache lives in GPU memory and dies with the
container; the snapshot is taken once, with an empty cache. A first request
after sleep pays the restore (~10 s measured for Gemma's ~10 GiB; expected
longer for 27B, to be read from the log) plus a full prefill of the turn's
context. Persisting the cache across sleeps is possible with LMCache to a
Volume, but on a 20k turn it saves about a second against a restore it
cannot remove, and it adds a component and per-user gigabytes; declined for
now, noted here as the path if prefill of long turns ever dominates.

## Sources

- https://huggingface.co/Qwen/Qwen3.8-27B and `/raw/main/config.json`
- https://huggingface.co/Qwen/Qwen3.8-27B-FP8 (`api/models`: sha, sizes)
- https://quesma.com/blog/qwen38-27b-quantizations-benchmarked/
- https://forums.developer.nvidia.com/t/qwen3-8-27b-on-dgx-spark-using-vllm-nvfp4-vs-fp8-performance/380258
- https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- https://github.com/vllm-project/vllm/issues/42021
- vLLM v0.26.0 `vllm/tool_parsers/__init__.py`, `vllm/entrypoints/openai/cli_args.py`
