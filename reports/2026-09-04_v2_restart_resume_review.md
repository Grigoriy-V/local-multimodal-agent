# Version 2 — 4.7 restart, resume and the scenario suite, against the references

**Date:** 2026-09-04
**Agent:** Claude, direct session
**Status:** analysis. No code changed, nothing started, nothing deployed. Every
design below is an option until the human approves it in words; the
recommended shape is marked as such and is not yet approved.

## 1. What 4.7 asks for

`ROADMAP.md` 4.7: restart, resume and the scenario suite, "asserting on
harness events and outcomes rather than model wording, and compared against
item 3's numbers, including that a turn continues correctly across a
compaction. Live suites run as one warm window and only with explicit
permission." The preparation report of 2026-08-30 sets the acceptance: "an
interrupted multi-step task continues truthfully without repeating completed
side effects; the suite asserts on harness events, never on model wording."

Three deliverables, then: **(a)** a turn that a dead worker left half-done is
finished rather than lost or redone; **(b)** a suite, offline and live, that
proves it and the fold-in-the-middle case on events; **(c)** the numbers of a
suite run beside the item 3 baseline.

## 2. What happens today when a worker dies mid-turn

Read from `deploy/modal/control_app.py`, `ui/telegram/webhook.py`,
`ui/telegram/inbox.py`, `app/agent/runtime.py`, `app/agent/graph.py`.

1. **The checkpoint holds the work.** LangGraph writes the thread's state
   after every node: after `model` the assistant message with its tool calls
   is durable; after `tools` all results of that step are; after `persist`
   the store has the turn. A death inside `tools` loses the results of that
   step only, and some of its calls may have run. A death inside `model`
   loses only the streamed text the person was watching.
2. **Nothing ever resumes it.** `Agent.pending()` reads interrupts only, and
   `resume()` answers a consent question. There is no path that asks the
   checkpoint "is a turn unfinished here" and continues it.
3. **The row stays `running` until the lease expires**, 900 s after the
   claim, against a container timeout of 600 s (ISS-0034). A killed
   container never calls `retry`, so the update is not re-queued: the
   `attempts` counter and `MAX_ATTEMPTS = 3` only cover an exception inside a
   living worker. Nothing re-spawns a worker for an expired lease; the next
   claim happens when the person's *next* message arrives, and `claim_next`
   then takes the oldest unfinished update first.
4. **When it is claimed again it starts over.** The adapter calls
   `agent.events(thread_id, message)` with the same user message; the
   `extend` reducer sees a user message and replaces the state's messages,
   so the checkpointed half-turn is discarded. Every tool of the dead
   attempt runs again: `write_file` answers `unchanged:`, `fetch_page`
   fetches again, `send_file` sends the same file a second time,
   `remember_fact` saves the fact twice. The person's next message waits
   behind this replay and the first attempt's preview and status messages
   stay on screen, because the code that clears them ran in a process that
   is gone.
5. **The turn's record is one run twice.** The retry reuses `job.run_id`, so
   the second attempt's events append to the first attempt's, after a
   `turn_failed` from the dead worker's `finally` — if that ever ran; on a
   kill it did not, and the run has no ending at all.

So the acceptance sentence fails on both halves today: the task does not
continue, and what did finish is repeated. This is not a defect in the
sense of `ISSUES.md` — it is the unbuilt step — but ISS-0034 and ISS-0033
sit directly under it.

## 3. What the references do

Read on 2026-09-04: OpenClaw `docs/gateway/restart-recovery`, DeepSeek
Harness `docs/architecture.md`, `docs/testing.md` and the persistence
reference, Hermes Agent's checkpoints page, Claude Code's CLI reference, and
the open issue trackers of Claude Code, Codex CLI, Hermes and OpenClaw on
interrupted sessions. Anything marked *(recalled)* is from memory and is to
be checked before anyone builds on it.

| Concern | Reference shape | Ours today |
|---|---|---|
| What is durable before the model runs | OpenClaw: the user message, the `running` mark and the recovery claim in **one SQLite transaction** at admission. DeepSeek: an append-only session log that *is* the model's context — "model-visible means logged". | The inbox row (`running`, lease); the checkpoint after each node |
| How an unfinished turn is found after a restart | OpenClaw: at shutdown every active run is stamped; at startup the gateway scans for sessions "that still claim to be running but have no live owner". DeepSeek: an orphaned turn is closed with a synthetic `turn/end {interrupted}`, never truncated. | Nothing looks |
| What the model is told | OpenClaw: a synthetic system message, "previous turn was interrupted by a restart … continue from the existing transcript". DeepSeek: a synthetic result per call — `TOOL_NOT_STARTED` ("interrupted before the Harness recorded it as started") or `TOOL_OUTCOME_UNKNOWN` ("interrupted after it was recorded, but no result was durably recorded"), with the rule "retry only if the operation is read-only or idempotent; if it may have side effects, first verify external state or ask the user". Claude Code, Codex: a dangling `tool_use` gets a synthetic "interrupted" result *(recalled)*; both trackers carry sessions made unresumable by exactly this seam. | The turn is restarted from the user message; the model is told nothing |
| Whether tools are replayed | OpenClaw: a dangling call is "dropped from the next provider payload and restricted to restart-safe tools unless it is audited replay-safe". DeepSeek: by tool semantics, above. Hermes: no turn recovery at all — its checkpoints are file snapshots before destructive operations, one per directory per turn, and `/rollback` also "undoes the last conversation turn"; an open issue proposes a restart ledger and a hidden continuation turn. | All replayed, blindly |
| Who continues | The always-on gateways (OpenClaw, and Hermes' proposal) continue automatically with a **budget of three** charged attempts, then tombstone. The CLIs (Claude Code, Codex) leave it to the person's `--resume`. | Nobody, until the next message |
| Partial streamed text | OpenClaw: stays in the transcript, the continuation "picks up from the message beneath it". | Lost with the process (never stored: by design, only finished messages are) |
| Messages arriving during a restart | OpenClaw: "rejected with an explicit restart error rather than silently queued into a dying process". | Queued durably in the inbox — better than the reference here |
| What a scenario asserts on | DeepSeek: a recorded `session.jsonl` replays as the model; the persisted log and "the complete `workspace.expected/` tree" are compared; "mid-stream cancellation" is a scenario; recovery tests "prove failed chunks derive no message or tool side effect". Nothing asserts on wording. | `scripts/loop_live.py` A–I: PASS/FAIL on tool names, failure codes and trace events, never wording; `tools/prompt_scenarios.py` compares two runs' shape and keeps the whole answer for a person |

Two things stand out. First, every reference that survives a restart does it
with the same two moves: **make the fact "a turn is running" durable with
the message, and on recovery tell the model per call what is known**, rather
than replaying or forgetting. Second, the replay decision is a **property of
the tool**, read-only or not, exactly like `requires_approval` is a property
of the tool today; nobody guesses it at resume time.

Our checkpoint gives us more than the references start from: the assistant's
tool-call message is durable *before* the tools run, and the results are
durable *after* the step. DeepSeek's two states map onto that directly. A
death inside `tools` means "every call of this step: outcome unknown, and
some may have run"; a death inside `model` means nothing is unknown.

## 4. Options

### 4.1 What to do with the half-done turn

- **A — Close the step honestly and continue (the references' shape;
  recommended).** On claim, ask the checkpoint whether the graph has a
  pending node and no interrupt. If the pending node is `tools`: append,
  as the `tools` node, one synthetic result per call of that step —
  `interrupted`: "the worker was restarted while this call was running;
  whether it ran is unknown — check before doing it again" — for a tool
  that changes anything, and for a read-only tool run it now and append
  the real result. Then continue the graph from `model` with the
  checkpointed messages. If the pending node is `model`: continue from
  `model`; nothing is unknown. If it is `persist`: run `persist`. The person
  sees the turn finish; the model sees what the harness knows.
- **B — LangGraph's own resume** (`ainvoke(None, config)` re-runs the
  pending node). Every call of the dead step runs again, `send_file`
  included. This is the blind replay both references refuse. Rejected.
- **C — Today: restart from the user message.** Fails the acceptance on
  both halves. Rejected.

For A the tool needs one new fact: `replay_safe: bool`, default `False`.
`read_file`, `list_files`, `search_history`, `read_history`,
`search_memory`, `fetch_page`, `search_web`, `view_web_page`,
`inspect_page`, `view_pages`, `read_document` are `True`. `write_file`,
`edit_file`, `send_file`, `remember_fact` and the todo tool stay `False`.
(`write_file` is atomic and answers `unchanged:`, so it *could* be replayed;
leaving it unknown costs one model step and keeps the rule simple.)

### 4.2 Who notices the dead turn

The recovery in A runs inside a worker; something has to start one. Today
nothing does until the next message.

- **A — Modal re-invokes the call, lease equal to the timeout (recommended,
  to be verified for the timeout case).** Modal's guide (read 2026-09-04):
  "If a `modal.Function` container crashes … Modal will reschedule the
  container and any work it was currently assigned" — a crashed or OOM'd
  worker is re-invoked with the same `update_id` without any setting. For
  the kill at `timeout=600`, give `process_telegram_update` `retries=1`;
  whether a timeout counts as a retried failure is not stated on that page
  and is to be read in the reference or tried once. With
  `claim(lease_seconds=600)` the lease has expired by the time either
  re-invocation claims, so the claim succeeds and the recovery path runs.
  `attempts` already counts claims; the third claim abandons with a message
  to the person ("this request was interrupted twice and could not be
  finished") — OpenClaw's budget of three and its tombstone. This also
  closes ISS-0034, since the lease no longer outlives the kill. If the
  timeout is not retried, option B covers that one case.
- **B — A sweeper**: a scheduled CPU function every few minutes spawning a
  worker for every `running` row past its lease. Cheap, but a new
  product-runtime worker that runs whether or not anything died.
- **C — Nothing new; the next message triggers recovery.** Free, and the
  person who sent one message and walked away never gets an answer.
  Rejected as the only mechanism, kept as the fallback that A and B both
  keep.

### 4.3 What the person sees

The dead attempt's status and preview messages cannot be cleared by the
new worker: their Telegram ids died with the process. Option: store the
preview's message id beside the run so the next worker can edit it in place
(one column, one write per preview) — **deferred**; the orphan is a cosmetic
cost and recorded as a known limitation of the first version. The resumed
turn says nothing about the restart on its own; the model's answer carries
what it did. Trace event `turn_resumed` with `unknown=<n>`, `replayed=<n>`.

### 4.4 The suite

- **Offline.** `tests/test_turn_resume.py` on `ScriptedBackend` with the
  SQLite checkpointer: drive a turn to the checkpoint after `model` with two
  calls, one read-only and one writing; open a second `Agent` on the same
  checkpoint file; assert the synthetic `interrupted` result on the write,
  the real result on the read, exactly one `send_file` across both
  attempts, `turn_resumed` in the trace, the answer delivered, the store
  holding the turn once. A second test kills inside `persist` and asserts
  no duplicate rows. A third drives a fold in the middle of a turn
  (`context_tokens` small, three tool steps) and asserts `context_folded`
  between two `loop_step` events and the turn's answer after it — the
  "continues correctly across a compaction" of the roadmap, on events.
- **Live, `scripts/loop_live.py`.** Two scenarios. **J** — a turn cancelled
  while a write tool runs (an `asyncio` cancel after the first `write_file`
  result), then a fresh `Agent` on the same checkpoints: PASS on
  `turn_resumed`, one file on disk, no second `send_file`, an answer. **K**
  — a fold mid-turn: seed the temporary store with a long history, set
  `context_tokens` low, run G's request: PASS on `context_folded` inside
  the turn and the files delivered. Both keep the rule: events and
  outcomes, never wording. One warm window: the script already runs its
  scenarios sequentially in one process; J and K join A–I and
  `--after-deploy` stays A, B, G.
- **The item 3 comparison.** `loop_live` prints model calls, tool calls and
  seconds per scenario. Add derived GPU-active seconds and cost from the
  run's own telemetry (`app/telemetry/cost.py`, the same formula
  `show_run` uses) to the per-scenario line and a footer with the item 3
  reference numbers (2026-08-29: six live turns, 21.22 s derived GPU,
  $0.0065 a successful turn; prefill ~2.3k tok/s, decode ~45 tok/s). A
  table to read, not a gate: the roadmap says "compared", not "bounded".
- **`tools/prompt_scenarios.py`** stays the prompt-variant instrument and is
  not merged into `loop_live`; two instruments with two questions is
  smaller than one with a mode.

### 4.5 Not in 4.7

`ask_user` (4.8) reuses the same interrupt seam and nothing here changes
it. Coalescing messages, the lease sweeper of 4.2 B if A works, tool
deadlines (ISS-0033: a hung tool now ends as "interrupted, outcome unknown"
after the container timeout, which is honest but slow), the orphaned
preview of 4.3.

## 5. Size, cost, gates

- Code: `app/agent/runtime.py` (`unfinished()` reading `aget_state().next`,
  `resume_interrupted()` using `aupdate_state(as_node="tools")` then
  `ainvoke(None)`), `app/agent/graph.py` (the `interrupted` failure code,
  `turn_resumed`), `app/tools/base.py` (`replay_safe`) and the tool
  modules' declarations, `ui/telegram/adapter.py` (check for an unfinished
  turn before starting a new one on the same thread; the abandon message),
  `ui/telegram/webhook.py` (lease, attempts), `deploy/modal/control_app.py`
  (`retries`). About 300 lines and three tests; the suite another 200.
- No schema migration: `attempts` exists, the checkpoint tables exist.
- Gates: the offline suite is free. J and K wake the GPU; one permission
  for the suite run. The control-app deploy (lease, retries) is a deploy
  gate. Verifying Modal's retry-on-timeout needs one real kill: a worker
  with a deliberately low timeout on a test update — a product-runtime
  worker, its own permission — or Modal's documentation if it is explicit.

## 6. What this document does not authorize

No implementation, no deploy, no GPU run, no worker. The next gate is the
human's word on §4.1 A, §4.2 A and the suite shape, and then a separate
start signal for the implementation.

## 7. Built, 2026-09-04

After the human's "делай" on the recommended shape:

- `Tool.replay_safe`, set on the eleven reading tools; the `interrupted`
  failure code and `interrupted()` in `app/agent/graph.py`;
  `already_stored()` makes `persist` idempotent.
- `Agent.unfinished(thread_id)` reads `aget_state().next` with no interrupt
  pending; `Agent.resume_interrupted_events` answers a dead `tools` step per
  call (`aupdate_state(as_node="tools")`), records `turn_resumed`
  (`node`, `unknown`, `replayed`) and continues the graph with `None`.
- Telegram: the adapter takes a turn up when the update's text is the
  message the turn began with (`same_request`), starts afresh otherwise;
  `give_up` tells the person. The worker claims with `LEASE_SECONDS` 590,
  gives up at the fourth claim (`update_abandoned`), and the Modal function
  has `retries=1` beside `WORKER_TIMEOUT_SECONDS = 600`.
- Tests: `tests/test_turn_resume.py` (killed inside `tools`: the read is
  replayed, the write and the dead call are `interrupted`, the person's
  later edit of the file stands, the turn is stored once; killed between
  steps; killed inside `persist` after the store was written; nothing to
  take up; the `replay_safe` declarations), three adapter tests, one worker
  test. Offline suite: 1026 passed, 27 skipped.
- `scripts/loop_live.py`: **K** (a fold between two steps of a turn, on a
  9k budget over seeded history) and **J** (the turn killed once the model
  asked for its first tool, taken up by a fresh agent on the same
  checkpoints); every scenario line now carries derived GPU-active seconds
  and cost, and the run ends with the item 3 baseline for comparison.

Not built, as §4: the orphaned preview of the dead attempt; whether Modal
retries a timeout is confirmed on the first real kill. Live J and K, the
deploy and the after-deploy run are the next gates.
