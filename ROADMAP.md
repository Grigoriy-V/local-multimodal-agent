# Roadmap

**Updated:** 2026-08-28

**Project status:** Version 1.5 closed; Version 2 direction agreed, not authorized

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
- Interfaces are replaceable thin adapters. An adapter maps its own transport
  and identity onto the application's canonical identity; agent behavior lives
  in `app/`.
- The local and deployed profiles run the same `app/` behind configuration.
  Deployment is never a fork, and a capability that works in only one profile
  is unfinished.
- `ModelBackend` is the only model-facing application interface. Conversations
  and memory persist outside the model behind one contract, are scoped by user,
  survive summarization as raw messages, and record model-generated facts only
  on an explicit save decision.
- Messages preserve the supplied order of text, image and audio parts;
  unsupported or oversized input is refused before a model request.
- The workspace is the permission boundary, whether it is a local directory or
  an ephemeral remote sandbox, and each user has their own. Relative paths and
  absolute paths inside it are valid; escaping paths are refused and ambiguous
  filenames are clarified rather than guessed.

## Current state

- Version 1 remains the persistent local multimodal chat baseline. Evidence:
  `reports/2026-08-01_v1_product_smoke.md`.
- Version 1.5 is closed. One natural-language entry point routes direct answers
  or autonomous work through a general harness, with model-created plans and
  validation strategies, scoped capability grants, bounded
  implementation/evaluation/repair, browser and filesystem evidence, durable
  cancellation and downloadable artifacts. Final engineering and product
  evidence, including the known 16,384-token boundary, is in
  `reports/2026-08-02_v15_product_acceptance.md`; representative screenshots are
  in `reports/test_v1.5/`.
- The Version 2 direction is agreed and recorded below. Step 1 is closed and
  step 2 is implemented; the local database is at schema version 1 and both
  conversations and files are scoped by user. Step 3 is split into 3a and 3b;
  neither is authorized.

## Closed stages

- Stage 1 — multimodal smoke: `reports/2026-08-01_stage1_smoke_script.md`.
- Stage 2 — minimal LangGraph agent: `reports/2026-08-01_stage2_agent.md`.
- Stage 3 / Version 1 — working product: `reports/2026-08-01_v1_product_smoke.md`.
- Version 1.5 — general autonomous harness:
  `reports/2026-08-02_v15_product_acceptance.md`. Per-step evidence is in the
  `reports/2026-08-0[12]_v15_step*.md` series.

## Version 2 — Deployable personal assistant (agreed, not authorized)

**Outcome:** the same harness serves a small number of people as a practical
assistant over Telegram, deployed serverless so that no GPU runs while idle,
while remaining fully usable as a local agent on the human's own machine.

Direction and its rationale are in `docs/personal_assistant_direction.md`;
durable architectural choices are in `DECISIONS.md`; verified platform facts and
constraints for the deployed profile are in `docs/modal_platform_notes.md`. This
roadmap is the plan.

Ordered plan:

1. **Closed.** `ConversationStore` is the persistence contract, `SqliteStore`
   its first implementation, and conversations, summaries and facts are scoped
   by owner. A shared contract suite is parameterised over implementations so
   the deployed one answers to the same tests, and a `PRAGMA user_version`
   migration carried the existing local database forward. Files followed during
   step 2: each user now has their own workspace root, so the file tools cannot
   read across people. Evidence:
   `reports/2026-08-27_v2_step1_store_contract.md`.
2. **Implemented, not yet accepted.** `ui/telegram/` is a thin adapter over the
   same harness surface: identity is derived rather than adopted, the open
   conversation lives in the store, consent reuses the durable interrupts, and
   the polling transport is isolated in `run.py` so a webhook replaces it
   without touching the adapter. Access is an explicit allow list that is empty
   by default; `TELEGRAM_OPEN_ACCESS` admits everyone instead, and says so at
   start-up. Real Telegram traffic reached the adapter and was recorded under a
   derived owner with its own workspace directory. Evidence:
   `reports/2026-08-28_v2_step2_telegram_adapter.md`. Acceptance still needs a
   conversational turn, which needs a model server; the machine currently has no
   GPU.
3. **Deployed profile.** Split in two, because the control plane cannot be
   tested before a model can answer at all, and because the model application
   3a deploys is carried into 3b unchanged.

   a. **Closed.** `deploy/modal/` serves Gemma 4 12B on an A10 through vLLM's
      OpenAI-compatible API. Weights load into a Volume once from CPU, the
      endpoint requires Modal proxy auth and refuses an unauthorized caller at
      the edge without waking the GPU, and the application answers through the
      unmodified `OpenAICompatibleBackend` — a proxy token is accepted as an
      ordinary bearer token, so the change this project's notes predicted was
      not needed. Nothing in `app/` changed. Scale to zero confirmed. Measured:
      first boot ~196 s, idle to answer 201 s, answer 1.8-2.4 s warm; the wake
      is dominated by container and image start rather than compilation.
      Evidence: `reports/2026-08-28_v2_step3a_model_endpoint.md`.

   b. **Control plane.** A second store implementation on external Postgres and
      a matching LangGraph checkpointer; a webhook that only validates,
      persists and spawns, with the agent loop in a separate worker; and file
      tools reimplemented over an ephemeral sandbox rather than a local path.
      The Telegram secret token and an allowed-user list are checked in the
      application, because platform proxy auth cannot be used for a Telegram
      webhook. Registering the webhook retires the polling transport rather
      than joining it: Telegram refuses `getUpdates` while a webhook is set.

   Constraints and their sources: `docs/modal_platform_notes.md`. Optimizing
   the measured latency is later work.
4. **Document ingestion.** PDF, Markdown, text and office documents as a
   first-class capability reusable by chat, retrieval and coding work, with
   page and section boundaries preserved. Attachments today accept images and
   audio only.

`app/api/` stays deferred. Telegram runs in-process, so an HTTP layer would
again have no separately hosted caller; see the amended FastAPI decision in
`DECISIONS.md`. The trigger is a UI hosted apart from the application.

**Closing criterion:** through Telegram, a normal conversational request is
answered and a work request completes end to end for two different users
without either seeing the other's conversations or memory, with no GPU running
while the assistant is idle — and the same `app/` still serves the local
profile.

## Superseded direction

The earlier Version 2 — a policy-governed, observable and testable tool
platform with an MCP surface — is not the current plan. Its detailed material
is preserved in `docs/BACKLOG.md`. Individual items may be promoted back into
this roadmap when a concrete assistant use case needs them.

## Next step candidates

1. Accept step 2: one answered message and one work request through the local
   Telegram bot against the deployed endpoint. Nothing blocks this now.
2. Reduce the 189-second wake before it becomes the assistant's normal
   behaviour. A GPU-snapshot implementation is written and unverified; what is
   applied, what is deliberately not, and the sources for each are in
   `docs/modal_vllm_cold_start.md`.
3. Step 3b, once step 2 is accepted.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, and Open WebUI as the main UI. Changing scope requires a `ROADMAP.md`
update; record the rationale in `DECISIONS.md` when the change is
architecturally durable.

## Maintenance

Keep current state short. Closed stages collapse to one evidence link. Historical
step-by-step results belong in reports; durable architectural rationale belongs
in `DECISIONS.md`. Metrics and commands belong in `reports/`.
