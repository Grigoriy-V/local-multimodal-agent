# Stage 2 — the minimal LangGraph agent

**Date:** 2026-08-01
**Model:** `gemma-4-12b-it` (w4a16 QAT) on vLLM 0.26, `http://127.0.0.1:8000/v1`
**Code:** `app/agent/`, `app/context/`, `app/memory/`, `app/tools/`, `ui/`

## What was built

A four-node graph — `load`, `model`, `tools`, `persist` — over the project's own
`Message` type. No `langchain_core` type appears in graph state or anywhere in
`app/`; `langgraph` is imported only by `app/agent/`, `httpx` only by
`app/models/`.

| Piece | Where |
|---|---|
| Threads, messages, facts, FTS5 | `app/memory/store.py` |
| Four context layers, rolling summary | `app/context/` |
| `list_files`, `read_file` confined to a root | `app/tools/filesystem.py` |
| `remember_fact`, `search_memory` | `app/tools/memory.py` |
| Graph and wiring | `app/agent/graph.py`, `app/agent/runtime.py` |
| Chat, attachments, tool steps | `ui/chainlit_app.py` |

## Live evidence

One run, two sessions, a fresh SQLite file, the repository as the workspace.

| Step | What the model did |
|---|---|
| Session one, turn 1 | called `remember_fact("The user's GPU is an RTX 4090 with 24 GB, and they run vLLM inside WSL2.")`, then confirmed |
| Session one, turn 2 | called `list_files(".")`, then answered from the listing |
| Session two, new thread | called `search_memory("GPU")`, answered "You have an RTX 4090 with 24 GB." |
| After the store was reopened | thread one still held its 8 messages |
| After five more turns | summary written covering positions 0–11; 18 messages still stored |

Whole flow: **10.0 s** for eight model calls including the summarization call.

The summary the model produced:

> The user operates an RTX 4090 GPU with 24 GB of VRAM running vLLM within a
> WSL2 environment. The assistant identified six top-level markdown files in the
> workspace: AGENTS.md, CLAUDE.md, DECISIONS.md, HANDOFF.md, README.md, and
> ROADMAP.md. In the most recent exchange, the user instructed the assistant to
> output specific numbers, and the assistant correctly responded with "0" and
> "1" respectively.

## Closing criteria

| Criterion | Evidence |
|---|---|
| Conversations survive a restart | live run above; `tests/test_agent_session.py` reopens the file and replays the earlier turn to the model |
| A fact saved in one session is retrieved in a later one | live run above; retrieval also happens without a tool call, through context layer four |
| Older context is summarized rather than grown | summary at position 12 while 18 messages remain stored; nothing is deleted |
| Integration tests cover the agent | 137 offline tests, of which 14 drive the real store, tools, context and graph against a scripted model |

## Chainlit

`.venv\Scripts\python.exe -m chainlit run ui/chainlit_app.py -w` starts and
serves. Each tool call appears as a `cl.Step` with its arguments, and the step is
filled in when the result arrives, because the UI consumes `Agent.steps`, which
yields messages as nodes finish rather than after the turn.

## Limitations

- The UI resumes the most recent thread rather than offering a thread list.
  Chainlit's own thread history needs a data layer, which Stage 2 does not have.
- Retrieval is FTS5 keyword matching. A question that shares no word with a
  saved fact will not find it; the model can still call `search_memory` with
  better words.
- No checkpointer. A crash mid-turn loses that turn — the store is written once,
  after the answer. Resumable mid-turn state is Stage 3.
- Media is stored base64-encoded in SQLite. Fine at one user; not a durable
  answer for large audio.
- The summarizer is the same model with the same `max_tokens`; a very long fold
  could be truncated by that limit.
