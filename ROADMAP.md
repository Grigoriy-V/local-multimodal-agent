# Roadmap

**Updated:** 2026-08-30

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** none. Sub-step 4.1 is done and accepted live, in the
deployed profile as well as locally; 4.2, the tool execution seam, is next and
needs approval. `reports/2026-08-30_v2_one_loop.md`.

**Corrected and accepted 2026-08-29 after live tests.** `assistant-control` v14's
automatic delivery of media returned by any tool was rejected product behaviour.
Its replacement is now implemented, tested offline and accepted in a real
Telegram chat. Read
`reports/2026-08-29_v2_capabilities_browser_workspace_documents.md`, section
"Correction after the last live test", before changing anything.

This is the only source for current product direction, state, order and approved
work. The human approves one step before implementation.

`docs/PRODUCT.md` is the stable product contract; `docs/PROJECT_MAP.md`,
`docs/CODEMAP.md` and `docs/OPERATIONS_MAP.md` describe the current system,
ownership and operations. `AGENTS.md` holds execution rules. `DECISIONS.md`
preserves approved durable choices and their rationale. This file alone owns
current work, order and authorization. `README.md` and `chainlit.md` are display
documents.

## Current state

- Both databases at schema version 2; conversations, memory and files scoped by
  user, and the conversation each person is in stored as their own choice.
  Deployed database is **Neon**, reached through its pooled endpoint.
- `assistant-llm-v2` at
  `https://grigoriy-v--assistant-llm-v2-server-serve.modal.run` is the primary
  model deployment, reached with `MODEL_AUTH_STYLE=modal_proxy`. The original
  `assistant-llm` stays deployed as rollback only; retiring it is a destructive
  human gate.
- `assistant-control` serves the Telegram webhook and the update worker. Idle
  windows: 60 s on both CPU functions, 12 s on the GPU. The GPU value is live
  through `deploy/modal/autoscale.py` and matches `SCALEDOWN_WINDOW`, so a
  deploy restores it. A third function, `render_web_page`, is deployed at
  `https://grigoriy-v--assistant-control-render-web-page.modal.run` behind proxy
  auth. It has run both in the deployed self-test and in a real Telegram turn.
  The web keys are in the `assistant-control` secret, published from the owner's
  own `.env` by `tools/sync_control_secret.py`.
- Owed to the next `assistant-llm-v2` deploy, and not a reason to create one:
  the NCCL loopback rendezvous fix before snapshot creation.
  `reports/2026-08-28_v2_step3b_nccl_snapshot_warnings.md`.

## Closed stages

- Stage 1 — multimodal smoke: `reports/2026-08-01_stage1_smoke_script.md`.
- Stage 2 — minimal LangGraph agent: `reports/2026-08-01_stage2_agent.md`.
- Stage 3 / Version 1 — the persistent local multimodal product:
  `reports/2026-08-01_v1_product_smoke.md`.
- Version 1.5 — general autonomous harness, with a known 16,384-token boundary:
  `reports/2026-08-02_v15_product_acceptance.md`, screenshots in
  `reports/test_v1.5/`, per-step evidence in `reports/2026-08-0[12]_v15_step*.md`.

## Version 2 — Deployable personal assistant

**Outcome:** the same harness serves a small number of people as a practical
assistant over Telegram, deployed serverless so that no GPU runs while idle,
while remaining fully usable as a local agent on the human's own machine.

The canonical product and current system are described by `docs/PRODUCT.md` and
`docs/PROJECT_MAP.md`; operational ownership is in `docs/OPERATIONS_MAP.md`.
Verified platform facts and cold-start evidence remain in
`docs/modal_platform_notes.md`, `docs/modal_vllm_cold_start.md` and
`docs/control_plane_cold_start_notes.md`.

### Done

- **Persistence contract** — `ConversationStore`, `SqliteStore`, per-owner
  scoping, one contract suite over every implementation, a `user_version`
  migration. `reports/2026-08-27_v2_step1_store_contract.md`.
- **Telegram adapter** — derived identity, allow list empty by default,
  transport isolated in `run.py`; conversational and work acceptance both passed
  live. `reports/2026-08-28_v2_step2_telegram_adapter.md`,
  `reports/2026-08-28_v2_step3b_telegram_live_acceptance.md`,
  `reports/2026-08-28_v2_telegram_voice_and_media_budget.md`.
- **First model endpoint** — Gemma 4 12B on an A10 through vLLM, 189-201 s from
  idle. `reports/2026-08-28_v2_step3a_model_endpoint.md`.
- **Optimized endpoint** — CPU and GPU snapshots, scale to zero, restored cold
  start 10.4 s, unauthorized callers refused at the edge.
  `reports/2026-08-28_v2_step3b_restored_cold_start.md`,
  `reports/2026-08-28_v2_step3b_edge_auth_refusal.md`,
  `reports/2026-08-28_v2_step3b_snapshot_boot.md`,
  `reports/2026-08-28_v2_step3b_first_boot_failure.md`.
- **Capability honesty and Telegram shape** — the assistant describes itself
  from its own wiring, `/can` answers without a model call, `/check` tries each
  capability where the agent runs, and the plan and result have a readable form.
  `reports/2026-08-28_v2_capability_honesty_and_telegram_shape.md`.
- **Control plane, accepted live.** A real Telegram message goes webhook →
  checked secret and allow list → Neon inbox → spawned CPU worker → the same
  harness → GPU wake → reply, with nothing on the human's machine. Polling
  retired. `PostgresStore` is the second `ConversationStore` and joins the
  contract suite only when `AGENT_TEST_DATABASE_URL` is set.
  `reports/2026-08-28_v2_control_plane_postgres_store.md`,
  `reports/2026-08-28_v2_control_plane_offline_foundation.md`,
  `reports/2026-08-28_v2_control_plane_cpu_adapter.md`,
  `reports/2026-08-28_v2_control_plane_neon_live.md`,
  `reports/2026-08-28_v2_control_plane_live_acceptance.md`.
- **Database latency gate withdrawn.** Placement stays unpinned and current
  delays are accepted; the probe stays an instrument, not acceptance.
  `DECISIONS.md` 2026-08-28,
  `reports/2026-08-28_v2_control_plane_database_latency_probe.md`.
- **Cold start reduced.** The agent stack is off the webhook's import path, a
  memory snapshot was tried and reverted, the worker's cold start is measured,
  and the webhook now starts the model waking for updates that need one — a cold
  first message about 9.2 s against 14.4 s, unconfirmed live. Telegram's typing
  indicator runs for any turn that reaches the model.
  `reports/2026-08-29_v2_control_plane_cold_start.md`.
- **1. Baseline capabilities, accepted live.** The deployed assistant has a
  persistent per-user workspace, filesystem tools, document text and visual
  reading, an isolated browser, web search/fetch/view, and agent-controlled file
  delivery. In the final live web scenario the model chose `view_web_page`,
  inspected the returned page and screenshot, chose `send_file`, delivered the
  PNG and described what it saw. This also exercised the deployed shared
  Chromium cleanup correction; another synthetic `/check` was not required to
  close the product capability.
  `reports/2026-08-29_v2_capabilities_browser_workspace_documents.md`,
  `reports/2026-08-29_v2_web_capability.md`.
- **2. Baseline chat product, accepted live.** Onboarding, Telegram Markdown with
  a plain fallback, transient English tool activity and truthful inline
  settlement were confirmed in the real chat. Conversation selection then
  replaced "the newest thread is the open one" with a stored choice: `/new`,
  `/chats`, and ownership verified where the choice is written. It was deployed
  with an additive schema-2 migration that left the existing conversations in
  place, and accepted live — a conversation nearly seven hours behind the newest
  was chosen at 04:53:51 and the next message landed in it at 04:54:40, where the
  old rule would have sent it elsewhere. Real answer streaming was carved out and
  stays in the queue.
  `reports/2026-08-29_v2_baseline_chat_product_offline.md`,
  `reports/2026-08-29_v2_conversation_selection.md`.
- **2. Real answer streaming, accepted live.** The model call streams through
  the graph, so tool calls, usage, finish reason and persistence are the ones
  the turn always had; the runtime reports deltas and finished messages as
  separate events; Telegram shows one message being written and finalizes it in
  place. Only finished messages are stored, and `AGENT_STREAM_ANSWERS` turns it
  off in configuration. The same session exposed an unrelated task-route defect:
  a plan whose validation step named no capability ended the task. Fixed and
  deployed, not yet exercised live.
  `reports/2026-08-29_v2_answer_streaming_preparation.md`,
  `reports/2026-08-29_v2_answer_streaming_implementation.md`.
- **3. Baseline measurement, metrics and logs, closed.** A turn is one `run_id`
  from ingress to delivery, with its stages, model calls, tool calls and paths
  in `turn_runs`/`trace_events` and no message text. `tools/show_run.py` reads
  one run, lists failed and unfinished ones, and reports the primary metric —
  GPU active seconds per successful turn, derived and labelled as derived; over
  the first six live turns, 21.2 s and $0.0065 a turn. A real autonomous task
  was reconstructed from the trace without opening a Modal log. The engine
  baseline is measured: decode 21-24 ms per output token, prefill dominant and
  superlinear, prefix caching confirmed at 98% on a repeated prefix.
  `reports/2026-08-29_v2_turn_telemetry_implementation.md`,
  `reports/2026-08-29_v2_run_inspector_implementation.md`,
  `reports/2026-08-29_v2_gpu_baseline_measured.md`.

### Queue

4. **Agent harness and loop: one turn, one loop.** The real agent-development
   phase, now that baseline tools, the baseline chat product and measurement
   exist. The general loop already exists in `app/agent/graph.py`; this item
   removes the second lifecycle beside it and the model call that chooses
   between them, then gives the survivor what only the task path had. Ordered
   sub-steps, each starting on its own approval. Grounding, risks and
   per-sub-step acceptance:
   `reports/2026-08-30_v2_step4_harness_preparation.md`.

   - **4.0 Conversation serialization — done, accepted live.** The lease belongs
     to the conversation and the worker drains it in order. Two messages 323 ms
     apart were answered in order, the second claimed a tenth of a second after
     the first finished. Coalescing an image and the question after it is held
     back — it redefines the turn every recorded number counts.
     `reports/2026-08-30_v2_conversation_serialization.md`.
   - **4.1 One loop — done, accepted live.** The router and the
     plan/implement/test/evaluate lifecycle are deleted, about 1,730 lines, and
     an ordinary message costs one model call where it used to cost two. The
     surviving loop has a `TurnBudget` (steps, tool calls, seconds), `loop_step`
     events the run inspector renders, and a step number in the chat's status.
     A control signal travels out of band in both profiles and the loop reads a
     stop at each step boundary. Live in the deployed bot: `route loop`
     everywhere, `plan.txt` written and read back with no plan to approve, and a
     stop that ended a running turn at its next step with no model call spent.
     The `browser_verifier` and `web_verifier` modules went with the lifecycle;
     they were already unreachable, and 4.3 decides what validation the one loop
     does. `reports/2026-08-30_v2_one_loop.md`, `DECISIONS.md` 2026-08-30.

     The live check also found and closed a blocking defect: a consent button
     pressed after Telegram expired its callback query failed the whole turn,
     and after 4.0 a failed update is claimed ahead of every later message of
     that conversation for ever. The acknowledgement can no longer fail a turn,
     and the queue gives up on an update after three attempts.

   - **4.2 Tool execution seam.** One `pre_execute → execute → post_execute`
     path for every tool, holding consent policy, validation and telemetry.
     Where autonomy inside the workspace is implemented; `DECISIONS.md`
     2026-08-30.
   - **4.3 Turn stopping and proportional validation.** A stopping seam instead
     of a mandatory repair lifecycle. The preserved product acceptance scenario
     lands here: from a natural request, create a simple PDF, validate the real
     document and deliver it — as a harness test, never a PDF workflow.
   - **4.4 `todo` as agent state, not a mode**, surviving folding and restart.
   - **4.5 `ask_user`** for a genuinely missing decision, not for permission.
   - **4.6 Cache-friendly context assembly.** Per-turn retrieved facts sit in
     front of the conversation today and invalidate the prefix cache from there
     down.
   - **4.7 Restart, resume and the scenario suite**, asserting on harness events
     and outcomes rather than model wording, and compared against item 3's
     numbers. Live suites run as one warm window and only with explicit
     permission, because every run wakes a GPU.

5. **Isolated execution.** A sandbox backend behind the 4.2 seam: shell, Python
   and package installation in a restricted workspace holding no control-plane
   secret. Isolation, not a confirmation prompt, is the boundary for arbitrary
   generated code. What executes it in the local profile is undecided. Every run
   is a product-runtime worker and a separate human gate.

6. **Optimization after the agent is observable.** Adaptive scaledown through
   `autoscale.py`. Prefix caching is confirmed active and needs no work before
   it is used deliberately; speculative decoding is the weakest lever, since
   decode is 21-24 ms per output token while prefill dominates long turns. The
   router's second request per message is already gone, deleted with the route
   it existed to choose.

`app/api/` stays deferred: Telegram runs in-process, so an HTTP layer would have
no separately hosted caller. The trigger is a UI hosted apart from the
application; see the amended FastAPI decision in `DECISIONS.md`.

### Not started

Recorded, not approved, not begun, and not in the order above. One line each.

- **Latency to the first visible word**, to give 4.1 a "before" number:
  `reports/2026-08-30_v2_first_visible_latency_handoff.md`.

**Closing criterion:** through Telegram, a normal conversational request is
answered and a work request completes end to end for two different users without
either seeing the other's conversations or memory, with no GPU running while the
assistant is idle — and the same `app/` still serves the local profile.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, Open WebUI as the main UI, and the superseded policy-platform/MCP version
of Version 2. A separate 64k/128k context and VRAM experiment remains deferred
unless explicit GPU approval and a concrete product trigger make it current.
Changing scope requires an edit here, and a `DECISIONS.md` entry when the change
is architecturally durable.

## How this file is kept

- **Only approved work.** A conclusion the human has not approved in words is a
  draft and belongs in `reports/`, not here. See `AGENTS.md`, Records.
- **State and order, not reasoning.** No options, comparisons, prices or
  research. Those go to `reports/`; durable architecture goes to `DECISIONS.md`.
- **One entry per item, a few lines, plus links.** Evidence lives in the report
  it links to and is not summarized twice.
- **Done is a list of outcomes**, not a history of how they were reached.
- **Queue is an order, not a list.** Unfinished work returns as its own queue
  item instead of staying as a caveat inside a closed one.
- **Short beats complete.** If this file needs a table of contents, cut it.
