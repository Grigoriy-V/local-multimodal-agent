"""The first thing with a reason to object when a turn tries to end.

`app/agent/stopping.py` is a seam with no policy in it: the default stops, and
a turn continues only when an injected extension asks for it in words. This is
that extension, and it says exactly one thing — *your own list still has open
items* — using state the model wrote itself.

It is deliberately not a validator. It never reads the answer, never judges
whether the work was any good, and costs no model call: an agent that wrote no
list is never interrupted by it, which is most turns. The only claim it makes
is that the model contradicted itself, by planning steps and then stopping with
some of them open.

The objection is capped. An extension that could refuse the same ending
repeatedly would turn a stale list into an unbounded bill, so it speaks once per
turn and then lets the turn end however the model wants. The instruction also
offers the way out that costs nothing: update the list to say what actually
happened. Being made to keep working is one acceptable outcome; being made to
be honest about the plan is the other.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.stopping import Candidate, Steering
from app.tools.todo import current, unfinished

SOURCE = "todo"

INSTRUCTION = (
    "Your own task list still has open items: {items}. Do the remaining work "
    "now, or call todo_write to record what actually happened — mark what is "
    "done, drop what you are not going to do — and then give your answer."
)

# How many open items are named back to the model. The list is bounded already;
# this keeps one long plan from becoming a long injected message.
NAMED_ITEMS = 5


def _named(items: Sequence[dict[str, str]]) -> str:
    shown = ", ".join(item["content"] for item in items[:NAMED_ITEMS])
    remaining = len(items) - NAMED_ITEMS
    return f"{shown} (+{remaining} more)" if remaining > 0 else shown


class FinishesItsOwnList:
    """Refuse one ending while the agent's own todo list has open items."""

    def __init__(self, limit: int = 1) -> None:
        self.limit = limit

    async def stopping(self, candidate: Candidate) -> Steering | None:
        # The cap counts every objection of the turn, not only this one's.
        # Sharing the count is the honest reading: a turn that has already been
        # sent back once has been argued with, whoever did it.
        if candidate.steerings >= self.limit:
            return None
        open_items = unfinished(current(candidate.messages))
        if not open_items:
            return None
        return Steering(
            instruction=INSTRUCTION.format(items=_named(open_items)),
            source=SOURCE,
        )
