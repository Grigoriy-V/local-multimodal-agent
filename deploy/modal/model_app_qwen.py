"""A second model endpoint: Qwen3.8-27B in FP8 on an L40S, beside the Gemma one.

The same shape as `model_app.py` — vLLM behind an OpenAI-compatible server,
snapshotted asleep, scaled to zero — and the same machinery, imported from
there rather than copied: the readiness wait, sleep and wake, the warmup, the
image, the two Volumes and every timeout. What is this file's own is the
identity, the checkpoint, the card and the numbers that follow from them.

Why a second App rather than a change to the first: the assistant is pointed
at a model by `MODEL_ENDPOINT` and `MODEL_NAME` alone, so with both Apps
deployed switching is two keys in the control secret and the rollback is the
same two keys back. Both sleep for free. And `assistant-llm-v2` stays the
configuration behind the recorded measurements, which a redeploy over it
would silently overwrite (`DECISIONS.md` 2026-09-05).

This file also holds what every Qwen3.8 App shares — the `Serving` spec, the
command, the boot, the two CPU checks — so `model_app_qwen_int4.py` is only
its own numbers and a small class. The boot history that shaped those helpers
is `reports/2026-09-05_qwen38_second_model.md` §5.

    modal run deploy/modal/model_app_qwen.py::fetch_weights
    modal run deploy/modal/model_app_qwen.py::preflight
    modal deploy deploy/modal/model_app_qwen.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import modal

import model_app as base

APP_NAME = "assistant-llm-qwen"

# Qwen's own FP8 checkpoint: fine-grained block-128 e4m3 weights with the
# embeddings, head and vision tower left in bf16, 27.8 GB over 77 shards, not
# gated. Chosen over the community int4 builds because the quality of this
# quantization is the publisher's, and over bf16 because 54 GB fits no single
# card this project would pay for. The comparison of quantizations, and the
# arithmetic behind the card and the ceiling, is
# `reports/2026-09-05_qwen38_second_model.md`.
MODEL_REPO = "Qwen/Qwen3.8-27B-FP8"
MODEL_REVISION = "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"

# What `/v1/models` reports; `MODEL_NAME` in the application must equal this.
SERVED_NAME = "qwen3.8-27b"

# Ada, not Ampere: FP8 is a hardware path on the L40S, so the block-quantized
# weights run at FP8 speed instead of being unpacked to bf16 for every matmul
# as they would be on an A10 or an A100. And 48 GB: the weights alone are more
# than an A10 holds.
GPU = "L40S"

# What vLLM reported as the device's total on this card (`Free memory on
# device (43.97/44.39 GiB)`); the pool is a share of this, and `fits` below
# is only as good as this number.
CARD_GIB = 44.39

# The pool is sized here, as in the first App, and the ceiling is only checked
# against it. Qwen3.8's attention is 16 full-attention layers of 4 KV heads at
# 256 out of 64 (the other 48 are Gated DeltaNet, whose state is fixed per
# sequence), so a token of KV is 64 KB in bf16 and 128k is 8 GiB. At 0.86 of
# 48 GB the pool was 38.3 GiB and, after 28.5 GiB of weights and 2.7 GiB of
# profiling, encoder cache and graphs, held 7.04 GiB of KV: too little for
# 131,072, which is why utilization is 0.90 below. 262k would need the cache in
# fp8 — quantization on top of quantization, with no scales in this
# checkpoint — and its prefill is minutes; declined for now.
#
# All of that is arithmetic. The numbers that count are `Available KV cache
# memory` and `Maximum concurrency for 131,072 tokens per request` in the first
# boot log, and the report records them.
MAX_MODEL_LEN = 131072

# 0.90 on the human's word, 2026-09-05, after 0.86 was refused: at 0.86 the
# first boot found 28.51 GiB of weights resident (not the ~26 estimated),
# 1.11 GiB of CUDA graphs and 7.04 GiB left for KV, against the 8.18 GiB that
# 131,072 tokens need. vLLM's own line on that boot: 0.86 is 0.8351 in the
# accounting before graph profiling was counted, and 0.8849 reproduces the old
# pool. Every 0.01 here is about 0.45 GiB, so 0.90 leaves ~0.6 GiB beyond what
# the ceiling needs. The first App's 0.80 was set against an OOM at 0.92 on a
# 22 GiB card under the cumem allocator's overshoot; on 48 GB that overshoot
# is a smaller share. The refused boot and its log:
# `reports/2026-09-05_qwen38_second_model.md` §5.
GPU_MEMORY_UTILIZATION = 0.90

# Thinking is on by default in Qwen3.8's chat template, at `xhigh` effort. Left
# there, a ten-call turn would reason at length before every call. `low` keeps
# the model's reasoning — the thing its agentic scores are measured with — at a
# cost an interactive turn can carry. The reasoning parser separates it from
# the answer; the client reads `content` alone. A first setting to measure
# against, not a finding: `reports/2026-09-05_qwen38_second_model.md`.
DEFAULT_CHAT_TEMPLATE_KWARGS = {"reasoning_effort": "low"}

# The template writes a call as `<tool_call><function=name><parameter=key>…`;
# `qwen3_xml` is vLLM's parser for that shape, and `qwen3` splits the `<think>`
# block out of the answer so the client's `content` is the answer alone.
TOOL_CALL_PARSER = "qwen3_xml"
REASONING_PARSER = "qwen3"

# How many sequences the engine schedules at once. vLLM's default is 256, and
# for this model every decoding sequence also holds one Gated DeltaNet state
# block; the second boot (0.90, 2026-09-05) sized the pool at 141,036 KV
# tokens and 184 of those blocks and refused to capture CUDA graphs for 256.
# The container accepts 8 inputs at a time, so 16 is twice what can arrive,
# and the state the other 240 would have reserved goes back to the KV pool.
MAX_NUM_SEQS = 16

# Image and video are this model's modalities; there is no audio. `video: 0`
# keeps vLLM from profiling with video inputs, which would take a share of the
# pool for a modality the assistant never sends. The warning in
# `model_app.MM_LIMITS` about naming `video` is about Gemma's audio path and
# does not apply here.
MM_LIMITS = {"image": 4, "video": 0}

# Sleep level 1 moves the weights into the container's CPU memory so the GPU
# snapshot can capture them — about 28 GB here, against ~10 for Gemma, and the
# first App never had to say so. Requested, not limited: the container may use
# more if it needs to.
MEMORY_MB = 32 * 1024

# --- what every Qwen3.8 App shares ---------------------------------------------

# Measured on the FP8 boots of 2026-09-05, and what `fits` reasons with:
#
# - a token of KV is 65,536 bytes: 8.18 GiB for 131,072 (vLLM's own line);
# - weights resident are the checkpoint's bytes on disk, as near as makes
#   no difference (28.75 GiB on disk, 28.51 GiB resident);
# - beside them the profiling run, the encoder cache and the CUDA graphs
#   took 1.7 GiB at 0.90 and 2.6 GiB at 0.86 before the pool was measured
#   (the graph accounting is relative to the pool); 2.0 sits between;
# - with 16 sequences, the DeltaNet state blocks and the rest took the
#   difference between 9.75 GiB available and 155,600 tokens, ~0.25 GiB.
#
# Applied to the two boots: at 0.90 this predicts 9.2 GiB for KV against 9.75
# measured (cautious by half a gigabyte); at 0.86, 7.4 against 7.04 (generous
# by 0.4), and still refuses that ceiling, as vLLM did. So the estimate is
# good to about half a gigabyte either way, which is why a ceiling wants a
# margin of more than that.
# Readiness budgets of their own. The first App's seven minutes were sized
# for Gemma's 172 s start with a warm compile cache. A Qwen App on a card it
# has not compiled for yet spent 191 s in torch.compile alone (INT4 on the
# A100, 2026-09-05) and was still profiling when the 420 s ran out; the
# container was killed by its own watchdog, and the boot paid for nothing.
# Twelve minutes covers a cold compile with the profiling and graphs after
# it; the whole start path still has to fit under what Modal waits for.
START_READY_TIMEOUT = 12 * base.MINUTES
STARTUP_TIMEOUT = 20 * base.MINUTES
assert START_READY_TIMEOUT + base.WARMUP_TIMEOUT * base.WARMUP_REQUESTS + base.SLEEP_TIMEOUT < STARTUP_TIMEOUT

# Where the compile cache is while vLLM runs, and where it is kept between
# boots. The snapshot must hold nothing open on a Volume: a path the container
# itself created there is not found by the restore, committed or not — the
# FP8 App's third boot died on its AOT directory (ISS-0047), and after the
# commit-before-sleep fix the INT4 App's second boot died the same way on a
# Triton kernel directory written during warmup. Only paths that existed on
# the Volume before the container started have survived a restore. So the
# engine runs against the container's own disk: the Volume's cache is copied
# in before `vllm serve` and what the boot added is copied back and committed
# after warmup, and by the time the snapshot is taken no file on the Volume
# is open. The cost is a copy each way on the first boot only; a restore
# copies nothing.
VLLM_CACHE_LOCAL = "/root/.cache/vllm"
VLLM_CACHE_VOLUME = "/vllm-cache"

KV_BYTES_PER_TOKEN = 65_536
RESIDENT_OVER_DISK = 1.0
ENGINE_OVERHEAD_GIB = 2.0
STATE_AND_SLACK_GIB = 0.3
GIB = 1024**3


@dataclass(frozen=True)
class Serving:
    """One Qwen3.8 deployment: the checkpoint, the card and the engine's numbers."""

    repo: str
    revision: str
    served_name: str
    gpu: str
    card_gib: float
    max_model_len: int
    utilization: float
    max_num_seqs: int = MAX_NUM_SEQS
    mm_limits: dict = field(default_factory=lambda: dict(MM_LIMITS))
    chat_template_kwargs: dict = field(default_factory=lambda: dict(DEFAULT_CHAT_TEMPLATE_KWARGS))
    tool_call_parser: str = TOOL_CALL_PARSER
    reasoning_parser: str = REASONING_PARSER


SERVING = Serving(
    repo=MODEL_REPO,
    revision=MODEL_REVISION,
    served_name=SERVED_NAME,
    gpu=GPU,
    card_gib=CARD_GIB,
    max_model_len=MAX_MODEL_LEN,
    utilization=GPU_MEMORY_UTILIZATION,
)


def kv_gib(tokens: int) -> float:
    return tokens * KV_BYTES_PER_TOKEN / GIB


def fits(spec: Serving, weights_disk_gib: float) -> tuple[bool, str]:
    """Whether the ceiling's KV fits the pool, by the arithmetic of the boots.

    Returns the verdict and one line of the numbers, so a refused deploy says
    why in the same terms the boot log would.
    """

    pool = spec.card_gib * spec.utilization
    resident = weights_disk_gib * RESIDENT_OVER_DISK
    available = pool - resident - ENGINE_OVERHEAD_GIB
    needed = kv_gib(spec.max_model_len) + STATE_AND_SLACK_GIB
    line = (
        f"pool {pool:.2f} GiB = {spec.card_gib} x {spec.utilization}; weights ~{resident:.2f} GiB "
        f"resident; ~{available:.2f} GiB for KV against {needed:.2f} GiB that "
        f"{spec.max_model_len:,} needs ({available / needed:.2f}x)"
    )
    return available >= needed, line


def serve_command(spec: Serving) -> list[str]:
    import json

    command = [
        "vllm",
        "serve",
        spec.repo,
        "--revision",
        spec.revision,
        "--served-model-name",
        spec.served_name,
        "--max-model-len",
        str(spec.max_model_len),
        "--gpu-memory-utilization",
        str(spec.utilization),
        "--max-num-seqs",
        str(spec.max_num_seqs),
        "--limit-mm-per-prompt",
        json.dumps(spec.mm_limits),
        "--enable-auto-tool-choice",
        "--enable-prompt-tokens-details",
        "--tool-call-parser",
        spec.tool_call_parser,
        "--reasoning-parser",
        spec.reasoning_parser,
        "--default-chat-template-kwargs",
        json.dumps(spec.chat_template_kwargs),
        "--enable-sleep-mode",
        "--uvicorn-log-level=info",
        "--host",
        "0.0.0.0",
        "--port",
        str(base.VLLM_PORT),
    ]
    command += ["--enforce-eager" if base.FAST_BOOT else "--no-enforce-eager"]
    return command


def copy_tree(source: str, target: str) -> int:
    """Copy a directory tree, files that differ in size or are absent; return how many."""

    import shutil

    copied = 0
    src = Path(source)
    if not src.exists():
        return 0
    for file in src.rglob("*"):
        if not file.is_file():
            continue
        destination = Path(target) / file.relative_to(src)
        if destination.exists() and destination.stat().st_size == file.stat().st_size:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, destination)
        copied += 1
    return copied


def boot(spec: Serving):
    """Start vLLM, warm it, keep what it compiled, put it to sleep; return the process."""

    import subprocess

    print(f"compile cache: {copy_tree(VLLM_CACHE_VOLUME, VLLM_CACHE_LOCAL)} files in", flush=True)
    command = serve_command(spec)
    print(*command, flush=True)
    process = subprocess.Popen(command)
    base._wait_ready(process, START_READY_TIMEOUT, "start")
    base._warmup(spec.served_name)
    print(f"compile cache: {copy_tree(VLLM_CACHE_LOCAL, VLLM_CACHE_VOLUME)} files out", flush=True)
    base.vllm_cache.commit()
    base._sleep()
    return process


def wake(process) -> None:
    base._wake_up()
    base._wait_ready(process, base.WAKE_READY_TIMEOUT, "resume")


def fetch(spec: Serving) -> None:
    from huggingface_hub import snapshot_download

    path = snapshot_download(spec.repo, revision=spec.revision)
    base.hf_cache.commit()
    print(f"weights ready at {path}", flush=True)


def weights_on_disk_gib(spec: Serving) -> float:
    """The checkpoint's safetensors bytes in the HF cache, which `fetch` filled."""

    from huggingface_hub import snapshot_download

    path = Path(snapshot_download(spec.repo, revision=spec.revision, local_files_only=True))
    return sum(file.stat().st_size for file in path.rglob("*.safetensors")) / GIB


def check(spec: Serving) -> None:
    """The two things a boot has failed on, answered on CPU first.

    The engine configuration, where a transformers/vLLM pair can refuse the
    architecture; and the memory arithmetic, where the first FP8 boot was
    refused at 0.86 and the second at 256 sequences. Neither proves the boot;
    each refuses one that the boots of 2026-09-05 say would fail, for CPU
    cents instead of GPU minutes. Needs the weights on the Volume.
    """

    import transformers
    import vllm
    from vllm.config import ModelConfig

    print(f"vllm {vllm.__version__} / transformers {transformers.__version__}", flush=True)
    config = ModelConfig(model=spec.repo, revision=spec.revision, max_model_len=spec.max_model_len)
    print(f"  architectures: {config.architectures}", flush=True)
    print(f"  max_model_len: {config.max_model_len}", flush=True)
    disk = weights_on_disk_gib(spec)
    ok, line = fits(spec, disk)
    print(f"  weights on disk: {disk:.2f} GiB", flush=True)
    print(f"  {line}", flush=True)
    if not ok:
        raise RuntimeError(f"preflight refused: {line}")
    if spec.max_num_seqs > 32:
        raise RuntimeError("preflight refused: max_num_seqs above 32 exceeded the DeltaNet state blocks on 2026-09-05")
    print("PASS: the configuration builds and the ceiling fits the pool", flush=True)


app = modal.App(APP_NAME)

# The image is the first App's, with this directory's modules on it: the
# helpers this file calls live in `model_app`, and Modal includes only the
# entrypoint by itself.
image = base.image.add_local_python_source("model_app", "model_app_qwen")


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": base.hf_cache},
    cpu=8,
    timeout=60 * base.MINUTES,
)
def fetch_weights() -> None:
    """Populate the weights Volume on CPU, at the pinned revision."""

    fetch(SERVING)


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": base.hf_cache},
    cpu=2,
    timeout=15 * base.MINUTES,
)
def preflight() -> None:
    """Build the engine's configuration and check the pool on CPU; see `check`."""

    check(SERVING)


@app.cls(
    image=image,
    gpu=GPU,
    memory=MEMORY_MB,
    volumes={
        "/root/.cache/huggingface": base.hf_cache,
        VLLM_CACHE_VOLUME: base.vllm_cache,
    },
    scaledown_window=base.SCALEDOWN_WINDOW,
    min_containers=base.MIN_CONTAINERS,
    max_containers=base.MAX_CONTAINERS,
    timeout=STARTUP_TIMEOUT,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=8)
class Server:
    """vLLM's own server for Qwen3.8, snapshotted asleep; see `model_app.Server`."""

    @modal.enter(snap=True)
    def start(self) -> None:
        self.process = boot(SERVING)

    @modal.enter(snap=False)
    def resume(self) -> None:
        wake(self.process)

    @modal.web_server(
        port=base.VLLM_PORT,
        startup_timeout=STARTUP_TIMEOUT,
        requires_proxy_auth=True,
    )
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        process = getattr(self, "process", None)
        if process is not None:
            process.terminate()
