# Local Multimodal Agent — Contract

## Goal

Build a local multimodal agent around **Gemma 4 12B IT** with a model-agnostic architecture.

The project must support:

- text;
- images;
- audio;
- tool calling;
- persistent conversations;
- controlled context;
- short-term and long-term memory.

Fine-tuning is not part of the current stage.

## Core stack

- **Model:** `gemma-4-12B-it-qat-w4a16-ct` — Gemma 4 12B IT, w4a16 QAT
- **Inference:** vLLM with an OpenAI-compatible API, run outside this repository
- **Orchestration:** LangGraph, from the first agent onward
- **UI:** Chainlit
- **Application API:** FastAPI, deferred until a consumer other than Chainlit
  exists. The deployment boundary is a goal, not a Stage 2 task.
- **Persistence:** SQLite
- **Language:** Python
- **Hardware target:** NVIDIA RTX 4090 24 GB

A Transformers + BitsAndBytes fallback is not part of the stack. It would put an
inference dependency inside a repository that deliberately has none; it is parked
in `docs/BACKLOG.md` against the trigger "vLLM proves unworkable".

Do not bind the application directly to Gemma internals. All model access must go through a common backend interface or OpenAI-compatible API.

## Architecture

```text
Chainlit
  ↓
LangGraph agent
  ↓
ModelBackend
  ↓
vLLM OpenAI-compatible API
  ↓
Gemma 4 12B IT
```

FastAPI enters between Chainlit and the agent when a second consumer appears.
The agent must not assume it is called over HTTP, so that insertion stays cheap.

## Stage 1 — Multimodal smoke test

Implement and verify:

- model loading in 4-bit or another configuration that fits RTX 4090;
- text chat;
- image input;
- multiple images in one request;
- short audio input;
- streaming;
- system prompt;
- structured JSON output;
- one test tool call;
- logging of latency, VRAM usage and failures.

The smoke test must be independent from the final agent UI where practical.

## Stage 2 — Minimal LangGraph agent

A small graph: call the model, run any tools it asked for, call it again, answer.
The point of Stage 2 is a working agent, not a complete graph.

Implement a minimal working agent with these tools:

```text
list_files(path)
read_file(path)
remember_fact(text)
search_memory(query)
```

Required behavior:

- receive text, images and audio;
- call tools through structured function calls;
- preserve conversations between restarts;
- save explicit long-term facts;
- retrieve relevant memories;
- avoid sending the complete conversation history on every request;
- expose tool calls and intermediate steps in Chainlit.

## Memory and context

Use four context layers:

1. Recent conversation messages.
2. Rolling summary of older messages.
3. Long-term facts stored in SQLite.
4. Files or memories retrieved only when relevant.

Memory must remain outside the model.

Initial retrieval may use SQLite full-text search. Vector embeddings are optional and should not be added before the basic system works.

## Stage 3 — Full graph

After the minimal agent is stable, grow the graph to the full flow:

```text
receive_input
→ load_thread
→ retrieve_memory
→ build_context
→ call_model
→ execute_tools
→ update_summary
→ save_state
→ return_response
```

This is the required logical flow, not a required count or naming of LangGraph
nodes. Adjacent responsibilities may share a node when their boundaries remain
explicit and independently testable.

Stage 3 must add:

- explicit state;
- checkpoints;
- resumable sessions;
- context-size control;
- tool error handling;
- retry paths;
- confirmation before potentially destructive actions.

## Model abstraction

Provide one model-facing interface:

```python
class ModelBackend:
    async def invoke(self, messages, tools=None, response_format=None):
        ...

    async def stream(self, messages, tools=None, response_format=None):
        ...
```

The rest of the application must not depend on a specific Gemma class, tokenizer or processor.

Replacing Gemma with Gemma E4B, Qwen or another OpenAI-compatible model should require configuration changes, not agent rewrites.

A message must be able to carry an assistant's own tool calls and a tool result,
otherwise the tool loop cannot close.

The project's own message type is what the graph state holds. An orchestration
framework's message classes are not adopted as the project's domain language,
because that trades a dependency on the model for a dependency on the framework
and moves multimodal content back into a format the project does not control.

## Suggested repository structure

```text
local-multimodal-agent/
├── app/
│   ├── api/                    (empty until FastAPI is needed)
│   ├── agent/
│   │   └── graph.py
│   ├── context/
│   ├── memory/
│   ├── models/
│   │   ├── base.py
│   │   └── openai_compatible.py
│   └── tools/
├── ui/
│   └── chainlit_app.py
├── configs/
├── scripts/
│   ├── doctor.py
│   └── smoke_test.py
├── tests/
├── README.md
└── pyproject.toml
```

## Constraints

- Do not add fine-tuning.
- Do not add multi-agent orchestration.
- Do not add a vector database before SQLite retrieval is working.
- Do not use Open WebUI as the main application UI.
- Do not place business logic inside Chainlit callbacks.
- Do not silently truncate context.
- Do not store model-generated facts as trusted memory without an explicit save decision.
- Do not expose unrestricted filesystem access.
- Do not build the FastAPI layer before a second consumer needs it.

## Version 1 acceptance criteria

Version 1 is a working product baseline, not only a collection of implemented
features. It is complete when all of the following hold together:

- Gemma 4 12B IT runs locally on RTX 4090;
- text, image and audio requests work;
- Chainlit communicates with the agent;
- the UI provides normal persistent chat history with create, switch, resume
  and restart behavior, while preserving conversations created before the
  history integration;
- the model can call all five current tools, with `write_file` confirmed before
  execution;
- conversations survive application restarts;
- saved facts can be retrieved in a later session;
- older context is summarized instead of growing indefinitely;
- inference and agent layers are model-agnostic;
- the agent is covered by basic integration tests;
- uploads expose only supported input types at explicit safe sizes;
- unsupported or oversized input is refused clearly and never becomes an empty
  model turn;
- expected tool and filesystem failures return readable tool results rather
  than terminating the graph;
- an overlong request gets one bounded recovery attempt after context folding,
  or a clear refusal when the new input cannot fit by itself;
- pending destructive calls survive restart, while the checkpoint database is
  treated as non-canonical execution state that may retain completed
  checkpoints;
- the complete UI experience passes a browser/restart product smoke against the
  local endpoint, in addition to offline regression tests.
