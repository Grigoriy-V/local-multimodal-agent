# Roadmap

**Updated:** 2026-08-02

**Project status:** Version 1 closed; Version 1.5 general harness in progress

**Current approved step:** none

This is the canonical current plan. The human approves one step before
implementation. Detailed deferred direction lives in `docs/BACKLOG.md`; it is
truthful planning input, but not a contract or authorization.

## Current state

- Version 1 is a persistent local multimodal chat over `ModelBackend`, SQLite,
  four context layers, six governed tools and a thin Chainlit adapter. Evidence:
  `reports/2026-08-01_v1_product_smoke.md`.
- The task-loop foundations exist: structured plan, bounded iterations and tool
  calls, checkpointed scoped grants, sandboxed `edit_file`, retry feedback and
  browser-probe experiments.
- The first Version 1.5 vertical slice incorrectly promoted Snake-specific
  verification and manual `task`/`preview` workflows into the product. Those
  routes are now disconnected. The architectural decision and historical
  evidence index live in `DECISIONS.md`.
- The workspace remains the permission boundary. File tools accept relative
  paths and absolute paths that resolve inside it; paths outside it are refused.
  An ambiguous bare filename must be clarified rather than guessed.
- The general autonomous agent-mode harness is not complete. For now the app
  exposes the conversational agent; the human performs product evaluation.

## Closed stages

- Stage 1 — multimodal smoke: `reports/2026-08-01_stage1_smoke_script.md`.
- Stage 2 — minimal LangGraph agent: `reports/2026-08-01_stage2_agent.md`.
- Stage 3 / Version 1 — working product: `reports/2026-08-01_v1_product_smoke.md`.

## Version 1.5 — General autonomous agent harness

**Outcome:** in agent mode, one ordinary request enters
`understand -> plan -> act -> validate -> repair/finalize`. The model chooses
governed filesystem/browser capabilities and task-specific evidence. The UI
shows scope, approval, progress and artifacts without choosing tools for it.

Ordered plan:

1. **Closed:** disconnect the manual `preview`/scripted `task` product routes and
   Snake-specific verifier; keep benchmark code only as historical evaluation
   material.
2. Add a grant-governed capability registry for filesystem and browser
   operations. The model selects capabilities; the user approves scoped side
   effects.
3. Add a high-level agent mode in Chainlit. A normal-language request enters the
   general harness without a slash-command contract; conversation mode remains.
4. Make planning produce task-specific acceptance criteria and a validation
   strategy, then evaluate real tool evidence against them.
5. Keep Chainlit thin while showing plan, scope, approval, progress, evidence,
   cancellation and artifacts.
6. Run honest app-level product checks from empty sandboxes: Snake with visual
   validation and a materially different task, with no special command,
   scenario branch or scripted model response.
7. Load applicable workspace `AGENTS.md` instructions without expanding sandbox
   scope or tool permissions.
8. Make SQLite memory inspectable/editable and separate proposed memories from
   user-approved memory.
9. Run the full regression plus browser/restart product smoke and close V1.5.

**Closing criterion:** two materially different normal-language tasks complete
through the actual app; the model chooses governed tools, validates against
task-derived criteria, repairs or stops honestly, and returns evidence and
artifacts. No benchmark-specific production logic is present.

## Version 2 — Policy-governed tool platform (deferred)

**Outcome:** durable policy and grants shared by every interface; governed
documents and future tools; an MCP surface for stronger external models; and
comparable tracing, statistics and graph/tool evaluations.

Provisional plan:

1. Define one inspectable policy predicate and durable grant lifecycle.
2. Put document ingestion and later capabilities behind that boundary.
3. Expose governed tools and memory through MCP, including evaluation of a
   Codex app-server model route without nesting incompatible agent loops.
4. Record comparable model, graph, policy and tool traces and statistics.
5. Build reproducible evaluations for tool choice, policy compliance, memory
   retrieval and graph regressions.

Details remain in `docs/BACKLOG.md`. Version 2 is not authorized.

## Next step candidates

1. Approve Version 1.5 step 2: grant-governed general filesystem/browser
   capability registry selected by the model.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before SQLite
retrieval works, and Open WebUI as the main UI. Changing scope requires a
`DECISIONS.md` entry.

## Maintenance

Keep current state short. Closed stages collapse to one evidence link. Historical
step-by-step plans belong in reports or an architectural summary in
`DECISIONS.md`, never here. Metrics and commands belong in `reports/`.
