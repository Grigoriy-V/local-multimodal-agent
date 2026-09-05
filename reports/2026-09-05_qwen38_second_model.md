# A second model: Qwen3.8-27B in FP8 on an L40S

**Date:** 2026-09-05
**Status:** built, deployed as `assistant-llm-qwen`, and serving: text,
image and a tool call answered from a restored snapshot on the fourth boot
(§5). The live scenarios on it, and the choice of which model the assistant
uses, are separate gates (`ROADMAP.md` item 9).

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

### The second boot, 0.90: the pool fits, the scheduler does not

The human chose 0.90 at 131,072. One attempt, stopped by a watcher on the
log rather than left to Modal's restarts:

```text
Available KV cache memory: 8.82 GiB
GPU KV cache size: 141,036 tokens
Maximum concurrency for 131,072 tokens per request: 1.08x
ValueError: max_num_seqs (256) exceeds available Mamba cache blocks (184).
  Each decode sequence requires one Mamba cache block, so CUDA graph
  capture cannot proceed.
```

The pool is now what §5's table said 0.90 would give. The new refusal is
the hybrid architecture's: every decoding sequence holds one Gated DeltaNet
state block, vLLM's default schedules 256 sequences, and the pool held 184
blocks. The container accepts 8 inputs at a time, so `--max-num-seqs 16`
(`MAX_NUM_SEQS`) — twice what can arrive — and the state the other 240
would have reserved goes back to KV.

### The third boot: the engine is up, the restore dies

```text
Loading weights took 12.5 s; Model loading took 28.51 GiB
torch.compile took 97.6 s (fresh: the scheduler change is a new compile key)
Available KV cache memory: 9.75 GiB
GPU KV cache size: 155,600 tokens
Maximum concurrency for 131,072 tokens per request: 1.19x
init engine took 180.7 s; start: healthy after 268.3 s
CuMemAllocator: sleep freed 38.25 GiB, 28.53 GiB backed up in CPU, 9.72 discarded
It took 9.7 s to fall asleep
Snapshot created. Restoring Function from memory snapshot.
restoring container: failed to complete restore for filesystem type "9p":
  failed to walk ".../torch_compile_cache/torch_aot_compile/e2dbd899…":
  no such file or directory
Runner failed with exit code: 128
```

The boot compiled afresh and saved its AOT graph to the compile-cache
Volume — in this container only, uncommitted — then slept and was
snapshotted with a handle into that path. The restore re-mounts the Volume
at its committed state, where the path does not exist. A harness defect
(ISS-0047): the Gemma App never met it only because its compile cache
predates its snapshot. Fixed in both files by committing the Volume after
the warmup and before the sleep.

### The fourth boot: served

```text
start: healthy after 286.3 s   (weights 21 s, compile from cache 94 s,
                                profiling 54 s, init engine 170 s)
It took 9.3 s to fall asleep; Snapshot created; Restoring
It took 2.07 s to wake up tags {'weights', 'kv_cache'}
resume: healthy after 0.0 s
REQUEST TO SERVING: 490.1 s  (the wake request, start to snapshot to restore)
```

Then, twelve seconds later, the container asleep again, a second wake
from the restored snapshot alone:

```text
REQUEST TO SERVING: 88.5 s   (restore of a 28.5 GiB CPU snapshot; Gemma's ~10 s)
```

Four raw probes on the warm container, `reasoning_effort: low`:

| Probe | Time | Finish | Content | Reasoning separated | Tokens out |
|---|---|---|---|---|---|
| text, 3 primary colours | 10.2 s | stop | the answer, RYB and RGB | yes | 168 |
| image, red circle | 25.8 s | stop | "Red circle." | yes; 64 image tokens | 47 |
| tool, `get_weather` | 3.9 s | tool_calls | empty | yes | 61, one parsed call `{"city": "Paris"}` |
| text, `enable_thinking: false` | 3.9 s | length at 64 | the answer, no reasoning | n/a | 64 |

The tool call comes back parsed with thinking on, so vLLM issue #42021 is
not present with `qwen3_xml` on 0.26.0. The first text and image requests
carry Triton JIT of a kernel and the vision path ("JIT compilation during
inference: _compute_slot_mapping_kernel"), so their times are not the
steady state; the tool probe's 61 tokens in 3.9 s puts decode near 16
tokens/s, below the ~30 estimated from bandwidth. Prefill was not
measured; the scenarios will.

**What `measure_endpoint_wake.py` needed:** `--model` and `--no-audio`,
because it named Gemma and probed audio, and because a 48-token cap with
thinking on returns `content: null` — the reasoning spends the cap. That
last point is the product's too: `MODEL_MAX_TOKENS` is 8192, so a turn
has room, but every call now pays reasoning tokens before its answer.

**Cost of getting here:** four boots and their retries, about 35
L40S-minutes, ~$1.15.

## 6. The cache and the cold start, for the record

Asked separately: the KV cache lives in GPU memory and dies with the
container; the snapshot is taken once, with an empty cache. A first request
after sleep pays the restore (~10 s measured for Gemma's ~10 GiB; expected
longer for 27B, to be read from the log) plus a full prefill of the turn's
context. Persisting the cache across sleeps is possible with LMCache to a
Volume, but on a 20k turn it saves about a second against a restore it
cannot remove, and it adds a component and per-user gigabytes; declined for
now, noted here as the path if prefill of long turns ever dominates.

## 7. The live scenarios on Qwen, first attempt: A–F pass the harness, G does not come back

The assistant was pointed at the new endpoint by the two keys in the
control secret and a control-plane deploy; the sixteen scenarios ran in
the deployed worker (`loop_live --deployed`). What the record holds:

| Run | Scenario | Time | Calls | Tokens in/out | Outcome |
|---|---|---|---|---|---|
| `3a7b245a-10` | A | 40.1 s | 1m/0t | 4,824/43 | answered |
| `3a7b245a-20` | B | 10.7 s | 2m/1t | 9,709/77 | answered |
| `3a7b245a-30` | C | 20.2 s | 3m/2t | 14,865/223 | answered |
| `3a7b245a-40` | D | 36.1 s | 2m/5t | 10,164/536 | answered |
| `3a7b245a-50` | E | 16.9 s | 2m/1t | 9,804/192 | answered |
| `3a7b245a-60` | F | 32.9 s | 3m/2t | 15,836/409 | answered |
| `3a7b245a-70` | G | 274.6 s | 1m/0t | 0/0 | killed: the container went away during the first model call |
| `d6beb190-10…60` | A–F again | 9–99 s | | | answered; A's 99 s is a restore |
| `d6beb190-70` | G | 456.9 s | 2m/0t | 9,176/8,334 | first model token at 454.7 s; then ISS-0048 |

The Gemma runs of the same day for comparison: B 3.2 s, C 5.1 s, D 4.5 s,
F 15.5 s, G 102 s with 9 calls and 3,534 tokens out.

Three things, in the order they matter:

1. **G's first model call wrote 8,334 tokens in one go — 7.5 minutes at
   ~18 tokens/s — and called no tool.** Gemma answers G with nine calls
   and eight tool uses. With `reasoning_effort: low` Qwen still reasons
   at length over a four-file request and then, apparently, writes the
   files into its answer instead of into `write_file`; the turn was not
   stored (see 3), so the text itself is gone. Whether this is the
   thinking budget, the tool parser with a long `<think>` block, or the
   model's reading of the request is the next thing to measure, on G
   alone, with the turn stored.
2. **The first G was killed at 274 s** in the scenarios container, with
   the model call still open: `turn_failed error_type=killed`, then the
   Function's input was rescheduled and the run started over from A
   (`d6beb190-*`). The control-app log for that window returned nothing
   through the CLI; cause not established. Recorded, not diagnosed.
3. **ISS-0048.** After G's 457 s the store's connection had been hung up
   on by Neon; `persist` failed on the store's first statement, the run
   died, G's turn was never stored. Fixed: the store resends its own
   search-path statement once on a fresh connection.

Also seen: a restore in the middle of the run cost A 99 s
(`d6beb190-10`, one model call), because the 12 s idle window had closed
the model container between scenarios. The window is the first App's,
priced for Gemma's ~10 s restore, and on a 28.5 GiB snapshot it charges
a person a minute for every pause; not changed here, the human's call.

Cost of the attempt: about 22 minutes of L40S across three model
containers, ~$0.70, plus the control container.

**Correction to §6.** It said a smaller snapshot would save "a few
seconds"; the restores measured today (19 s, 28 s, 80 s, 86 s on the
same 28.5 GiB snapshot) are proportional to the snapshot and dominated
by whether the host has it cached, so a 17 GiB INT4 snapshot is about
half the restore, not a few seconds off it. The human chose to move to
`RedHatAI/Qwen3.8-27B-INT4`; noted, not begun.

## 8. The third App: INT4 on an A100-40GB, and a preflight that refuses on CPU

The human's words after §7: the cold starts of the FP8 App do not suit
scale-to-zero; a separate App with `RedHatAI/Qwen3.8-27B-INT4` on an
A100-40GB, "without the deploy mistakes of today, so nothing is wasted".

**The checkpoint.** W4A16, group 128, symmetric, llm-compressor with 512
calibration samples; the vision tower, embeddings, head and the
linear-attention projections stay bf16. 18.14 GB on disk (one shard plus
an MTP head vLLM ignores), revision `2fb0debc`. Red Hat's card reports
97–102% of the bf16 base on gsm8k, ifeval, aime25, math_500, gpqa; text
only.

**The card.** A100-40GB, 0.90, ceiling 131,072 as the FP8 App's, for a
like-for-like comparison. By the arithmetic below: ~16.5 GiB for KV
against 8.5 needed, 1.9x, the estimate's half-gigabyte left as margin. Why not the A10: ~2 GiB for KV, about 24k tokens (§3 recomputed
with the measured weights).

**Not wasting boots.** What the four FP8 boots cost was known before the
GPU started, in principle: the pool arithmetic. So `model_app_qwen.fits`
carries it now, calibrated on those boots — KV 65,536 bytes a token,
weights resident at their bytes on disk, ~2 GiB of profiling, encoder
cache and graphs, 0.3 GiB for the DeltaNet state at 16 sequences — and
predicts 9.2 GiB for the L40S at 0.90 against 9.75 measured, 7.4 at 0.86
against 7.04: good to about half a gigabyte either way, and it refuses
the 0.86 ceiling as vLLM did. `preflight` on CPU builds the engine
configuration, sums the checkpoint's safetensors on the Volume and
refuses a ceiling the pool cannot hold, in the same terms the boot log
uses. Offline, `fits` reproduces the refused 0.86 boot and passes the
served 0.90 one. What it cannot see from CPU: the card's exact size (the
A100's `CARD_GIB` is nominal until its first boot reports it), a kernel
that fails on the architecture, and the restore. `max_num_seqs` is 16 by
the shared spec; the compile-cache commit is in the shared `boot`.

The three Apps: `model_app.py` (Gemma, A10), `model_app_qwen.py` (FP8,
L40S, and everything the Qwen Apps share), `model_app_qwen_int4.py` (its
numbers and a small class).

## 9. The INT4 App's boots, and what the documentation says about Volumes

Two boots on the A100-40GB, both on the human's word, neither served:

1. **Killed by our own readiness budget.** Weights loaded in 20 s (17.71
   GiB resident), then `torch.compile` from nothing took 191 s, and the
   seven-minute `START_READY_TIMEOUT` — sized for Gemma's 172 s start
   with a warm cache — ran out during profiling. The Qwen Apps now have
   their own twelve-minute budget under a twenty-minute Modal ceiling.
2. **The engine served and the restore died.** Compile from cache 43 s,
   profiling 68 s, `Free memory on device (39.08/39.49 GiB)`, `Available
   KV cache memory: 16.74 GiB`, 267,509 tokens, `2.04x` at 131,072 (the
   preflight's 15.3 GiB was cautious by 1.4), healthy after 290 s,
   asleep in 4.5 s, snapshot created — then the same `9p … failed to
   walk … no such file or directory` as the FP8 App's third boot, this
   time on `…/inductor_cache/triton/0/<kernel>`, a directory the warmup's
   JIT had written, and after the Volume had been committed.

Read afterwards, as it should have been read before: Modal's memory
snapshot guide says "Changes to Modal Volumes do not cause Memory
Snapshots to update. Deleting files in a Volume used during restore will
cause restore failures", and "redeploying your Function with new
configuration or new code will cause previous Memory Snapshots to become
obsolete". Modal's own vLLM snapshot example mounts its `vllm-cache`
Volume under `/root/.cache/vllm` as this project did, with a 3B model and
`--max-num-seqs 2`; nothing there says a large model's compilers, which
write through temporary names and rename or remove them, leave the
snapshot pointing at paths the restore cannot find. The commit before the
sleep addressed the wrong half of the rule.

So the Qwen Apps now keep the snapshot off the Volume entirely: the cache
Volume is mounted beside the engine at `/vllm-cache`, copied to the
container's disk before `vllm serve`, and what the boot added is copied
back and committed after warmup (`copy_tree`; a boot with a warm cache
copies nothing new). The restore then re-opens nothing on 9p. Deployed,
not booted.

Two costs of this day worth naming. Every redeploy of an App makes its
previous snapshot obsolete, so each of the INT4 App's deploys meant a
full boot rather than a restore — the price of changing one constant at
a time on the GPU instead of reading first. And the watcher that stopped
the App on a failed boot removed the deployment each time; from here it
stops the container by id and leaves the App.

**The third boot, the copy.** Started on the human's word with the copy
in place, it printed nothing from the engine for eight minutes: the copy
of the Volume's cache — six AOT directories, eight compile caches, the
Triton kernels of each, thousands of small files over 9p — had not
finished. Stopped by hand. The copy was the wrong shape too. What the
Volume ever bought a Qwen App was a faster first boot of a version, and
a restore never compiles; so the Qwen Apps' `Server` no longer mounts the
compile-cache Volume at all, and a version's first boot compiles from
nothing, once. Deployed, not booted.

Spent on the INT4 App: three boots, about 21 A100-minutes, ~$0.75.

## Sources

- https://huggingface.co/Qwen/Qwen3.8-27B and `/raw/main/config.json`
- https://huggingface.co/Qwen/Qwen3.8-27B-FP8 (`api/models`: sha, sizes)
- https://quesma.com/blog/qwen38-27b-quantizations-benchmarked/
- https://forums.developer.nvidia.com/t/qwen3-8-27b-on-dgx-spark-using-vllm-nvfp4-vs-fp8-performance/380258
- https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- https://github.com/vllm-project/vllm/issues/42021
- vLLM v0.26.0 `vllm/tool_parsers/__init__.py`, `vllm/entrypoints/openai/cli_args.py`
