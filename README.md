# Local Multimodal Agent

A local multimodal agent built around **Gemma 4 12B IT** with a model-agnostic
architecture: text, images, audio, tool calling, persistent conversations,
controlled context, and short- and long-term memory.

The application never binds to model internals. Everything goes through
`ModelBackend`, so swapping the model is a configuration change.

## Stack

| Layer | Choice |
|---|---|
| Model | `gemma-4-12B-it-qat-w4a16-ct` |
| Inference | vLLM, OpenAI-compatible API, outside this repository |
| Orchestration | LangGraph |
| UI | Chainlit |
| Application API | FastAPI, deferred until a second consumer exists |
| Persistence | SQLite |
| Runtime | Python 3.12, `uv`, Windows, RTX 4090 24 GB |

## Architecture

```text
Chainlit -> LangGraph agent -> ModelBackend -> vLLM -> Gemma 4 12B IT
```

The graph is `load -> model -> tools -> model -> persist`: context is assembled
from four layers, the model answers or asks for a tool, and only the turn's own
messages are written back. A tool marked destructive stops the turn and asks
first; the question is checkpointed, so it can be answered after a restart.

## Layout

```text
app/       api, agent, context, memory, models, tools
ui/        Chainlit entry point
scripts/   smoke test, live checks, environment doctor
configs/   runtime configuration
tests/     offline tests and fixtures
tools/     work_log.py
docs/      detailed deferred and possible future direction
reports/   evidence and the two JSONL journals
```

## Status

**Version 1 is complete.** Closing evidence is in
`reports/2026-08-01_v1_product_smoke.md`; current direction is in `ROADMAP.md`.
The agent answers text, images and audio; calls
`list_files`, `read_file`, `write_file`, `edit_file`, `remember_fact` and
`search_memory`;
keeps conversations in SQLite across restarts; finds a fact saved in an earlier
session; folds older turns into a rolling summary after a completed request is
measured over budget; stops to ask before it writes a file, resuming that
question even after the process that asked it is gone; retries a model call that
failed transiently; provides native persistent chat history; enforces explicit
upload limits; recovers once from context overflow; and shows images and audio
in its answers. Current development status is published in `ROADMAP.md`.

The server reports the ceiling through `/v1/models` and the completed request
size through `usage.prompt_tokens`. `AGENT_CONTEXT_FRACTION` decides when an
over-budget request triggers a fold before the next turn. A context-overflow
response forces one fold and one retry; if the request still cannot fit, the
agent returns and stores a readable refusal.

The model server is infrastructure and lives outside this repository; the
project reaches it over `MODEL_ENDPOINT` only. Copy `.env.example` to `.env` to
point somewhere else.

## Install the application

The tested application environment is Windows with Python 3.12 and `uv`:

```powershell
git clone https://github.com/Grigoriy-V/local-multimodal-agent.git
cd local-multimodal-agent
uv sync --all-groups
Copy-Item .env.example .env
```

Model weights and the vLLM environment are intentionally not part of this
repository.

## Start the model server

The validated inference setup is vLLM 0.26 in WSL2 `Ubuntu-22.04` on an RTX
4090 24 GB. Download or otherwise provide the Gemma weights separately, then
adjust `MODEL_PATH` and the vLLM environment path for your machine:

```bash
# Run inside WSL2 Ubuntu-22.04.
source "$HOME/venvs/vllm/bin/activate"

MODEL_PATH="$HOME/models/gemma-4-12B-it-qat-w4a16-ct"
export VLLM_USE_V2_MODEL_RUNNER=0
export VLLM_USE_FLASHINFER_SAMPLER=0
export CUDA_HOME="$VIRTUAL_ENV/lib/python3.10/site-packages/nvidia/cu13"

vllm serve "$MODEL_PATH" \
  --served-model-name gemma-4-12b-it \
  --max-model-len 16384 \
  --limit-mm-per-prompt '{"image":4,"audio":1}' \
  --enable-auto-tool-choice \
  --tool-call-parser gemma4 \
  --reasoning-parser gemma4 \
  --host 0.0.0.0 \
  --port 8000
```

`0.0.0.0` is used for the tested Windows-to-WSL localhost forwarding. Check
your firewall before exposing the WSL interface to another machine.

From Windows PowerShell, verify that the endpoint is visible:

```powershell
.venv\Scripts\python.exe -m scripts.doctor
```

## Start the UI

With the model server running, start Chainlit from Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m chainlit run ui/chainlit_app.py --port 8100 --headless
```

Open <http://127.0.0.1:8100>. Stop the UI with `Ctrl+C`; conversations remain
in the local SQLite database and are restored on the next start.

The product target is one general autonomous interface, not a menu of modes or
individual tools. An ordinary request is answered directly when that is enough;
otherwise the same harness plans, chooses governed filesystem/browser
capabilities, validates the result and repairs or finalizes. Permission prompts
approve scope or consequential effects, not an operating mode or tool choice.

The rejected experimental `task`/`preview` controls and Snake-specific verifier
are disconnected from the UI and application task runtime. The Version 1
baseline exposes its conversational graph through a grant-filtered capability
registry: read/write filesystem capabilities and the model-selected
`inspect_page` browser capability. `inspect_page` opens a self-contained local
HTML file in installed Chrome/Edge, blocks external network and file URLs, and
returns visible text, console errors and a screenshot to both model and UI.
Every ordinary message now enters the same general harness, which asks the model
whether to answer through the normal agent or enter the bounded task lifecycle;
there is no user-facing mode selector. On the task path, the model derives
acceptance criteria and an evidence strategy, the approval prompt includes the
required validation capabilities, and a separate evaluator judges real file or
browser evidence before retrying or finalizing. Snake remains only a regression
benchmark.

For work requests, the native chat surface shows planning, approved scope and
capabilities, live graph progress, validation evidence and downloadable output
files when they exist. Chainlit's stop control records a durable cancelled
outcome instead of leaving resumable work behind. Native chat deletion removes
the conversation and its resumable checkpoints while preserving separately
approved account-level memory.

## Checks

```powershell
.venv\Scripts\python.exe -m pytest -q            # offline, needs nothing
.venv\Scripts\python.exe -m scripts.doctor       # can this machine run it
.venv\Scripts\python.exe -m scripts.smoke_test   # every Stage 1 item, needs the server
.venv\Scripts\python.exe -m scripts.stage3_live  # asking before a write, needs the server
.venv\Scripts\python.exe -m scripts.v1_live      # first-pass v1 checks, needs the server
```

The agent touches only `AGENT_WORKSPACE`, which defaults to `workspace/`, and
only after you approve a write. File tools accept either a relative path inside
that root or an absolute path such as
`D:\ML\local-multimodal-agent\workspace\snake.html`; resolving outside the root
is still refused. If only a filename is supplied and its directory is unknown,
the agent is instructed to ask for the location instead of guessing.
It writes `AGENT_DATABASE`, the conversation, and `AGENT_CHECKPOINTS`, which
holds turns still in flight and can be deleted without losing one.
Task grants use the separate `AGENT_TASK_CHECKPOINTS` file, which defaults to
`data/task-checkpoints.sqlite3`.
