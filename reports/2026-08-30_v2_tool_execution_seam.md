# Version 2 step 4.2 — tool execution seam

**Date:** 2026-08-30  
**Status:** done and accepted live

## Outcome

Every model-requested tool in the agent loop now travels through one
`pre_execute -> execute -> post_execute` lifecycle around the existing
`Toolbox`. The lifecycle owns validation, approval policy, execution and tool
telemetry while the graph retains only turn ordering, budget/stop checks and
the resumable pause needed when an approval is actually required.

Workspace `write_file` and `edit_file` are autonomous inside the already
confined per-user root. Explicit `send_file` presentation to the same person
remains autonomous. A tool declaring an external consequential effect still
pauses before anything in its batch runs; approval, decline, restart and the
no-checkpointer refusal path remain intact.

## Implementation

- `app/tools/execution.py` owns `ToolExecutor` and the prepared-call contract.
- `app/agent/graph.py` prepares the whole batch, pauses only for valid calls
  requiring approval, then executes each allowed call through the seam.
- `app/tools/base.py` exposes preparation and names the policy through
  `requires_approval`; the existing `destructive` field remains compatible as
  the declaration stored on a tool.
- Tool events include the tool name, `stage=execute`, duration, status and a
  `path` when the call has one. Other argument values are not recorded.
- `/can` and the model capability brief are still derived from the actual
  toolbox and now truthfully report that no current same-user tool asks first.

No sandbox or second execution backend was added. The seam is the boundary a
future sandbox backend can use without changing the loop or consent policy.

## Offline evidence

Focused lifecycle, graph, approval, capability and telemetry tests:

```text
99 passed in 2.94s
```

Full offline suite after the final correction:

```text
744 passed, 27 skipped in 40.00s
```

The skipped tests require optional/live dependencies or explicitly configured
external services; no model endpoint, network service, product worker, deploy
or GPU was called. External cost was zero.

## Remaining acceptance

The control plane was deployed on 2026-08-30 with:

```text
.venv\Scripts\modal.exe deploy deploy/modal/control_app.py
App deployed in 21.739s
```

Only `assistant-control` was deployed; the model App was not redeployed and no
GPU worker was started. The Telegram command menu was not republished because
its command set did not change.

## First live result and correction

The real Telegram test proved the 4.2 behavior. Run
`f46242b705d34fa59f90773719716f65` read and edited `test_file.txt` without an
approval, and both tool events reported `stage=execute`, path and success.

The same run exposed a separate streaming presentation defect. Its second model
step streamed text but finished with `tool_calls`; Telegram finalized that
intermediate narration at 6.81 s, then finalized the real answer after the edit
at 8.63 s. There was one update and one run, not duplicate webhook processing.

`TelegramAdapter._deliver` now treats any completion carrying tool calls as an
unfinished action even when it also carries text: it discards that preview,
shows the ordinary tool activity, and only finalizes a later completion that
actually answers. A regression test reproduces the exact `text + tool call`
shape and verifies that the intermediate preview and activity are deleted while
only the final answer is finalized.

```text
targeted streaming tests: 10 passed
complete Telegram adapter tests: 85 passed
```

The correction was redeployed to `assistant-control` on 2026-08-30 in 25.366 s.
The model App was not redeployed and no GPU worker was started. At that point
one live recheck remained before acceptance.

## Final live acceptance

The recheck passed in the real Telegram product. The three tool runs inspected
after redeploy were each one update, one completed run and one
`telegram_final_sent`:

```text
349598d96ce349e3bb1c94b9bfdfd230  read_file   success  test_file.txt
c3c22c2f102b4e748c781cc50786170b  edit_file   success  test_file.txt
04acb23870054c409a16a524b1735309  write_file  success  roadmap.md
```

The last run completed in 8.82 s with two model calls and one tool call. Its
tool event included `stage=execute`, path and success, and only the final model
completion produced `telegram_final_sent`. There was no approval request,
duplicate webhook processing or second answer. Together with the earlier live
run that exposed the defect and the exact offline regression, this closes 4.2.
