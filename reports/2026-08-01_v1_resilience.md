# Version 1 tool and context resilience

**Date:** 2026-08-01

## Result

Expected tool failures now stay inside the tool loop. Unknown tools, refused
paths, bad arguments, declared `ToolError`s and operating-system I/O failures
become readable `tool` messages carrying the original call id. Programming
errors outside those expected categories still propagate rather than being
misreported as user-correctable failures.

Context overflow is now a model-backend-level typed condition. The
OpenAI-compatible adapter classifies the common 400/413/422 overflow responses;
the provider-independent graph reacts by forcing a rolling-summary fold,
rebuilding context, and retrying the original model request exactly once. If
nothing can be folded, the summary itself overflows, or the retry still does not
fit, the turn ends with a readable assistant refusal which is persisted with
the user's input.

## Evidence

- `.venv\Scripts\python.exe -m pytest -q`: `213 passed in 3.97s`.
- `.venv\Scripts\python.exe -m compileall -q app ui tests`: passed.
- `git diff --check`: passed.
- Focused tests cover an `OSError` through the complete tool loop, successful
  fold and retry, overflow on the sole input, overflow on the retry, and
  overflow while generating the summary.
- Generic HTTP 400 errors remain ordinary `BackendError`s; only recognized
  context failures become `ContextOverflowError`.
- Chainlit was restarted successfully and listened on `127.0.0.1:8100` as PID
  `11932`.

## Limitations

This step was verified offline. The local model endpoint was not running, so a
real vLLM overflow and the final browser/restart product smoke remain the last
Version 1 acceptance gate. Overflow recognition intentionally uses a narrow set
of common provider messages; a future backend with different wording must map
its own response to `ContextOverflowError`.

There is still no preflight tokenizer inside the application. This is
deliberate: model tokenization remains behind `ModelBackend`, and Version 1 uses
the server's exact response plus one bounded recovery rather than adding a
provider tokenizer dependency.

## External actions and cost

Chainlit was restarted locally. No model request, GPU work, download, database
migration, provider call or destructive external action occurred. External cost
and VRAM use were zero.
