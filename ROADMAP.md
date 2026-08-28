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

Version 2 is in progress: **Done** below is finished, **Queue** is the remaining
order. Everything earlier is closed and listed under **Closed stages**.

- The local database is at schema version 1; conversations, memory and files are
  scoped by user.
- `assistant-llm-v2` at
  `https://grigoriy-v--assistant-llm-v2-server-serve.modal.run` is the primary
  model deployment, reached with `MODEL_AUTH_STYLE=modal_proxy`. The original
  `assistant-llm` stays deployed as rollback only; retiring it is a destructive
  human gate.
- Standing constraint on the next `assistant-llm-v2` deploy, and never a reason
  to create one: apply the NCCL loopback rendezvous fix before snapshot creation
  and verify the logs in that deploy's acceptance. The current warnings are
  harmless. `reports/2026-08-28_v2_step3b_nccl_snapshot_warnings.md`.

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
`docs/modal_vllm_cold_start.md`.

### Done

- **Persistence contract** — `ConversationStore`, `SqliteStore`, per-owner
  scoping, one contract suite over every implementation, a `user_version`
  migration. `reports/2026-08-27_v2_step1_store_contract.md`.
- **Telegram adapter** — derived identity, allow list empty by default,
  transport isolated in `run.py`; conversational and work acceptance both passed
  live, and voice and media delivery were fixed after them.
  `reports/2026-08-28_v2_step2_telegram_adapter.md`,
  `reports/2026-08-28_v2_step3b_telegram_live_acceptance.md`,
  `reports/2026-08-28_v2_telegram_voice_and_media_budget.md`.
- **First model endpoint** — Gemma 4 12B on an A10 through vLLM, 189-201 s from
  idle. That wake is why the optimized endpoint became its own stage.
  `reports/2026-08-28_v2_step3a_model_endpoint.md`.
- **Optimized endpoint** — CPU + GPU snapshots, scale to zero, restored cold
  start **10.4 s**, text, image and audio all served, unauthorized callers
  refused at the edge without starting a container.
  `reports/2026-08-28_v2_step3b_restored_cold_start.md`,
  `reports/2026-08-28_v2_step3b_edge_auth_refusal.md`,
  `reports/2026-08-28_v2_step3b_snapshot_boot.md`,
  `reports/2026-08-28_v2_step3b_first_boot_failure.md`.
- **Capability honesty and Telegram shape** — the assistant describes itself
  from its own wiring, `/can` answers the same without a model call, and the
  plan and result have a readable form. Offline only; queue 3 is its evidence.
  `reports/2026-08-28_v2_capability_honesty_and_telegram_shape.md`.

### Queue

1. **Control plane.** The step previously numbered 3c. It deploys new
   components; it does not redeploy `assistant-llm-v2`.

   - **Written, never run.** `PostgresStore` is the second `ConversationStore`,
     provider-agnostic: the deployed database is **Neon**, reached through its
     pooled endpoint because a fleet that scales to zero opens and drops
     connections in bursts, and everything provider-specific lives in
     `AGENT_DATABASE_URL`. SQLite stays the local backend. It joins the contract
     suite only when `AGENT_TEST_DATABASE_URL` is set, so no offline test can
     reach a real database. Nothing has executed a statement yet.
     `reports/2026-08-28_v2_control_plane_postgres_store.md`.
   - **Offline foundation written, never connected or spawned.** The local and
     PostgreSQL LangGraph savers now share one lifecycle; webhook validation,
     persist-before-spawn, a leased update inbox and the worker call boundary
     are covered offline. The platform HTTP/spawn adapter, live database
     migrations, ephemeral sandbox and deployment remain open.
     `reports/2026-08-28_v2_control_plane_offline_foundation.md`.
   - Live setup and contract acceptance for the conversation store,
     checkpointer and update inbox on the same database.
   - The platform HTTP/spawn adapter around the written webhook core, with the
     agent loop in a separate worker. The Telegram secret token and an
     allowed-user list are checked in the application, because platform proxy
     auth cannot be used for a Telegram webhook. Registering the webhook retires
     the polling transport rather than joining it: Telegram refuses
     `getUpdates` while a webhook is set.
   - File tools over an ephemeral sandbox rather than a local path.

2. **Document ingestion.** PDF, Markdown, text and office documents as a
   first-class capability reusable by chat, retrieval and coding work, with page
   and section boundaries preserved. Attachments today accept images and audio
   only. It comes before the two items below on purpose: evidence collected
   without it would be evidence for a product nobody has, and a measurement
   taken before it would be invalidated by the input sizes it introduces.

3. **Live product evidence.** Nothing from the daily-use work above has been
   seen by a user: that the assistant now answers a capability question
   correctly, that `/can` agrees with it, and that the shaped plan and result
   read well in a real chat. Alongside it, evidence that the harness is
   genuinely agentic rather than demo-shaped: multi-step work that survives a
   restart, asks when it should, and claims no result it did not verify. Needs
   one warm window. Telegram voice recognition quality belongs here too and is
   separate work — the audio decodes, so it is a mis-hearing; isolating codec
   from bitrate and language needs one clean comparison of the same sentence as
   Opus and WAV.

4. **Measurement, metrics, economics, optimization, in that order.** Last,
   because a measurement is only worth taking once the capabilities that
   determine what a turn costs are in place. Nothing here is tuning by feel:
   today's 15-17 tok/s is `completion_tokens / wall time` over 48-token answers
   from a Windows client, so it conflates network, prefill and decode; there is
   no prefill measurement on the A10, and whether prefix caching is on has never
   been read out of a startup log.

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
