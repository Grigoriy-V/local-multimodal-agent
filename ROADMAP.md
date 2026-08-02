# Roadmap

**Updated:** 2026-08-02

**Project status:** Version 1.5 general autonomous harness closed

**Current approved step:** none

This is the only source for current product direction, development state,
order and approved work. The human approves one step before implementation.

`docs/BACKLOG.md` is the source of truth for detailed deferred and possible
later direction. It is not read or used for current development unless the
human explicitly promotes an item into this roadmap.
`README.md` and `chainlit.md` are display documents, not development context.
`DECISIONS.md` preserves architectural rationale and history. It is read only
when this roadmap links a relevant decision or an architectural choice is being
reconsidered; this roadmap wins any conflict.

## Product invariants

- One natural-language interface serves both direct answers and autonomous
  work. The harness, not the user, decides whether tools and validation are
  needed.
- The agent chooses among capabilities allowed by policy and the user's grants,
  and chooses the required evidence. UI controls may approve scope and
  consequential actions or provide cancellation and status, but never
  substitute manual tool selection for agent behavior.
- Plans define task-specific acceptance criteria and validation. Production
  control flow is never specialized to Snake or another benchmark.
- Chainlit remains a replaceable adapter; agent behavior lives in `app/`.
- `ModelBackend` is the only model-facing application interface. Persistence is
  SQLite, memory remains outside the model, raw conversation messages survive
  summarization, and model-generated facts require an explicit save decision.
- Messages preserve the supplied order of text, image and audio parts;
  unsupported or oversized input is refused before a model request.
- The workspace is the permission boundary. Relative paths and absolute paths
  inside it are valid; escaping paths are refused and ambiguous filenames are
  clarified rather than guessed.

## Current state

- Version 1 remains the persistent local multimodal chat baseline. Evidence:
  `reports/2026-08-01_v1_product_smoke.md`.
- Version 1.5 is closed. One natural-language entry point now routes direct
  answers or autonomous work through a general harness. Work requests use
  model-created plans and validation strategies, scoped capability grants,
  bounded implementation/evaluation/repair, browser and filesystem evidence,
  durable cancellation and downloadable artifacts. Chainlit remains a thin
  adapter over the UI-agnostic application runtime.
- Final engineering and product evidence, including the known 16,384-token
  boundary, is in `reports/2026-08-02_v15_product_acceptance.md`; representative
  screenshots are in `reports/test_v1.5/`.

## Closed stages

- Stage 1 — multimodal smoke: `reports/2026-08-01_stage1_smoke_script.md`.
- Stage 2 — minimal LangGraph agent: `reports/2026-08-01_stage2_agent.md`.
- Stage 3 / Version 1 — working product: `reports/2026-08-01_v1_product_smoke.md`.
- Version 1.5 — general autonomous harness:
  `reports/2026-08-02_v15_product_acceptance.md`.

## Version 1.5 — General autonomous agent harness (closed)

**Outcome:** every ordinary request enters one general harness. The harness
understands the request and either answers directly or, when work is required,
continues through `plan -> act -> validate -> repair/finalize`. The model chooses
governed filesystem/browser capabilities and task-specific evidence. When
applicable, the UI shows scope, approval, progress and artifacts without asking
the user to select a mode or tool.

Ordered plan:

1. **Closed:** disconnect the manual `preview`/scripted `task` product routes and
   Snake-specific verifier; keep benchmark code only as historical evaluation
   material.
2. **Closed:** add a grant-governed capability registry for filesystem and
   browser operations. The model selects capabilities; the user approves
   scoped side effects. Evidence: `reports/2026-08-02_v15_step2.md`.
3. **Closed:** replace the split conversational/task entry paths with one
   natural-language entry point. The harness decides `answer` versus `act`; no
   `Conversation` / `Agent` selector, slash-command contract or per-tool control
   is required. Evidence: `reports/2026-08-02_v15_step3_unified_entry.md`. The
   previous selector implementation and `reports/2026-08-02_v15_step3.md` remain
   rejected evidence, not acceptance.
4. **Closed:** on the `act` branch, planning produces task-specific acceptance
   criteria and a validation strategy, then a model evaluator judges real
   grant-governed tool evidence against every criterion. Evidence:
   `reports/2026-08-02_v15_step4_task_validation.md`.
5. **Closed:** keep Chainlit thin while showing applicable plan, scope,
   approval, progress, evidence, cancellation and artifacts. Evidence:
   `reports/2026-08-02_v15_step5_chainlit_product_surface.md`.
6. **Closed:** final human-visual and agent-technical acceptance. The actual app
   handled direct conversation and general work requests without a special
   command or benchmark branch; the human verified the generated Snake through
   live play. Evidence: `reports/2026-08-02_v15_product_acceptance.md`.

**Closing criterion:** through the actual app, a normal conversational request
is answered directly and two materially different work requests complete from
the same entry point. The model chooses governed tools, validates against
task-derived criteria, repairs or stops honestly, and returns evidence and
artifacts; the human visually confirms the rendered results. No mode selector,
separate user-facing route or benchmark-specific production logic is present.

## Version 2 — Policy-governed tool platform (deferred)

**Outcome:** durable policy and grants shared by every interface; governed
documents and future tools; an MCP surface for stronger external models; and
comparable tracing, statistics and graph/tool evaluations.

Provisional plan:

1. Define one inspectable policy predicate and durable grant lifecycle.
2. Load applicable workspace `AGENTS.md` instructions without expanding sandbox
   scope or tool permissions.
3. Make SQLite memory inspectable/editable and separate proposed memories from
   user-approved memory.
4. Put document ingestion and later capabilities behind the policy boundary.
5. Expose governed tools and memory through MCP, including evaluation of a
   Codex app-server model route without nesting incompatible agent loops.
6. Record comparable model, graph, policy and tool traces and statistics.
7. Build reproducible evaluations for tool choice, policy compliance, memory
   retrieval and graph regressions.

This roadmap contains the complete active Version 2 direction. Related future
ideas may exist in `docs/BACKLOG.md`, but are not development input. Version 2
is not authorized.

## Next step candidates

1. Discuss and approve the next stage before implementation. Version 2 remains
   deferred and is not authorized by this roadmap.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before SQLite
retrieval works, and Open WebUI as the main UI. Changing scope requires a
`ROADMAP.md` update; record the rationale in `DECISIONS.md` when the change is
architecturally durable.

## Maintenance

Keep current state short. Closed stages collapse to one evidence link. Historical
step-by-step results belong in reports; durable architectural rationale belongs
in `DECISIONS.md`. Metrics and commands belong in `reports/`.
