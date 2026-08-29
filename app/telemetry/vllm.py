"""Reading the model server's own metrics, rather than guessing at them.

The application can time a request from outside, which is what 3A did. It cannot
see prefill, decode or the prefix cache from there — those are engine facts, and
vLLM already publishes them. So this parses vLLM's Prometheus text and takes the
difference between two readings around a controlled request.

Two rules the task document is explicit about, and both are enforced here rather
than assumed:

**Names are discovered, not copied.** Metric names move between vLLM releases,
so every concept carries a list of candidates and the probe reports which name
the deployed engine actually exposes — and which concepts it does not have at
all. A missing counter must be visible as missing, never as a zero.

**A delta across a restart is not a measurement.** These counters belong to one
container's engine and reset when it scales to zero and comes back. A reading
whose totals went backwards is refused instead of published as a negative
number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# What the baseline needs, and every name the deployed engine might publish it
# under. First match wins; an entry with no match is reported as missing.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "time_to_first_token": ("vllm:time_to_first_token_seconds",),
    # 0.26.0 publishes the per-request average under a longer name and also
    # exposes raw inter-token latency; the short name the docs use is not here.
    "time_per_output_token": (
        "vllm:request_time_per_output_token_seconds",
        "vllm:time_per_output_token_seconds",
        "vllm:inter_token_latency_seconds",
    ),
    "prefill_time": ("vllm:request_prefill_time_seconds",),
    "decode_time": ("vllm:request_decode_time_seconds",),
    "inference_time": ("vllm:request_inference_time_seconds",),
    "end_to_end_latency": ("vllm:e2e_request_latency_seconds",),
    "queue_time": ("vllm:request_queue_time_seconds",),
    "prompt_tokens": ("vllm:prompt_tokens_total", "vllm:prompt_tokens"),
    "generation_tokens": ("vllm:generation_tokens_total", "vllm:generation_tokens"),
    "prefix_cache_queries": (
        "vllm:gpu_prefix_cache_queries_total",
        "vllm:prefix_cache_queries_total",
        "vllm:gpu_prefix_cache_queries",
        "vllm:prefix_cache_queries",
    ),
    "prefix_cache_hits": (
        "vllm:gpu_prefix_cache_hits_total",
        "vllm:prefix_cache_hits_total",
        "vllm:gpu_prefix_cache_hits",
        "vllm:prefix_cache_hits",
    ),
    "requests_finished": ("vllm:request_success_total", "vllm:request_success"),
    # Block-level hits answer "was the cache used"; these two answer "how much
    # of this prompt did the GPU actually have to compute", which is the
    # question scenario C exists for.
    "cached_prompt_tokens": ("vllm:prompt_tokens_cached_total",),
    "prefill_kv_computed_tokens": ("vllm:request_prefill_kv_computed_tokens",),
}

# Concepts without which the baseline cannot answer the questions item 3 asks.
REQUIRED = (
    "time_to_first_token",
    "prompt_tokens",
    "generation_tokens",
    "prefix_cache_queries",
    "prefix_cache_hits",
)

# A histogram publishes these beside its buckets; a counter publishes neither.
HISTOGRAM_PARTS = ("_sum", "_count")


@dataclass(frozen=True)
class Snapshot:
    """One reading of the engine's counters.

    `values` is summed across label sets: this deployment serves one model from
    one container, so a per-label breakdown would be detail without a question.
    Bucket lines are dropped — a histogram's mean comes from its sum and count,
    and summing `le` buckets would produce a number that means nothing.
    """

    values: dict[str, float] = field(default_factory=dict)
    families: tuple[str, ...] = ()
    process_start: float | None = None

    def get(self, name: str) -> float | None:
        return self.values.get(name)


def parse_metrics(text: str) -> Snapshot:
    values: dict[str, float] = {}
    families: list[str] = []
    process_start: float | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "TYPE" and parts[2].startswith("vllm:"):
                families.append(parts[2])
            continue
        name, _, rest = line.partition("{")
        if rest:
            _labels, _, tail = rest.partition("}")
            raw = tail.strip()
        else:
            name, _, raw = line.partition(" ")
            raw = raw.strip()
        name = name.strip()
        if name.endswith("_bucket"):
            continue
        try:
            value = float(raw.split()[0])
        except (IndexError, ValueError):
            continue
        if name == "process_start_time_seconds":
            process_start = value
            continue
        values[name] = values.get(name, 0.0) + value
    return Snapshot(values, tuple(sorted(set(families))), process_start)


def discover(snapshot: Snapshot) -> dict[str, str | None]:
    """Which name each concept actually has here, or `None` if it has none."""

    found: dict[str, str | None] = {}
    for concept, candidates in CONCEPTS.items():
        found[concept] = None
        for candidate in candidates:
            if candidate in snapshot.values or any(
                candidate + part in snapshot.values for part in HISTOGRAM_PARTS
            ):
                found[concept] = candidate
                break
    return found


def missing(found: Mapping[str, str | None]) -> tuple[str, ...]:
    return tuple(concept for concept in REQUIRED if not found.get(concept))


def restarted(before: Snapshot, after: Snapshot) -> bool:
    """Did the engine that produced the second reading start after the first?

    Counters only ever rise inside one container's life, so a total that fell is
    proof of a new one — and a restart between the two readings means the delta
    describes two different engines.
    """

    if (
        before.process_start is not None
        and after.process_start is not None
        and before.process_start != after.process_start
    ):
        return True
    for name, value in before.values.items():
        if name.endswith(("_total", "_count", "_sum")) and after.values.get(name, 0.0) < value:
            return True
    return False


def delta(before: Snapshot, after: Snapshot) -> dict[str, float]:
    changed: dict[str, float] = {}
    for name, value in after.values.items():
        difference = value - before.values.get(name, 0.0)
        if difference:
            changed[name] = difference
    return changed


def mean(changed: Mapping[str, float], base: str | None) -> float | None:
    """A histogram's average over the requests inside the delta."""

    if not base:
        return None
    total = changed.get(base + "_sum")
    count = changed.get(base + "_count")
    if total is None or not count:
        return None
    return total / count


def counted(changed: Mapping[str, float], base: str | None) -> float | None:
    """How much a counter moved, where zero and unknown are different answers.

    `delta` keeps only what changed, so a counter that stayed put is absent from
    it. That absence means it did not move — which is a measurement, and the
    prefix cache reporting no hits is exactly the case where confusing it with
    "not published" would be a lie.
    """

    if not base:
        return None
    if base in changed:
        return changed[base]
    return changed.get(base + "_count", 0.0)


@dataclass(frozen=True)
class Measurement:
    """What one controlled request, or a batch of them, cost the engine."""

    requests: float | None = None
    ttft_ms: float | None = None
    tpot_ms: float | None = None
    prefill_ms: float | None = None
    decode_ms: float | None = None
    inference_ms: float | None = None
    queue_ms: float | None = None
    end_to_end_ms: float | None = None
    prompt_tokens: float | None = None
    generation_tokens: float | None = None
    prefix_cache_queries: float | None = None
    prefix_cache_hits: float | None = None
    cached_prompt_tokens: float | None = None
    prefill_kv_computed_tokens: float | None = None

    @property
    def prefix_hit_rate(self) -> float | None:
        """Measured, never inferred from configuration."""

        if not self.prefix_cache_queries:
            return None
        return (self.prefix_cache_hits or 0.0) / self.prefix_cache_queries

    @property
    def cached_token_share(self) -> float | None:
        """How much of the prompt the GPU did not have to compute."""

        if not self.prompt_tokens:
            return None
        if self.cached_prompt_tokens is None:
            return None
        return self.cached_prompt_tokens / self.prompt_tokens


def milliseconds(seconds: float | None) -> float | None:
    return None if seconds is None else seconds * 1000


def summarize(found: Mapping[str, str | None], changed: Mapping[str, float]) -> Measurement:
    return Measurement(
        requests=counted(changed, found.get("requests_finished"))
        or counted(changed, found.get("time_to_first_token")),
        ttft_ms=milliseconds(mean(changed, found.get("time_to_first_token"))),
        tpot_ms=milliseconds(mean(changed, found.get("time_per_output_token"))),
        prefill_ms=milliseconds(mean(changed, found.get("prefill_time"))),
        decode_ms=milliseconds(mean(changed, found.get("decode_time"))),
        inference_ms=milliseconds(mean(changed, found.get("inference_time"))),
        queue_ms=milliseconds(mean(changed, found.get("queue_time"))),
        end_to_end_ms=milliseconds(mean(changed, found.get("end_to_end_latency"))),
        prompt_tokens=counted(changed, found.get("prompt_tokens")),
        generation_tokens=counted(changed, found.get("generation_tokens")),
        prefix_cache_queries=counted(changed, found.get("prefix_cache_queries")),
        prefix_cache_hits=counted(changed, found.get("prefix_cache_hits")),
        cached_prompt_tokens=counted(changed, found.get("cached_prompt_tokens")),
        # A histogram of tokens per request: the sum is how many were computed.
        prefill_kv_computed_tokens=(
            changed.get(found["prefill_kv_computed_tokens"] + "_sum", 0.0)
            if found.get("prefill_kv_computed_tokens")
            else None
        ),
    )


def render_measurement(label: str, measured: Measurement) -> str:
    def number(value: float | None, unit: str = "") -> str:
        return "-" if value is None else f"{value:,.1f}{unit}"

    rate = measured.prefix_hit_rate
    return "\n".join(
        [
            f"{label}",
            f"  requests            {number(measured.requests)}",
            f"  prefill / TTFT      {number(measured.prefill_ms, ' ms')}"
            f" / {number(measured.ttft_ms, ' ms')}",
            f"  time per output tok {number(measured.tpot_ms, ' ms')}",
            f"  decode / inference  {number(measured.decode_ms, ' ms')}"
            f" / {number(measured.inference_ms, ' ms')}",
            f"  queue / end to end  {number(measured.queue_ms, ' ms')}"
            f" / {number(measured.end_to_end_ms, ' ms')}",
            f"  tokens              {number(measured.prompt_tokens)} in"
            f" / {number(measured.generation_tokens)} out",
            f"  prefix cache        {number(measured.prefix_cache_hits)}"
            f" hits of {number(measured.prefix_cache_queries)} queries"
            + (f" ({rate:.0%})" if rate is not None else ""),
            f"  prompt tokens cached {number(measured.cached_prompt_tokens)}"
            + (
                f" ({share:.0%} of the prompt)"
                if (share := measured.cached_token_share) is not None
                else ""
            ),
            f"  KV computed         {number(measured.prefill_kv_computed_tokens)} tokens",
        ]
    )


def render_discovery(snapshot: Snapshot, found: Mapping[str, str | None]) -> str:
    lines = ["Metric names on the deployed engine", ""]
    for concept in CONCEPTS:
        name = found.get(concept)
        mark = " " if name else "!"
        lines.append(f" {mark} {concept:<28}{name or 'NOT PUBLISHED'}")
    absent = missing(found)
    lines.append("")
    if absent:
        lines.append(f"Required and absent: {', '.join(absent)}")
    else:
        lines.append("Every required concept is published.")
    lines.append(f"{len(snapshot.families)} vllm: families exposed in total.")
    return "\n".join(lines)


def families(snapshot: Snapshot) -> Sequence[str]:
    return snapshot.families
