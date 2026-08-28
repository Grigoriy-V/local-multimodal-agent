# V2 step 3b — application auth for the optimized Modal endpoint

**Status:** implemented and verified offline; the later live Telegram
acceptance passed. See
`reports/2026-08-28_v2_step3b_telegram_live_acceptance.md`.

## Change

`OpenAICompatibleBackend` now has two explicit authentication styles:

- `bearer` remains the default and preserves local, ordinary OpenAI-compatible
  and step 3a behaviour;
- `modal_proxy` parses the existing joined `wk-… . ws-…` value from
  `MODEL_API_KEY` and sends `Modal-Key` plus `Modal-Secret`, the header form
  already exercised successfully against `assistant-llm-v2`.

The selection is configuration, `MODEL_AUTH_STYLE`, rather than endpoint URL
guessing. Missing or malformed Modal credentials fail before any HTTP request,
so a bad local configuration cannot wake a paid worker merely to discover its
shape.

No secret was written to source or logs. `.env` remains unchanged and still
targets the baseline endpoint.

## Checks

- `uv run python -m pytest -q tests/test_openai_compatible.py
  tests/test_telegram_adapter.py` — **77 passed in 1.55 s**;
- `uv run python -m pytest -q` — **408 passed in 10.17 s**;
- `uv run ruff check app/config.py app/models/openai_compatible.py
  tests/test_openai_compatible.py` — passed;
- `git diff --check` — passed.

The first attempted test command named a nonexistent `tests/test_config.py`, so
pytest collected no tests. It was corrected immediately; the 77-test result
above is the actual executed check.

## Not done

- no endpoint request;
- no Telegram polling;
- no Modal worker or snapshot activity;
- no deployment and no paid compute;
- no claim yet that Telegram answered through v2.

## Original next human gate — completed later

Temporarily configure the local profile with the v2 URL and
`MODEL_AUTH_STYLE=modal_proxy`, start Telegram polling, send one ordinary
message, and retain the real reply, latency, snapshot-restore evidence and
scale-to-zero result. That single live run closes the remaining product wiring
of step 3b if it succeeds.
