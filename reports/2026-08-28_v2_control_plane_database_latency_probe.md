# Control-plane database latency probe

**Date:** 2026-08-28  
**Scope:** offline implementation, corrected CPU control-plane deployment and packaging runtime evidence; no database probe

## Result

The production context-loading path and the database latency acceptance now
share one application-level operation, `load_turn_context`. It includes the
rolling-summary read, recent-message read and fact retrieval. The production
graph and `Agent.context_prompt` both call this boundary, so the probe cannot
pass by timing a smaller, benchmark-only query.

The CPU-only Modal probe supports three deliberately separate invocations:

1. `prepare` creates an isolated representative fixture with one summary,
   eight recent messages and five matching durable facts;
2. `read` measures store construction/connection plus the complete context
   read, then five complete warm reads and judges the maximum;
3. `write` measures store construction/connection plus a complete two-message
   turn append, then five complete warm appends and judges the maximum.

Every first sample includes `open_store`, including every connection and SQL
round-trip the current implementation performs. Warm acceptance uses the
maximum observed sample, not an average or percentile. The limits are encoded
as **cold <=500 ms** and **warm max <=100 ms**. The read refuses to report a
result unless the representative fixture has the expected shape. Temporary
write threads are removed after the measurement; the isolated read fixture is
retained until explicit cleanup.

The control functions deliberately use Modal's default unpinned placement, so
no compute-region price multiplier is requested. The probe records the actual
`MODAL_REGION` with every result. The latency limits apply to that real
production placement: a remote placement is not excluded from the result and a
miss is not hidden by selecting a more favorable sample.

## Checks

- Targeted context, graph, agent-session and Modal adapter tests:
  **63 passed in 1.70 s**.
- Full offline regression after the final code: **461 passed, 1 skipped in
  16.52 s**. The skipped test is the opt-in live database acceptance.
- Ruff over every touched Python file: passed.
- `git diff --check`: passed, apart from Git's existing CRLF conversion notice.

## External actions, cost and limits

The Modal Secret `assistant-control` was created from 10 allow-listed runtime
keys. `AGENT_TEST_DATABASE_URL` and unrelated `.env` values were not copied.
The secret values were not printed or written into the repository.

The `assistant-control` app was successfully deployed after the human ran the
UTF-8-enabled Modal client command. Modal reported **6.748 s** and published
`process_telegram_update`, `measure_database_latency`, and the
`telegram_webhook` endpoint. Opening the endpoint in a browser then generated a
`GET /favicon.ico`. Modal repeatedly started CPU containers, but every start
failed before application code with `ModuleNotFoundError: No module named
'control_app'`: `include_source=False` was correct for excluding unrelated
repository content, but the allow-listed image inputs omitted the deployment
module itself. The corrected image now copies exactly that file to
`/root/project/control_app.py` and was deployed in **13.254 s**.

The old queued favicon call survived the redeploy and started one corrected CPU
container. It returned the expected 404 instead of crashing: the first request
had 9.83 s total duration and 29.8 ms execution, and a second request on the
same container had 66.0 ms total duration and 19.5 ms execution. This confirms
module packaging only; it is not database latency evidence.

No Telegram update, database operation, model request or GPU worker reached
application code. VRAM use was **0**. Deployment and failed CPU-start cost was
not measured. No latency result exists, so the database performance gate
remains open.

The separately authorized CPU-only `prepare` invocation subsequently returned
`{"operation": "prepare", "fixture": "ready"}`. The representative Neon
fixture is ready and the Modal app returned to zero active tasks. This write is
setup evidence only: it is not a latency sample and it made Neon warm, so the
first read must wait for confirmed database scale-to-zero.

The first authorized deploy attempt built two small intermediate image layers
and then stopped before publication: `uv_sync` had incorrectly been given a
remote Linux path even though its argument is a local project path. On Windows
that became `/root/project\\pyproject.toml`. The image definition now passes
`.`; `uv_sync` uploads only the local `pyproject.toml` and `uv.lock` itself.
No application Function was invoked. A retry is a new worker/deploy gate.

The second authorized attempt was terminated by the local command wrapper's
10-second timeout while Modal was still building. A read-only App listing
showed the new `assistant-control` attempt as `stopped` with zero tasks. This is
not a deployment result and no application Function was invoked. The next
attempt must use a command timeout long enough for the image build and remains
a separate deploy gate.

The third authorized attempt built the corrected image layers, then the local
Windows Modal client failed while encoding its Unicode checkmark through the
system `charmap` codec. The resulting App attempt is again `stopped` with zero
tasks. The next command must set `PYTHONUTF8=1` for the client process; this does
not alter the image or runtime configuration and remains a separate deploy
gate.

## Remaining acceptance sequence

Each item starts a distinct CPU worker and therefore needs fresh explicit
permission immediately before it runs:

1. deploy the optimized control image without invoking a function;
2. invoke one warm `read` to validate the SQL and warm budget;
3. after Neon has scaled to zero, invoke `read` once for cold acceptance;
4. after Neon has scaled to zero again, invoke `write` once.

The first sample may be called database-cold only when Neon, not merely the
Modal Function, was idle. If either operation misses either limit, the control
plane stays open and the measured call sequence must be optimized before a
retry.

## First warm result and correction

The first deployed read ran in Modal region `eu-south-2` and returned the
expected shape (eight history messages and three prelude entries), but failed
the performance gate:

- first sample: **2421.686 ms**; not accepted as a database-cold result because
  Neon had just been prepared;
- warm samples: **749.049, 640.399, 648.692, 641.838, 961.732 ms**;
- warm maximum: **961.732 ms**, versus the **100 ms** limit.

Neon's query-performance view showed individual server execution at only
**0.1-6.7 ms**, while also showing repeated `CREATE SCHEMA`, `CREATE TABLE`,
`CREATE INDEX` and schema-version queries. The miss is therefore dominated by
application-generated network round-trips, not database execution.

The correction is written and offline-verified but not deployed:

- ordinary `PostgresStore` opening no longer runs migrations; only the explicit
  control-plane setup path requests them;
- `turn_context` is a production persistence boundary. SQLite retains the
  simple composed implementation, while PostgreSQL returns summary,
  unsummarized messages and matching facts in one schema-qualified SQL execute
  without a separate `SET LOCAL`;
- PostgreSQL append materializes the complete turn into one schema-qualified
  SQL execute and pipelines its commit instead of serializing thread creation,
  position lookup, message inserts and the thread update across the network.

Offline verification after the correction: targeted persistence/control tests
**30 passed in 0.92 s**; final full regression **465 passed, 1 skipped in
12.92 s**; scoped Ruff and `git diff --check` passed (apart from Git's CRLF
conversion notice). A broader Ruff invocation also inspected unrelated files
and found a pre-existing unused `field` import in `app/agent/task_graph.py`; it
was not changed as part of this database correction.

## Second warm result: the code stopped being the bottleneck

The corrected image was deployed in **19.086 s** with zero tasks started, and
one authorized warm `read` was then invoked in region `eu-south-2`. The
representative shape was returned as expected.

| | before | after |
|---|---|---|
| warm samples (ms) | 749.0, 640.4, 648.7, 641.8, 961.7 | 109.8, 109.5, 109.4, 109.4, **218.0** |
| warm max (ms) | 961.7 | 218.0 |
| cold (ms) | 2421.7 | 1009.0 |

Four of the five warm samples land within **0.4 ms of each other at 109.4 ms**.
That is not a measurement of this application any more. Neon is in AWS
**us-east-2 (Ohio)** and the worker ran in **eu-south-2 (Spain)**; server
execution for the whole workload is about 5 ms, so 109 ms is one trans-Atlantic
round trip and essentially nothing else. The read is now a single round trip, as
the correction intended — an **8.8x** improvement on the warm maximum.

**The gate still fails, and no code change can pass it.** The limit is 100 ms
and the floor imposed by geography is 109 ms. Nine milliseconds of that gap is
distance, not software.

Two questions remain open, and only the first is about this repository:

1. **The fifth sample at 218.0 ms is almost exactly two round trips.** Something
   occasionally costs a second one — a pooler-dropped connection, a reconnect,
   or a stray statement. Acceptance uses the maximum, so this alone fails the
   gate even at a distance where the median would pass. It needs identifying
   before placement is blamed for it.
2. **Placement.** With both ends on one continent the same read is roughly
   5-30 ms and the budget is comfortable. The current split is the only
   arrangement that cannot pass. The human deferred this decision until the
   engineering was settled; it now is.

The cold sample of 1009.0 ms is not accepted as database-cold: Neon's idleness
before the call was not confirmed. At 109 ms per round trip a TLS handshake and
authentication alone account for several hundred milliseconds of it.

## The A/B, and why it reversed the conclusion

A second Neon project was created in **eu-central-1 (Frankfurt)** and given the
same schema through the same migration. The probe gained a `compare` operation
that measures both databases **inside one invocation**, because placement is
unpinned: measured in two calls, the difference between the results would have
included the difference between the workers, which is the variable being
controlled for. A DSN is never an argument — it would land in the platform's
call records — so the choice is a name and the values stay in the secret.

The container landed in **us-east-2** this time, not `eu-south-2`.

| | database | warm samples (ms) | warm max |
|---|---|---|---|
| primary | Neon **us-east-2** | 2.764, 2.677, 2.243, 2.120, 3.442 | **3.442** |
| alternate | Neon **eu-central-1** | 98.796, 98.699, 99.038, 98.877, 196.902 | 196.902 |

Cold: **111.8 ms** primary, **707.6 ms** alternate. Both read the expected shape.

**Co-located, the gate passes with room to spare.** 3.4 ms against a 100 ms
limit is not a pass by inches; it is thirty times under. The same database that
answered in 109 ms from Spain answers in 2.5 ms from Ohio.

**So the database is not in the wrong place — the worker is in an unpredictable
one.** Two invocations of the same deployed function landed on two continents.
That variance, not the database's address, is what the first measurement was
actually recording.

**Moving the database to Europe would have been the wrong move, and this run is
what prevented it.** Had the primary been migrated to Frankfurt on the strength
of the `eu-south-2` reading, this container would have measured 98.7-196.9 ms
instead of 2.1-3.4 ms — a gate failure produced by the fix. The experiment cost
one free Neon project and a few seconds of CPU.

### What actually closes the gate

Pin the control functions to the region the database is in. The functions
currently use Modal's default unpinned placement, chosen to avoid a region price
multiplier; that trade was made before there was a number, and the number is
**40x on every database round trip**. The multiplier for the US region the
database already sits in should be checked before assuming it costs anything.

### The outlier is one extra round trip, now confirmed

The fifth sample was anomalous in both databases at once: 196.902 ms against a
98.8 ms baseline, and 3.442 ms against a 2.4 ms one. Doubling on the slow path
and a fixed ~1 ms on the fast path is the signature of exactly one additional
round trip, not of variance. It reproduces on the fifth sample of five across
three separate runs, so it is periodic rather than random — a pooler recycling
the connection is the first thing to look at. Co-located it costs a millisecond
and cannot fail the gate; it should still be identified before acceptance.
