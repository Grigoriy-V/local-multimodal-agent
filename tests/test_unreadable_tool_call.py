"""A tool call the served parser could not read, and what reaches the loop.

Measured live on 2026-08-31. The model wrote a page, ended it with a stray
markdown fence, and the string's closing delimiter never arrived; the served
parser read on to the next one, which was inside the *following* tool call. What
came back was a `write_file` with no `path`, carrying fragments of a
`todo_write` as argument names. Nothing reported an error.

Two answers were tried. Asking again without streaming: measured, and the second
answer was corrupt in the same way at twenty-five seconds a time, so there is no
retry here. Cleaning the call before anyone sees it: kept, because it costs
nothing and it keeps another call's text out of the history the model imitates —
it copied its own malformed call three times over.

No network: the transport is a stubbed `httpx` handler. No model, no GPU.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import ModelSettings
from app.models import ToolCall
from app.models.base import CompletionDone, TextDelta
from app.models.openai_compatible import (
    OpenAICompatibleBackend,
    repaired,
    swallowed_name,
    unreadable,
)
from tests.fakes import user

PAGE = "<!DOCTYPE html>\n<h1>Snake</h1>\n```"
BLANK = "\n\n"


def call(**arguments: object) -> ToolCall:
    return ToolCall(id="c1", name="write_file", arguments=arguments)


# --- recognising it -----------------------------------------------------------


def test_an_ordinary_call_is_readable() -> None:
    assert unreadable(call(path="page.html", content="<h1>hi</h1>")) == ""


def test_a_value_ending_in_a_missing_argument_name_is_the_signature() -> None:
    assert "lost the argument 'path'" in unreadable(call(content=f"{PAGE},path:"))


def test_a_name_that_cannot_be_a_parameter_name_is_the_other_signature() -> None:
    """What the live call's later names were: fragments of another call."""

    why = unreadable(
        ToolCall(id="c", name="write_file", arguments={"},{content": "Inspect it."})
    )

    assert "cannot be a parameter name" in why


def test_an_argument_that_is_present_is_not_reported_as_lost() -> None:
    assert unreadable(call(path="a.html", content="see ,path:")) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"{PAGE},path:", "path"),
        ("nothing here", ""),
        ("ends with a colon:", ""),
        ("trailing comma,", ""),
        ("a,not an identifier:", ""),
        ("a,two words:", ""),
    ],
)
def test_only_one_specific_accident_is_recognised(value: str, expected: str) -> None:
    """Narrow on purpose: it recognises an accident, it does not read text."""

    assert swallowed_name(value) == expected


# --- taking out what is provably not the model's ------------------------------


def test_the_value_gets_its_own_tail_back() -> None:
    assert repaired(call(content=f"{PAGE},path:")).arguments["content"] == PAGE


def test_the_lost_argument_is_not_invented() -> None:
    """Its value went into the next name, and a guessed filename is a file
    written somewhere nobody asked for."""

    assert "path" not in repaired(call(content=f"{PAGE},path:")).arguments


def test_another_calls_fragments_are_dropped() -> None:
    spoiled = ToolCall(
        id="c",
        name="write_file",
        arguments={"content": PAGE, "},{content": "Inspect it.", "status": "pending"},
    )

    assert repaired(spoiled).arguments == {"content": PAGE, "status": "pending"}


# --- and what reaches the loop ------------------------------------------------


def backend(handler) -> OpenAICompatibleBackend:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://model.test/v1"
    )
    made = OpenAICompatibleBackend(ModelSettings(endpoint="https://model.test/v1"))
    made._client = client  # noqa: SLF001 - the transport is the point of the test
    return made


def streamed_call(arguments: dict[str, object]) -> str:
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    body = "".join("data: " + json.dumps(chunk) + BLANK for chunk in chunks)
    return body + "data: [DONE]" + BLANK


def streaming(arguments: dict[str, object], seen: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            text=streamed_call(arguments),
            headers={"content-type": "text/event-stream"},
        )

    return handler


async def drain(made: OpenAICompatibleBackend, messages):
    events = [event async for event in made.stream(messages)]
    return [event for event in events if isinstance(event, CompletionDone)][-1].completion


async def test_a_corrupt_call_is_asked_for_exactly_once() -> None:
    """Asking again was measured and did not help, so it is not done."""

    seen: list[str] = []

    finished = await drain(
        backend(streaming({"content": f"{PAGE},path:"}, seen)), [user("write a page")]
    )

    assert len(seen) == 1
    assert finished.tool_calls[0].arguments == {"content": PAGE}


async def test_another_calls_fragments_never_reach_the_conversation() -> None:
    """History the model reads is history the model imitates."""

    seen: list[str] = []
    corrupt = {
        "content": PAGE,
        "},{content": "Inspect the game to ensure it works.",
        "status": "pending",
    }

    finished = await drain(backend(streaming(corrupt, seen)), [user("write a page")])

    assert finished.tool_calls[0].arguments == {"content": PAGE, "status": "pending"}


async def test_a_good_call_passes_through_untouched() -> None:
    seen: list[str] = []
    good = {"path": "snake.html", "content": PAGE}

    finished = await drain(backend(streaming(good, seen)), [user("write a page")])

    assert len(seen) == 1
    assert finished.tool_calls[0].arguments == good


async def test_the_text_already_shown_is_not_unsaid() -> None:
    """A preview the person is reading is not withdrawn over a bad call."""

    spoken = {"choices": [{"delta": {"content": "Writing it now."}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "data: "
                + json.dumps(spoken)
                + BLANK
                + streamed_call({"content": f"{PAGE},path:"})
            ),
            headers={"content-type": "text/event-stream"},
        )

    events = [event async for event in backend(handler).stream([user("write a page")])]

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "Writing it now."
    ]


def test_a_call_cut_at_the_output_limit_is_marked_as_cut() -> None:
    """ISS-0031: `finish_reason == "length"` with unreadable arguments is a
    cut call, not a malformed one, and the executor names the cause."""

    from app.models import Completion
    from app.models.openai_compatible import readable, tool_call

    cut = Completion(
        text="",
        tool_calls=(tool_call("c1", "write_file", '{"path": "a.html", "content": "<html'),),
        finish_reason="length",
    )
    whole = Completion(text="", tool_calls=cut.tool_calls, finish_reason="tool_calls")

    assert readable(cut).tool_calls[0].cut is True
    assert readable(whole).tool_calls[0].cut is False
    assert readable(cut).tool_calls[0].raw_arguments is not None
