# V2 control plane — the PostgreSQL conversation store

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** the second `ConversationStore` implementation is written and wired.
**No SQL has ever been executed.** No database, no container, no connection, no
worker of any kind was started. The contract is green for SQLite only.

## Why a second implementation at all

The deployed profile has no shared disk. Workers are separate processes on
separate machines, scaled to zero between messages, so the SQLite file that
serves the local profile perfectly cannot serve them at all. `ConversationStore`
existed from step 1 precisely so this could arrive as a second implementation
rather than as a rewrite.

## Decisions the human made

- **Neon** for the deployed database.
- **`PostgresStore` stays provider-agnostic.** Pooling, TLS and reconnect
  behaviour are connection configuration, not code. The word "Neon" appears in
  `app/config.py` and in this report, and nowhere in the store.
- **Neon's pooled endpoint** for Modal workers. A fleet that scales to zero
  opens and drops connections in bursts; a direct endpoint exhausts them long
  before the database runs out of capacity.
- **SQLite stays the local backend.** Not a fallback and not a legacy path — a
  personal machine has one process and a disk under it.
- **Starting a local PostgreSQL container counts as starting a worker**, so it
  needs explicit permission every time. That is why nothing here was run.

## What was built

| File | What it is |
|---|---|
| `app/memory/postgres.py` | the implementation |
| `app/memory/records.py` | message encoding, moved out of the SQLite store |
| `app/memory/open.py` | the one place that picks an implementation |
| `app/config.py` | `AGENT_DATABASE_URL`, `AGENT_DATABASE_SCHEMA` |
| `tests/test_store_contract.py` | postgres joins the suite when a DSN exists |
| `tests/test_store_selection.py` | the choice is configuration and nothing else |

### Search is not a translation of the SQLite one

SQLite uses FTS5; PostgreSQL uses `tsvector` with a GIN index and a generated
column, so there are no triggers to keep in step. The text-search configuration
is `simple`, which does not stem. That is the deliberate match for FTS5's
default behaviour, and it is also the answer for a Russian-speaking user: an
English stemmer would make the deployed assistant search *worse* than the local
one it replaces.

### Reconnection is not a Neon feature

A networked database hangs up on an idle client, and this assistant is idle by
design between messages, so reconnecting is the normal path after a pause rather
than an error path. A connection that dies mid-statement is *not* retried: the
caller's statements would have to be replayed, and the store cannot know whether
that is safe. It is dropped, and the next call opens a new one.

### Schemas

`PostgresStore(dsn, schema=...)` keeps the application's tables together in a
database that may hold other things, and gives each contract test a namespace of
its own. `drop_schema` refuses `public` outright: the default schema is where a
real deployment's conversations live, and a method that can delete them by being
called with default arguments is a method that eventually will be.

### The test DSN is a separate variable

The contract suite reads `AGENT_TEST_DATABASE_URL`, never `AGENT_DATABASE_URL`.
Running the tests must not be able to reach the deployed database by accident,
and a shared variable is exactly how that accident happens.

## Checks

- `uv run python -m pytest -q` — **442 passed**, no skips;
- `ruff check app tests deploy` — clean apart from the pre-existing `F401` in
  `app/agent/task_graph.py`;
- the module imports with the driver installed, and `PostgresStore` has no
  abstract methods left, so the contract is implemented rather than partly
  implemented;
- `match_query` checked on punctuation-only input.

None of that executes a statement. The offline suite exercises SQLite and the
selection logic; the PostgreSQL rows in the contract table are unproven.

## What the first live run has to settle

Three things are relied on and not verified. They are named here so the first
run checks them deliberately rather than discovering them as a stack trace:

1. **Multi-statement `execute`.** `SCHEMA` is applied in one call. psycopg 3
   permits that only when no parameters are passed, which is the case — but it
   has not been observed.
2. **The generated column.** `to_tsvector('simple', text)` uses `text` as a
   column name in a position where it is also a type name.
3. **`SET search_path` after a reconnect.** It is issued and committed in
   `_open`, so it must survive on a connection that replaced a dropped one.

## Cost and state

Zero. Nothing was deployed, connected to, or woken. The only external action was
downloading `psycopg[binary]` from PyPI into the local environment, so that the
module could be imported at all.

## Not done

- The contract suite against a real PostgreSQL. Needs either a Neon DSN in
  `AGENT_TEST_DATABASE_URL` or explicit permission for a local container.
- The rest of the control plane: the LangGraph checkpointer on the same
  database, the validate-persist-spawn webhook with the agent loop in a separate
  worker, file tools over an ephemeral sandbox, and the application-level
  Telegram secret-token and allow-list checks.
