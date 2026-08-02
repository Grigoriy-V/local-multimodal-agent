# Version 1.5 step 5 — Chainlit product surface

**Date:** 2026-08-02  
**Result:** closed

## Product result

Chainlit remains an adapter over the general harness. A normal work request now
shows the model-created plan, workspace scope and required capabilities before
approval. After approval, native steps report committed graph progress through
implementation, validation, evaluation, repair when needed and finalization.
The final answer includes collected image evidence and downloadable files that
exist inside the granted workspace.

The native stop control persists a stopped task outcome and revokes its grant,
so an interrupted task is not silently resumed. Native sidebar deletion now
removes the canonical conversation plus both conversation and task checkpoints;
separately approved account-level facts are preserved with deleted provenance
cleared.

## Automated evidence

- Full offline regression: `321 passed in 7.50s`.
- Focused adapter/runtime/history regression during implementation: `64 passed`.
- Python compilation for `app/` and `ui/`: passed.
- `git diff --check`: passed.

Coverage added for committed lifecycle progress, pending and active-task
cancellation, grant revocation, conversation/checkpoint deletion, preservation
of approved memory, progress rendering and safe in-scope artifact attachment.

## Actual application check

The already running local model endpoint was used; it was not restarted. The UI
was restarted on port 8100 after the implementation changed.

1. An ordinary request created `step5-ui-smoke.html` from an absolute path and
   requested visual validation. The generated plan selected filesystem and
   browser capabilities. The task completed in one iteration with 7 tool calls
   and 3/3 criteria passed; Chainlit showed the plan, progress and screenshot.
2. A second ordinary request edited the same file to display `STEP 5 OK`. It
   completed in one iteration with 6 tool calls and 2/2 criteria passed. The UI
   showed browser evidence and a working `step5-ui-smoke.html` download link.
3. A third ordinary task was stopped with Chainlit's native stop control. The
   final state was `stopped`, the reason was `cancelled by user`, and the state
   remained stopped after a browser reload.
4. The exact temporary test chat was deleted through the native sidebar menu.
   It disappeared from the list, the UI remained healthy and the server log had
   no `Internal Server Error` or deletion exception.

The first artifact rendering attempt exposed a frontend error because Chainlit
received an HTML file without a MIME type and dereferenced it as a string. The
adapter now always supplies the guessed MIME type or
`application/octet-stream`; the second live run verified the correction.

A final database audit also caught Chainlit emitting a metadata update after
the deletion callback, which recreated an empty phantom thread. Metadata-only
updates no longer create canonical conversations; a focused callback-sequence
test and a check against the real SQLite files confirmed that the thread and
both checkpoint identities remain absent.

All generated smoke HTML files and screenshots were removed after the check.
No existing user chat or artifact was deleted.

## Limits and cost

The live progress steps are transient UI telemetry; the canonical reopened
conversation retains the final result, checks and image evidence rather than a
second copy of every progress update. Downloadable artifact elements are shown
on the live completion; the canonical transcript still records their paths.

There was no external provider call or monetary cost. Local inference used the
already running vLLM/GPU service. Per-request latency and VRAM were not measured
in this step. The UI remains running at `http://127.0.0.1:8100` (PID 41328).
