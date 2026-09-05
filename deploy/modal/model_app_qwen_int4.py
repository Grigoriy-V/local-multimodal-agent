"""A third model endpoint: Qwen3.8-27B in INT4 on an A100-40GB.

Everything but the numbers is `model_app_qwen.py`'s: the spec, the command,
the boot with its commit before the sleep, the CPU checks, the image and the
Volumes. What this file decides is the checkpoint, the card and the ceiling,
and why (`reports/2026-09-05_qwen38_second_model.md` §8).

Why a third App: the FP8 App's snapshot is 28.5 GiB, and a restore of it
measured 19–86 s depending on whether the host had it cached; the human
called that unfit for a product that scales to zero. INT4 halves the
snapshot. Why the A100-40GB and not the L40S: with int4 weights the L40S's
FP8 hardware path buys nothing, and the A100's memory bandwidth is 1.8x,
which is decode; it costs about the same per hour. Why not the A10: 27B
int4 leaves it ~2 GiB for KV, about 24k tokens.

    modal run deploy/modal/model_app_qwen_int4.py::fetch_weights
    modal run deploy/modal/model_app_qwen_int4.py::preflight
    modal deploy deploy/modal/model_app_qwen_int4.py
"""

from __future__ import annotations

import modal

import model_app as base
import model_app_qwen as qwen

APP_NAME = "assistant-llm-qwen-int4"

# Red Hat's W4A16 build of the same model: int4 weights in groups of 128 for
# the transformer blocks' linear layers; the vision tower, embeddings, head
# and the linear-attention projections stay bf16. 18.1 GB on disk in one
# shard plus the MTP head, not gated. Red Hat publishes the quantizations vLLM
# itself ships with, and their card reports 97–102% of the bf16 base on
# gsm8k, ifeval, aime25, math_500 and gpqa; nothing there measured images or
# tool calls, which is what the live scenarios are for.
MODEL_REPO = "RedHatAI/Qwen3.8-27B-INT4"
MODEL_REVISION = "2fb0debc365fb6c1683d7d3ad7722470919627a8"

SERVED_NAME = "qwen3.8-27b-int4"

# Ampere. W4A16 runs through the same Marlin kernels that serve the Gemma
# App's w4a16 checkpoint on the A10, so nothing here is a first.
GPU = "A100-40GB"

# 40 GiB of HBM2; vLLM has not reported this card yet, so this is the
# nominal size less the ~0.6 GiB the L40S kept back from its own. Read the
# `Free memory on device` line of the first boot and correct it.
CARD_GIB = 39.4

# The same ceiling as the FP8 App, for a like-for-like comparison. At 0.90
# the arithmetic of `model_app_qwen.fits` gives ~16.5 GiB for KV against
# 8.5 GiB needed, about 1.9x, with the half-gigabyte of uncertainty that
# estimate carries left as margin rather than spent on a higher ceiling.
MAX_MODEL_LEN = 131072
GPU_MEMORY_UTILIZATION = 0.90

# Sleep level 1 holds the weights in CPU memory: ~17 GiB here.
MEMORY_MB = 24 * 1024

SERVING = qwen.Serving(
    repo=MODEL_REPO,
    revision=MODEL_REVISION,
    served_name=SERVED_NAME,
    gpu=GPU,
    card_gib=CARD_GIB,
    max_model_len=MAX_MODEL_LEN,
    utilization=GPU_MEMORY_UTILIZATION,
)

app = modal.App(APP_NAME)
image = base.image.add_local_python_source("model_app", "model_app_qwen", "model_app_qwen_int4")


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": base.hf_cache},
    cpu=8,
    timeout=60 * base.MINUTES,
)
def fetch_weights() -> None:
    qwen.fetch(SERVING)


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": base.hf_cache},
    cpu=2,
    timeout=15 * base.MINUTES,
)
def preflight() -> None:
    qwen.check(SERVING)


@app.cls(
    image=image,
    gpu=GPU,
    memory=MEMORY_MB,
    volumes={"/root/.cache/huggingface": base.hf_cache},
    scaledown_window=base.SCALEDOWN_WINDOW,
    min_containers=base.MIN_CONTAINERS,
    max_containers=base.MAX_CONTAINERS,
    timeout=qwen.STARTUP_TIMEOUT,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=8)
class Server:
    """vLLM's own server for Qwen3.8 INT4, snapshotted asleep."""

    @modal.enter(snap=True)
    def start(self) -> None:
        self.process = qwen.boot(SERVING)

    @modal.enter(snap=False)
    def resume(self) -> None:
        qwen.wake(self.process)

    @modal.web_server(
        port=base.VLLM_PORT,
        startup_timeout=qwen.STARTUP_TIMEOUT,
        requires_proxy_auth=True,
    )
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        process = getattr(self, "process", None)
        if process is not None:
            process.terminate()
