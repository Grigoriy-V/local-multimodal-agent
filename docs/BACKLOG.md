# Backlog

Ideas and deferred work. Nothing here is planned or authorized. The agent does
not read this file unless a task names it.

Move an item into `ROADMAP.md` only when it becomes the next step, and delete it
from here.

## Deferred with a known trigger

- **Import-graph test for layer boundaries.** Would prove the contract's claim
  that swapping the model does not require rewriting other layers, and would
  mechanically catch a `langchain_core` import leaking out of `app/models/`.
  Premature until `app/agent/` exists. Revisit as a Stage 3 precondition.
- **Vector embeddings for memory retrieval.** Only after SQLite full-text
  retrieval is working and measured.
- **Docker packaging.** Only when there is something worth shipping.
- **Transformers + BitsAndBytes fallback backend.** Only if vLLM proves
  unworkable on 24 GB, with the failure recorded. Removed from the contract's
  stack on 2026-08-01: it would put an inference dependency inside a repository
  that deliberately has none.
- **FastAPI application layer.** Only when a consumer other than Chainlit
  exists. See `DECISIONS.md`.

## Version 2

Agreed in direction, ruled out of version 1 by `DECISIONS.md`. Ordered by the
human's stated priority.

- **Documents dropped into the chat** — `.txt`, `.md`, `.pdf`, `.docx`. The
  human calls this the important one. Text formats are nearly free; `.pdf` and
  `.docx` need a parsing dependency. Partial relief exists already: a text file
  placed in the workspace is readable today through `read_file`.
- **Policy as a predicate over `(tool, arguments)`**, replacing the boolean
  `Tool.destructive`, together with directory grants: the user permits a
  workspace, the grant is stored, survives a restart and can be revoked. A
  native file-browser dialog is not available to a web UI; the realistic form is
  a choice among allowed roots.
- **`edit_file`** — a targeted change instead of rewriting a whole file. A 12B
  model asked to alter one line by rewriting the file will corrupt it.
- **Video, frame by frame.** The model has no video input; frames are images.
  Trigger: a context of 64–128k, plus frame batching and compression. Feasible
  on 24 GB because Gemma's sliding-window attention keeps a full KV cache only
  on every sixth layer — roughly 8 GB at 128k, halved again by
  `--kv-cache-dtype fp8`. The arithmetic is an estimate and has not been
  measured.
- **Run tracing** — every model call, tool call and context decision of a turn,
  inspectable after the fact.
- **An MCP server over the memory**, so Claude Code or Codex can reach this
  project's long-term facts.
- **An evaluation harness** for tool selection and memory retrieval.

## Directions, not tasks

- **Learn fine-tuning.** A real goal of the human's, and the reason the
  BitsAndBytes fallback was originally in the plan. It is a separate stack —
  PEFT/LoRA, a dataset, a training loop — and a separate repository. The
  contract rules fine-tuning out of this project; that stands.

## Ideas

- Compare agent behaviour across the two agent applications using the `--agent`
  field in the journals.
- Cost and latency budget per request surfaced in the UI.
- Replace the rolling summary with a structured session state once LangGraph
  provides explicit state.
- Evaluation set for memory retrieval, analogous to a small RAG evaluation.
