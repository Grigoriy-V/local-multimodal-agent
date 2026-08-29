# Roadmap

**Updated:** 2026-08-29

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** none. Item 3 is closed and moved to Done, and the
three defects its live run exposed are fixed and deployed. Item 4, the agent
harness and loop, is next and needs approval. Every live product-runtime run
remains a separate human gate.

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

4. **Agent harness and loop: from a functional assistant to a strong autonomous
   agent.** This is the real agent-development phase, after baseline tools, the
   baseline chat product, and basic metrics and logs exist. Improve the complete
   loop rather than accumulating demo workflows: task understanding, planning,
   tool choice, use of tool history and provenance, clarification, validation,
   repair, truthful completion, restart continuity and efficient context use.
   Evaluate behaviour with scenario suites that assert on harness events and
   outcomes rather than exact model wording. Live suites run as one warm window
   only with explicit permission, because every run wakes a GPU.

   Preserve the failed live PDF task as a future product acceptance scenario:
   from a natural request, the agent must create a simple PDF, validate the real
   document and deliver it. It exposed an ungrounded plan, an implementation
   toolbox unable to execute its own script, an invalid validation strategy and
   exhaustion of all 20 tool calls before validation. These are loop concerns;
   the scenario must not become a hard-coded PDF workflow.

   The first known correctness prerequisite is conversation serialization.
   Found live: a screenshot and a question sent seconds apart ran in two
   containers and were answered out of order. The inbox leases an `update_id`
   and nothing else.

   - **Mutual exclusion.** Two turns must not run on one thread. Today each
     loads context without the other's message, both append, and both write the
     same checkpoint. `current_thread` is a check-then-act, so two workers
     meeting a user with no thread create two.
   - **Order.** The owner drains its conversation by ascending `update_id`.
   - **Coalescing.** A screenshot then a question is one intent in two messages.

   The lease belongs in the database both profiles share, so the behaviour does
   not depend on the platform. That needs a migration on a populated database,
   which is a human gate. Stopgap without a migration: `max_containers=1` on the
   worker.

5. **Optimization after the agent is observable.** Improve efficiency against
   the measurements above without delaying the harness phase: adaptive
   scaledown through `autoscale.py`, and the single-call change that removes the
   router's second full-context request per message — now priced at about 1.0 s
   of prefill a turn, since the router shares no prefix with the answer call.
   Prefix caching is confirmed active and needs no further work before it is
   used deliberately. Speculative decoding is the weakest lever of the three:
   decode is 21-24 ms per output token while prefill dominates long turns.

`app/api/` stays deferred: Telegram runs in-process, so an HTTP layer would have
no separately hosted caller. The trigger is a UI hosted apart from the
application; see the amended FastAPI decision in `DECISIONS.md`.

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
