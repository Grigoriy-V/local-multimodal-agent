"""What a turn's telemetry is, apart from any one database.

Operational telemetry and conversation persistence are different domains, so
this contract deliberately does not live in `ConversationStore`. A turn's shape
— when it started, how long each step took, how many model and tool calls it
spent, what the person actually received — outlives the container that produced
it and belongs to whoever is developing the agent, not to the conversation.

What is stored here is timings, counts and state transitions. Never message
text, attachments, prompts, tool results or streamed deltas: telemetry that
duplicates the conversation is a second copy of the private part of the product
with none of its access rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Self

# What the person got out of the turn. Separate from `status`, which describes
# execution, because a turn that correctly stops to ask a question produced no
# answer and is not a failure — counting it as one would make every approval
# look like a defect.
Outcome = Literal[
    "answer_delivered",
    "approval_requested",
    "task_result_delivered",
    "cancelled",
    "failed",
]

Status = Literal["running", "completed", "failed", "cancelled"]

SUCCESSFUL: frozenset[str] = frozenset(
    {"answer_delivered", "approval_requested", "task_result_delivered"}
)


def stamp() -> str:
    """One instant, at the resolution telemetry actually needs."""

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def moment(timestamp: str) -> datetime | None:
    """`stamp` read back. Unparseable input is unknown, never an exception.

    Anything reading a trace is reading rows that may have been written by an
    older version of this code, and one odd timestamp must not stop a run from
    being inspected.
    """

    try:
        return datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None


@dataclass
class TurnRun:
    """The summary row for one user turn.

    Mutable, and filled in as the turn happens: the row is written once when the
    turn starts, so a turn whose container dies leaves a `running` row that
    never finished, and rewritten once when it ends.
    """

    run_id: str
    user_id: str = ""
    thread_id: str = ""
    source: str = ""
    source_update_id: str = ""
    started_at: str = field(default_factory=stamp)
    finished_at: str | None = None
    status: Status = "running"
    outcome: Outcome | None = None
    route: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    first_model_token_ms: int | None = None
    first_visible_ms: int | None = None
    total_ms: int | None = None
    error_type: str | None = None

    @property
    def successful(self) -> bool:
        return self.outcome in SUCCESSFUL


@dataclass(frozen=True)
class TraceEvent:
    """One ordered structured fact belonging to one run.

    `seq` rather than the timestamp is the order: two events inside the same
    millisecond are common, and a trace that cannot be read in order is not a
    trace.
    """

    run_id: str
    seq: int
    type: str
    timestamp: str = field(default_factory=stamp)
    duration_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


class TelemetryStore(ABC):
    """Durable turn records and traces for one deployment."""

    @abstractmethod
    def start_turn(self, run: TurnRun) -> None:
        """Write the summary row of a turn that has just begun.

        Writing a run that already exists is not an error: a redelivered update
        must not fail a turn over its own bookkeeping.
        """

    @abstractmethod
    def finish_turn(self, run: TurnRun) -> None:
        """Rewrite the summary row of a turn that has ended."""

    @abstractmethod
    def record_events(self, events: Sequence[TraceEvent]) -> None:
        """Append events. Called in batches, never once per event."""

    @abstractmethod
    def get_turn(self, run_id: str) -> TurnRun | None: ...

    @abstractmethod
    def recent_runs(
        self,
        *,
        limit: int = 20,
        user_id: str | None = None,
        unsuccessful: bool = False,
    ) -> list[TurnRun]:
        """The most recently started turns first.

        `unsuccessful` is deliberately not `status = 'failed'`. A turn whose
        container died never reached the code that closes its row, so it stays
        `running` forever — and those are exactly the turns worth reading. So
        the filter means *the outcome was a failure, or the turn never ended at
        all*, which is the only definition under which a crash is findable.
        """

    @abstractmethod
    def events(self, run_id: str) -> list[TraceEvent]:
        """This run's events in `seq` order."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()
