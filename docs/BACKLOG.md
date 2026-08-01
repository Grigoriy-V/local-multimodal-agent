# Backlog

This is the source of truth for detailed deferred and possible later direction.
An item may describe a real intended outcome even when its stage has not started
and may never start. The file is not a contract, an implementation plan or an
authorization to work; `ROADMAP.md` holds the short current direction, order and
approved step. The agent does not read this file unless a task names it.

When a direction becomes current, summarize it in `ROADMAP.md` and keep the
useful detail here until implementation or a later decision makes it stale.

## Deferred with a known trigger

- **Import-graph test for layer boundaries.** Would prove the contract's claim
  that swapping the model does not require rewriting other layers, and would
  mechanically catch a `langchain_core` import leaking out of `app/models/`.
  The boundary currently passes a static audit. Automate it when a second
  backend or a broad layer refactor makes regression likely.
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

Version 2 turns the working local agent into a policy-governed, observable and
testable tool platform. The direction is agreed; its detailed design and work
order are deliberately not fixed before Version 1 closes.

- **Policy as a predicate over tool, arguments, identity and durable grants.**
  It replaces the boolean `Tool.destructive`; grants survive restart, can be
  inspected and revoked, and the same policy applies no matter which model or
  interface requests a tool. A browser cannot grant an arbitrary native path
  directly, so directory access will be a choice among explicitly allowed
  roots.
- **Capabilities added only behind that policy.** This includes `edit_file` for
  targeted changes instead of risky whole-file rewrites, and documents dropped
  into chat — `.txt`, `.md`, `.pdf`, `.docx`. Text formats are nearly free;
  `.pdf` and `.docx` need parsing dependencies. Documents remain an important
  user capability, but must not bypass the same access rules as other tools.
- **An MCP server over the policy-governed tools and memory**, so stronger
  external models such as Claude Code or Codex can use the system without
  receiving a second, less safe implementation of its capabilities.
- **Run tracing and statistics** for model calls, tool calls, policy decisions,
  context decisions, latency, retries, failures and outcome quality, inspectable
  after the fact.
- **An evaluation harness** built on those traces for tool selection, policy
  compliance, memory retrieval and graph regressions, with reproducible fixture
  tasks and comparable results.
- **Video, frame by frame.** The model has no video input; frames are images.
  Trigger: a context of 64–128k, plus frame batching and compression. Feasible
  on 24 GB because Gemma's sliding-window attention keeps a full KV cache only
  on every sixth layer — roughly 8 GB at 128k, halved again by
  `--kv-cache-dtype fp8`. The arithmetic is an estimate and has not been
  measured.

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
