"""What a turn probably cost in GPU time, and what that is worth.

Three quantities the task document insists must never be confused, and this
module produces exactly one of them from another:

```text
model_request_time        measured — the engine was working
estimated_gpu_active_ms   derived  — the container was awake and billable
platform_billed_time      neither  — Modal's own aggregation, not visible here
```

The application knows when it asked the model for something. It does not know
the billed life of a Modal container, so this is an estimate with a stated
formula and a known direction of error, computed when a run is read rather than
stored in a column. That is deliberate: the estimate will get better, and every
past run should improve with it instead of carrying a frozen wrong number.

**It is an upper bound per turn.** The idle window is charged in full to the
turn that opened it, though a following turn inside that window shares the same
awake container, and a turn arriving while the GPU is already up for someone
else pays nothing of the wake it did not cause. Summing these across a busy
period therefore over-counts, and the aggregate to compare against `modal
billing` is the platform's, not this sum.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.telemetry.base import TraceEvent, moment

# Mirrors `SCALEDOWN_WINDOW` in `deploy/modal/model_app.py`, which cannot be
# imported here because that module imports `modal`. A test asserts the two stay
# equal, so the duplication cannot drift silently.
IDLE_WINDOW_SECONDS = 12.0

# Modal's A10 rate at the time these baselines were taken, and the number every
# cost note in this repository has used. Overridable on the command line,
# because a price is a fact about a moment.
A10_USD_PER_SECOND = 0.000306


@dataclass(frozen=True)
class GpuCost:
    model_ms: float
    span_ms: float
    idle_ms: float
    rate_per_second: float

    @property
    def estimated_active_ms(self) -> float:
        return self.span_ms + self.idle_ms

    @property
    def derived_usd(self) -> float:
        return self.estimated_active_ms / 1000 * self.rate_per_second


def gpu_cost(
    events: Sequence[TraceEvent],
    *,
    idle_window_seconds: float = IDLE_WINDOW_SECONDS,
    rate_per_second: float = A10_USD_PER_SECOND,
) -> GpuCost | None:
    """The awake span this turn is responsible for, or nothing if it used no GPU.

    The span runs from the first model request to the last one, not from the
    start of the turn: the queue wait and the worker's cold start happen on CPU
    while no GPU is up. A wake is already inside the first request's own
    duration, because the client waited through it.
    """

    model_ms = 0.0
    started: datetime | None = None
    ended: datetime | None = None
    for event in events:
        at = moment(event.timestamp)
        if event.type == "model_started" and started is None:
            started = at
        elif event.type in {"model_finished", "model_failed"}:
            model_ms += event.duration_ms or 0
            ended = at or ended
    if started is None or ended is None:
        return None
    span_ms = (ended - started).total_seconds() * 1000
    return GpuCost(
        model_ms=model_ms,
        # The span is what the container was up for; it cannot be less than the
        # work it did, whatever the clocks say.
        span_ms=max(model_ms, span_ms),
        idle_ms=idle_window_seconds * 1000,
        rate_per_second=rate_per_second,
    )


def render_cost(cost: GpuCost | None) -> list[str]:
    if cost is None:
        return []
    return [
        "",
        "GPU (derived, not billed)",
        f"  model request time  {cost.model_ms / 1000:7.2f}s   measured",
        f"  estimated active    {cost.estimated_active_ms / 1000:7.2f}s   derived:"
        f" model span plus a {cost.idle_ms / 1000:.0f}s idle window",
        f"  derived cost        ${cost.derived_usd:.4f}   at"
        f" ${cost.rate_per_second}/s; an upper bound, never an invoice",
    ]
