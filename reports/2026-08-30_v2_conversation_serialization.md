# 4.0 Conversation serialization — implementation and offline evidence

**Date:** 2026-08-30
**Roadmap item:** queue 4, sub-step 4.0.
**Preparation:** `reports/2026-08-30_v2_step4_harness_preparation.md`
**Fixes:** the live race recorded in `ROADMAP.md` — a screenshot and the question
after it, sent seconds apart, ran in two containers and were answered out of
order.

Not deployed and not accepted live. Everything below was proven offline, and one
part of it cannot be proven offline at all; see Checks.

## What changed

- **A lease belongs to a conversation, not to one update.** `claim()` now reads
  the conversation from the row that woke the worker and takes *that
  conversation's* oldest unfinished update, refusing while another of its
  updates is still running. The worker started for the second message of a burst
  therefore finds nothing to take and exits, instead of answering ahead of the
  first.
- **The claim's exclusion is a lock, not a check.** Two workers holding
  different updates of one conversation both find nothing running and both
  proceed, because they lock different rows and never meet. A per-conversation
  advisory lock, taken in the same transaction as the claim, is what makes them
  meet. Its identifier is computed in Python from the key rather than by
  `hashtext()`, so the behaviour does not depend on a server function that is
  not part of the SQL contract.
- **The conversation is the person, and the front door names it.**
  `canonical_user_id` moved from `adapter.py` to `wire.py` — which the webhook
  already imports and which may import nothing but the standard library — so the
  key is written by the insert that already happens, with no extra query and no
  agent import on the cold path. Which thread a message lands in is the worker's
  first store read; a person is in exactly one conversation at a time, so
  serializing them serializes it. This also closes the check-then-act in
  `current_thread` that let two workers meeting a new user create two threads.
- **The worker drains its conversation.** After completing an update it takes
  the next one, so a burst is answered in order by one warm container. Past
  `DRAIN_SECONDS` (240 s) it hands the rest to a fresh worker rather than gamble
  on its own 600 s timeout with a turn that may spend 300 s.
- **The migration is additive.** A nullable `conversation_key` column and an
  index over `(conversation_key, state, update_id)`, both `IF NOT EXISTS`, in
  the setup tool that already owns deployed migrations. No row is rewritten or
  dropped. A row queued before the column existed has no key and is claimed on
  its own, exactly as it was accepted — so an update in flight across the deploy
  is still answered.

## What it does not do

- **No coalescing.** An image and the question after it are still two turns.
  Merging them changes what a turn *is*, and every number recorded in item 3
  counts turns — one update, one `run_id`, one row. It needs its own decision.
- **No change to the local profile.** `ui/telegram/run.py` already serializes a
  chat with an in-process lock. The two profiles now make the same promise by
  different means, which is the point of putting the deployed one in the
  database both share.
- **No stopgap.** `max_containers=1` was considered and is not needed: it would
  serialize every person against every other, and the real lease is here.

## Checks

Offline suite: **778 passed, 11 skipped** (`.venv\Scripts\python.exe -m pytest
tests/ -q`), up from 771 passed and 1 skipped.

**The ten new skips are the honest part of this report.** The rules above live
in one `UPDATE` statement and an advisory lock, and this project's own position
is that a store which passes against a stand-in has demonstrated nothing about
the database it will run on. So `tests/test_update_inbox_contract.py` is written
against PostgreSQL itself and skips without `AGENT_TEST_DATABASE_URL`, which is
not set here. It asserts: one conversation runs one update at a time; the oldest
is answered first whichever spawn won the race; a finished update still names
its conversation, which is how a hand-off finds the rest of it; two people do not
wait for each other; an expired lease is reclaimable, because nothing else
releases the lease of a container that died; a failed turn returns to the queue;
a row without a key is answered alone; a redelivered update keeps one identity;
a claimed update is not spawned twice; and running the migration again on a
populated table changes nothing.

Offline, seven new tests in `tests/test_telegram_webhook.py` drive the real
worker against a queue fake that holds the same two rules: a second message
waits instead of racing; a worker answers the oldest message first whichever id
woke it; two people do not block each other; a long burst is handed to a fresh
worker with the remainder still queued; a hand-off with nobody to spawn leaves
the update queued rather than losing it; an update queued before conversations
existed is still answered; and the front door names the conversation it queues.

Three fake queues across the test suite became one shared `QueuedInbox` in
`tests/fakes.py`. That merge found a real inaccuracy: two of them reported a
redelivered but unclaimed update as needing no worker, while the real queue asks
for one — deliberately, since the only reason to see a pending row twice is that
nobody answered it. A test had been written against that fiction and now asserts
the true behaviour.

Not run: `ruff` (configured in `pyproject.toml`, not installed here), and the
PostgreSQL contract suite above.

## Files

New: `tests/test_update_inbox_contract.py`.

Changed: `ui/telegram/inbox.py`, `ui/telegram/webhook.py`, `ui/telegram/wire.py`,
`ui/telegram/adapter.py`, `ui/telegram/__init__.py`,
`deploy/modal/control_app.py`, `tests/fakes.py`,
`tests/test_telegram_webhook.py`, `tests/test_turn_telemetry.py`,
`docs/PROJECT_MAP.md`, `docs/CODEMAP.md`, `docs/OPERATIONS_MAP.md`.

`docs/PRODUCT.md` is unchanged: being answered in order is what the product
already promised.

While editing `docs/PROJECT_MAP.md` a stale line was corrected in passing — it
still said the run inspector did not exist, which item 3 closed.

## Migrated and deployed, 2026-08-30

Both on the human's explicit permission, live acceptance deliberately left to
them.

**Migration.** `tools/setup_control_plane.py` against the deployed Neon
database, exit 0. Confirmed by reading the catalogue back: `telegram_updates`
now has `attempts, conversation_key, created_at, last_error, lease_token,
lease_until, payload, run_id, state, update_id, updated_at` and the indexes
`telegram_updates_conversation` and `telegram_updates_pkey`.

**The claim SQL was planned before it was deployed.** Deploying a statement that
has never reached a server is how a syntax error becomes a bot that stops
answering, and the contract suite that would have caught it needs a database
this environment does not have. `EXPLAIN` without `ANALYZE` plans a statement
and does not execute it, so both claim paths were planned against the real
table — with the SQL taken from the real code by driving `claim()` and
`claim_next()` against a recording stub, so this could not pass against a
statement the application does not actually send. Both planned:

```text
SELECT conversation_key FROM "assistant"."telegram_updates"
  -> Index Scan using telegram_updates_pkey  (cost=0.14..8.16 rows=1 width=32)
UPDATE "assistant"."telegram_updates" SET state = 'running', ...
  -> Update on telegram_updates            (cost=16.49..24.52 rows=1 width=90)
```

Nothing was written by this. It proves the statements are valid against the
real schema; it does not prove the exclusion or the ordering, which only the
contract suite or the live check can.

**Deploy.** `assistant-control` in 21.3 s, five functions re-created. No GPU was
touched.

## What is owed before this can be called done

**Live acceptance**: two messages sent seconds apart, answered in order, with
`tools/show_run.py` showing two runs on one thread whose intervals do not
overlap. The human runs it; this wakes a GPU and is their own permission to
spend.

Until then the ordering guarantee is deployed but unproven in the product.
