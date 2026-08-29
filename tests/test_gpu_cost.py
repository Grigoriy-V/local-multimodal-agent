"""Derived GPU time and derived cost, kept honest about being derived.

The task document's rule is that measured, derived and billed quantities must
never be labelled as each other. These tests hold the derivation to its stated
formula, its stated direction of error, and its stated source for the idle
window.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.telemetry.base import TraceEvent
from app.telemetry.cost import (
    A10_USD_PER_SECOND,
    IDLE_WINDOW_SECONDS,
    gpu_cost,
    render_cost,
)


def event(seq: int, type: str, at: str, duration_ms: int | None = None) -> TraceEvent:
    return TraceEvent(run_id="r1", seq=seq, type=type, timestamp=at, duration_ms=duration_ms)


def two_calls() -> list[TraceEvent]:
    return [
        event(1, "turn_started", "2026-08-29T10:00:00.000+00:00"),
        event(2, "model_started", "2026-08-29T10:00:02.000+00:00"),
        event(3, "model_finished", "2026-08-29T10:00:03.000+00:00", 1000),
        event(4, "tool_started", "2026-08-29T10:00:03.100+00:00"),
        event(5, "tool_finished", "2026-08-29T10:00:04.100+00:00", 1000),
        event(6, "model_started", "2026-08-29T10:00:04.200+00:00"),
        event(7, "model_finished", "2026-08-29T10:00:08.200+00:00", 4000),
        event(8, "turn_finished", "2026-08-29T10:00:09.000+00:00", 9000),
    ]


def test_the_span_runs_from_the_first_request_to_the_last() -> None:
    """Not from the start of the turn: the queue wait happens on CPU.

    Between the two calls the GPU was up and idle waiting for a tool, which the
    span includes and the sum of request durations does not.
    """

    cost = gpu_cost(two_calls())

    assert cost is not None
    assert cost.model_ms == 5000
    assert cost.span_ms == 6200


def test_the_idle_window_is_charged_to_the_turn_that_opened_it() -> None:
    cost = gpu_cost(two_calls(), idle_window_seconds=12.0)

    assert cost is not None
    assert cost.estimated_active_ms == 6200 + 12000
    assert cost.derived_usd == (6200 + 12000) / 1000 * A10_USD_PER_SECOND


def test_a_different_price_or_window_changes_the_estimate() -> None:
    """The formula is the durable part; both inputs are facts about a moment."""

    cost = gpu_cost(two_calls(), idle_window_seconds=2.0, rate_per_second=0.001)

    assert cost is not None
    assert cost.estimated_active_ms == 8200
    assert round(cost.derived_usd, 4) == 0.0082


def test_a_turn_that_reached_no_model_has_no_gpu_cost() -> None:
    """A free command or a cancellation spent no GPU and must not be given one."""

    events = [
        event(1, "turn_started", "2026-08-29T10:00:00.000+00:00"),
        event(2, "turn_finished", "2026-08-29T10:00:00.200+00:00", 200),
    ]

    assert gpu_cost(events) is None
    assert render_cost(gpu_cost(events)) == []


def test_a_failed_model_call_still_cost_gpu_time() -> None:
    events = [
        event(1, "model_started", "2026-08-29T10:00:00.000+00:00"),
        event(2, "model_failed", "2026-08-29T10:00:03.000+00:00", 3000),
    ]

    cost = gpu_cost(events)

    assert cost is not None
    assert cost.model_ms == 3000


def test_the_estimate_says_it_is_derived_and_not_an_invoice() -> None:
    text = "\n".join(render_cost(gpu_cost(two_calls())))

    assert "derived" in text
    assert "measured" in text
    assert "never an invoice" in text


def test_the_idle_window_matches_the_deployment_it_mirrors() -> None:
    """One number in two files is one number and one lie waiting to happen.

    `deploy/modal/model_app.py` cannot be imported here — it imports `modal` —
    so the copy is checked against the source text instead of being trusted.
    """

    source = Path("deploy/modal/model_app.py").read_text(encoding="utf-8")
    found = re.search(r"^SCALEDOWN_WINDOW = (\d+)", source, re.MULTILINE)

    assert found is not None
    assert float(found.group(1)) == IDLE_WINDOW_SECONDS
