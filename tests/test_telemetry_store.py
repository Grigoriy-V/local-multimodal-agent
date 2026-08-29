"""One suite every `TelemetryStore` implementation must pass.

The same rule as the conversation store: a second implementation that is not
exercised by the first one's tests drifts silently. The PostgreSQL entry appears
only when `AGENT_TEST_DATABASE_URL` is configured, so the offline suite stays
offline and no test can reach the deployed database by accident.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app.telemetry import TelemetryStore, TraceEvent, TurnRun
from app.telemetry.sqlite import SqliteTelemetry

POSTGRES_DSN = os.environ.get("AGENT_TEST_DATABASE_URL", "")


def postgres_telemetry(_tmp_path: Path) -> TelemetryStore:
    from app.telemetry.postgres import PostgresTelemetry

    return PostgresTelemetry(
        POSTGRES_DSN,
        schema=f"telemetry_{uuid.uuid4().hex[:12]}",
        migrate_schema=True,
    )


FACTORIES: dict[str, Callable[[Path], TelemetryStore]] = {
    "sqlite": lambda tmp_path: SqliteTelemetry(tmp_path / "telemetry.sqlite3"),
}
if POSTGRES_DSN:
    FACTORIES["postgres"] = postgres_telemetry


@pytest.fixture(params=sorted(FACTORIES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TelemetryStore]:
    opened = FACTORIES[request.param](tmp_path)
    try:
        yield opened
    finally:
        drop = getattr(opened, "drop_schema", None)
        if drop is not None:
            drop()
        opened.close()


def run(run_id: str = "r1") -> TurnRun:
    return TurnRun(
        run_id=run_id,
        user_id="user-alice",
        thread_id="t1",
        source="telegram",
        source_update_id="7",
    )


def test_a_started_turn_is_readable_before_it_finishes(store: TelemetryStore) -> None:
    """A container that dies mid-turn must still leave the turn visible."""

    store.start_turn(run())

    stored = store.get_turn("r1")
    assert stored is not None
    assert stored.status == "running"
    assert stored.outcome is None
    assert stored.finished_at is None


def test_finishing_rewrites_the_same_row(store: TelemetryStore) -> None:
    record = run()
    store.start_turn(record)
    record.status = "completed"
    record.outcome = "answer_delivered"
    record.finished_at = "2026-08-29T10:00:00.000+00:00"
    record.model_calls = 2
    record.tool_calls = 1
    record.input_tokens = 4872
    record.output_tokens = 614
    record.first_model_token_ms = 1160
    record.first_visible_ms = 2100
    record.total_ms = 8400
    store.finish_turn(record)

    stored = store.get_turn("r1")
    assert stored is not None
    assert (stored.status, stored.outcome) == ("completed", "answer_delivered")
    assert (stored.model_calls, stored.tool_calls) == (2, 1)
    assert (stored.input_tokens, stored.output_tokens) == (4872, 614)
    assert stored.first_model_token_ms == 1160
    assert stored.first_visible_ms == 2100
    assert stored.successful is True


def test_an_unknown_run_has_no_row(store: TelemetryStore) -> None:
    assert store.get_turn("never-happened") is None


def test_events_come_back_in_sequence_order(store: TelemetryStore) -> None:
    """`seq`, not the timestamp: events inside one millisecond are ordinary."""

    store.start_turn(run())
    store.record_events(
        [
            TraceEvent("r1", 3, "model_finished", timestamp="2026-08-29T10:00:00.000+00:00"),
            TraceEvent("r1", 1, "turn_started", timestamp="2026-08-29T10:00:00.000+00:00"),
            TraceEvent("r1", 2, "model_started", timestamp="2026-08-29T10:00:00.000+00:00"),
        ]
    )

    assert [event.type for event in store.events("r1")] == [
        "turn_started",
        "model_started",
        "model_finished",
    ]


def test_events_keep_their_data_and_duration(store: TelemetryStore) -> None:
    store.start_turn(run())
    store.record_events(
        [
            TraceEvent(
                "r1",
                1,
                "tool_finished",
                duration_ms=1834,
                data={"tool": "view_web_page", "status": "success"},
            )
        ]
    )

    [event] = store.events("r1")
    assert event.duration_ms == 1834
    assert event.data == {"tool": "view_web_page", "status": "success"}


def test_events_belong_to_their_own_run(store: TelemetryStore) -> None:
    store.start_turn(run("r1"))
    store.start_turn(run("r2"))
    store.record_events([TraceEvent("r1", 1, "turn_started")])
    store.record_events([TraceEvent("r2", 1, "turn_started"), TraceEvent("r2", 2, "turn_finished")])

    assert len(store.events("r1")) == 1
    assert len(store.events("r2")) == 2


def test_writing_a_batch_twice_does_not_duplicate_it(store: TelemetryStore) -> None:
    """A flush retried after a failure elsewhere must not double the trace."""

    store.start_turn(run())
    batch = [TraceEvent("r1", 1, "turn_started"), TraceEvent("r1", 2, "model_started")]
    store.record_events(batch)
    store.record_events(batch)

    assert len(store.events("r1")) == 2


def test_an_empty_batch_writes_nothing(store: TelemetryStore) -> None:
    store.start_turn(run())
    store.record_events([])

    assert store.events("r1") == []
