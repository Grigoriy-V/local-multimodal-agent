# Stage 1 smoke script

**Date:** 2026-08-01
**Run identity:** repository code (`scripts/smoke_test.py`) against the endpoint
described in `2026-08-01_gemma4_endpoint_smoke.md`; server configuration
unchanged, warm.

The earlier report proved the *endpoint* by hand. This one proves the
*repository code* that drives it.

## Configuration

- entry point: `python -m scripts.smoke_test [--json] [--report PATH]`,
  exit code 0 only if every check passes.
- settings: `app/config.py`, environment prefix `MODEL_`, defaults
  `http://127.0.0.1:8000/v1` and `gemma-4-12b-it`, `temperature 0`,
  `max_tokens 512`. `.env.example` documents them.
- backend: `app/models/openai_compatible.py` on `httpx`, reached only through
  the `ModelBackend` interface. Nothing outside `app/models/` imports `httpx`.
- fixtures: `tests/fixtures/` — `red_circle.png`, `blue_square.png` (224x224),
  `speech.flac` and `speech.wav` (3.0 s, 16 kHz mono, the same trimmed sample).

Every check judges the answer, not just the status code, so a request that
succeeds and returns nonsense still fails.

## Result

| Check | Verdict | Latency | Judged by |
|---|---|---|---|
| text chat | PASS | 0.27 s | answer contains "pong" |
| system prompt | PASS | 0.08 s | system instruction overrides the question |
| streaming | PASS | 0.38 s | 20 chunks, first after 0.04 s, content complete |
| single image | PASS | 0.12 s | "red" and "circle" both named |
| multiple images | PASS | 0.22 s | both images named in order |
| audio wav | PASS | 0.25 s | speech transcribed |
| audio flac | PASS | 0.22 s | speech transcribed |
| tool call | PASS | 0.37 s | `get_weather{"city":"Tbilisi"}`, `finish_reason: tool_calls` |
| structured JSON | PASS | 0.65 s | schema satisfied, value inside declared bounds |

| Metric | Value |
|---|---|
| offline tests | 42 passed (`pytest -q`), no server required |
| VRAM | 23712 of 24564 MiB reserved by the driver — not peak use, see below |
| failures at the end | none |

Latencies are lower than the hand-run figures because the server was warm and
prefix caching was in play. They are single-shot, not benchmarks.

## Observations

Three checks failed on the first run. All three were real, and none was a
transport bug.

1. **Guided decoding runs away on an unbounded numeric field.** With
   `{"type": "number"}` and then `{"type": "integer"}`, the model emitted
   `1.15000000000000010000…` and `110000000000000000000…` until `max_tokens`
   was exhausted, and the truncated body failed to parse. Adding `minimum` and
   `maximum` fixed it: 8.63 s and unparsable became 0.65 s and correct. The
   grammar backend does honour numeric bounds. **Any JSON schema this project
   sends must bound its numeric fields.**
2. **A 20 ms tone proves nothing.** `tone.wav` made the model answer "please
   provide the audio file", so a "did it return text" check passed while the
   audio was effectively absent. Replaced with 3 s of real speech in both wav
   and flac, checked against the transcript. `tone.wav` remains a transport-only
   fixture and is no longer used by the smoke run.
3. **Colour naming is literal.** A circle filled `(220, 20, 20)` was called
   "pink". Fixtures now use pure `(255, 0, 0)` and `(0, 0, 255)`. Worth
   remembering before asserting on any colour the model reports.

**Peak VRAM still cannot be read from `nvidia-smi`**, for the reason recorded in
the previous report: vLLM claims `gpu_memory_utilization` in one block at
startup. The script prints the driver figure with that caveat attached rather
than pretending it is a measurement.

## Offline coverage

`tests/test_openai_compatible.py` covers the two places that fail quietly
against a live server, without touching one:

- media part assembly — image data URLs, bare-base64 audio with a format field,
  the media-type-to-format map, an unknown audio type refused, part order,
  roles, `tool_call_id`;
- tool-call parsing — arguments decoded from the JSON string, several calls in
  order, and loud refusal of invalid JSON, non-object arguments, a nameless
  call, and an empty response. A mis-parsed tool call otherwise arrives as an
  empty answer.

Plus request shaping through `httpx.MockTransport` (URL, auth header, tools,
`tool_choice`, `response_format`, `stream`) and error translation.

## Limitations

- One assistant turn only. There is no tool-result round trip: `Message` can
  carry a `tool_call_id` but cannot yet carry an assistant's own tool calls.
  That belongs to Stage 2 and is deliberately not built.
- The speech fixture is 3 s of one speaker. Audio remains speech-oriented; the
  earlier finding about synthetic sound stands.
- The image checks use flat synthetic shapes, not photographs.
- Single-shot timings on a warm, idle server, no concurrency, no repetition.

## Next gate

Human decision on Stage 2. Stage 1 is closed by this run.
