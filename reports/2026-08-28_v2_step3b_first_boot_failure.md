# V2 step 3b — first paid invocation of `assistant-llm-v2`: failed

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** failed. vLLM never served a request. No snapshot was created, so
no cold-start number exists for the replacement.

## What was attempted

The first authorized paid GPU invocation of the snapshot replacement, intended
to boot vLLM, warm it, sleep it, let Modal capture a CPU+GPU snapshot, and
produce a request-to-ready measurement.

Request: `GET /v1/models` with `Modal-Key` / `Modal-Secret` headers against
`https://grigoriy-v--assistant-llm-v2-server-serve.modal.run`.

## Result

| | Value |
|---|---|
| First request | `HTTP 303`, 150.7 s, empty body |
| Container 1 `ta-01M12RBHNZ504BHG0G2GEM9NGR` | vLLM exited code 1 after **212.2 s** |
| Container 2 `ta-01M12RJ5FZPPM9T18NWCSHEEVR` | started automatically, killed by operator |
| Second request | `HTTP 000`, no response within 120 s |
| Snapshot | not created |
| GPU container-minutes | roughly 6 on an A10 across both containers |

## Root cause

`--enable-sleep-mode` switches vLLM onto the cumem allocator — the log says so
directly: `Enabling cumem allocator because sleep mode requires it.` That
allocator is what makes GPU memory movable to CPU memory, and therefore what
makes a GPU snapshot possible at all. It also invalidates the memory profiler's
arithmetic.

```
Model loading took 8.28 GiB memory and 9.60 seconds
Estimated CUDA graph memory: 0.79 GiB total
Available KV cache memory: 13.77 GiB
GPU KV cache size: 107,923 tokens
Maximum concurrency for 16,384 tokens per request: 6.59x
CUDA Error: out of memory at /workspace/csrc/cumem_allocator.cpp:163
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.72 GiB.
  GPU 0 has a total capacity of 22.06 GiB of which 947.44 MiB is free.
  Process 1 has 21.12 GiB memory in use.
  Of the allocated memory 24.29 GiB is allocated by PyTorch,
  with 3.80 GiB allocated in private pools (e.g., CUDA Graphs)
```

**24.29 GiB reported as allocated by PyTorch on a card with 22.06 GiB.** The
profiler is measuring an address space the allocator never fully commits, so it
sized a 13.77 GiB KV cache that does not physically fit. vLLM logged
`--gpu-memory-utilization=0.9200` as the value in force; nothing in this
repository set it, so it is a default.

The baseline `assistant-llm` never hit this because it has no
`--enable-sleep-mode`, therefore no cumem allocator and no double count. It ran
a 10.03 GiB KV cache on the same GPU type. This is not a latent bug inherited
from the baseline; it is a cost of the optimization being attempted.

## What worked

Worth separating from the failure, because these were unverified before:

- **The snapshot machinery engaged.** Modal logged `Creating GPU memory
  snapshot for Function.`
- **The readiness wait did its job.** It reported
  `start: vLLM exited with code 1 after 212.2s; see this container's logs for
  its traceback` instead of hanging until Modal killed the container
  anonymously. That diagnosis is what made the root cause reachable.
- **Proxy auth on a `.modal.run` endpoint accepted `Modal-Key` /
  `Modal-Secret`** and routed to the container. Whether a joined bearer token
  also works — the property step 3a relied on — is still untested.
- **`max_containers=1` held.** Only one container existed at a time.

## What went wrong operationally

Modal restarted the container after the failed start, exactly the retry loop
the step 3a report warned about. The second container was terminated with
`modal app stop -y assistant-llm-v2`. Roughly six A10 container-minutes were
spent for no measurement. The precise charge should be read from Modal's
dashboard rather than estimated here.

`assistant-llm-v2` is now **stopped**. `assistant-llm` remains deployed at zero
containers and still serves `MODEL_ENDPOINT`; it was never touched.

## Fix applied, not yet validated

`GPU_MEMORY_UTILIZATION = 0.83`, passed explicitly as
`--gpu-memory-utilization`. The failed boot was 1.72 GiB short with 947 MiB
free, so about 2 GiB must come off a 22.06 GiB card; 0.92 → 0.83 is roughly
that. The resulting KV cache should still exceed the baseline's working
10.03 GiB, keeping 16384 tokens safe.

**This is an estimate derived from one failure, not a measurement.** The next
boot confirms or refutes it.

A regression test asserts the value stays below the 0.92 that failed.

## If 0.83 is not enough

Do not iterate blindly; each attempt is a paid boot. In order:

1. lower utilization further, one step at a time, reading the reported
   `Available KV cache memory` from each attempt;
2. reduce `MAX_MODEL_LEN`, accepting less context for the snapshot benefit;
3. accept that sleep mode may not fit this model on a 24 GB A10 and test
   `FAST_BOOT` / `--enforce-eager` without snapshots as the fallback, which
   `ROADMAP.md` step 3b already names;
4. only then consider a larger GPU, which changes the cost basis and is a
   separate decision.

## Limitations

- No cold-start, restore-to-health, TTFT or throughput number exists for the
  replacement. Nothing about its performance may be claimed.
- The snapshot was never completed, so the whole premise of step 3b — that
  snapshots cut the three-minute wake — remains untested.
- The `HTTP 303` on the first request was not explained. It appeared when the
  container failed to start; whether Modal always answers that way for a failed
  web-server start was not established.
