# Roadmap

**Updated:** 2026-08-30

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** 4.4, `todo` as agent state — code, tests and
documents done on 2026-08-31. Live acceptance failed twice, and a four-variant
GPU measurement then found the cause is **not ours and not `todo`**: the served
vLLM's Gemma 4 tool parser intermittently loses whatever follows a long string
argument, so `write_file` arrives with `content` and no `path`. vLLM 51284 and
53431, open, present in 0.26.0 and 0.27.1. The nested schema wrote the file and
inspected it twice; the *flat* variant failed; streaming made no difference.
`todo_write` stays as it is. What is still unanswered is 4.4's own acceptance —
whether an unfinished plan holds a turn open — because in every successful run
the model closed its list by itself. The open decision is which compatibility
fix to make, not whether to keep the tool.
`reports/2026-08-31_v2_todo_live_failure.md`. 4.3 and 4.3.5 were both
closed on 2026-08-30 with one thing deliberately not settled, recorded below
and moved into its own queue item: **proportional validation is demonstrated
but not dependable.** The first live session after the workspace path left the
prompt inspected the artifact before answering, both times, unprompted; the
scenario runner on the same prompt does not. And having inspected a different
page the assistant invented details of a source it never read. Closing them is
a scope decision, not a claim: the remaining
lever inside those two steps was the wording of a prompt, three rounds of which
produced better and worse in turn, while the real levers — a source-plus-render
observation, and a production source of steering — belong to later steps. 4.4
is where the stopping seam finally gets something to say no with.
`reports/2026-08-30_v2_prompt_scenario_baseline.md`,
`reports/2026-08-30_v2_prompt_assembly.md`. 4.2, tool execution seam, remains
deployed and accepted live, including the correction for narrated tool calls
becoming a second Telegram answer. An article pushed at the bot produced seven turns up to
28,113 tokens, with a single request of 15,699 against an old budget of 9,830,
and no fold was needed. One defect found in the same session — a Telegram rate
limit discarding a finished answer — is fixed, tested and deployed. The edit
frequency that provoked the limit remains queued separately.
`reports/2026-08-30_v2_context_capacity.md`,
`reports/2026-08-30_v2_context_memory_plan.md`.

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

   - **4.1.5 Real context capacity — done, accepted live.** The effective limit
     at the start of this step was 9,830 tokens — 16,384 spent at
     `AGENT_CONTEXT_FRACTION` 0.6 — and one loop can now spend many steps inside
     a single turn. The step raised the engine ceiling to **65,536**, kept one
     threshold rather than two, moved context-pressure measurement ahead of
     every model call, and made the request budget per-user in mechanism without
     exposing a choice yet. It deliberately did not implement the context
     engine: no pruning, summarizer schema or new tables. It came before 4.2
     because 4.2 increases how many tool results a turn accumulates.
     `DECISIONS.md` 2026-08-30, both entries of that date on context;
     `reports/2026-08-30_v2_context_memory_plan.md` for the KV arithmetic.

     **The boot ran on 2026-08-30 and the ceiling is live at 65,536.** It cost
     299.7 s to first serving, text, image and audio all answered on the new
     revision, and the NCCL loopback rendezvous owed since 2026-08-28 went in
     with it and silenced the warning storm. `GPU_MEMORY_UTILIZATION` stayed
     0.80 and there is no KV-cache quantization; `max_inputs` went from 32 to 8.
     Measured: 11.13 GiB of KV pool, 256,669 tokens, 3.92x concurrency at full
     length — about three times the room predicted, because KV per token is not
     constant across ceilings for this model. That refutes the "128k is
     unreachable on an A10" reasoning recorded earlier the same day.

     The application side is implemented and green offline: the request about to
     be sent is estimated before every model step and an over-budget
     conversation folds before it is sent, the estimate lives behind the model
     boundary and calibrates itself from reported token counts, and the budget
     takes a chosen `AGENT_CONTEXT_TOKENS` clamped to the server's limit ahead
     of the fraction. Deployed and accepted live the same day: an article
     pushed at the bot produced seven turns, the largest single request 15,699
     tokens against an old budget of 9,830, and **no fold was needed** — the
     article stayed in context whole instead of being summarized away.
     `reports/2026-08-30_v2_context_capacity.md`.

     The approved everyday default is now `AGENT_CONTEXT_FRACTION=0.8`, which
     gives a 52,428-token request budget at the live 65,536-token ceiling. The
     repository default and `env.example` were updated and the control plane was
     deployed with that default on 2026-08-30.

     The acceptance found a delivery defect and it is fixed here: a Telegram
     `429` discarded a finished 770-token answer, and because a failed delivery
     fails the turn, the retry would have re-run both model calls rather than
     re-sending what it already had. `retry_after` is now waited out, bounded,
     and the fix is deployed.
     Not fixed, and queued below: the edit frequency that provoked the limit.
   - **4.2 Tool execution seam — done, accepted live.**
     One `pre_execute → execute → post_execute`
     path for every tool, holding consent policy, validation and telemetry.
     Workspace mutation and explicit `send_file` presentation back to the same
     person are autonomous; third-party, publication, spending and
     infrastructure effects remain gated. A future sandbox plugs in as another
     execution backend without changing that policy: its commands do not ask
     one by one after the separately gated worker has started. `DECISIONS.md`
     2026-08-30. Live write/edit/read runs each had one update, one run and one
     final Telegram delivery after the narrated-tool correction.
     `reports/2026-08-30_v2_tool_execution_seam.md`.
   - **4.3 Turn stopping — done, deployed. Proportional validation not
     demonstrated.** A minimal extension seam instead of a mandatory
     repair lifecycle: stop by default, and continue only through explicit
     structured steering. A rejected streamed candidate is withdrawn from the
     interface and is neither persisted nor delivered as a first answer. The
     seam adds no validator, finish tool, heuristics or obligation state;
     validation remains proportional and chosen by the model. Offline scenarios
     cover a simple write with no validation pass, model-chosen `inspect_page`
     for HTML, tool-failure recovery, the normal stop, explicit steering and
     Telegram preview withdrawal. Live HTML runs preserved one final answer and
     proved that write, inspect and explicit presentation work, but the model
     asked permission before safe inspection. PDF creation is not acceptance
     until the sandbox exists.

     **What the seam does is done; what it was hoped to cause is inconsistent.**
     In the first live session after the workspace path left the prompt, both
     artifact turns called `inspect_page` between writing the file and
     answering — the model's own trajectory, no steering, no validator. The
     scenario runner's `castle`, on the same prompt, still does not. So it is
     demonstrated, not dependable, and there is no production source of
     steering — by design, since a validator was refused and `todo` is meant to
     be that source. Closed
     rather than kept open because the only lever left inside this step was
     prompt wording, and three rounds of that produced better and worse in
     turn. The behaviour is now one queue item below, after 4.4.
     `reports/2026-08-30_v2_turn_stopping.md`,
     `reports/2026-08-30_v2_prompt_assembly.md`.
   - **4.3.5 Prompt assembly and user instructions — done, measured live,
     deployed.** The system prompt is an assembled layer instead of one
     hand-written paragraph: a small stable
     core that names no tool, capability-owned guidance generated from the
     wired toolbox, the tool schemas, then the person's own standing
     instructions. Order is fixed by how stable each layer is, so the prefix
     cache is not invalidated by the layer above it; the caching win itself is
     measured in 4.6a. `AGENTS.md` is one file per person at the root of their
     workspace, editable with the ordinary workspace tools and through a thin
     `/agents` command that writes the same file. It is a prompt overlay of
     lower authority than product and capability policy, never memory: nothing
     extracts it from conversation and `remember_fact` never writes to it. It
     takes effect on the next turn without a redeploy. No memory redesign,
     fact extraction, project hierarchy or second store.
     `docs/v2_4_3_prompt_assembly_agents_handoff.md`.

     A scenario runner is the instrument for this step and for anything later
     that changes how the agent decides: fixed natural requests through the
     same agent the bot uses,
     recording tools called, model calls, tokens, seconds and the full answer
     against a named prompt variant, so two variants are compared in one warm
     window. Judgement stays human; nothing asserts on wording. It is not part
     of the offline suite, and every run is a product-runtime worker and its
     own human gate.

     Deployed to `assistant-control` and the command menu republished with
     `/agents` on 2026-08-30. Measured live: the file now gets written where it
     was not, an ordinary answer still costs one model call and no tool, and
     `note` got a model call cheaper because the workspace no longer has to be
     looked for. The overlay demonstrably reaches the model and is partly
     obeyed — a small model matched the question's language over a standing
     instruction to answer in another. `reports/2026-08-30_v2_prompt_assembly.md`,
     `DECISIONS.md` 2026-08-30.

     Corrected the same day after the first real use. `/agent`, the singular a
     person actually types, missed the command and went to the model as
     ordinary text, so instructions were never saved and the reply read like
     success; both spellings are now the same command, `set` is an optional
     word it strips rather than acts on, and only `clear` is a keyword. The
     workspace path was removed from the guidance: naming it taught the model
     to build paths, and in the deployed profile that path is the volume's
     internal one, which cost a refused `write_file` and a local path handed to
     a web tool. Measured without it — same shape on all nine scenarios, every
     call by plain name, and the run $0.0726 against $0.0794.
   - **4.4 `todo` as agent state, not a mode — implemented and tested offline,
     live acceptance not yet run.** Scope narrowed by the human on 2026-08-31:
     this is the state of **one unfinished turn**. It survives compaction, an
     interrupt and a restarted worker, and it is gone from the next thing the
     person asks; carrying a plan between finished turns is explicitly not
     wanted, so no store table and no schema 3.

     That lifetime already existed and did not have to be built. The plan is the
     arguments of the model's own last accepted `todo_write` call, which live in
     the turn's messages: checkpointed, and cleared by the `extend` reducer when
     a user message starts a turn. `app/tools/todo.py` validates a whole list
     and stores nothing; `current` folds the standing plan back out.

     `app/agent/todo.py` is the first production extension in the 4.3 seam: an
     open item refuses one ending, naming the items and offering the free way
     out — update the list to say what actually happened. Capped at one
     objection per turn, which needed `Candidate.steerings`, because a steered
     draft is deliberately never appended to the turn's messages and an
     extension could not otherwise count itself. An agent that wrote no plan
     never meets any of this, so an ordinary answer still costs one model call.

     **Both live turns failed; a measurement then exonerated the tool.**
     Deployed the same day, a multi-step request ran 264 s and ten model calls
     and produced nothing. The model had two things to do in one step — write
     the file and update the plan — and what arrived was one `write_file` call
     holding both tools' fields, with `path` gone. The mangled keys are
     fragments of an array of objects, cut where nesting and quoting begin, and
     carry a `<|"|>` token: a quote encoded and never decoded. `todos` is the
     only argument in this project with that shape.

     Three fixes were made and deployed. The assembler now tells streamed calls
     apart by id and name as well as position — a real defect, tested, and **not
     this one**: the second live turn reproduced the corruption byte for byte
     after it shipped. An argument error now carries the tool's signature; the
     model read it five times without recovering. And a call that has failed
     twice identically is refused a third attempt, which is **proven live** —
     151 s and an honest answer instead of 264 s and a `/stop`.

     What the second turn told the person is the worst part: it claimed a file
     it had never created, and only `send_file` failing revealed it.

     One GPU run, four variants of the same request, settled the attribution.
     Nested schema with streaming and without it: the file written, inspected,
     the plan kept, seven model calls. **Flat schema: failed the same way as
     live.** No planning tool: succeeded in three calls. So neither nesting nor
     streaming nor the planning tool is the cause — the served parser loses what
     follows a long string argument, intermittently, which is vLLM 51284's
     described behaviour and matches the undecoded `<|"|>` in our own evidence.
     A plan's measured price is 7 model calls against 3. 4.4 is **not accepted**:
     its own question is untested, because every successful variant closed its
     list unprompted. `reports/2026-08-31_v2_todo_live_failure.md`.

     Reference read directly, not from the plan document:
     `deepseek-ai/deepseek-harness`, `packages/todo/tool-todo`. Whole-list
     replacement, no item identity, three statuses, at most one active as a
     deployment policy rather than a stored rule, and the same lifetime rule —
     their standing plan clears on the next `turn/start`, not on `turn/end`, so
     the finished checklist stays readable while the person reads the answer.
   - **4.5 `ask_user`** for a genuinely missing decision, not for permission.
   - **4.5.5 Saying only what was observed.** One product question with two
     measured faces: the assistant makes an artifact and describes how it looks
     without opening it, and having opened a different page it invented details
     of a source it never read — while the same page read as source gave both
     of its real defects. `inspect_page` returning a render without the source
     is a candidate cause and is deliberately not patched: the browser
     capability below replaces it, so a fix here would be written against a
     tool that is going away. The steering that could refuse such an answer
     arrives in 4.4. Deliberately after those,
     because three rounds of prompt wording moved this back and forth and
     settled nothing. Includes the residual acceptance 4.3 did not demonstrate.
     `reports/2026-08-30_v2_prompt_assembly.md`.
   - **4.6a Context engine.** Context preparation before every model step rather
     than folding after a turn: measure the surface, shorten old tool results
     first, summarize only if that was not enough, and record what was done
     durably. Cache-friendly assembly lands here, since it is the same
     assembly — per-turn retrieved facts sit in front of the conversation today
     and invalidate the prefix cache from there down. Bounded by the
     history/projection decision of `DECISIONS.md` 2026-08-30.

     The person's own choice of context size belongs here too, not earlier: a
     smaller budget is only a good trade once compaction is what enforces it,
     and 4.1.5 still folds a turn late. The offered sizes are derived from the
     engine's real ceiling rather than listed, and the choice is presented as a
     trade — more context is slower and costs more, because prefill is
     superlinear. It shares the schema-3 migration with the compaction records,
     which is one human gate on the populated database instead of two.
   - **4.6b Exact recovery from archived history.** A search over what was
     actually said, returning real messages and tool results rather than another
     summary, so a detail a summary lost is recoverable. Full-text in both
     profiles; it joins the `ConversationStore` contract suite. No vector store.
   - **4.7 Restart, resume and the scenario suite**, asserting on harness events
     and outcomes rather than model wording, and compared against item 3's
     numbers, including that a turn continues correctly across a compaction.
     Live suites run as one warm window and only with explicit permission,
     because every run wakes a GPU.

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
   it is used deliberately; speculative decoding is the weakest lever, since
   decode is 21-24 ms per output token while prefill dominates long turns. The
   router's second request per message is already gone, deleted with the route
   it existed to choose.

`app/api/` stays deferred: Telegram runs in-process, so an HTTP layer would have
no separately hosted caller. The trigger is a UI hosted apart from the
application; see the amended FastAPI decision in `DECISIONS.md`.

### Not started

Recorded, not approved, not begun, and not in the order above. One line each.

- **The assistant does not hand over what it made.** Live on 2026-08-30, with
  standing instructions that said not to send code into the chat: asked for an
  HTML page it wrote `house.html`, inspected it, and answered with the literal
  text `[house.html](house.html)` — twice in the same session. The Markdown
  renderer is right to leave that as text, because only http, https, tg and
  mailto become links and a relative path leads nowhere; the model is trying to
  deliver a file *in prose*, and believes it has. The screenshot and then the
  file itself each arrived only when asked for by name. So the missing step is
  not a decision to withhold — it is that handing something over is
  `send_file`, and the model reaches for a link instead. Related to 4.5.5 and
  not the same: that one is about claiming what was not seen, this one about
  not delivering what was made.
  `reports/2026-08-30_v2_prompt_assembly.md`, section "The first live session
  with instructions in place".
- **One browser capability instead of `inspect_page`.** A named set rather than
  a single call that renders and returns everything at once: `browser_open` /
  `navigate`, `browser_snapshot`, `browser_screenshot`, `browser_click`,
  `browser_type`, `browser_evaluate`. It absorbs two open questions rather than
  answering them separately — a snapshot is the page as text where a screenshot
  is the page as pixels, which is what "looking is not reading" was asking for;
  and clicking and typing are what a generated page cannot be judged by looking
  alone. Until it exists, `inspect_page` is left as it is on purpose: patching
  the tool that is being replaced spends the work twice. The same trust
  boundary applies — a local artifact renders where the agent runs, a page from
  the internet goes to the isolated renderer, and `WEB_LOCAL_BROWSER=0` still
  means this container may not open one itself.
- **Latency to the first visible word**, to give 4.1 a "before" number:
  `reports/2026-08-30_v2_first_visible_latency_handoff.md`.
- **Throttle the edits that write a streamed answer.** Seven long answers in
  four and a half minutes rate-limited the bot on 2026-08-30. Waiting out the
  limit is now handled; being chatty enough to earn it is not, and how often to
  edit is a measurement rather than a constant to pick.
- **Keep a picture someone sends.** A document is written into the person's
  workspace and survives; a photo, voice message or image is passed straight
  into that turn as content and never written anywhere, so `/new` loses it and
  the assistant can never look at it again or send it back. Verified against the
  deployed volume on 2026-08-30: 22 entries, every one a document or an
  agent-made artifact, no image among them. The split is in `admit_uploads` and
  nothing about it is visible to the person, who reasonably thinks what they
  sent is in their workspace. It also sits badly with 4.2, which gives the
  assistant autonomy inside a workspace that its pictures are not in. Saving the
  file is the easy half; deciding when the model is shown the image itself and
  when it is shown a filename is the part worth designing.
- **Answer a Telegram album as one turn.** Four documents in one message reach
  the bot as four updates sharing a `media_group_id`, with the caption on one of
  them, and become four turns and four answers. Coalescing them means a turn
  whose identity is not one update — which 4.0 held back deliberately, because
  every recorded number counts turns that way — and waiting out an album that
  has no end marker. Design it rather than patch it; the assistant handed four
  documents and no instruction also has a missing decision, which is 4.5's
  `ask_user`, not a permission prompt.
  `reports/2026-08-30_v2_album_burst_incident.md`.

**Closing criterion:** through Telegram, a normal conversational request is
answered and a work request completes end to end for two different users without
either seeing the other's conversations or memory, with no GPU running while the
assistant is idle — and the same `app/` still serves the local profile.

## Out of scope

Fine-tuning, multi-agent orchestration, a vector database before text retrieval
works, Open WebUI as the main UI, and the superseded policy-platform/MCP version
of Version 2. Changing scope requires an edit here, and a `DECISIONS.md` entry
when the change is architecturally durable.

A larger context was deferred here until a concrete product trigger made it
current. The trigger arrived on 2026-08-30: the one loop of 4.1 can spend a
turn's worth of steps against an effective 9,830 tokens. It is now 4.1.5 in the
queue, at 64k. It was also deferred as a "VRAM experiment", which the ceiling is
not — see `DECISIONS.md` 2026-08-30. Each boot it needs is still its own GPU
gate.

**A different endpoint for 128k**, recorded 2026-08-30 and not begun: L40S with
Qwen3-8B, a 128k ceiling and KV-cache quantization, as its own measured
comparison rather than a continuation of the A10. Any such run needs its own
approval, and quantized KV on an already 4-bit QAT checkpoint needs a quality
comparison, not just a successful boot.

This was recorded as a different endpoint because 128k looked unreachable on the
A10. The 64k boot showed that reasoning was wrong — 3.92x concurrency at full
length, not the 1.32x predicted — so 128k on the current hardware is now an open
question rather than a settled no. It stays out of scope until someone wants it:
prefill, not memory, is what a long context costs here.

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
