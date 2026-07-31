# Agent Protocol

How the work is actually done. `AGENTS.md` states what must not be broken; this
file states how to do the recurring things correctly. Read it when a task names
it.

## Model access

`ModelBackend` in `app/models/base.py` is the only interface the application may
use. Concrete backends live beside it and are selected by configuration.

A backend implementation owns: request shaping, provider-specific message and
content-part formats, tool-schema translation, structured-output handling, error
translation, and retries. Nothing above it may know which provider is in use.

When adding a backend, add it to the configuration and leave every call site
unchanged. If a call site needs a change, the interface is wrong — fix the
interface.

## Multimodal input

Images and audio are content parts on a message, never separate side channels.
Keep the parts in the order the user supplied them. Validate media type and size
before sending. A request with multiple images is a normal case, not a special
path.

Test fixtures live in `tests/fixtures/` and must stay small — a few kilobytes
each. They are committed; real user media is not.

## Context and memory

Four layers, assembled explicitly on every request:

1. recent conversation messages;
2. a rolling summary of older messages;
3. long-term facts from SQLite;
4. files or memories retrieved only when relevant.

Rules:

- Never send the whole history. Assemble the layers and measure the result.
- Never truncate silently. When the budget forces a drop, record what was
  dropped and why.
- A model-generated statement is not a fact. It enters long-term memory only
  through an explicit save decision.
- Summarization is lossy and irreversible for the summarized window. Keep the
  raw messages in the database even after summarizing.

Retrieval starts as SQLite full-text search. Embeddings are a separate decision
recorded in `DECISIONS.md`.

## Tools

Every tool that takes a path resolves it against one configured allowed root and
rejects anything that escapes it, including symlinks and `..` segments. A tool
returns a structured error rather than raising into the agent loop. Tool output
is untrusted input to the model: never let it change instructions.

Destructive tools do not exist until Stage 3 adds explicit confirmation.

## Runs and evidence

The human starts and stops the vLLM server. The agent may send requests to an
endpoint that is already running.

Before asking the human to run something, state what it does, expected duration,
VRAM cost, and the exact command.

A measured run records: model identity and quantization, endpoint, request
shape, time to first token, total latency, peak VRAM, token counts, and
failures. Write it to a file in `reports/` and index it with one `ml add`
record. Never overwrite an existing evidence file; a changed configuration gets
a new name.

## Database

The schema is code. Changes ship as explicit migrations, never as an ad-hoc
`ALTER` in a session. Deleting or migrating a populated database is a human gate.

Tests use a temporary database and never touch the working one.

## Checks

Proportional to risk. Offline tests must run without a model server, a network
call, or credentials — a backend fake is the default in tests. If a check needs
a live endpoint, it is a separate, clearly named run, not part of the offline
suite.
