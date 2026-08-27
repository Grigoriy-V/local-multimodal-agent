"""The model endpoint: vLLM behind an OpenAI-compatible HTTP server on Modal.

This is infrastructure, not application code. Nothing in `app/` imports it and
nothing here imports `app/`; the only connection between them is the URL in
`MODEL_ENDPOINT`. That is the same relationship the local vLLM server has, which
is the point — the deployment target is a configuration axis, not a fork.

Two functions with deliberately different costs:

- `fetch_weights` runs on CPU and fills the Hugging Face cache Volume. Weights
  are downloaded once, by a container that is not paying for a GPU.
- `Server` runs on the GPU, finds the weights already cached, and scales to zero
  when idle. No GPU runs while nobody is talking to the assistant.

The served model name matches `MODEL_NAME` in the application's settings, so
pointing the assistant here is one line in `.env`.

    modal run deploy/modal/model_app.py::fetch_weights
    modal deploy deploy/modal/model_app.py
"""

from __future__ import annotations

import modal

# A separate identity from the measured baseline. `assistant-llm` is the
# unsnapshotted deployment behind the numbers in
# `reports/2026-08-28_v2_step3a_model_endpoint.md`; deploying this file over it
# would destroy both the comparison and the rollback. The name says "second
# deployment" rather than "snapshot" on purpose: if snapshots fail and the
# fallback is `FAST_BOOT`, this identity survives that change, while a
# technique-shaped name would have to be renamed and lose its own history.
APP_NAME = "assistant-llm-v2"

# Google's own QAT checkpoint in compressed-tensors format, built for vLLM. This
# is the same repository the local server was validated against, so behaviour is
# comparable to the recorded Version 1 and 1.5 evidence rather than starting
# from an unknown baseline. 10.3 GB in a single shard, not gated.
MODEL_REPO = "google/gemma-4-12B-it-qat-w4a16-ct"

# Pinned like the reference example pins its own. A tag can move; a commit
# cannot, and the Volume holds this exact snapshot already.
MODEL_REVISION = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"

# What `/v1/models` reports. `MODEL_NAME` in the application must equal this.
SERVED_NAME = "gemma-4-12b-it"

# Pinned to the version that produced the existing reports. A different version
# is a different run identity and gets recorded as one.
VLLM_VERSION = "0.26.0"

# Pinning vLLM alone is not enough: it declares `transformers>=5.5.3` with no
# upper bound, so the resolver takes the newest release and the pair becomes
# whatever the calendar says. 5.16.1 arrived that way and killed config parsing
# with `AmbiguousGlobalPerLayerAttributeError` on `head_dim`, which Gemma 4
# defines per layer.
#
# This is not a guess: it is the version installed in the WSL environment that
# served this exact checkpoint with text, images, audio, tool calls and
# structured output — see `reports/2026-08-01_gemma4_endpoint_smoke.md`. The
# whole pair is copied from a configuration known to work, and departures from
# it get made one at a time.
TRANSFORMERS_VERSION = "5.14.1"

VLLM_PORT = 8000
MINUTES = 60

# The hard context ceiling. It reserves KV cache at start-up, so it cannot be
# changed on a running server — but the application reads it from `/v1/models`
# and spends only `AGENT_CONTEXT_FRACTION` of it, which means experiments with
# effective context are an `.env` edit rather than a deploy. Kept at the
# validated 16384 for the first deploy; raise it once the GPU has reported how
# much KV cache actually fits.
MAX_MODEL_LEN = 16384

# Sleep mode's price, discovered by paying it. `--enable-sleep-mode` switches
# vLLM onto the cumem allocator, which maps and unmaps physical pages so that
# GPU memory can be moved to CPU memory — the thing that makes a GPU snapshot
# possible at all. It also breaks the memory profiler's arithmetic: on the first
# invocation vLLM sized the KV cache at 13.77 GiB, then died allocating it with
# `CUDA Error: out of memory at cumem_allocator.cpp:163`, reporting 24.29 GiB
# "allocated by PyTorch" on a card with 22.06 GiB total. The profiler measures
# an address space the allocator never fully commits.
#
# The baseline needed no such setting because without sleep mode there is no
# cumem allocator and no double count. So this is not a tuning knob inherited
# from the baseline; it is the cost of the optimization being attempted.
#
# 0.80 rather than the observed default of 0.92. The failed boot was 1.72 GiB
# short with 947 MiB free, so about 2 GiB has to come off a 22.06 GiB card;
# 0.80 removes roughly 2.65 GiB, which clears the shortfall with margin instead
# of landing on it. The KV cache should still come out near 11 GiB, above the
# baseline's working 10.03 GiB, so 16384 tokens stay safe.
#
# Deliberately the cautious end: raising this later costs one boot, while
# another OOM costs a boot plus whatever Modal's automatic retry burns before
# the App is stopped. It remains an estimate from one failure, and the next boot
# is what confirms or refutes it — read `Available KV cache memory` from the log
# rather than inferring success from the absence of a crash.
GPU_MEMORY_UTILIZATION = 0.80

# How long the GPU stays warm after the last request. This is the idle-GPU dial
# and the whole reason the deployment is worth doing. It can also be changed
# without deploying — see `autoscale.py` — but a deploy resets it to this value,
# so this constant is the intended default and not merely a starting point.
#
# Ten minutes, up from the baseline's 30 s. The baseline's window was chosen to
# observe scale-to-zero quickly; this one is chosen for a person. A wake costs
# minutes today, so dropping the GPU while someone reads an answer and types the
# next message pays that cost repeatedly inside one conversation. Revisit it
# against observed traffic and cost, not taste.
SCALEDOWN_WINDOW = 600

# Scale-to-zero is the product requirement, so the floor is stated rather than
# inherited from a platform default that could change. The ceiling caps cost:
# one A10 serves the initial private group, and `@modal.concurrent` already
# gives one container 32 concurrent inputs.
MIN_CONTAINERS = 0
MAX_CONTAINERS = 1

# The real ceiling on everything the enter hooks do. Modal stops waiting for the
# container to come up after this, so a budget that can exceed it is not a
# budget: the container gets killed mid-diagnosis, which is exactly the anonymous
# failure the bounded waits exist to prevent. Every timeout below is chosen so
# that the worst case of a whole path stays under it.
STARTUP_TIMEOUT = 15 * MINUTES

# Readiness budgets. The cold path may legitimately take minutes — the measured
# baseline needed about 172 s from `vllm serve` to a listening server — while a
# restored container should be ready in seconds. Seven minutes is roughly 2.4x
# the observed start, and the shared `assistant-vllm-cache` Volume means this App
# inherits the baseline's warm compile cache rather than paying the 78 s first
# compilation.
START_READY_TIMEOUT = 7 * MINUTES
WAKE_READY_TIMEOUT = 5 * MINUTES

# Seconds between readiness polls. A refused connection fails instantly, so
# without a pause the wait would spin a core for the entire cold start.
POLL_INTERVAL = 2.0

# Sleep and wake move roughly ten gigabytes between GPU and CPU memory.
SLEEP_TIMEOUT = 3 * MINUTES

# One warmup answer is 16 tokens, and the baseline answered 24 tokens in 1.8-2.4 s
# warm. Ninety seconds is generous for the first one, which may still be capturing
# CUDA graphs, and three of them cannot crowd out the readiness budget.
WARMUP_TIMEOUT = 90
WARMUP_REQUESTS = 3

# Worst case, `start` is READY + WARMUP*REQUESTS + SLEEP and `resume` is
# SLEEP(wake) + WAKE_READY. Both must fit under what Modal allows, and
# `tests/test_model_endpoint.py` asserts it so a later timeout edit cannot
# quietly reintroduce the anonymous kill.
assert START_READY_TIMEOUT + WARMUP_TIMEOUT * WARMUP_REQUESTS + SLEEP_TIMEOUT < STARTUP_TIMEOUT
assert SLEEP_TIMEOUT + WAKE_READY_TIMEOUT < STARTUP_TIMEOUT

# The reference example's switch, kept by name. `--enforce-eager` skips CUDA
# graph capture: a shorter cold start for lower steady-state throughput. For an
# assistant that scales to zero and therefore boots often, that trade may be
# worth making permanently — but it is a measurement, not a preference, so the
# first comparable run keeps the reference default.
FAST_BOOT = False

# Exactly the value from the validated local launch script, and the key absent
# from it matters as much as the keys present.
#
# vLLM profiles the single modality with the largest feature size. Leaving
# `video` unset keeps its non-zero default, so video is what gets profiled:
# `profiled with 1 video items` in the working local log. Adding `"video": 0`
# here — copied from Modal's example, which disables every modality — promoted
# audio to the profiled modality instead. That path reads
# `processor.feature_extractor.fft_length`, which this checkpoint's extractor
# does not define, and vLLM died before listening:
# `profiled with 3 audio items` followed by the AttributeError.
#
# So audio works, and the crash was this dictionary rather than a vLLM or
# transformers defect. Do not "complete" it by naming every modality.
MM_LIMITS = {"image": 4, "audio": 1}

app = modal.App(APP_NAME)

# Weights and the vLLM compile cache. Volumes are write-once-read-many, which is
# exactly what model weights are; nothing mutable lives here.
hf_cache = modal.Volume.from_name("assistant-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("assistant-vllm-cache", create_if_missing=True)

image = (
    # Modal's own vLLM example builds on the CUDA devel image rather than a slim
    # Debian, and the difference is not cosmetic: a `debian_slim` build here
    # produced `ModuleNotFoundError: No module named 'vllm._C'`, meaning vLLM's
    # compiled extension was missing. Follow the reference.
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(
        f"vllm=={VLLM_VERSION}",
        f"transformers=={TRANSFORMERS_VERSION}",
        "huggingface_hub[hf_transfer]",
    )
    .env(
        {
            # Saturates the network rather than downloading a 10 GB shard over a
            # single stream. Matters only for `fetch_weights`. The older
            # `HF_HUB_ENABLE_HF_TRANSFER` is deprecated in favour of this one.
            "HF_XET_HIGH_PERFORMANCE": "1",
            # Carried over from the validated local configuration so the first
            # cloud run differs from the recorded evidence in the hardware only.
            # Both are candidates for removal once there is a measurement to
            # compare against.
            "VLLM_USE_V2_MODEL_RUNNER": "0",
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            # Sleep mode is exposed on `/sleep` and `/wake_up` only in dev mode,
            # and those two endpoints are what makes a GPU snapshot possible.
            "VLLM_SERVER_DEV_MODE": "1",
            # Modal's snapshot documentation warns that `torch.compile` can fail
            # snapshot creation and names this as the mitigation; their vLLM
            # snapshot example sets it too.
            "TORCHINDUCTOR_COMPILE_THREADS": "1",
        }
    )
)

with image.imports():
    import requests


def _sleep(level: int = 1) -> None:
    """Move the GPU's contents into CPU memory so a snapshot can capture it."""

    requests.post(
        f"http://localhost:{VLLM_PORT}/sleep?level={level}", timeout=SLEEP_TIMEOUT
    ).raise_for_status()


def _wake_up() -> None:
    requests.post(f"http://localhost:{VLLM_PORT}/wake_up", timeout=SLEEP_TIMEOUT).raise_for_status()


def _wait_ready(process, timeout: float, stage: str) -> float:
    """Block until vLLM reports itself healthy, or fail with what went wrong.

    Readiness is `/health`, not an open socket. Uvicorn binds the port before
    the engine can answer anything, so a TCP connect says "the process reached
    the HTTP server", which is not the question. `/health` returns 200 only once
    the engine is serving, which is what both a snapshot warmup and a restored
    wake actually need.

    Three ways this ends, and each says which one it was:

    - ready: returns the elapsed seconds, which is the measurement step 3b asks
      for at both cold start and restore;
    - the subprocess exited: reported with its return code, because the useful
      detail is vLLM's own traceback and that is already in the Modal logs;
    - the budget expired with the process still alive: reported with the last
      thing `/health` did, which distinguishes "still loading" from "wedged".
    """

    import time

    deadline = time.monotonic() + timeout
    started = time.monotonic()
    last_seen = "no connection yet"

    while True:
        code = process.poll()
        if code is not None:
            raise RuntimeError(
                f"{stage}: vLLM exited with code {code} after "
                f"{time.monotonic() - started:.1f}s; see this container's logs "
                f"for its traceback"
            )

        try:
            response = requests.get(f"http://localhost:{VLLM_PORT}/health", timeout=5)
            if response.status_code == 200:
                elapsed = time.monotonic() - started
                print(f"{stage}: healthy after {elapsed:.1f}s", flush=True)
                return elapsed
            last_seen = f"/health returned {response.status_code}"
        except requests.RequestException as error:
            last_seen = f"{type(error).__name__}"

        if time.monotonic() > deadline:
            raise RuntimeError(
                f"{stage}: vLLM was still not healthy after {timeout:.0f}s and is "
                f"still running; last attempt: {last_seen}"
            )

        # Poll rather than spin. A refused connection returns immediately, so
        # without this the loop would burn a CPU core for the whole cold start.
        time.sleep(POLL_INTERVAL)


def _warmup() -> None:
    """Force the compilation and graph capture that must land inside the snapshot."""

    payload = {
        "model": SERVED_NAME,
        "messages": [{"role": "user", "content": "Who are you?"}],
        "max_tokens": 16,
    }
    for _ in range(WARMUP_REQUESTS):
        requests.post(
            f"http://localhost:{VLLM_PORT}/v1/chat/completions",
            json=payload,
            timeout=WARMUP_TIMEOUT,
        ).raise_for_status()


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache},
    cpu=8,
    timeout=60 * MINUTES,
)
def fetch_weights() -> None:
    """Populate the weights Volume without paying for GPU time.

    vLLM would download the model itself on first boot, but it would do so on a
    GPU container with the meter running. Doing it here costs CPU cents instead.
    """

    from huggingface_hub import snapshot_download

    path = snapshot_download(MODEL_REPO)
    hf_cache.commit()
    print(f"weights ready at {path}", flush=True)


@app.function(
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache},
    cpu=2,
    timeout=15 * MINUTES,
)
def preflight() -> None:
    """Build the vLLM engine configuration on CPU. Run this before every deploy.

    The first deploy of this app crash-looped on an A10 because a transitive
    `transformers` upgrade broke vLLM's model-config parsing. That failure needs
    no GPU to reproduce: it happens in `ModelConfig`, before any weight is
    touched. Reproducing it here costs CPU cents; discovering it by deploying
    costs GPU minutes, because Modal restarts a container that exits.

    Two checks, one per failure this deployment has actually hit on a GPU:

    1. `ModelConfig` — where a `transformers` that forbids global `head_dim`
       access on a per-layer model kills vLLM during config parsing.
    2. The multimodal processor's audio feature extractor — where
       `gemma4_mm.get_dummy_mm_data` reads `fft_length` during the profiling
       run, and an older `transformers` has no such attribute.

    `ModelConfig` is constructed directly rather than through
    `EngineArgs.create_engine_config()`, which checks the device first and dies
    on a CPU container before parsing anything.
    """

    import transformers
    import vllm
    from vllm.config import ModelConfig

    print(f"vllm {vllm.__version__} / transformers {transformers.__version__}", flush=True)
    failures = []

    try:
        config = ModelConfig(model=MODEL_REPO, max_model_len=MAX_MODEL_LEN)
        architecture = getattr(config, "model_arch_config", None)
        print(f"  head_dim: OK (head_size={getattr(architecture, 'head_size', '?')})", flush=True)
    except Exception as error:  # noqa: BLE001 - classifying anything is the point
        failures.append(f"head_dim: {type(error).__name__}: {str(error)[:160]}")
        print(f"  head_dim: FAIL {failures[-1]}", flush=True)

    # Not a check for `fft_length`: that attribute is absent from this
    # checkpoint's extractor in every transformers release from 5.10 to 5.16,
    # and the working local server never needed it. What must hold is that
    # `video` stays unset, so video remains the profiled modality and vLLM never
    # enters the audio dummy-input path.
    if "video" in MM_LIMITS:
        failures.append("MM_LIMITS names 'video', which promotes audio to the profiled modality")
        print(f"  mm limits: FAIL {failures[-1]}", flush=True)
    else:
        print(f"  mm limits: OK {MM_LIMITS}, video left at its default", flush=True)

    if failures:
        raise RuntimeError(f"preflight failed: {'; '.join(failures)}")
    print("PASS: both known startup failures are absent", flush=True)


@app.cls(
    image=image,
    gpu="A10",
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },
    scaledown_window=SCALEDOWN_WINDOW,
    min_containers=MIN_CONTAINERS,
    max_containers=MAX_CONTAINERS,
    timeout=15 * MINUTES,
    # The whole point of this shape. The snapshot is taken after vLLM has
    # started, been warmed up and been put to sleep, so a later wake restores a
    # ready server instead of repeating imports, weight loading, compilation and
    # graph capture. Measured without it: 189 s from request to ready, of which
    # 14.6 s was the container and image and the rest was this work.
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
@modal.concurrent(max_inputs=32)
class Server:
    """vLLM's own OpenAI-compatible server, unmodified, snapshotted asleep.

    Modal's Ministral 3 example is the template. The subprocess stays: a GPU
    snapshot captures the container, so vLLM does not need to be rebuilt in
    process and no vLLM internals are imported here.
    """

    @modal.enter(snap=True)
    def start(self) -> None:
        """Everything expensive, then sleep so the snapshot can capture it."""

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
            # Explicit because sleep mode's allocator makes the default overshoot
            # physical memory. See GPU_MEMORY_UTILIZATION.
            "--gpu-memory-utilization",
            str(GPU_MEMORY_UTILIZATION),
            "--limit-mm-per-prompt",
            json.dumps(MM_LIMITS),
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            "gemma4",
            "--reasoning-parser",
            "gemma4",
            # Sleep moves GPU memory to CPU memory on demand. Without it there
            # is nothing for a GPU snapshot to capture.
            "--enable-sleep-mode",
            "--uvicorn-log-level=info",
            "--host",
            "0.0.0.0",
            "--port",
            str(VLLM_PORT),
        ]
        command += ["--enforce-eager" if FAST_BOOT else "--no-enforce-eager"]
        print(*command, flush=True)

        self.process = subprocess.Popen(command)
        _wait_ready(self.process, START_READY_TIMEOUT, "start")
        # Real requests, so torch.compile and CUDA graph capture happen now and
        # land inside the snapshot rather than on every wake.
        _warmup()
        _sleep()

    @modal.enter(snap=False)
    def resume(self) -> None:
        """Restore from the snapshot: wake the sleeping server and serve.

        The elapsed time this prints is restore-to-health, which is the number
        step 3b compares against the baseline's ~172 s server start.
        """

        _wake_up()
        _wait_ready(self.process, WAKE_READY_TIMEOUT, "resume")

    @modal.web_server(
        port=VLLM_PORT,
        startup_timeout=STARTUP_TIMEOUT,
        # Absent `requires_proxy_auth=False`, so Modal refuses an unauthorized
        # request at the edge and the GPU never wakes for it. vLLM's own
        # `--api-key` would answer 401 only after paying for a cold start.
        requires_proxy_auth=True,
    )
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        # `start` can raise before the attribute exists — a failed preflight
        # assumption, a vLLM that dies on launch. Shutdown must not replace that
        # diagnosis with an AttributeError from the exit hook.
        process = getattr(self, "process", None)
        if process is not None:
            process.terminate()
