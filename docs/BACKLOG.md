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
