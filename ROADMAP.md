# Roadmap

**Updated:** 2026-08-28

**Project status:** Version 1.5 closed; Version 2 in progress

**Current approved step:** queue 1, the control plane. No worker start is
authorized.

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

- **Version 1** is the persistent local multimodal chat baseline.
  Evidence: `reports/2026-08-01_v1_product_smoke.md`.
- **Version 1.5** is closed: one entry point, model-authored plans and
  validation, scoped grants, bounded implement/evaluate/repair, browser and
  filesystem evidence, durable cancellation, downloadable artifacts, and a known
  16,384-token boundary. Evidence:
  `reports/2026-08-02_v15_product_acceptance.md`, screenshots in
  `reports/test_v1.5/`.
- **Version 2** is in progress: everything under **Done** below is finished, and
  the **Queue** is the remaining order. The local database is at schema version
  1 and conversations, memory and files are scoped by user. `assistant-llm-v2`
  is the primary model deployment and the local profile targets it with
  `MODEL_AUTH_STYLE=modal_proxy`; the original `assistant-llm` remains deployed
  as rollback only, and retiring it is a destructive human gate.

## Closed stages

- Stage 1 — multimodal smoke: `reports/2026-08-01_stage1_smoke_script.md`.
- Stage 2 — minimal LangGraph agent: `reports/2026-08-01_stage2_agent.md`.
- Stage 3 / Version 1 — working product: `reports/2026-08-01_v1_product_smoke.md`.
- Version 1.5 — general autonomous harness:
  `reports/2026-08-02_v15_product_acceptance.md`, with per-step evidence in the
  `reports/2026-08-0[12]_v15_step*.md` series.

## Version 2 — Deployable personal assistant

**Outcome:** the same harness serves a small number of people as a practical
assistant over Telegram, deployed serverless so that no GPU runs while idle,
while remaining fully usable as a local agent on the human's own machine.

Direction and rationale: `docs/personal_assistant_direction.md`. Durable
architectural choices: `DECISIONS.md`. Verified platform facts for the deployed
profile: `docs/modal_platform_notes.md`. Cold-start technical rationale:
`docs/modal_vllm_cold_start.md`.

### Done

- **Persistence contract.** `ConversationStore` is the contract,
  `SqliteStore` its first implementation, conversations and facts are scoped by
  owner, a shared contract suite is parameterised over implementations, and a
  `PRAGMA user_version` migration carried the existing database forward.
  Evidence: `reports/2026-08-27_v2_step1_store_contract.md`.

- **Telegram adapter.** `ui/telegram/` is a thin adapter over the same
   harness surface: identity is derived rather than adopted, the open
   conversation lives in the store, consent reuses the durable interrupts, and
   the polling transport is isolated in `run.py` so a webhook replaces it without
   touching the adapter. Access is an explicit allow list, empty by default.
   Both acceptances passed live: a conversational turn, and a bounded work
   request that created and delivered a file. The same session exposed and fixed
   three defects — an `input_audio` format literal that refused Ogg, history
   replay past the served audio cap, and an adapter that never sent a message's
   own media. Evidence:
   `reports/2026-08-28_v2_step2_telegram_adapter.md`,
   `reports/2026-08-28_v2_step3b_telegram_live_acceptance.md`,
  `reports/2026-08-28_v2_telegram_voice_and_media_budget.md`.

- **First model endpoint.** `deploy/modal/` serves Gemma 4 12B on an A10
  through vLLM's OpenAI-compatible API, with weights in a Volume, proxy auth at
  the edge and no change to `app/`. Measured 189-201 s to answer from idle,
  1.8-2.4 s warm; the wake is dominated by vLLM import, profiling, compilation
  and CUDA graph capture, not by loading weights. Its roughly three-minute wake
  is why the optimized endpoint became its own stage before the control plane.
  Evidence: `reports/2026-08-28_v2_step3a_model_endpoint.md`.

- **Optimized endpoint, accepted through Telegram.** `assistant-llm-v2` is a
  separate App identity at
  `https://grigoriy-v--assistant-llm-v2-server-serve.modal.run`, using CPU + GPU
  memory snapshots, explicit `min_containers=0` / `max_containers=1` /
  `scaledown_window`, and readiness hooks that wait on vLLM's `/health`.
  Restored cold start measured **10.4 s** request-to-serving with no new
  snapshot build, against the 189-201 s baseline; text, image and audio all
  pass; scale to zero confirmed. Unauthenticated and invalid-credential requests
  are refused with 401 at the edge in under 1.2 s without starting a container,
  so the public URL is not a secret. Credentials are the documented
  `Modal-Key` / `Modal-Secret` headers, which `OpenAICompatibleBackend` sends
  under `MODEL_AUTH_STYLE=modal_proxy`. Evidence:
  `reports/2026-08-28_v2_step3b_restored_cold_start.md`,
  `reports/2026-08-28_v2_step3b_edge_auth_refusal.md`,
  `reports/2026-08-28_v2_step3b_snapshot_boot.md`,
  `reports/2026-08-28_v2_step3b_first_boot_failure.md`.

  *Carried forward to the next v2 deploy, and never a reason to create one:*
  apply the NCCL loopback rendezvous fix before snapshot creation and verify the
  logs as part of that deploy's acceptance. The current TCPStore warnings are a
  restored heartbeat monitor polling a stale pre-snapshot address — noisy,
  harmless. If `TORCH_NCCL_ENABLE_MONITORING=0` is reconsidered, record that it
  removes PyTorch's protection against a stuck NCCL watchdog. Evidence:
  `reports/2026-08-28_v2_step3b_nccl_snapshot_warnings.md`.

- **The assistant stopped misdescribing itself.** `app/capabilities.py`
  generates what it can do from the toolbox the graph is compiled with, the
  attachment admission policy, and a `Delivery` each adapter declares beside its
  own rendering code; the same sentence closes the tool list for the task
  implementer and validator, which is where the invented `browser.inspect` came
  from. `/can` answers the same question in Telegram from the wiring, with no
  model call. Telegram gained headings for the plan a person approves and for
  the finished task, with model text escaped and a plain-text fallback, and
  `autoscale.py` warns below the 20 s an approval pause needs. Offline only —
  none of it has been seen in a real chat. Evidence:
  `reports/2026-08-28_v2_capability_honesty_and_telegram_shape.md`.

### Queue

1. **Control plane.** The step previously numbered 3c. A second store
   implementation on external Postgres and a matching LangGraph checkpointer; a
   webhook that only validates, persists and spawns, with the agent loop in a
   separate worker; and file tools reimplemented over an ephemeral sandbox
   rather than a local path. The Telegram secret token and an allowed-user list
   are checked in the application, because platform proxy auth cannot be used
   for a Telegram webhook. Registering the webhook retires the polling transport
   rather than joining it: Telegram refuses `getUpdates` while a webhook is set.
   It deploys new components; it does not redeploy `assistant-llm-v2`.

2. **Live product evidence.** Nothing from the daily-use work above has been
   seen by a user: that the assistant now answers a capability question
   correctly, that `/can` agrees with it, and that the shaped plan and result
   read well in a real chat. Alongside it, evidence that the harness is
   genuinely agentic rather than demo-shaped: multi-step work that survives a
   restart, asks when it should, and claims no result it did not verify. Needs
   one warm window. Telegram voice recognition quality belongs here too and is
   separate work — the audio decodes, so it is a mis-hearing; isolating codec
   from bitrate and language needs one clean comparison of the same sentence as
   Opus and WAV.

3. **Measurement, metrics, economics, optimization, in that order.** Nothing
   here is tuning by feel. Today's 15-17 tok/s is `completion_tokens / wall
   time` over 48-token answers from a Windows client, so it conflates network,
   prefill and decode; there is no prefill measurement on the A10, and whether
   prefix caching is on has never been read out of a startup log.

   - Measure first: one long-output run separating prefill from decode, and the
     same for input size, so later changes have a baseline to beat.
   - **GPU active seconds per successful user turn** is the primary metric, not
     total spend. "Successful" needs a definition a failed or abandoned turn
     cannot quietly satisfy.
   - Real economics on top of it: cost per turn and per user, counting the
     harness's two model calls per message honestly. Modal bills by App in
     hourly buckets, so per-turn cost is derived from container lifetime and
     must be labelled as derived.
   - Adaptive scaledown instead of one fixed number. Warm-snapshot wake is about
     8 s and Modal's floor is 2 s: when a person is slow, hold nothing; when
     messages come in a run, raise the window to 15-30 s. `autoscale.py` changes
     this over the network without a deploy, which is what makes it feasible —
     but a deploy resets it to `SCALEDOWN_WINDOW` in `model_app.py`.
   - Only then optimization: prefix caching confirmed rather than assumed,
     speculative decoding, and the router call that costs a second full-context
     request on every message.

4. **Document ingestion.** PDF, Markdown, text and office documents as a
   first-class capability reusable by chat, retrieval and coding work, with page
   and section boundaries preserved. Attachments today accept images and audio
   only.

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

## Maintenance

Keep this file short. Closed work moves to **Done** as one paragraph and its
evidence links; step-by-step history, metrics and commands belong in `reports/`,
durable rationale in `DECISIONS.md`. **Queue** is an order, not a list: work
that turns out to be unfinished comes back as its own queue item rather than
staying as a caveat inside a closed one, and nothing is numbered twice.
