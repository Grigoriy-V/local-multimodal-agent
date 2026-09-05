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

    modal run deploy/modal/model_app_qwen.py::fetch_weights
    modal run deploy/modal/model_app_qwen.py::preflight
    modal deploy deploy/modal/model_app_qwen.py
"""

from __future__ import annotations

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

# The pool is sized here, as in the first App, and the ceiling is only checked
# against it. Qwen3.8's attention is 16 full-attention layers of 4 KV heads at
# 256 out of 64 (the other 48 are Gated DeltaNet, whose state is fixed per
# sequence), so a token of KV is 64 KB in bf16 and 128k is 8 GiB. At 0.86 of
# 48 GB the pool is about 38.7 GiB; after ~26 GiB of weights and tower that
# leaves ~12 GiB, so one 128k sequence fits in bf16 with room, and the
# ordinary 20-60k turns fit several at a time. 262k would need the cache in
# fp8 — quantization on top of quantization, with no scales in this
# checkpoint — and its prefill is minutes; declined for now.
#
# All of that is arithmetic. The numbers that count are `Available KV cache
# memory` and `Maximum concurrency for 131,072 tokens per request` in the first
# boot log, and the report records them.
MAX_MODEL_LEN = 131072

# 0.86 on the human's word, 2026-09-05. Higher than the first App's 0.80,
# which was set against an OOM on a 22 GiB card under the cumem allocator's
# overshoot; the same overshoot on a 48 GB card is a smaller share of it. Every
# 0.01 here is about 0.45 GiB of pool.
GPU_MEMORY_UTILIZATION = 0.86

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

    from huggingface_hub import snapshot_download

    path = snapshot_download(MODEL_REPO, revision=MODEL_REVISION)
    base.hf_cache.commit()
    print(f"weights ready at {path}", flush=True)


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": base.hf_cache},
    cpu=2,
    timeout=15 * base.MINUTES,
)
def preflight() -> None:
    """Build the engine's model configuration on CPU before paying for a boot.

    The first App's preflight exists because a `transformers` release once
    broke config parsing on a GPU container. This checkpoint's architecture is
    newer than the pinned pair, so the same question is worth the same CPU
    cents: can this vLLM and this transformers read this config at this
    ceiling. It cannot prove the boot; it can refuse one that would fail here.
    """

    import transformers
    import vllm
    from vllm.config import ModelConfig

    print(f"vllm {vllm.__version__} / transformers {transformers.__version__}", flush=True)
    config = ModelConfig(model=MODEL_REPO, revision=MODEL_REVISION, max_model_len=MAX_MODEL_LEN)
    print(f"  architectures: {config.architectures}", flush=True)
    print(f"  max_model_len: {config.max_model_len}", flush=True)
    print("PASS: the engine configuration builds", flush=True)


@app.cls(
    image=image,
    gpu=GPU,
    memory=MEMORY_MB,
    volumes={
        "/root/.cache/huggingface": base.hf_cache,
        "/root/.cache/vllm": base.vllm_cache,
    },
    scaledown_window=base.SCALEDOWN_WINDOW,
    min_containers=base.MIN_CONTAINERS,
    max_containers=base.MAX_CONTAINERS,
    timeout=15 * base.MINUTES,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=8)
class Server:
    """vLLM's own server for Qwen3.8, snapshotted asleep; see `model_app.Server`."""

    @modal.enter(snap=True)
    def start(self) -> None:
        import json
        import subprocess

        command = [
            "vllm",
            "serve",
            MODEL_REPO,
            "--revision",
            MODEL_REVISION,
            "--served-model-name",
            SERVED_NAME,
            "--max-model-len",
            str(MAX_MODEL_LEN),
            "--gpu-memory-utilization",
            str(GPU_MEMORY_UTILIZATION),
            "--limit-mm-per-prompt",
            json.dumps(MM_LIMITS),
            "--enable-auto-tool-choice",
            "--enable-prompt-tokens-details",
            "--tool-call-parser",
            TOOL_CALL_PARSER,
            "--reasoning-parser",
            REASONING_PARSER,
            "--default-chat-template-kwargs",
            json.dumps(DEFAULT_CHAT_TEMPLATE_KWARGS),
            "--enable-sleep-mode",
            "--uvicorn-log-level=info",
            "--host",
            "0.0.0.0",
            "--port",
            str(base.VLLM_PORT),
        ]
        command += ["--enforce-eager" if base.FAST_BOOT else "--no-enforce-eager"]
        print(*command, flush=True)

        self.process = subprocess.Popen(command)
        base._wait_ready(self.process, base.START_READY_TIMEOUT, "start")
        base._warmup(SERVED_NAME)
        base._sleep()

    @modal.enter(snap=False)
    def resume(self) -> None:
        base._wake_up()
        base._wait_ready(self.process, base.WAKE_READY_TIMEOUT, "resume")

    @modal.web_server(
        port=base.VLLM_PORT,
        startup_timeout=base.STARTUP_TIMEOUT,
        requires_proxy_auth=True,
    )
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        process = getattr(self, "process", None)
        if process is not None:
            process.terminate()
