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

Stage 2 builds a minimal graph; Stage 3 grows it to the full flow — explicit
state, checkpoints, resumable sessions, retries, confirmation before destructive
actions — without touching the inference, UI, memory, or tool layers.

## Layout

```text
app/       api, agent, context, memory, models, tools
ui/        Chainlit entry point
scripts/   smoke test, environment doctor
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

Stage 1 is closed: the model answers text, image, multi-image, audio, streaming,
tool-call and structured-JSON requests through repository code. Stage 2 has
started — a two-node graph closes the tool loop over `list_files` and
`read_file`; persistence, memory and the UI are still missing. Work proceeds one
approved step at a time after an explicit human command.

The model server is infrastructure and lives outside this repository; the
project reaches it over `MODEL_ENDPOINT` only. Copy `.env.example` to `.env` to
point somewhere else.

```powershell
.venv\Scripts\python.exe -m pytest -q            # offline, needs nothing
.venv\Scripts\python.exe -m scripts.doctor       # can this machine run it
.venv\Scripts\python.exe -m scripts.smoke_test   # every Stage 1 item, needs the server
```
