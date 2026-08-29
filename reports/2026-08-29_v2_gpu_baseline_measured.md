# The measured model baseline — prefill, decode and the prefix cache

**Date:** 2026-08-29
**Instrument:** `reports/2026-08-29_v2_gpu_baseline_implementation.md`
**Raw readings:** `reports/vllm_baseline_20260829T092823Z.json` (discovery),
`reports/vllm_baseline_20260829T093324Z.json` (the suite)
**Endpoint:** `assistant-llm-v2`, Gemma 4 12B on an A10, vLLM 0.26.0,
`--max-model-len 16384`
**Roadmap item:** queue 3, 3C.

Two authorized GPU wakes, one for discovery and one for the suite. Everything
below is the engine's own counters, taken as deltas around isolated requests.

## What the numbers are

| scenario | input tokens | prefill | TTFT | TPOT | prefill tok/s |
|---|---|---|---|---|---|
| A short in, 512 out | 36 | 62 ms | 69 ms | 21.2 ms | 580 |
| B ~1k | 853 | 352 ms | 357 ms | 21.7 ms | 2,425 |
| B ~4k | 3,285 | 1,356 ms | 1,365 ms | 22.0 ms | 2,423 |
| B ~8k | 6,528 | 2,881 ms | 2,897 ms | 22.8 ms | 2,266 |
| B ~12k | 9,773 | 4,689 ms | 4,711 ms | 23.9 ms | 2,084 |
| C1 cold prefix | 3,277 | 1,370 ms | 1,379 ms | 22.7 ms | 2,392 |
| C2 same prefix | 3,277 | **82 ms** | 91 ms | 22.1 ms | 40,110 |

Each B row is the mean of three isolated requests; the spread inside a row was
under 20 ms.

## Three findings

**Decode is about 45 tokens a second, not 15-17.** Time per output token is
21.2-23.9 ms across every input size, and scenario A generated 512 tokens in
10.8 s of decode — 47 tok/s. The 15-17 tok/s the roadmap has been quoting was an
end-to-end number that conflated network, prefill and decode, exactly as item 3
suspected. Decode-side optimization has less room in it than that figure
implied.

**Prefill is what long turns actually cost.** At ~12k input the request spends
4.69 s in prefill and 0.64 s in decode. Prefill throughput is not flat either:
2,425 tok/s at 853 tokens falls to 2,084 tok/s at 9,773, so an 11.5x longer
prompt costs 13.3x more prefill. Context is superlinear here, and the fold that
keeps a request inside `AGENT_CONTEXT_FRACTION` is buying time, not just VRAM.

**Prefix caching works, measured rather than assumed.** The same 3,277-token
prefix asked a second question: 3,200 of its tokens came from cache (98%), KV
computation fell from 3,277 tokens to 77, and prefill went from 1,370 ms to
82 ms — **16.8x**. End to end the request went from 1,402 ms to 621 ms. The B
repeats confirm the other half of the design: every one of them shows zero cache
hits, because each prompt carried a marker unique to its request, so the prefill
scaling above is real prefill and not the cache answering.

## What this says about the next work

The router's second full-context request is now priced rather than assumed. Its
prompt begins with its own system prompt, so it shares no prefix with the answer
call and cannot be served from cache: at the ~2,450 input tokens the live
baseline measured for it, that is about **1.0 s of pure prefill per turn**, plus
its own decode. Queue item 5's single-call change has a measured target.

The same finding argues for keeping conversation context tight and for reusing
prefixes deliberately — a stable system prompt and a stable context prefix are
worth more than any decode-side tuning available here.

## Method, and what it is not

- Isolated requests, one container, snapshot-request-snapshot deltas. No delta
  was refused, so the whole suite ran on one engine and the numbers are
  comparable to each other.
- **The twelve-second idle window held for the entire run.** `autoscale.py` was
  not touched and did not need to be: the requests go out back to back, which
  was the correction made before this ran.
- Input sizes are the engine's counts. The targets were estimates at four
  characters per token and came out about 20% low — 12,000 asked for, 9,773
  measured. B stops there rather than at the task document's 16k because the
  server context is 16,384 and the output needs room.
- Client-observed time exceeds the engine's end-to-end by roughly 250-350 ms per
  request; that is the network to Modal and back, not the model.
- **Not measured:** the cold-start path. The wake was paid inside the first
  metrics read and not timed separately; existing cold-start evidence stands in
  `reports/2026-08-28_v2_step3b_restored_cold_start.md`.
- **Not measured:** whether a prefix-cache reset endpoint exists under
  `VLLM_SERVER_DEV_MODE=1`. It was unnecessary: C1's prompt carried a per-run
  marker, so it was cold by construction.

## Metric names on this engine

Discovered rather than copied, and the discovery immediately paid: the name the
vLLM docs use for time per output token does not exist in 0.26.0.

```text
time_to_first_token         vllm:time_to_first_token_seconds
time_per_output_token       vllm:request_time_per_output_token_seconds
prefill_time                vllm:request_prefill_time_seconds
decode_time                 vllm:request_decode_time_seconds
inference_time              vllm:request_inference_time_seconds
end_to_end_latency          vllm:e2e_request_latency_seconds
queue_time                  vllm:request_queue_time_seconds
prompt_tokens               vllm:prompt_tokens_total
generation_tokens           vllm:generation_tokens_total
prefix_cache_queries        vllm:prefix_cache_queries_total
prefix_cache_hits           vllm:prefix_cache_hits_total
cached_prompt_tokens        vllm:prompt_tokens_cached_total
prefill_kv_computed_tokens  vllm:request_prefill_kv_computed_tokens
requests_finished           vllm:request_success_total
```

68 `vllm:` families are exposed in total. Two of the names above were added
after the discovery run and applied to the saved reading offline, without a
second wake.

## Cost of this measurement

15 requests, 51.4 s of request time in one container, plus one restored wake and
the trailing idle window — roughly 75 s of GPU at $0.000306/s, about **$0.023**.
The preparation estimated $0.05 and the corrected plan was right about the shape
of the run.

## Gates ahead

Item 3 still owes its live half: deploy `assistant-control` so the deployed
worker records task-stage detail, then one live autonomous task turn read back
with `tools/show_run.py` alone. That turn wakes the GPU and is its own
permission.
