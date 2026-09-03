# 4.5 Tool system — implementation, 2026-09-03

Direct Claude session, on the human's explicit start signal ("Тогда начинай
реализацию"). Contract: `docs/v2_tool_system.md`. Decision: `DECISIONS.md`
2026-09-03. This report is the evidence for the roadmap's "implemented offline";
nothing here was observed live.

## What was built, in the contract's migration order

1. **Types and executor.** `ToolFailure(code, message, detail)` and
   `ToolCall.raw_arguments` in `app/models/base.py`; `Message.failure`, tool
   messages only, in `CHECKPOINT_TYPES`. `ToolError(message, code, detail)`,
   `ToolOutcome`, the runtime codes, `requires_approval` (was `destructive`),
   `timeout_seconds`, allowlisted name resolution and schema coercion in
   `app/tools/base.py`. `ToolExecutor` in `app/tools/execution.py` owns the
   three stages: resolve → read → coerce → validate → policy; run under the
   timeout with `ToolError` → typed, `Exception` → `internal` with the
   traceback logged, `BaseException` propagating; bound (head, marker, tail
   past 32 000 characters; at most 4 images, 16 MB), sanitize (first line, no
   fence, no role or tool token, no served delimiter, 400 characters), record
   `code` and `message` on `tool_failed`, project `error: <message>
   (<detail>)` plus the signature after `bad_arguments`. `Toolbox.run` and
   `run_async` are conveniences over the executor; there is one lifecycle.
   Every consumer of the prefix now asks `message.failure`: the graph's repeat
   guard, `declined` and `halted`, the plan reader, `/check`, the Chainlit
   step. Chainlit's stored-history view keeps the text projection until the
   failure column lands with schema 3 (4.6a), as the contract says.
2. **Model boundary.** `parse_arguments` (raised `BackendError`) became
   `read_arguments` and `tool_call`: arguments that are not a JSON object are
   delivered with the text kept, and the executor refuses the call as
   `bad_arguments`. The fragment removal of 2026-08-31 is unchanged.
3. **Filesystem.** `fs.outside_root`, `fs.not_found`, `fs.not_a_file`,
   `fs.not_a_directory`, `fs.is_directory`, `fs.blocked_by_file`,
   `fs.ambiguous_edit`, `fs.too_large`, `fs.io`; `strerror` as detail, never a
   resolved absolute path; `write_file` atomic through the same temp-fsync-
   replace as `edit_file`. `not_found` is new: a missing file used to be
   "not a file".
4. **Documents, presentation, memory, todo, web, browser.** `doc.unsupported`,
   `doc.unreadable`; `presentation.empty`; `memory.invalid`; `todo.invalid`;
   `web.refused`, `web.unreachable`, `web.no_provider` carried on `WebError`
   from `app/web.py` into the tool; `browser.unavailable`,
   `browser.load_failed`. No behaviour change beyond the code and, for
   path-taking tools, the `not_found` distinction.
5. **`ERROR_PREFIX`** is gone as a name. The wording lives in
   `execution.ERROR_WORD` and nothing reads it back.

Not done, and not planned in this step: promotion of a plain-text tool call, a
per-key argument repairer, output schemas, read-before-edit, any change to the
loop's repeat guard. `LEGACY_NAMES` is an empty table because the roadmap has
renamed no tool.

## Choices the contract left to the implementation

- **Timeout on a synchronous tool** runs the body in a worker thread under
  `asyncio.wait_for`; without a timeout it runs on the loop as before. A thread
  keeps running after the deadline; the turn does not. No current tool sets a
  timeout: the values are to be set from measurement, which needs live runs.
- **`TypeError` at the call** (a schema the callable does not agree with) is
  told apart from one raised inside the tool by binding the arguments to the
  signature before calling; the first is `bad_arguments`, the second is
  `internal`.
- **The internal detail** prefers `strerror` over `str(error)`, so an OS error
  reads `PermissionError (permission denied)` and not `[Errno 13] …`.
- **Caps**: 32 000 characters with a 2 000-character tail, 4 images, 16 MB.
  Every current tool's own limit is below them, so they change nothing today.

## Checks

| check | result |
| --- | --- |
| `pytest` offline suite | 943 passed, 27 skipped, 46 s |
| new `tests/test_tool_outcomes.py` | 39 tests: ISS-0001 shape through the graph, unknown/resolved/near-miss names, coercion, internal with traceback in the log, async and sync timeouts, `BaseException` propagating, declined/halted codes, bounds, sanitizing, checkpoint round-trip, one test per family, `tool_failed` reason, `show_run` output |
| `ruff check` on the changed files | clean; the tree's 20 pre-existing findings are unchanged |
| `scripts/loop_live.py` A–E, live on `assistant-llm-v2` | all scenarios passed on the second run; see below |
| deployed `/check` | 9/9 passed, run by the human in Telegram after the live loop run; reported, not observed here |

Tests changed with the contract, each for a stated reason: an unreadable
argument is delivered rather than raised (`test_openai_compatible`); an
unexpected exception is an `internal` result rather than a propagated error
(`test_tools`, `test_agent_graph`); a failing edit's atomic replace is `fs.io`
rather than a raw `PermissionError`; a missing file is `not_found`;
`destructive=True` is `requires_approval=True`.

## Live run, 2026-09-03

Two runs of `scripts/loop_live.py` with the human's permission for each, on the
deployed A10. The script was rewritten first: every scenario is now checked
and the exit code is the number of failed checks; the old docstring's claim
that `write_file` stops for approval was wrong since 2026-08-01 and is gone.

**Run 1** — A to D passed. E, written as "read `missing.txt`", did not
exercise a failure: the model listed the workspace, saw the file was absent
and answered "I cannot find the file" without calling `read_file`. That is the
product behaviour ISS-0004 asks for, and useless as a tool-failure test.
E was rewritten around `edit_file` on a word that occurs twice, which a
listing cannot reveal.

**Run 2** — all five passed. Scenario E: `edit_file` refused as
`fs.ambiguous_edit`, the model answered in one more call explaining exactly
that, no repeat, and `show_run live-50` prints under the call:

```text
   1  edit_file [execute]            0.00s  failed          fruit.txt
        fs.ambiguous_edit: old_text must occur exactly once in 'fruit.txt'; found 2 matches
```

Scenario D showed the projection live too: the `write_file` halted by the stop
reached the loop as `not_run`.

| run 2 | value |
| --- | --- |
| turns | 5, all successful |
| wall time of the five turns | 28 s, warm |
| GPU active per turn, derived upper bound | 14.8 s |
| derived cost for the window | $0.023 |
| model calls / tool calls per turn | 2.4 / 1.4 |

Telemetry files are under the temporary directories the script names
(`loop-live-010ht601`, `loop-live-0lsvf46l`); nothing was written to the
deployed database.

**Observed, not in scope:** a call the loop halts for a stop or a budget is
not in the telemetry at all — `show_run live-40` lists two tool calls where
the turn had three, and only `turn_stopped` says why. A declined call does get
a `tool_failed` event. Worth an `ISSUES.md` entry if it costs a diagnosis.

## Effect on the issue list

ISS-0007 fixed and seen live (run 2, scenario E); ISS-0005 extended to every
family and every escaping exception, the `fs.*` code seen live; ISS-0001
mitigation now includes the runtime surviving the corrupted call, which no live
run has produced since.

## Cost and external actions

Two runs of `scripts/loop_live.py`, each permitted separately, woke the
deployed model; derived cost about $0.02 each plus the wake. Nothing was
committed or pushed.

## Next gate

None for 4.5: the step is closed. The deployed `/check` ran the tools through
the new executor on the mounted volume and passed 9/9, per the human. Next in
the queue is 4.5.5, the browser capability, which needs its own approval.
