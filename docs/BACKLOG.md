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

## Version 1.5 (provisional)

Version 1.5 is a learning-oriented bridge between the working Version 1 product
and the policy platform of Version 2. Its final scope and order will be decided
only after Version 1 closes. The graph and harness matter more here than visual
customization.

- **Use native Chainlit product controls first.** Candidate capabilities are
  native commands such as `/compact`, `/workspace`, `/memory` and `/status`;
  chat settings; task/progress status; microphone/audio hooks; file uploads;
  actions and ordinary UI elements. Chainlit callbacks remain thin adapters to
  shared application services. Custom CSS, JavaScript and a replacement React
  frontend are deliberately deferred until native controls prove insufficient.
- **Validate tool calls before confirmation and support bounded correction.**
  The HTML Snake product check exposed a `write_file` call containing `content`
  but no required `path`. The safe tool rejected it, but the UI first asked the
  user to approve an invalid call and the model then asked conversationally
  instead of issuing a corrected call. Validate arguments before consent,
  return precise structured errors, and allow correction within an explicit
  retry budget.
- **Clean up the new-chat lifecycle.** The Version 1 closing smoke preserved the
  canonical conversation and resumed it after restart, but the initial
  Chainlit thread URL remained as an empty `Conversation` beside the canonical
  stored thread. Reconcile temporary and canonical IDs so create, switch and
  resume do not leave duplicate sidebar artifacts.
- **Load workspace instructions.** The local agent should discover applicable
  `AGENTS.md` instructions only inside its explicitly allowed workspace and add
  them to the instruction layer. Nested instructions and precedence need a
  small explicit rule before implementation. Instructions may constrain agent
  behavior but never expand filesystem roots, tool grants or safety policy.
- **Make memory inspectable and reviewable.** SQLite remains the canonical
  runtime store because it supports retrieval, provenance and safe updates. Add
  a human-readable view with edit/delete controls and, if useful, a generated
  Markdown export or projection. Do not make an uncontrolled Markdown file a
  second competing source of truth.
- **Separate candidate memory from committed memory.** The model may propose
  facts or preferences that appear worth remembering, including without an
  explicit `remember_fact` request, but model-generated candidates are not
  trusted memory until the user reviews, edits or approves them. Record source
  thread, time and provenance. Policy-based automatic saving of narrow,
  low-risk preferences may be reconsidered later.
- **Add a bounded task loop to the graph.** The intended learning flow is
  `task -> plan/reason -> implement -> test -> evaluate -> finalize`, with a
  failed evaluation returning to implementation while iteration, tool-call and
  time budgets remain. Store a structured plan, status and decision rationale,
  not private token-by-token chain-of-thought. Testing uses only policy-approved
  verifiers and every retry remains inside the workspace sandbox. A small HTML
  application such as Snake is a useful acceptance task: create it, validate or
  preview it, observe failures and retry within the budget.

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
- **Codex app-server integration research.** Codex can authenticate through a
  ChatGPT subscription, but app-server exposes the complete Codex agent runtime
  rather than a normal raw-model or OpenAI-compatible completion endpoint.
  Before treating it as another backend, compare two shapes: use this project
  as an app-server client, or expose this project's policy-governed tools and
  memory over MCP while Codex owns its loop. The latter is the more natural
  default hypothesis and avoids accidentally nesting one agent loop inside
  another. Start localhost-only, keep authentication material outside the
  repository, respect plan/rate limits, and investigate only after Version 1
  and the policy/MCP boundary are stable.
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
