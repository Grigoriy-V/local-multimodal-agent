# Version 1 closing product smoke

**Date:** 2026-08-01

## Result

Version 1 passed its closing regression and restart smoke. Two non-destructive
product limitations were observed and deferred to Version 1.5: malformed tool
calls are confirmed before schema validation, and creation of a new chat can
leave an empty temporary sidebar thread beside the canonical persisted thread.
Neither observation lost or overwrote conversation data.

## Evidence

- Full offline suite: `213 passed in 4.10s`.
- Live model smoke: 9 of 9 checks passed in 2.7 seconds wall time: text, system
  prompt, streaming, one image, multiple images, WAV, FLAC, tool calling and
  structured JSON.
- Sum of measured model-call latencies: 2.232 seconds. First streaming content
  arrived after 0.04 seconds.
- Reported GPU state: 23,860 MiB used and 24,564 MiB reserved by the driver;
  this is not a peak-use measurement.
- Browser product smoke created a new conversation, received the exact response
  `V1-SMOKE-OK`, switched to an older stored conversation, returned to the
  canonical new conversation, and retained both messages.
- Chainlit was stopped at PID 11932 and restarted from the repository virtual
  environment with launcher PID 27736 and serving child PID 31696. After
  restart, HTTP returned 200 and the canonical test conversation still
  displayed both messages. The model server was not restarted.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.smoke_test --json
.\.venv\Scripts\python.exe -m chainlit run ui/chainlit_app.py --port 8100 --headless
```

## Acceptance boundary

Version 1 demonstrates a working local multimodal chat agent with persistence,
safe upload admission, readable tool failures, bounded context-overflow
recovery and restart survival. Autonomous implementation/testing, validation
before confirmation, correction budgets and polished thread lifecycle belong
to the provisional Version 1.5 plan.
