"""The person's request as the turn's goal, checked once the work is done.

Every "not a win but a shift" turn of 2026-09-04 ended the same way: the
model stopped when it had *something* — a PDF in English against a request
in Russian, a text file against a request for a PDF, half of a handover —
not when it had what was asked. With a plan on, the same requests were
finished, and the measured reason was not better planning: the open list
kept the request in front of the model until the list was closed
(`reports/2026-09-04_v2_isolated_execution_review.md` §14).

This is that benefit without the list. The goal is the request itself, word
for word, never a paraphrase the model wrote: "in Russian" cannot be lost
from what the person typed. A turn that did work — at least one tool ran —
does not end on the model's first answer. It is asked one question, without
tools, over the turn it just made: did that give the person what they
asked, as they asked it? `done` ends the turn as it stands. `not yet` gives
the tools back for another round, at most `ROUNDS` in a turn and always
inside the turn's own budget. `blocked` ends the turn, and the answer has to
carry the reason in the model's own words. A turn that used no tool is never
asked and pays nothing.

It is the same model in the same conversation, deliberately: a separate
reviewer is a second opinion to keep true, and the measurement is exactly
whether this model, shown its own English PDF and the words "по-русски",
answers `done`. If it does, the mechanism is worthless and comes out.

This is DeepSeek Harness's goal-round-driver reduced to its smallest form:
no goal object, no tool to update it, one question about every request. It
differs from the check the human refused in 4.9 in what it is about — the
request, not a tool — and it is written from no defect's shape.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.stopping import Candidate, Steering
from app.models import Completion, ContentPart, Message, ModelBackend

SOURCE = "goal"

# How many endings one turn may be refused because the goal is not met. Two
# is one round to notice what is missing and one to finish it; a third is a
# model that cannot, and the person is owed the answer it has.
ROUNDS = 2

DONE = "done"
NOT_YET = "not_yet"
BLOCKED = "blocked"

# The question, as the model reads it. A user turn because that is the only
# channel a chat model has mid-turn; framed so it is not answered as if the
# person had typed it. The request is quoted whole.
CHECK = (
    "Turn control (not from the user). The person asked:\n\n{request}\n\n"
    "Did what you did in this turn give them that, as they asked it? Judge "
    "by the tool calls and their results above, not by what your answer "
    "says: something was sent only if a tool that sends it ran. Answer on "
    "the first line with exactly one of: `done` — they have it; `not yet` "
    "— there is work left that you can do now; `blocked: ` and the reason — "
    "you cannot finish. Nothing else."
)

CHECK_SYSTEM = (
    "You are checking your own work in this conversation before it is "
    "handed over. Be exact about the request, not generous to yourself."
)

# What the next step reads when the goal is not yet met. The candidate answer
# is shown beside it (see `carried` in the graph) and is dropped once the
# model does more work, so nothing is delivered twice.
CONTINUE = (
    "The person asked:\n\n{request}\n\nYou said that is not yet done. Do the "
    "rest now with your tools, then answer them. If you find nothing is left "
    "after all, answer with nothing and your answer above is delivered as it "
    "is."
)

# What the next step reads when the model says it is blocked. The answer is
# kept; only a reason the person has not been given is asked for.
EXPLAIN = (
    "You said you are blocked: {reason}. Your answer above is kept and will be "
    "delivered as it is. If it already tells the person why, answer with "
    "nothing; otherwise tell them now, in your own words."
)

WITHOUT_REASON = "no reason given"


def request_of(messages: Sequence[Message]) -> str:
    """The person's words that began the turn. Verbatim, never a paraphrase."""

    for message in messages:
        if message.role == "user":
            text = " ".join(part.text or "" for part in message.content).strip()
            return text or "(their message above, which has no text)"
    return "(their message above)"


def worked(messages: Sequence[Message]) -> bool:
    return any(message.role == "tool" for message in messages)


def verdict(text: str) -> tuple[str, str]:
    """The first line of the model's answer, read as one of three words.

    Anything else counts as `done`: an answer the check cannot read must not
    cost the person a round, and it is recorded so the measurement sees it.
    """

    first = next((line for line in text.splitlines() if line.strip()), "")
    lowered = first.strip().strip("`*'\" ").lower()
    if lowered.startswith("not yet") or lowered.startswith("not_yet"):
        return NOT_YET, ""
    if lowered.startswith("blocked"):
        reason = first.strip().strip("`*'\" ")[len("blocked") :].lstrip(" :.-—")
        return BLOCKED, reason.strip() or WITHOUT_REASON
    return DONE, ""


class MeetsTheRequest:
    """Ask the model whether the turn met the request, and refuse the ending if not.

    The question is one model call of the turn, traced with purpose `goal`,
    and what it answered is the `goal_checked` event's `verdict` — the word,
    never the text. `verdicts` is the same in order, for a caller holding the
    object rather than the trace.
    """

    def __init__(self, backend: ModelBackend, rounds: int = ROUNDS) -> None:
        self.backend = backend
        self.rounds = rounds
        self.verdicts: list[str] = []

    async def stopping(self, candidate: Candidate) -> Steering | None:
        if candidate.steerings >= self.rounds or not worked(candidate.messages):
            return None
        request = request_of(candidate.messages)
        with candidate.trace.model(SOURCE) as measured:
            completion: Completion = await self.backend.invoke(
                [
                    Message(role="system", content=[ContentPart(kind="text", text=CHECK_SYSTEM)]),
                    *candidate.messages,
                    Message(
                        role="user",
                        content=[ContentPart(kind="text", text=CHECK.format(request=request))],
                    ),
                ]
            )
            measured.done(completion)
        word, reason = verdict(completion.text or "")
        self.verdicts.append(word)
        candidate.trace.event("goal_checked", verdict=word, round=candidate.steerings + 1)
        if word == NOT_YET:
            return Steering(CONTINUE.format(request=request), source=f"{SOURCE}:{NOT_YET}")
        if word == BLOCKED:
            return Steering(EXPLAIN.format(reason=reason), source=f"{SOURCE}:{BLOCKED}")
        return None
