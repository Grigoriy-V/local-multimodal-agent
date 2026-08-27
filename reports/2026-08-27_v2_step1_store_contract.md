# Version 2 step 1 — persistence contract and user scope

**Date:** 2026-08-27, completed 2026-08-28
**Result:** closed. Implemented offline, then the human waived preservation of
the populated local database, which was migrated and checked through the running
application.

## What changed

`MemoryStore` was one concrete SQLite class used directly as a type throughout
the application. It is now a contract with one implementation.

- `app/memory/base.py` (new) — `ConversationStore`, the `Thread` record and
  `LOCAL_USER_ID`. Every operation that can reach across conversations —
  `threads`, `remember`, `search`, `facts` — takes the owning user explicitly
  and has no default. Thread-keyed operations do not repeat the user, because a
  thread has exactly one owner from creation; `thread_owner` is the check a
  caller uses on a thread it was handed.
- `app/memory/store.py` — `MemoryStore` became `SqliteStore(ConversationStore)`
  with `user_id` on `threads` and `facts`, indexes on both, and `search` scoped
  by owner inside the FTS join.
- Schema versioning via `PRAGMA user_version`, at `SCHEMA_VERSION = 1`. Opening
  a version 0 file adds the owner columns and hands every existing row to
  `LOCAL_USER_ID`.
- `set_summary` now raises `KeyError` for an unknown thread instead of silently
  creating an ownerless one.
- `Agent` carries `user_id` (defaulting to `LOCAL_USER_ID`), passes it to
  `build_agent` and `memory_tools`, and scopes its own `threads`, `search` and
  `append`. `create_agent` takes `user_id` so the deployed profile sets it in
  one place.
- Annotations across `app/` and `ui/` now name `ConversationStore`; only
  construction sites name `SqliteStore`. That split is the seam a second
  implementation plugs into.

## Checks

- Full offline suite: **340 passed in 8.69s** (321 before; 19 new). No network,
  no model endpoint, temporary databases only.
- `tests/test_store_contract.py` (new, 13 tests) is parameterised over
  implementations through `STORE_FACTORIES`. Adding the deployed
  implementation there is what makes it answerable to the same contract.
  It fixes where fact sharing stops: shared across one user's conversations,
  never across users, including when the text matches.
- `tests/test_store_migration.py` (new, 6 tests) builds a literal version 0
  database, opens it and asserts the backfill, preserved messages and
  summaries, the recorded version, and that reopening is idempotent.
- `ruff check` on every touched file: clean. One pre-existing unused import in
  `ui/chainlit_history.py` was removed by `--fix` as it re-sorted that block.
- Wiring smoke, offline: two `Agent`s with different `user_id` over one database
  file each saw only their own thread, and a fact saved by one was invisible to
  the other's search.

## Migration rehearsed on real data, original untouched

`data/memory.sqlite3` holds 3 threads, 8 messages and 1 fact at
`user_version = 0`. A **copy** was migrated in the scratchpad: all 3 threads,
all 8 messages and the fact came back under `LOCAL_USER_ID`, Russian text
intact, and a different user id returned nothing.

The original file was not opened by the new code. Migrating a populated
database is a human gate under `AGENTS.md`, and the migration runs
automatically on first open — so starting the application is what triggers it.

## The live database, migrated (2026-08-28)

The human waived preservation ("нечего терять"), so no backup was taken. The
migration adds columns and backfills; it deletes nothing, and nothing was lost:
`data/memory.sqlite3` went from `user_version` 0 to 1 with all 3 threads, 8
messages and 1 fact intact under `LOCAL_USER_ID`, and no row left without an
owner.

## Application check (2026-08-28)

Chainlit was started on port 8765 against the migrated database.

- The native history sidebar listed all three migrated conversations by their
  opening text — `расскажи сказку`, `привет`,
  `сделай html файл с игрой змейка` — which is the data layer reading through
  `threads(LOCAL_USER_ID)` and `thread_owner`, the two calls this step changed.
- Opening `/thread/4742b917…` rendered that conversation's full stored history,
  including the earlier Snake task result and its recorded 16,384-token failure.
  That is `messages(thread_id)` through the real UI.
- After shutdown the database was re-read: 3 threads, 8 messages, 1 fact, all
  owned by `local-user`, still at version 1.

A conversational turn was not attempted: it needs the model server, whose start
is a human gate in the local profile, and the store change does not require one
to be exercised.

## Not done

- Nothing was committed.

No external call, GPU work or monetary cost.
