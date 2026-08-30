"""The single lifecycle for a model-requested tool call.

The agent loop decides *when* a batch runs or pauses. This seam owns what must
happen around every individual call: validation, consent policy, execution and
telemetry. A later execution backend can replace ``execute`` without teaching
the loop a second lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import Message, ToolCall
from app.telemetry import TurnTrace

from .base import Toolbox, tool_failed


@dataclass(frozen=True)
class PreparedToolCall:
    """A validated policy decision with no tool effect performed yet."""

    call: ToolCall
    refusal: Message | None
    approval_required: bool


class ToolMeasurement(Protocol):
    def failed(self, status: str = "failed") -> None: ...


class ToolExecutor:
    """Run every tool through ``pre_execute -> execute -> post_execute``."""

    def __init__(self, toolbox: Toolbox, trace: TurnTrace) -> None:
        self.toolbox = toolbox
        self.trace = trace

    def pre_execute(self, call: ToolCall) -> PreparedToolCall:
        """Validate the call and apply consent policy without running it."""

        _tool, refusal = self.toolbox.prepare(call)
        return PreparedToolCall(
            call=call,
            refusal=refusal,
            approval_required=(
                refusal is None and self.toolbox.requires_approval(call.name)
            ),
        )

    async def execute(self, prepared: PreparedToolCall) -> Message:
        """Execute one prepared call through the current local backend."""

        if prepared.refusal is not None:
            return prepared.refusal
        return await self.toolbox.run_async(prepared.call)

    @staticmethod
    def post_execute(result: Message, measured: ToolMeasurement) -> Message:
        """Settle result status while preserving the model-visible message."""

        if tool_failed(result):
            measured.failed()
        return result

    async def run(self, prepared: PreparedToolCall) -> Message:
        """Execute and settle one call, including safe identifying telemetry."""

        path = prepared.call.arguments.get("path")
        data = {"stage": "execute"}
        if isinstance(path, str):
            data["path"] = path
        with self.trace.tool(prepared.call.name, **data) as measured:
            result = await self.execute(prepared)
            return self.post_execute(result, measured)
