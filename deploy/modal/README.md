# Model endpoint on Modal

The GPU half of the deployed profile: vLLM serving Gemma 4 12B behind an
OpenAI-compatible API, scaled to zero so no GPU runs while the assistant is
idle.

The live `assistant-llm` App is the unsnapshotted baseline measured in
`reports/2026-08-28_v2_step3a_model_endpoint.md`. The current `model_app.py` is
an unverified CPU+GPU snapshot candidate. Before it is deployed, it must receive
a new App identity and the remaining readiness/autoscaling fixes listed in
`ROADMAP.md` step 3b. Do not deploy it over the measured baseline.

This directory is infrastructure. Nothing in `app/` imports it, and nothing here
imports `app/`. The only connection is the URL in `MODEL_ENDPOINT`, which is the
same relationship the local vLLM server has.

## Commands

Install the deploy dependency once with `uv sync --all-groups`.

```powershell
# 1. Fill the weights Volume. CPU only, runs once, cents.
.venv\Scripts\python.exe -m modal run deploy/modal/model_app.py::fetch_weights

# 2. Deploy only after step 3b names the replacement App and the human approves.
# Deployment does not authorize the paid invocations needed to create/verify snapshots.
.venv\Scripts\python.exe -m modal deploy deploy/modal/model_app.py

# 3. Change the idle window without deploying.
.venv\Scripts\python.exe deploy/modal/autoscale.py --window 300
```

On Windows, prefix with `$env:PYTHONIOENCODING="utf-8"` if the console rejects
Modal's output characters.

## Why the server sleeps

`Server` starts vLLM, sends three warmup requests, then puts vLLM to sleep — and
Modal snapshots the container at that moment. A later wake restores the
snapshot instead of repeating the imports, weight load, compilation and CUDA
graph capture that a measured wake spent 174 of its 189 seconds on.

Sleep mode is what makes this possible: it moves GPU memory into CPU memory so
there is something to capture. It needs `--enable-sleep-mode` and
`VLLM_SERVER_DEV_MODE=1`, which is what exposes `/sleep` and `/wake_up`.

Modal may create two or three snapshots for one GPU type during the first few
invocations. Confirm creation and restore in the Containers view or from
`Snapshot created. Restoring Function from memory snapshot.`; latency alone is
not proof.

## Access

The endpoint is closed. `@app.server` requires authentication unless
`unauthenticated=True` is passed, and it is deliberately not passed here: Modal
rejects an unauthorized request at the edge, so **the GPU never wakes for it**.
Running vLLM's own `--api-key` instead would pay for a cold start before
answering 401.

Create a proxy token yourself — it is a credential, so it is not something this
project's tooling generates for you:

```powershell
.venv\Scripts\python.exe -m modal workspace proxy-tokens create
```

It prints a token id (`wk-…`) and a secret (`ws-…`). Modal accepts them joined
by a period as an ordinary bearer token, which is what the application already
sends, so no code changes and the value goes straight into `.env`:

```text
MODEL_ENDPOINT=https://grigoriy-v--assistant-llm-server.us-east.modal.direct/v1
MODEL_API_KEY=wk-....ws-...
```

Never commit the token. `.env` is ignored; `.env.example` holds the shape only.

## What costs what

| Change | Cost |
|---|---|
| `MODEL_MAX_TOKENS`, `AGENT_CONTEXT_FRACTION` | none — `.env`, no restart |
| Idle window | seconds — `autoscale.py`, no deploy; planned default is 600 s |
| `MAX_MODEL_LEN`, GPU type | seconds — deploy, no image rebuild, weights stay |
| vLLM version, weights | minutes — image rebuild or Volume refill |

`MAX_MODEL_LEN` reserves KV cache at start-up and therefore cannot change on a
running server. The application reads the ceiling from `/v1/models` and spends
`AGENT_CONTEXT_FRACTION` of it, so experiments with effective context stay on
the free row of that table.

`autoscale.py` changes revert to `SCALEDOWN_WINDOW` in `model_app.py` on the
next deploy. That constant is the decision; the script is for experiments.

The replacement starts explicitly at `min_containers=0`, `max_containers=1`.
The zero preserves scale-to-zero; the one caps cost for the initial private
service. The baseline App remains available until text, multimodal, backend and
Telegram acceptance pass on the replacement.
