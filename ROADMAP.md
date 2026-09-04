# Roadmap

**Updated:** 2026-09-04

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** 5, isolated execution, selected by the human
2026-09-04 with item 4 closed as a whole and split into 5a (deployed) and
5b (local). Reviewed against the references and the shape approved the same
day; 5b built and passed live the same day; 5a is next and its start is a
separate signal.

**Before changing media delivery**, read
`reports/2026-08-29_v2_capabilities_browser_workspace_documents.md`, section
"Correction after the last live test": automatic delivery of media returned by
any tool was rejected product behaviour and its replacement is what is deployed.

Observed defects are in `ISSUES.md`, which is not a plan and authorizes nothing.

This is the only source for current product direction, state, order and approved
work. The human approves one step before implementation.

`docs/PRODUCT.md` is the stable product contract; `docs/PROJECT_MAP.md`,
`docs/CODEMAP.md` and `docs/OPERATIONS_MAP.md` describe the current system,
ownership and operations. `AGENTS.md` holds execution rules. `DECISIONS.md`
preserves approved durable choices and their rationale. This file alone owns
current work, order and authorization. `README.md` and `chainlit.md` are display
documents.

## Current state

- Both databases at schema version 3 (2026-09-03); conversations, memory and files scoped by
  user, and the conversation each person is in stored as their own choice.
  Deployed database is **Neon**, reached through its pooled endpoint.
- `assistant-llm-v2` at
  `https://grigoriy-v--assistant-llm-v2-server-serve.modal.run` is the primary
  model deployment, reached with `MODEL_AUTH_STYLE=modal_proxy`. Its context
  ceiling is 65,536 since 2026-08-30, at 0.80 utilization and unquantized KV.
  The original `assistant-llm` stays deployed as rollback only; retiring it is a
  destructive human gate.
- `assistant-control` serves the Telegram webhook and the update worker. Idle
  windows: 60 s on both CPU functions, 12 s on the GPU. The GPU value is live
  through `deploy/modal/autoscale.py` and matches `SCALEDOWN_WINDOW`, so a
  deploy restores it. A third function, `render_web_page`, is deployed at
  `https://grigoriy-v--assistant-control-render-web-page.modal.run` behind proxy
  auth. It has run both in the deployed self-test and in a real Telegram turn.
  The web keys are in the `assistant-control` secret, published from the owner's
  own `.env` by `tools/sync_control_secret.py`.
- The NCCL loopback rendezvous went in with the 2026-08-30 ceiling boot and the
  warning storm is gone: no `Broken pipe` line at or after that boot, where the
  previous revision produced one a second for a container's whole life.
  `reports/2026-08-28_v2_step3b_nccl_snapshot_warnings.md`,
  `reports/2026-08-30_v2_context_capacity.md`.

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

What exists. How it was reached, and every number, is in the linked report.

- **Persistence contract** — `ConversationStore`, `SqliteStore`, per-owner
  scoping, one contract suite over every implementation, `user_version`
  migrations. `reports/2026-08-27_v2_step1_store_contract.md`.
- **Telegram adapter** — derived identity, allow list empty by default,
  transport isolated. `reports/2026-08-28_v2_step2_telegram_adapter.md`,
  `reports/2026-08-28_v2_step3b_telegram_live_acceptance.md`,
  `reports/2026-08-28_v2_telegram_voice_and_media_budget.md`.
- **Model endpoint, then optimized** — Gemma 4 12B on an A10 through vLLM, with
  snapshots, scale to zero and callers refused at the edge.
  `reports/2026-08-28_v2_step3a_model_endpoint.md`,
  `reports/2026-08-28_v2_step3b_*.md`.
- **Capability honesty** — the assistant describes itself from its own wiring;
  `/can` answers without a model call, `/check` tries each capability.
  `reports/2026-08-28_v2_capability_honesty_and_telegram_shape.md`.
- **Control plane, accepted live** — webhook, checked secret and allow list,
  Neon inbox, spawned CPU worker, harness, GPU wake, reply, with nothing on the
  human's machine. Polling retired; `PostgresStore` joins the contract suite
  under `AGENT_TEST_DATABASE_URL`. `reports/2026-08-28_v2_control_plane_*.md`.
- **Database latency gate withdrawn** — the probe is an instrument, not
  acceptance. `DECISIONS.md` 2026-08-28,
  `reports/2026-08-28_v2_control_plane_database_latency_probe.md`.
- **Cold start reduced** — the agent stack is off the webhook's import path and
  the webhook starts the model waking for updates that need one.
  `reports/2026-08-29_v2_control_plane_cold_start.md`.
- **1. Baseline capabilities, accepted live** — persistent per-user workspace,
  filesystem tools, document text and visual reading, isolated browser, web
  search/fetch/view, agent-controlled file delivery.
  `reports/2026-08-29_v2_capabilities_browser_workspace_documents.md`,
  `reports/2026-08-29_v2_web_capability.md`.
- **2. Baseline chat product, accepted live** — onboarding, Telegram Markdown
  with a plain fallback, transient tool activity, truthful inline settlement,
  and conversation selection as a stored choice (`/new`, `/chats`) behind an
  additive schema-2 migration.
  `reports/2026-08-29_v2_baseline_chat_product_offline.md`,
  `reports/2026-08-29_v2_conversation_selection.md`.
- **2. Real answer streaming, accepted live** — the model call streams through
  the graph, only finished messages are stored, and `AGENT_STREAM_ANSWERS`
  turns it off. `reports/2026-08-29_v2_answer_streaming_*.md`.
- **3. Baseline measurement, metrics and logs, closed** — a turn is one `run_id`
  from ingress to delivery, carrying no message text; `tools/show_run.py` reads
  one run and reports GPU active seconds per successful turn, labelled as
  derived. The engine baseline is measured.
  `reports/2026-08-29_v2_turn_telemetry_implementation.md`,
  `reports/2026-08-29_v2_run_inspector_implementation.md`,
  `reports/2026-08-29_v2_gpu_baseline_measured.md`.

### Queue

4. **Agent harness and loop — closed 2026-09-04.** One loop, one tool
   path, a real context window, a browser that looks, resume across a dead
   worker, and a scenario suite that accepts on events rather than wording.
   Outcomes, each with its report:
   - 4.0 the lease belongs to the conversation and the worker drains it in
     order — `reports/2026-08-30_v2_conversation_serialization.md`;
   - 4.1 one loop with a `TurnBudget` and an out-of-band stop; the router and
     the plan/implement/test lifecycle are gone —
     `reports/2026-08-30_v2_one_loop.md`;
   - 4.1.5 the request is estimated before every model step and folds only
     over budget — `reports/2026-08-30_v2_context_capacity.md`;
   - 4.2 one `pre_execute -> execute -> post_execute` path for every tool,
     consent policy and telemetry inside it; a sandbox plugs in as another
     backend — `reports/2026-08-30_v2_tool_execution_seam.md`;
   - 4.3 stop by default, continue only through explicit structured
     steering; the seam's one extension, the plan objection, is off —
     `reports/2026-08-30_v2_turn_stopping.md`;
   - 4.3.5 the prompt assembled in order of stability, the person's own
     `AGENTS.md` as a prompt overlay, the scenario runner as the instrument
     — `reports/2026-08-30_v2_prompt_assembly.md`;
   - 4.4 `todo` as agent state, off unless the person turns it on —
     `reports/2026-08-31_v2_todo_live_failure.md`;
   - 4.5 typed tool outcomes, the executor owning validation, bounds,
     timeout and the model projection — `docs/v2_tool_system.md`,
     `reports/2026-09-03_v2_tool_system_implementation.md`;
   - 4.5.5 one `BrowserSession` with the full action set, observation alone
     exposed as `inspect_page` — `reports/2026-09-03_v2_browser_session.md`;
   - 4.6a context preparation before every model step, results shortened by
     age, the last two exchanges verbatim, a fold taking only what has to go
     — `reports/2026-09-03_v2_context_engine_review.md`;
   - 4.6b full-text recovery of what was actually said, `search_history` and
     `read_history` — `reports/2026-09-03_v2_history_recovery_review.md`;
   - 4.7 a turn a dead worker left is taken up from its checkpoint, reading
     tools re-run and the rest reported unknown; `scripts/loop_live.py` A–K
     — `reports/2026-09-04_v2_restart_resume_review.md`;
   - 4.9 saying only what was observed stays measurement, not a mechanism:
     the proposed checks were withdrawn as a script of past defects and the
     rule is in `AGENTS.md` — `reports/2026-09-04_v2_observed_claims_review.md`.

   Durable choices: `DECISIONS.md` 2026-08-30 through 2026-09-04. Left open
   as observations in `ISSUES.md`, to be fixed where the next work meets
   them: a page described from its address alone, a path offered beside a
   real send, an application called working without a look (browser actions
   exist and are not exposed), the memory layer that says nothing when its
   keyword retrieval finds nothing. `ask_user` and the `todo` follow-up are
   in Not started.

5. **Isolated execution — current, selected 2026-09-04.** An execution
   backend behind the 4.2 seam: shell, Python and package installation in a
   workspace holding no control-plane secret. Isolation, not a confirmation
   prompt, is the boundary for arbitrary generated code. Every deployed run
   is a product-runtime worker and a separate human gate during development.
   The natural-request PDF scenario is accepted only after this capability
   exists: create the PDF, inspect the real document and explicitly deliver
   it, without a PDF-specific workflow. Split on the human's word 2026-09-04
   into the two profiles; reviewed against the references and **the shape
   approved the same day** (`reports/2026-09-04_v2_isolated_execution_review.md`
   §5, `DECISIONS.md` 2026-09-04); **not started**. One `run_command`
   tool; what is installed lives in the workspace; two modes per
   conversation, `full` (default) and `careful`; cold start measured
   before anything is built on it. Order: 5b, then 5a.

   - **5b Local (this machine) — done 2026-09-04.** `run_command` over a
     one-method `Runner`; a process in the workspace with the agent's own
     environment withheld, killed with its tree at the deadline; the two
     modes and `/mode`; the brief says where commands run. Offline: 17
     tests and one adapter test. Live the same day: O (a script written and
     run), P (the PDF made, checked and sent — the 4.3 acceptance), Q (a
     command killed at its timeout) passed. ISS-0038, the first install
     going to the machine's Python, fixed the same day on the human's rule:
     the workspace's own venv is the `python` and `pip` a command sees,
     and pip refuses any other; P re-run passed with the install in
     `.venv`.
     `reports/2026-09-04_v2_isolated_execution_review.md` §9.
   - **5a Deployed (Modal) — next.** A `run_command` Function beside the renderer:
     same image plus base tools, the workspaces Volume, no secret, 180 s
     scaledown; the Volume round trip, O, P, Q through Telegram, the
     after-deploy run, the cold-start number.

6. **Optimization after the agent is observable.** Adaptive scaledown through
   `autoscale.py`. Prefix caching is confirmed active and needs no work before
   it is used deliberately; speculative decoding is the weakest lever, because
   prefill dominates long turns. `reports/2026-08-29_v2_gpu_baseline_measured.md`.

`app/api/` stays deferred: Telegram runs in-process, so an HTTP layer would have
no separately hosted caller. The trigger is a UI hosted apart from the
application; see the amended FastAPI decision in `DECISIONS.md`.

### Not started

Recorded, not approved, not begun, and not in the order above. One line each;
an observed defect is described in `ISSUES.md`, not here.

- **The whole-code review of 2026-09-03**, thirteen findings ranked and an
  order proposed: `reports/2026-09-03_v2_whole_code_review.md`. Items 1 and 2
  of its order (§2.1–2.4: the summarizer reads stubs, a fold cannot fail a
  turn, folding by size, a cut call named, identical successes bounded) were
  built and deployed 2026-09-04 on the human's word; the rest is not approved.
- **Finish the `todo` tool.** What 4.4 left: a live turn where a plan and the
  finished work arrive together, the wording split into when a list is worth
  opening and how coarse its items are, and a turn ending on an item the model
  does not want to close. `reports/2026-08-31_v2_todo_live_failure.md`.
- **Let a plan be corrected by the person**, who can currently only read it.
- **`ask_user`** for a genuinely missing decision, not for permission. Was
  4.8 until 2026-09-04; a feature rather than architecture, so it waits for
  the base harness. It returns through the same interrupt seam consent
  uses.
- **Hand over what was made.** Delivery is `send_file` and the model reaches for
  a Markdown link instead. `ISSUES.md` ISS-0003.
- **Latency to the first visible word**, to give 4.1 a "before" number.
  `reports/2026-08-30_v2_first_visible_latency_handoff.md`.
- **Throttle the edits that write a streamed answer.** How often to edit is a
  measurement, not a constant to pick.
- **Keep a picture someone sends.** Saving the file is the easy half; when the
  model is shown the image and when it is shown a filename is the design.
  `ISSUES.md` ISS-0002.
- **Answer a Telegram album as one turn.** It means a turn whose identity is not
  one update, which 4.0 held back deliberately, and waiting out an album with no
  end marker. `reports/2026-08-30_v2_album_burst_incident.md`.
- **Show the preview only when it will survive.** `ISSUES.md` ISS-0009.
- **Put the reason in `tool_failed`.** `ISSUES.md` ISS-0007.
- **The local interface as a product path.** Chainlit and the agent on the
  person's machine, the model on Modal: a second way to use the same
  assistant, beside Telegram. Confirmed as a product path on 2026-09-03 and
  deferred by the human until the base harness is done; the adapter is
  covered by tests only since the 4.5 changes and has not been run live.

**Closing criterion:** through Telegram, a normal conversational request is
answered and a work request completes end to end for two different users without
either seeing the other's conversations or memory, with no GPU running while the
assistant is idle — and the same `app/` still serves the local profile.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, Open WebUI as the main UI, and the superseded policy-platform/MCP version
of Version 2. Changing scope requires an edit here, and a `DECISIONS.md` entry
when the change is architecturally durable.

**A different endpoint for 128k**, recorded 2026-08-30 and not begun: L40S with
Qwen3-8B, a 128k ceiling and KV-cache quantization, as its own measured
comparison rather than a continuation of the A10. 128k on the current hardware
is an open question rather than a settled no; it stays out of scope until
someone wants it. Any such run needs its own approval, and quantized KV on an
already 4-bit QAT checkpoint needs a quality comparison, not just a successful
boot. `DECISIONS.md` 2026-08-30.

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
