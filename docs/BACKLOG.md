# Backlog

Ideas and deferred work. Nothing here is planned or authorized. The agent does
not read this file unless a task names it.

Move an item into `ROADMAP.md` only when it becomes the next step, and delete it
from here.

## Deferred with a known trigger

- **Import-graph test for layer boundaries.** Would prove the contract's claim
  that swapping the model or migrating to LangGraph does not require rewriting
  other layers. Premature now — the layers do not exist and Stage 3 restructures
  `app/agent/`. Revisit as a Stage 3 precondition.
- **Vector embeddings for memory retrieval.** Only after SQLite full-text
  retrieval is working and measured.
- **Docker packaging.** Only when there is something worth shipping.
- **Transformers + BitsAndBytes fallback backend.** Only if vLLM proves
  unworkable on 24 GB, with the failure recorded.

## Ideas

- Compare agent behaviour across the two agent applications using the `--agent`
  field in the journals.
- Cost and latency budget per request surfaced in the UI.
- Replace the rolling summary with a structured session state once LangGraph
  provides explicit state.
- Evaluation set for memory retrieval, analogous to a small RAG evaluation.
