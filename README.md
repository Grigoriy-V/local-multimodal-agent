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
docs/      CONTRACT, AGENT_PROTOCOL, BACKLOG
reports/   evidence and the two JSONL journals
```

## Entry points

- `AGENTS.md` — the working contract. `CLAUDE.md` imports it.
- `ROADMAP.md` — current state, the three-stage plan, the approved step.
- `DECISIONS.md` — architecture and scope decisions.
- `HANDOFF.md` — first-session bootstrap.
- `docs/CONTRACT.md` — the full target specification.

## Status

Stages 1 and 2 are closed. The Stage 3 functional core is working, but
**version 1 is reopened for product completion**; current criteria are in
`docs/CONTRACT.md` and direction in `ROADMAP.md`. The first-pass evidence remains
in `reports/2026-08-01_v1.md`. The agent answers text, images and audio; calls
`list_files`, `read_file`, `write_file`, `remember_fact` and `search_memory`;
keeps conversations in SQLite across restarts; finds a fact saved in an earlier
session; folds older turns into a rolling summary after a completed request is
measured over budget; stops to ask before it writes a file, resuming that
question even after the process that asked it is gone; retries a model call that
failed transiently; can replay recent conversations; shows images and audio in
its answers; and says which attachment it could not read. Version 1 still needs
native persistent chat history, honest upload limits, complete tool-error
handling, context-overflow recovery and a final product smoke. Version 2 is
summarized in `ROADMAP.md` and detailed in `docs/BACKLOG.md`. Work proceeds one
approved step at a time after an explicit human command.

The server reports the ceiling through `/v1/models` and the completed request
size through `usage.prompt_tokens`. `AGENT_CONTEXT_FRACTION` decides when an
over-budget request triggers a fold before the next turn. This is reactive
accounting; Version 1 completion adds bounded recovery for a request the server
rejects before it can report usage.

The model server is infrastructure and lives outside this repository; the
project reaches it over `MODEL_ENDPOINT` only. Copy `.env.example` to `.env` to
point somewhere else.

```powershell
.venv\Scripts\python.exe -m pytest -q            # offline, needs nothing
.venv\Scripts\python.exe -m scripts.doctor       # can this machine run it
.venv\Scripts\python.exe -m scripts.smoke_test   # every Stage 1 item, needs the server
.venv\Scripts\python.exe -m scripts.stage3_live  # asking before a write, needs the server
.venv\Scripts\python.exe -m scripts.v1_live      # first-pass v1 checks, needs the server
.venv\Scripts\python.exe -m chainlit run ui/chainlit_app.py -w   # the agent, needs the server
```

The agent touches only `AGENT_WORKSPACE`, which defaults to `workspace/`, and
only after you approve a write.
It writes `AGENT_DATABASE`, the conversation, and `AGENT_CHECKPOINTS`, which
holds turns still in flight and can be deleted without losing one.
