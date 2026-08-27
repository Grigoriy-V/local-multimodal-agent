# Roadmap

**Updated:** 2026-08-28

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** 3b implementation only — no deploy, no worker start

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
  conversations and files are scoped by user. Step 3a is closed. Step 3b is
  implemented and working, but not yet measured where it matters. Sleep mode,
  snapshot creation and snapshot restore all succeed for Gemma 4 12B on an A10
  after an explicit `--gpu-memory-utilization 0.80`; the engine wakes in 1.0 s
  and answers warm in 1.3 s. Evidence:
  `reports/2026-08-28_v2_step3b_snapshot_boot.md`, with the OOM that preceded it
  in `reports/2026-08-28_v2_step3b_first_boot_failure.md`. **No restored
  cold-start number exists yet**, which is the number the whole step is for. The
  baseline `assistant-llm` still serves `MODEL_ENDPOINT`. Step 3c is not
  authorized.

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
3. **Deployed profile.** The first model endpoint proved compatibility, but its
   roughly three-minute wake is not acceptable as the assistant's normal
   behaviour. The optimized model deployment is therefore a separate product
   stage before the control plane. It gets a new Modal App identity; the
   measured baseline remains available for comparison and rollback until the
   replacement is accepted.

   a. **Closed.** `deploy/modal/` serves Gemma 4 12B on an A10 through vLLM's
      OpenAI-compatible API. Weights load into a Volume once from CPU, the
      endpoint requires Modal proxy auth and refuses an unauthorized caller at
      the edge without waking the GPU, and the application answers through the
      unmodified `OpenAICompatibleBackend` — a proxy token is accepted as an
      ordinary bearer token, so the change this project's notes predicted was
      not needed. Nothing in `app/` changed. Scale to zero confirmed. Measured:
      first boot ~196 s, idle to answer 201 s, answer 1.8-2.4 s warm. A later
      read-only audit of the deployed logs refined the diagnosis: weights load
      in 6.8-6.9 s, while vLLM imports/configuration, engine profiling,
      compilation and CUDA graph capture dominate the wake. The currently
      deployed App does not use memory snapshots.
      Evidence: `reports/2026-08-28_v2_step3a_model_endpoint.md`.

   b. **Optimized replacement model deployment.** Implementation authorized and
      done; deployment is not. A new App identity is built and validated
      offline rather than overwriting `assistant-llm`:

      1. **Done.** `deploy/modal/model_app.py` defines `assistant-llm-v2`, so a
         deploy of that file can no longer replace the measured baseline. Both
         `@modal.enter` hooks wait on vLLM's `/health` under a deadline instead
         of on an open port, print elapsed seconds, and distinguish a
         subprocess exit with its return code from an expired budget. Scaling
         is explicit: `min_containers=0`, `max_containers=1`,
         `scaledown_window=600`. `tests/test_model_endpoint.py` covers the
         readiness paths and asserts the identity and bounds offline.
      2. retain the proven CUDA-devel image, pinned model/vLLM/transformers,
         protected OpenAI-compatible endpoint, preloaded weights Volume and
         compile-cache Volume; do not optimize the image or add weight
         prefetch before measurements justify either;
      3. **Done.** Offline and static checks, and the CPU preflight, which
         passed against `assistant-llm-v2` on 2026-08-28 with `vllm 0.26.0 /
         transformers 5.14.1` and `head_size=512`, no GPU and no model call.
         That run also showed that `modal run` cannot validate the snapshot
         path at all — Modal disables memory snapshots for ephemeral apps — so
         deployment is a precondition of the first snapshot measurement rather
         than something it can follow;
      4. **Done.** `assistant-llm-v2` is deployed as of 2026-08-28, in 5 s from
         cached image layers, at zero containers. `assistant-llm` is untouched
         and also at zero. Its web URL is
         `https://grigoriy-v--assistant-llm-v2-server-serve.modal.run`. The
         domain differs from the baseline's `.modal.direct` because the snapshot
         hooks forced `@app.cls` + `@modal.web_server` in place of
         `app.server()`, not because protection differs — but that also changes
         the documented credential mechanism to `Modal-Key` / `Modal-Secret`
         headers, so step 3a's finding that a proxy token doubles as a bearer
         token is **not carried over** and must be retested here before
         `MODEL_ENDPOINT` moves. Creation of each paid GPU worker remains a
         separate human gate;
      5. **Attempted and failed once.** The first paid invocation never served
         a request: sleep mode's cumem allocator invalidates vLLM's memory
         profiling, so it sized a 13.77 GiB KV cache and died committing it on
         a 22.06 GiB card. An explicit `--gpu-memory-utilization=0.83` is the
         untested fix. Modal restarted the failed container, so a failed boot
         costs more than one boot; stop the App rather than letting it retry.
         Evidence: `reports/2026-08-28_v2_step3b_first_boot_failure.md`. Then
         create and verify CPU+GPU snapshots and measure at least two restored
         cold starts, because Modal may create several snapshots for one GPU
         type;
      6. record request-to-ready, restore-to-health, TTFT, warm answer latency,
         tokens/s, VRAM and cost. Verify text first, then image and audio; extend
         warmup only if the multimodal first request shows extra work;
      7. if GPU snapshots fail or do not materially improve wake time, measure
         `FAST_BOOT` / `--enforce-eager` as the fallback. Weight prefetch and
         removal of the two inherited WSL environment variables are later,
         one-variable A/B tests;
      8. switch `MODEL_ENDPOINT` only after the replacement passes the same
         backend and Telegram acceptance checks — which now includes proving
         how `OpenAICompatibleBackend` authenticates against a `.modal.run`
         proxy-auth endpoint, since the bearer-token equivalence was only ever
         shown for `.modal.direct`. Retiring the baseline App is a later
         destructive human gate, not part of deployment.

      Target: a reproducible scale-to-zero endpoint whose restored cold start
      is short enough for a private interactive assistant. No target number is
      claimed before measurement. Technical rationale and the exact evidence
      to collect are in `docs/modal_vllm_cold_start.md`.

   c. **Control plane.** A second store implementation on external Postgres and
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

1. Authorize the restored cold-start measurement: let `assistant-llm-v2` scale
   to zero, then invoke it at least twice, taking the timing from the container
   log rather than from the client — a plain request is answered `303` while the
   container is still coming up, so it cannot time readiness. Two wakes because
   Modal may build several worker-type-specific snapshots.
2. Then verify image and audio against the restored endpoint, and test whether a
   joined proxy token works as a bearer token on `.modal.run`. That last one
   decides whether `OpenAICompatibleBackend` needs the change step 3a concluded
   it did not.
3. Accept step 2 against the accepted endpoint: one conversational turn and one
   work request through Telegram. The baseline endpoint can prove integration,
   but the optimized replacement should become the normal product endpoint.
4. Start step 3c control-plane work after Telegram acceptance.
5. Continue to step 4 document ingestion; it remains planned and has not been
   removed or folded into deployment work.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, and Open WebUI as the main UI. Changing scope requires a `ROADMAP.md`
update; record the rationale in `DECISIONS.md` when the change is
architecturally durable.

## Maintenance

Keep current state short. Closed stages collapse to one evidence link. Historical
step-by-step results belong in reports; durable architectural rationale belongs
in `DECISIONS.md`. Metrics and commands belong in `reports/`.
