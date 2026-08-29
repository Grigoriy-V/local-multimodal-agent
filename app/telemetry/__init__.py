"""Turn telemetry: what a turn cost and where its time went.

Deliberately separate from `app/memory/`. Conversations are the product's
durable content and belong to the person; this is operational evidence about
the machine, holds no message text, and can be deleted without losing anything
a user would notice.
"""

from app.telemetry.base import (
    SUCCESSFUL,
    Outcome,
    Status,
    TelemetryStore,
    TraceEvent,
    TurnRun,
    stamp,
)
from app.telemetry.open import open_telemetry
from app.telemetry.trace import NO_TRACE, Telemetry, TurnTrace

__all__ = [
    "NO_TRACE",
    "SUCCESSFUL",
    "Outcome",
    "Status",
    "Telemetry",
    "TelemetryStore",
    "TraceEvent",
    "TurnRun",
    "TurnTrace",
    "open_telemetry",
    "stamp",
]
