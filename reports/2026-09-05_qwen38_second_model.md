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

**The fourth boot, uninvited.** Stopping the third boot's container did
not end the request behind it: Modal started another container for it
four seconds later, on the version with the copy, and that one loaded
the weights and died fourteen seconds into the profile run, in
`aot_compile_fullgraph`, tracing `weight_packed` on a
`MergedColumnParallelLinear` (ISS-0050) — then two more containers in
the next minute on the same crash, until the human stopped the App
(ISS-0049). The first boot of this App had completed the same AOT
compile in 191 s and the second had loaded its artifact; what differed
in the fourth is not established, and it is not worth a GPU to
establish: the artifact serves a later process, and no Qwen App has
one. `VLLM_USE_AOT_COMPILE=0` on the Qwen Apps (`vllm/envs.py` 0.26.0:
on by default with torch ≥ 2.10).

Two things the day's spawning taught, now in the procedure. A request
waits at the edge for as long as `startup_timeout` and Modal restarts a
failing container for it as often as it fails, so the wake probe is the
wrong instrument for a first boot; `dry_run`, a plain Function with
`retries=0`, boots the same configuration once to healthy, sleeps,
wakes, answers, and exits with its log. And the third boot's eight
silent minutes may not have been the copy at all: when its container
was stopped, the next one started in four seconds and printed
`vllm serve` at once, so the copy was fast, and the silence looks like a
wait for an A100 — the availability risk named in §3. Not established
either way; the copy is gone regardless.

**`dry_run`, PASS.** One container, no snapshot, no request behind it:
weights 21 s (17.71 GiB), `torch.compile` and the profiling run together
203.6 s with AOT off, graphs 3 s, healthy after 404.5 s; three warmup
completions; asleep in 4.4 s, awake in 4.1 s; three more completions;
exit. The card Modal handed this Function was an A100 with `79.25 GiB`
free — an 80 GB card for a `A100-40GB` request — so its pool (52.5 GiB of
KV, 6.42x) says nothing about the deployed server, which on its second
boot reported `39.49 GiB`. What the dry boot establishes: the
configuration with AOT off and no cache Volume boots, sleeps and wakes.
What it cannot: the restore. Cost ~7 A100-minutes.

Spent on the INT4 App: five boots, about 32 A100-minutes, ~$1.10. Next,
on the human's word: the first request to the deployed App, which
creates the snapshot and restores from it.

## 10. The INT4 App deployed: snapshot, restore, and the first scenarios

The first request to the deployed App (on the human's word): weights
21 s, compile and profiling 213 s with AOT off, `Free memory on device
(39.08/39.49 GiB)`, `Available KV cache memory: 16.74 GiB`, `2.04x` at
131,072, healthy after 412.5 s, asleep in 4.8 s, snapshot created,
restored, awake in 2.1 s; the request answered after 482.7 s. The
restore that ISS-0047 had blocked twice went through with no Volume
under the engine.

Then the restores:

| Request | What happened | Request to serving |
|---|---|---|
| 2, 12:54 UTC | restore on a host with the snapshot | **30.7 s**, wake 2.0 s inside |
| 3, 12:55 | `Creating GPU memory snapshot` — a full boot on another worker type | ~13 min, healthy 558.9 s |
| 4, 13:09 | restore of the second snapshot | ~22 s (container start to healthy), wake 6.1 s |
| 5, 13:12 | `Creating GPU memory snapshot` again, same compile-cache hash as request 3 | a full boot |

Modal's guide: snapshots are "specific to the underlying worker type
that created them", GPU Functions need "2-3 snapshots per GPU type".
Requests 3 and 5 are that. What the guide does not say is what a
worker type is beyond "e.g. CPU flags"; request 5 compiled into the
same cache directory as request 3 (`a9661e2104`, a key of the CPU),
so whatever distinguished its host is not the CPU. Whether the next
cold start restores or creates a fourth is the thing to watch; if it
creates, the question goes to Modal, not to more boots.

The first scenario attempt, A B C E F R S, chosen for having no package
installs inside a turn: died on the first model call with
`httpx.ReadTimeout` — ISS-0044, the stream path's 120 s with no retry,
while the endpoint was in request 5's boot. Fixed in the tree (§ISS-0044
in `ISSUES.md`): a stream that has produced nothing is sent again, up
to `MODEL_RETRIES`, as the non-streaming path always was. Before that,
the same seven scenarios had died on a `MODEL_ENDPOINT` without `/v1`
(`GET /models` 404) — a configuration slip, corrected by the human.

Restore of the INT4 snapshot, measured three times: ~20–31 s, against
the FP8 App's 19–28 s warm and 80–86 s cold. The snapshot is 17.7 GiB
against 28.5. All three on hosts that had the snapshot; the cold-host
case has not been observed on this App.

### The seven scenarios on INT4, with the stream retry deployed

Run `deployed-b1661cff-*`, 13:23–13:26 UTC, the model asleep at the
start. Gemma's figures are the same scenarios earlier the same day
(`deployed-abc3941b-*`).

| Scenario | INT4, s | Gemma, s | Calls (INT4) | Result |
|---|---|---|---|---|
| A, an ordinary question | 26.7 (20 s of it the restore, model 3 s) | — | 1m/0t | pass |
| B, one tool | 10.9 | 3.2 | 2m/1t | pass |
| C, multi-step work | 15.8 | 5.1 | 3m/2t | pass |
| E, a failing tool | 14.2 | 3.7 | 2m/1t | pass |
| F, a page made and looked at | 28.0 | 15.5 | 4m/3t | one check failed: `inspect_page` first failed, then succeeded (ISS-0051, the renderer's cold browser, not the model) |
| R, data into a picture | 40.0 | 15.8 | 5m/4t | pass |
| S, a failing script repaired | 27.7 | 11.0 | 6m/6t | pass |

All seven answered what was asked; the one failed check is the
renderer's. The model's own calls: 2.5–6 s each for short answers with
thinking at `low`, first token ~3 s; a turn is 2–3.5x Gemma's, which is
the price of a 27B with reasoning against a 12B without. No restore fell
inside a turn: the longest tool was R's `run_command` and the model's
12 s window held. Cost of the run ~$0.06 of derived GPU.

## 11. What can be faster, read before the next boot

Asked by the human after §10: why a 27B int4 on an A100 is slower per
turn than a 12B on an A10, and what else shortens the cold start. Read
from vLLM 0.26.0's own source and docs and Modal's guides, not tried.

### Inside a turn

**The turn is slow because every call prefills the whole prompt.** In
F, four calls of ~5k tokens each started their first token after ~3 s
and decoded at ~70 tokens/s; `cached_tokens: 0` on every call, the
engine's `Prefix cache hit rate: 0.0%`, and in the boot config
`enable_prefix_caching=False`. Gemma's calls on the same scenario take
0.5–0.8 s because its prefix is cached and only the new tokens are
computed. The cause is one line in `vllm/engine/arg_utils.py` (0.26.0):
"Hybrid models support prefix caching but keep it opt-in for now while
the feature matures" — `default_prefix_caching = supported and not
is_hybrid`. Qwen3.8 is hybrid. The FP8 App ran the same way, which is
part of why its G was so expensive.

1. **`--enable-prefix-caching`** — the one change with a known-shape
   gain. vLLM then sets `--mamba-cache-mode align` itself (GDN has no
   "all" mode; `MambaModelConfig.verify_and_update_config`), raises the
   attention block to 784 tokens to match the DeltaNet page, requires
   chunked prefill (on), and logs "experimental". How align caches: one
   DeltaNet checkpoint per request, at the last 784-token boundary
   before the prompt's end. In this harness's loop each call's prompt is
   the previous call's prompt plus a tool result, so the previous
   request's checkpoint lies inside the new request's shared prefix and
   the hit reaches it; what is prefilled is the tail past that boundary.
   Expected: calls near Gemma's, ~0.5–1 s instead of ~3 s. Known holes:
   issue #45238 (a checkpoint landing in request-unique tokens drops the
   hit to 0% silently — for this loop the checkpoint is in the shared
   part by construction, but a `/plan` update or a fold that rewrites the
   prefix loses it), #40696 (prompts under one block never hit), and the
   prefix-cache reset at every sleep, so a turn after a restore starts
   cold. Partial-block hits (PR #46384, merged July 2026) may or may not
   be in 0.26.0; unknown.
2. **MTP speculative decoding — not now.** Both checkpoints carry an MTP
   head (`mtp_num_hidden_layers: 1`, the INT4's `model_mtp.safetensors`),
   vLLM 0.26.0 registers `Qwen3_5MTP`, and the recipe recommends MTP-1
   "for latency-sensitive scenarios with low user concurrency, pairing
   it with disabled prefix caching". Decode would go from ~70 to
   perhaps 100+ tokens/s. But with prefix caching on, issue #47194
   reports tool-call XML leaking as text and multi-turn tool use at 0/5
   on Qwen3.5/3.6; the fix (PR #51113) is newer than 0.26.0. This
   product's calls are short outputs over long prompts, so the cache is
   worth more than the decode; MTP is for a later measurement, alone.
3. **Thinking budget.** `reasoning_effort: low` still writes reasoning
   before every call (F's `write_file` call: 240 output tokens for one
   short tool call). The template also takes `enable_thinking: false`
   (the recipe's own way to turn reasoning off) and Unsloth's guide lists
   a `none` effort. Fewer output tokens is time saved per call; what it
   costs on G, the scenario where reasoning should matter, is the
   measurement that decides it, not this note.
4. **`--max-num-batched-tokens`: leave it.** On an A100 vLLM's OpenAI
   server defaults to 2048, so a 5k prefill is three scheduler chunks;
   the source carries a note that larger values reduce A100 throughput
   (PR #17885). Only the prefix cache removes the prefill.
5. Not applicable: `--language-model-only` (vision is used), fp8 KV (no
   memory pressure, Ampere), a higher utilization.

### The cold start

The restore is bounded by the snapshot's size, 17.7 GiB of weights in
CPU memory, and by whether the host has it cached: 20–31 s measured on
warm hosts, and the cold-host case seen on FP8 at 80–86 s. Nothing in
vLLM changes that; sleep level 2 would drop the weights from the
snapshot and reload them from the Volume on wake (measured 17–21 s
here), no gain. What Modal offers, from its cold-start guide and
snapshot docs:

- **Fewer restores, not faster ones.** `scaledown_window` up to twenty
  minutes; `min_containers=1` in the hours the person is active,
  through `autoscale.py` or a schedule, at $2.10/h while on;
  `buffer_containers` is for spikes, not this. The adaptive window of
  `ROADMAP.md` item 6 is the product-shaped version.
- **Fewer full boots.** A snapshot is per version and per worker type
  (2–3 per GPU type), so each redeploy of a Qwen App costs 2–3 boots of
  ~7 min A100 (~$0.75) before restores begin; the flag changes below
  are one redeploy, bundled. Region pinning (`region="us"`, 1.15x price)
  is documented as widening the pool, not narrowing worker types.
- **Restore speed itself:** nothing configurable; Modal's own numbers
  (2–12 s) are for 3–8B models.
- **The first request's wait** (ISS-0044 fixed): the model client now
  retries until the endpoint serves; the webhook already wakes the GPU
  in parallel with the worker.

### What is proposed, one deploy

`--enable-prefix-caching` on the INT4 App (the FP8 App untouched, the
human's word), `preflight` checking that the built config has it on,
one redeploy, the snapshot boots, and the same seven scenarios: if the
calls drop from ~3 s to ~1 s the turn halves. MTP and the thinking
budget are separate measurements after that, each its own gate.

## 12. 0.28.0, prefix caching on, thinking off: the same seven scenarios

One redeploy on the human's word (no `dry_run`, their point: it costs
the same as the snapshot boot it precedes). The first request: vLLM
0.28.0 in the banner, "Mamba cache mode is set to 'align' for
Qwen3_5ForConditionalGeneration by default when prefix caching is
enabled", attention block 784 tokens, `Available KV cache memory: 15.35
GiB` (the preflight's 15.34), 241,051 tokens, 1.84x, healthy after
342 s (compile and profiling 162 s), asleep in 5.4 s, snapshot,
restore; served after 410 s, text and image answered with no reasoning.

Run `deployed-6ec70d65-*`, 14:06–14:08 UTC, all seven passed:

| Scenario | 0.26.0, no cache, thinking low | 0.28.0, cache, no thinking | Gemma |
|---|---|---|---|
| A | 26.7 s (20 s restore) | 33.1 s (28.5 s restore) | — |
| B | 10.9 | **4.1** | 3.2 |
| C | 15.8 | **6.6** | 5.1 |
| E | 14.2 | **5.9** | 3.7 |
| F | 28.0, one failed check | **11.3**, clean | 15.5 |
| R | 40.0 | **26.6** | 15.8 |
| S | 27.7 | **14.4** | 11.0 |

What the calls say now: `cached 4704` on every call after the first in
a turn (six aligned blocks of 784, the shared prefix), so a short call
is 0.7–1.0 s and a call that writes ~150 tokens 2.7–2.9 s at ~55–70
tokens/s. F's `inspect_page` succeeded first time in the cold renderer
(ISS-0051). The restore in A was 28.5 s, a fourth sample in the 20–31 s
band. The turn is now within 1.3–1.7x of Gemma on B, C, E and S, and
faster than Gemma on F; R's extra is three `run_command` calls where
Gemma used one.

What is not measured yet and belongs to the next gates: the remaining
scenarios, G above all (its first attempt on FP8 wrote 8k tokens in one
call with thinking at `low`; now thinking is off and the cache is on);
thinking turned back on by `MODEL_CHAT_TEMPLATE_KWARGS` for a
comparison; MTP alone.

## 13. The remaining scenarios, and a retry that queued copies

Started on the human's word with the model asleep: D, G, H, I, K, J, O,
P, Q. The first call landed on a worker type with no snapshot of the
0.28.0 version yet, so a full boot ran (healthy after 448.6 s), and the
human saw what the morning's ISS-0044 fix did in front of it: the
client's 120 s timeout expired, the stream was sent again, and again —
one input a minute queued at the edge behind the boot, each a copy the
server would answer to a closed connection. `measure_endpoint_wake.py`
had said as much in its own docstring: a timed-out request "may still
be queued, so retrying it would create another paid task". The fix
retried the wrong failure. Now a timeout is never retried (a refused
connection or a "later" status still is, before the first chunk), and
`MODEL_TIMEOUT` is 600 s, which covers a snapshot boot's first byte.
The run itself was left to finish: stopping it would have wasted the
boot it was paying for.

### The relaunch: D and G pass the model, H fails the template

The first attempt's scenarios container was lost on Modal's side —
"Function 'scenarios' is waiting to be scheduled on a CPU worker. We are
actively working on acquiring more capacity" — with D's turn recorded as
started and nothing after it; the morning's "killed" G on FP8 (§7) has
the same shape. Stopped and relaunched on the control plane with the
retry correction. Then: D answered in 22 s (3 calls); G answered in
134 s with 13 model calls, 11 tool calls and 6,561 output tokens —
against the FP8 attempt's one 457 s call and no tool — and H died on
its first call with `HTTP 400: System message must be at the
beginning.` (ISS-0052): the facts and summary layers are system
messages, and this template takes exactly one, first. Fixed at the
provider boundary; the remaining scenarios are the next gate.

G's answer, read from the store rather than the report the run never
printed: three files written, four looks with `inspect_page`, then a
`run_command` that patches `app.js` with demo tasks so the screenshot
shows something — run twice with the same arguments, refused by the
repeat guard as already succeeded, sent a third and a fourth time
unchanged, and the turn ended by the guard: "the same call kept failing
in the same way". No `send_file`. So G on INT4 with thinking off does
the work and loses the handover in a loop the guard has to break: a
model finding, the first for the thinking dial to be measured against
(`MODEL_CHAT_TEMPLATE_KWARGS`), not a harness one — the guard did what
it is for.

## Sources

- https://huggingface.co/Qwen/Qwen3.8-27B and `/raw/main/config.json`
- https://huggingface.co/Qwen/Qwen3.8-27B-FP8 (`api/models`: sha, sizes)
- https://quesma.com/blog/qwen38-27b-quantizations-benchmarked/
- https://forums.developer.nvidia.com/t/qwen3-8-27b-on-dgx-spark-using-vllm-nvfp4-vs-fp8-performance/380258
- https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- https://github.com/vllm-project/vllm/issues/42021
- vLLM v0.26.0 `vllm/tool_parsers/__init__.py`, `vllm/entrypoints/openai/cli_args.py`
