# Roadmap

**Updated:** 2026-08-29

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** none. Queue 1 is next and is not approved. No worker
start is authorized.

This is the only source for current product direction, state, order and approved
work. The human approves one step before implementation.

`AGENTS.md` holds the product and execution rules; they are not repeated here.
`docs/BACKLOG.md` is the source of truth for deferred and possible later
direction, and is not used for current development unless the human promotes an
item into this file. `DECISIONS.md` preserves architectural rationale and is read
only when this roadmap links a decision or one is being reconsidered; this
roadmap wins any conflict. `README.md` and `chainlit.md` are display documents.

One product invariant is not in `AGENTS.md`: messages preserve the supplied
order of text, image and audio parts, and unsupported or oversized input is
refused before a model request.

## Current state

- Local database at schema version 1; conversations, memory and files scoped by
  user. Deployed database is **Neon**, reached through its pooled endpoint.
- `assistant-llm-v2` at
  `https://grigoriy-v--assistant-llm-v2-server-serve.modal.run` is the primary
  model deployment, reached with `MODEL_AUTH_STYLE=modal_proxy`. The original
  `assistant-llm` stays deployed as rollback only; retiring it is a destructive
  human gate.
- `assistant-control` serves the Telegram webhook and the update worker. Idle
  windows: 60 s on both CPU functions, 12 s on the GPU. The GPU value is live
  through `deploy/modal/autoscale.py` and matches `SCALEDOWN_WINDOW`, so a
  deploy restores it.
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

Direction and rationale: `docs/personal_assistant_direction.md`. Durable
architectural choices: `DECISIONS.md`. Verified platform facts for the deployed
profile: `docs/modal_platform_notes.md`. Cold-start technical rationale:
`docs/modal_vllm_cold_start.md` and `docs/control_plane_cold_start_notes.md`.

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

### Queue

1. **Capabilities the assistant actually has.** Acceptance for the whole item:
   every tool the assistant advertises passes `/check` in the deployed
   container. Before the two items below, because evidence and measurement taken
   without these describe a different product.

   - **Chromium in the control image.** `/check` reports `FAIL browser.inspect`
     in the container today.
   - **File tools over an ephemeral sandbox.** The workspace dies with the
     container, so files do not survive between two messages.
   - **Document ingestion.** PDF, Markdown, text and office documents, with page
     and section boundaries preserved. Attachments accept images and audio only.
   - **Web: search, render, scrape — three tools, not one.** Search through
     Firecrawl comes first. Rendering a page is ours and runs in the tool
     sandbox. Scrape is laid in as a tool and is not a default.
     `reports/2026-08-29_v2_web_capability_options.md`.

2. **Live product evidence.** Nothing above has been seen by a user: that the
   assistant answers a capability question correctly, that `/can` agrees, and
   that the plan and result read well in a real chat. Alongside it, evidence
   that the harness is agentic rather than demo-shaped — multi-step work that
   survives a restart, asks when it should, and claims no result it did not
   verify. Needs one warm window.

   - The agentness evidence is a scenario suite. It asserts on what the harness
     emits and never on the model's wording; it uses our criteria, not the
     plan's; and it runs as one warm window on request, because every run wakes
     a GPU.
   - Telegram voice recognition quality: the audio decodes, so it is a
     mis-hearing. One clean comparison of the same sentence as Opus and WAV.
   - Streaming the answer, through Telegram's message drafts
     (`sendMessageDraft`, Bot API 10.0). The display is the cheap half; the
     source is not, because `ModelBackend.stream` drops `tool_calls` and
     `usage`. Worth more after the single-call change below.

3. **Measurement, metrics, economics, optimization, in that order.** Today's
   15-17 tok/s conflates network, prefill and decode; there is no prefill
   measurement on the A10, and prefix caching has never been read out of a
   startup log.

   - **Application telemetry first.** The worker emits nothing, so a turn's
     shape is invisible and what exists is Modal's dashboard, which the local
     profile does not have. One record per turn written to the shared store,
     with the boundaries `docs/control_plane_cold_start_notes.md` names, plus
     token counts and success. Timings and counts only — no message text, no
     attachments, nothing about a person beyond the owner id.
   - One long-output run separating prefill from decode, and the same for input
     size, as a baseline to beat.
   - **GPU active seconds per successful user turn** is the primary metric, not
     total spend. "Successful" needs a definition a failed turn cannot satisfy.
   - Cost per turn and per user, counting the harness's two model calls
     honestly. Modal bills by App in hourly buckets, so per-turn cost is derived
     and must be labelled as derived.
   - Adaptive scaledown instead of one fixed number, over the network through
     `autoscale.py`.
   - Then optimization: prefix caching confirmed rather than assumed,
     speculative decoding, and the single-call change that removes the router's
     second full-context request per message.

4. **Technical debt: one conversation is not serialized.** Found live — a
   screenshot and a question sent seconds apart ran in two containers and were
   answered out of order. The inbox leases an `update_id` and nothing else.

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

`app/api/` stays deferred: Telegram runs in-process, so an HTTP layer would have
no separately hosted caller. The trigger is a UI hosted apart from the
application; see the amended FastAPI decision in `DECISIONS.md`.

**Closing criterion:** through Telegram, a normal conversational request is
answered and a work request completes end to end for two different users without
either seeing the other's conversations or memory, with no GPU running while the
assistant is idle — and the same `app/` still serves the local profile.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, and Open WebUI as the main UI. The earlier Version 2 — a policy-governed
tool platform with an MCP surface — is superseded; its detail is in
`docs/BACKLOG.md`. Changing scope requires an edit here, and a `DECISIONS.md`
entry when the change is architecturally durable.

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
