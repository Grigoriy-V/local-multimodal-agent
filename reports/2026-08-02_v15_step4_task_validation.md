# Version 1.5 step 4 — task-derived validation

**Date:** 2026-08-02

## Outcome

The production task lifecycle no longer substitutes artifact existence for
semantic acceptance. The planner emits exactly one validation strategy item per
acceptance criterion. Each item names the evidence to collect and the minimum
read-only capabilities required. Those capabilities are included in the scoped
grant shown before `Run it`.

After implementation, a general model-driven validator selects concrete tool
calls, collects real filesystem or browser evidence, and a separate structured
evaluation call returns one verdict per criterion. Missing evidence stops the
task honestly. Failed criteria enter the existing bounded repair loop. There is
no task-type, filename, HTML or Snake branch in this flow.

## Checks

- Final offline suite: `314 passed` in 7.11 seconds with no warnings.
- Python compilation: `python -m compileall -q app ui` passed.
- Focused task/harness/UI suite: `64 passed` in 1.93 seconds.
- `git diff --check` is part of the final task check.

## Real app evidence

The existing local model endpoint reported `gemma-4-12b-it` with
`max_model_len=16384`. Chainlit was restarted on port 8100; the model server was
not restarted.

One ordinary request asked for
`D:\ML\local-multimodal-agent\workspace\step4-smoke.html` containing large blue
`STEP 4` text on a white background. Without a tool or validation algorithm in
the request, the model produced three criteria and selected:

- `filesystem.read` for existence and HTML structure;
- `browser.inspect` for rendered text, color and background.

The approval UI showed `filesystem.read`, `filesystem.write` and
`browser.inspect`. The single approved task completed in one iteration with five
tool calls. Its result showed three passed criterion verdicts and an inline
browser screenshot visibly containing blue `STEP 4` text on white. No separate
`show`, `preview`, mode selector or follow-up validation request was used.

The temporary HTML and browser screenshot were removed after the smoke check.

## Limitations

- Validation adds model calls for evidence collection and structured evaluation;
  exact latency and VRAM deltas were not measured in this step.
- Available evidence is currently limited to the registered filesystem-read and
  local-browser-inspection capabilities. A task that needs unavailable evidence
  stops rather than claiming completion.
- Honest two-scenario acceptance from empty sandboxes remains Version 1.5 step 6.
