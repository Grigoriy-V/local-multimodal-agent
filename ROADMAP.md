# Roadmap

**Updated:** 2026-09-03

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** none. 4.5 and 4.5.5 closed 2026-09-03, accepted
offline, live and, after the deploy the same day, by `/check` 9/9 in the
deployed profile. 4.6a is next and is not approved.

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

- Both databases at schema version 2; conversations, memory and files scoped by
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

4. **Agent harness and loop: one turn, one loop.** The real agent-development
   phase, now that baseline tools, the baseline chat product and measurement
   exist. The general loop already exists in `app/agent/graph.py`; this item
   removes the second lifecycle beside it and the model call that chooses
   between them, then gives the survivor what only the task path had. Ordered
   sub-steps, each starting on its own approval. Grounding, risks and
   per-sub-step acceptance:
   `reports/2026-08-30_v2_step4_harness_preparation.md`.

   - **4.0 Conversation serialization — done, accepted live.** The lease belongs
     to the conversation and the worker drains it in order. Coalescing an image
     and the question after it is deliberately held back.
     `reports/2026-08-30_v2_conversation_serialization.md`.
   - **4.1 One loop — done, accepted live.** The router and the
     plan/implement/test/evaluate lifecycle are gone; one loop with a
     `TurnBudget`, `loop_step` events and an out-of-band stop read at each step
     boundary. `reports/2026-08-30_v2_one_loop.md`, `DECISIONS.md` 2026-08-30.
   - **4.1.5 Real context capacity — done, accepted live.** The engine ceiling
     and the everyday default are in Current state above. The request is
     estimated before every model step and folds only when over budget; no
     context engine, pruning or summarizer schema was built here.
     `reports/2026-08-30_v2_context_capacity.md`,
     `reports/2026-08-30_v2_context_memory_plan.md`, `DECISIONS.md` 2026-08-30.
   - **4.2 Tool execution seam — done, accepted live.** One
     `pre_execute -> execute -> post_execute` path for every tool, holding
     consent policy, validation and telemetry. Workspace mutation and explicit
     `send_file` back to the same person are autonomous; third-party,
     publication, spending and infrastructure effects stay gated, and a sandbox
     will plug in as another backend without changing that.
     `reports/2026-08-30_v2_tool_execution_seam.md`, `DECISIONS.md` 2026-08-30.
   - **4.3 Turn stopping — done, deployed. Proportional validation demonstrated,
     not dependable.** A minimal extension seam instead of a mandatory repair
     lifecycle: stop by default, continue only through explicit structured
     steering, and withdraw a rejected streamed candidate from the interface. No
     validator, finish tool or obligation state. The residual acceptance moves
     to 4.5.5. `reports/2026-08-30_v2_turn_stopping.md`.
   - **4.3.5 Prompt assembly and user instructions — done, measured live,
     deployed.** The system prompt is assembled in order of stability so the
     prefix cache survives: a stable core naming no tool, capability guidance
     generated from the wired toolbox, the schemas, then the person's own
     `AGENTS.md` — one file at the root of their workspace, editable with the
     ordinary tools or `/agent`, a prompt overlay of lower authority than
     product policy and never memory. It takes effect without a redeploy. The
     scenario runner is the instrument for anything later that changes how the
     agent decides, and every run is a product-runtime worker and its own gate.
     `reports/2026-08-30_v2_prompt_assembly.md`,
     `docs/v2_4_3_prompt_assembly_agents_handoff.md`, `DECISIONS.md` 2026-08-30.
   - **4.4 `todo` as agent state, not a mode — closed 2026-08-31 with known
     problems rather than accepted.** The plan is the arguments of the model's
     own last `todo_write`, living in the turn's checkpointed messages: it
     survives an interrupt and a restarted worker, and is gone at the next user
     message, so there is no store table and no schema 3. An open item can
     refuse one ending, once per turn, and the plan is shown inside the
     transient Telegram status message. **Never observed: a live turn where a
     plan and the finished work arrive together.** The open problems are in
     `ISSUES.md`; the follow-up is in Not started.
     `reports/2026-08-31_v2_todo_live_failure.md`.
   - **4.5 Tool system — done 2026-09-03.** A typed outcome replaces the `error:` string protocol: a tool
     returns content or raises `ToolError` with a code, the executor owns
     resolution, coercion, validation, bounds, sanitizing, timeout, the
     telemetry reason and the model projection, and `Message.failure` rides
     through the checkpoint. A call with unreadable arguments is one refused
     result, not a failed request; names resolve against the allowlist and
     nothing is invented. Every family carries its codes; `write_file` is
     atomic. Accepted: `scripts/loop_live.py` A–E live, including a failing
     tool read and answered by the model. Deployed 2026-09-03 and `/check`
     9/9 on that container. `docs/v2_tool_system.md`,
     `reports/2026-09-03_v2_tool_system_implementation.md`,
     `DECISIONS.md` 2026-09-03.
   - **4.5.5 Browser capability — done 2026-09-03.** One `BrowserSession` with
     the full set — open, snapshot with element refs, screenshot, evaluate,
     console, navigate, click, type, press, select — and only observation
     exposed: `inspect_page` re-implemented on it and returning the structure
     with refs. No click, type or navigate tool in this version. The trust
     boundary is a property of the session, offline for a local artifact and a
     request policy for the isolated renderer, which drives the same session.
     Live: `scripts/loop_live.py` F passed 2026-09-03; deployed the same
     day and `/check` 9/9 on that container. `reports/2026-09-03_v2_browser_session.md`,
     `docs/v2_tool_system.md`, `ISSUES.md` ISS-0008.
   - **4.6a Context engine.** Context preparation before every model step rather
     than folding after a turn: measure the surface, shorten old tool results
     first, summarize only if that was not enough, and record what was done
     durably. Cache-friendly assembly lands here, since it is the same
     assembly — per-turn retrieved facts sit in front of the conversation today
     and invalidate the prefix cache from there down. Bounded by the
     history/projection decision of `DECISIONS.md` 2026-08-30.

     The person's own choice of context size belongs here too, not earlier,
     presented as a trade and derived from the engine's real ceiling. It shares
     the schema-3 migration with the compaction records: one human gate on the
     populated database instead of two.
   - **4.6b Exact recovery from archived history.** A search over what was
     actually said, returning real messages and tool results rather than another
     summary, so a detail a summary lost is recoverable. Full-text in both
     profiles; it joins the `ConversationStore` contract suite. No vector store.
   - **4.7 Restart, resume and the scenario suite**, asserting on harness events
     and outcomes rather than model wording, and compared against item 3's
     numbers, including that a turn continues correctly across a compaction.
     Live suites run as one warm window and only with explicit permission,
     because every run wakes a GPU.
   - **4.8 `ask_user`** for a genuinely missing decision, not for permission.
     Was 4.5; moved behind the tool system it returns through, and behind the
     suite that can accept it.
   - **4.9 Saying only what was observed.** The assistant describes artifacts
     and sources it did not open. Was 4.5.5. Deliberately last, because three
     rounds of prompt wording settled nothing, because the browser capability
     is what lets a generated page be exercised, and because the scenario
     suite is the only way to accept a change in what the model does. Includes
     the residual acceptance 4.3 did not demonstrate. `ISSUES.md` ISS-0004,
     `reports/2026-08-30_v2_prompt_assembly.md`.

5. **Isolated execution.** A sandbox backend behind the 4.2 seam: shell, Python
   and package installation in a restricted workspace holding no control-plane
   secret. Isolation, not a confirmation prompt, is the boundary for arbitrary
   generated code. What executes it in the local profile is undecided. Every run
   is a product-runtime worker and a separate human gate. The natural-request
   PDF scenario is accepted only after this capability exists: create the PDF,
   inspect the real document and explicitly deliver it, without a PDF-specific
   workflow.

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

- **Finish the `todo` tool.** What 4.4 left: a live turn where a plan and the
  finished work arrive together, the wording split into when a list is worth
  opening and how coarse its items are, and a turn ending on an item the model
  does not want to close. `reports/2026-08-31_v2_todo_live_failure.md`.
- **Let a plan be corrected by the person**, who can currently only read it.
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
