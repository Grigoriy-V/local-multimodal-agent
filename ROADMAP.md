# Roadmap

**Updated:** 2026-08-28

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** none — the 60-second restored-wake control passed;
no worker start is authorized

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
  conversations and files are scoped by user. Step 3a and Step 3b are closed.
  The optimized endpoint's first restored cold start measured at **25.0 s**, roughly
  an 8x reduction against the baseline's 189-201 s, with the documented
  `Modal-Key` / `Modal-Secret` proxy headers confirmed on the `.modal.run`
  endpoint. One restored wake
  is not acceptance-grade evidence by itself — Modal may build several
  worker-type-specific snapshots. The next image fixed the missing
  `vllm[audio]` dependency; its first invocation rebuilt the invalidated
  snapshot and served text, image and audio over HTTP 200, but the local command
  wrapper lost the final strict semantic result. A separate restored wake is
  still required. A subsequent strict run passed text, image and audio, but
  the first container was marked failed and Modal then built another GPU
  snapshot instead of restoring one; request-to-serving was **446.5 s**, so it
  is correctness evidence rather than restored-cold-start evidence. A final
  human-approved control with a 60-second ceiling then reused that snapshot
  successfully: **10.4 s request-to-serving**, `resume: healthy after 0.0s`, no
  new snapshot build, and scale-to-zero confirmed. The repeating NCCL TCPStore
  warnings are now diagnosed as a restored heartbeat monitor polling a stale
  pre-snapshot worker address; they are noisy but did not affect inference.
  The final product-wiring test then sent one real Telegram message through the
  shared harness and `MODEL_AUTH_STYLE=modal_proxy` to v2. The user received the
  model's reply; one restored container served the harness's two completion
  calls in 17.8 s and 1.66 s, then scaled to zero. Step 2's conversational
  acceptance is therefore closed; its work-request acceptance remains.
  The public endpoint URL is not a secret: unauthenticated and invalid-credential
  requests are refused with 401 at the edge in under 1.2 s without starting a
  container, verified on v2 itself.
  Evidence:
  `reports/2026-08-28_v2_step3b_edge_auth_refusal.md`,
  `reports/2026-08-28_v2_step3b_restored_cold_start.md`,
  `reports/2026-08-28_v2_step3b_nccl_snapshot_warnings.md`,
  building on `reports/2026-08-28_v2_step3b_snapshot_boot.md` and
  `reports/2026-08-28_v2_step3b_first_boot_failure.md`. `assistant-llm-v2` is
  now the primary model deployment and the persistent local profile targets it.
  The original `assistant-llm` remains deployed only as a rollback/reference
  App. Step 3c is not authorized.

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
2. **Implemented; conversational acceptance passed, work acceptance pending.**
   `ui/telegram/` is a thin adapter over the
   same harness surface: identity is derived rather than adopted, the open
   conversation lives in the store, consent reuses the durable interrupts, and
   the polling transport is isolated in `run.py` so a webhook replaces it
   without touching the adapter. Access is an explicit allow list that is empty
   by default; `TELEGRAM_OPEN_ACCESS` admits everyone instead, and says so at
   start-up. Real Telegram traffic reached the adapter and was recorded under a
   derived owner with its own workspace directory. Evidence:
   `reports/2026-08-28_v2_step2_telegram_adapter.md`. Acceptance still needs a
   work request with its capability approval. A real conversational turn has
   now passed through Telegram, the shared harness and `assistant-llm-v2`; the
   user received the model reply and the GPU scaled back to zero. Evidence:
   `reports/2026-08-28_v2_step3b_telegram_live_acceptance.md`.
3. **Deployed profile.** The first model endpoint proved compatibility, but its
   roughly three-minute wake was not acceptable as the assistant's normal
   behaviour. The optimized model deployment was therefore built as a separate
   product stage before the control plane, with a new Modal App identity. It is
   now accepted and primary; the measured original deployment remains available
   only for rollback and historical comparison.

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

   b. **Closed — optimized replacement deployed and accepted through Telegram.**
      A new App identity was built and
      validated without overwriting `assistant-llm`:

      1. **Done.** `deploy/modal/model_app.py` defines `assistant-llm-v2`, so a
         deploy of that file can no longer replace the measured baseline. Both
         `@modal.enter` hooks wait on vLLM's `/health` under a deadline instead
         of on an open port, print elapsed seconds, and distinguish a
         subprocess exit with its return code from an expired budget. Scaling
         is explicit: `min_containers=0`, `max_containers=1`,
         `scaledown_window=30`. `tests/test_model_endpoint.py` covers the
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
      5. **Recovered from the first failed boot.** Sleep mode's cumem allocator
         invalidated vLLM's memory profiling, so the first invocation sized a
         13.77 GiB KV cache and died committing it on a 22.06 GiB card. The
         deployed replacement now uses the measured-safe explicit GPU-memory
         utilization, and CPU+GPU snapshot creation succeeds. Evidence for the
         failure and correction begins in
         `reports/2026-08-28_v2_step3b_first_boot_failure.md`. One genuine
         restore measured 25.0 s. Two later invocations after the audio image
         change each rebuilt a
         GPU snapshot rather than reusing the preceding one. During the latest
         strict run the first container was marked failed; Modal continued the
         pending server task on another container, which built a snapshot and
         passed text, image and audio after 446.5 s to serving. A final
         60-second control then restored the resulting snapshot in 10.4 s with
         no new snapshot creation. Snapshot reuse is therefore working, though
         the preceding failed-container path remains unexplained;
      6. record request-to-ready, restore-to-health, TTFT, warm answer latency,
         tokens/s, VRAM and cost. Verify text first, then image and audio; extend
         warmup only if the multimodal first request shows extra work;
      7. if GPU snapshots fail or do not materially improve wake time, measure
         `FAST_BOOT` / `--enforce-eager` as the fallback. Weight prefetch and
         removal of the two inherited WSL environment variables are later,
         one-variable A/B tests;
      8. **Done. Auth wiring and live Telegram acceptance passed.**
         `OpenAICompatibleBackend` now keeps bearer auth as its default and adds
         an explicit `MODEL_AUTH_STYLE=modal_proxy` mode that splits the existing
         joined proxy token into the already proven `Modal-Key` /
         `Modal-Secret` headers. Offline request tests cover both valid headers
         and malformed credentials. The local `.env` still targeted the original
         deployment before the run. One process-level v2 configuration then carried a real
         Telegram turn through the shared harness: the user received the model
         reply, logs show one restored container and two successful completion
         calls, and scale-to-zero was confirmed. After that acceptance, the
         persistent local `.env` was promoted to v2 with
         `MODEL_AUTH_STYLE=modal_proxy`. The original App is rollback/reference
         only; retiring it remains a later destructive human gate.

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

1. Accept the current NCCL TCPStore warnings for now. Both the loopback fix and
   `TORCH_NCCL_ENABLE_MONITORING=0` must be active before vLLM constructs the
   process group captured by Modal; applying either therefore requires a new
   Function revision and GPU snapshot. The human explicitly chose not to
   rebuild a snapshot only to remove harmless log noise. No configuration or
   deployed state was changed. At the next independently necessary v2 deploy,
   apply the loopback rendezvous fix before snapshot creation and verify the
   logs as part of that deploy's normal acceptance; do not create a deployment
   only for this warning. If the monitoring flag is reconsidered during a
   future rebuild, record that it removes PyTorch's protection against a stuck
   NCCL watchdog and reassess it before any multi-GPU or parallel deployment.
   Evidence: `reports/2026-08-28_v2_step3b_nccl_snapshot_warnings.md`.
2. Step 2 is closed. The bounded work request ran through Telegram to a real
   result — `circle.html` created and delivered, `Status: completed;
   iterations: 1; tool calls: 5` — and the same live session
   exposed two defects that made voice messages impossible: an `input_audio`
   part whose `format` literal refuses Ogg, and a prompt that replayed stored
   media past the served `MM_LIMITS` audio cap. Both are fixed client-side, with
   no deploy or snapshot rebuild; four consecutive voice messages then succeeded
   in one thread. Recognition quality on Telegram voice is mediocre and is
   deferred as separate work, not a blocker. A third, pre-existing defect was
   fixed alongside: importing `chainlit` loaded the developer's `.env` into the
   environment, so thirteen offline tests failed according to local
   configuration. A fourth was found by the human reading the delivered chat
   against the store: the adapter sent text, tool-call names and on-disk
   artifacts but never a message's own media, so the task's browser screenshot
   reached the store and Chainlit and not the Telegram user. Images now go
   through `sendPhoto`, confirmed live: a task created `square.html`, ran
   `inspect_page` and its screenshot arrived in the chat as a picture. Evidence:
   `reports/2026-08-28_v2_telegram_voice_and_media_budget.md`.
3. Start step 3c control-plane work.
4. Turn the working path into a tool worth using daily, alongside step 4
   document ingestion, which remains planned and has not been folded into
   deployment work. The live runs showed the difference between "the pipeline
   works" and "the product is good":
   - The assistant misreports its own capabilities. Asked for a screenshot it
     answered that its output "supports only text", and repeated it when told
     otherwise; the same task text claimed `browser.inspect` was unavailable
     while `inspect_page` had just run and its evidence was counted in the
     acceptance criteria. The system prompt never tells the model that media
     can be delivered, and it invents tool names. Prompt work, no deploy.
   - A capability check the assistant can answer honestly: what it can see,
     hear, send, read and change, derived from the registered tools and the
     adapter's delivery paths rather than written by hand and left to rot.
   - Telegram presentation. Today a turn is a stack of plain messages; plan,
     progress, result and evidence deserve a readable shape, and `scaledown`
     must cover the pause a human takes to read a plan — a 10-second window
     turned one approval into two cold starts.
   - Evidence that it is genuinely agentic rather than demo-shaped: multi-step
     work that survives a restart, asks when it should and does not claim a
     result it did not verify.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, and Open WebUI as the main UI. Changing scope requires a `ROADMAP.md`
update; record the rationale in `DECISIONS.md` when the change is
architecturally durable.

## Maintenance

Keep current state short. Closed stages collapse to one evidence link. Historical
step-by-step results belong in reports; durable architectural rationale belongs
in `DECISIONS.md`. Metrics and commands belong in `reports/`.
