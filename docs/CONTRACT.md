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

- **Model:** `google/gemma-4-12b-it`
- **Inference:** vLLM with an OpenAI-compatible API
- **Inference fallback:** Transformers + BitsAndBytes 4-bit
- **Agent framework, stage 1:** LangChain
- **Agent framework, stage 2:** LangGraph
- **UI:** Chainlit
- **Application API:** FastAPI
- **Persistence:** SQLite
- **Language:** Python
- **Hardware target:** NVIDIA RTX 4090 24 GB

Do not bind the application directly to Gemma internals. All model access must go through a common backend interface or OpenAI-compatible API.

## Architecture

```text
Chainlit
  ↓
FastAPI application
  ↓
LangChain agent
  ↓
Model gateway
  ↓
vLLM OpenAI-compatible API
  ↓
Gemma 4 12B IT
```

Later:

```text
LangChain agent
  ↓ replace
LangGraph workflow
```

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

## Stage 2 — Basic LangChain agent

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

## Stage 3 — LangGraph migration

After the LangChain version is stable, replace implicit orchestration with an explicit graph:

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

The LangGraph version must add:

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

## Suggested repository structure

```text
local-multimodal-agent/
├── app/
│   ├── api/
│   ├── agent/
│   │   ├── langchain_agent.py
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
│   └── smoke_test.py
├── tests/
├── docker/
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

## Acceptance criteria

The current stage is complete when:

- Gemma 4 12B IT runs locally on RTX 4090;
- text, image and audio requests work;
- Chainlit communicates with the agent;
- the model can call all four tools;
- conversations survive application restarts;
- saved facts can be retrieved in a later session;
- older context is summarized instead of growing indefinitely;
- inference and agent layers are model-agnostic;
- LangChain implementation is covered by basic integration tests;
- LangGraph migration can begin without rewriting the inference, UI, memory or tool layers.
