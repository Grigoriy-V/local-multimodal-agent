"""A tool call the server could not read, and the turn carrying on anyway.

The live failure of 2026-08-31: the model wrote a page that ended in a markdown
fence, the served parser lost the string's closing delimiter, and what arrived
was a `write_file` whose `content` ended in `,path:` and which had no `path` at
all. Nothing reported an error. The model then repeated that call eight times,
because its own malformed call was in the history it was reading.

This is the client's answer: recognise it, throw the completion away before the
loop or the conversation ever sees it, and ask once more without streaming.

No network — the transport is a stubbed `httpx` handler. No model, no GPU.
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


def call(**arguments: object) -> ToolCall:
    return ToolCall(id="c1", name="write_file", arguments=arguments)


# --- recognising it -----------------------------------------------------------


def test_an_ordinary_call_is_readable() -> None:
    assert unreadable(call(path="page.html", content="<h1>hi</h1>")) == ""


def test_a_value_ending_in_a_missing_argument_name_is_the_signature() -> None:
    why = unreadable(call(content=f"{PAGE},path:"))

    assert "lost the argument 'path'" in why


def test_a_name_that_cannot_be_a_parameter_name_is_the_other_signature() -> None:
    """What the live call's later keys looked like: fragments of a value."""

    why = unreadable(
        ToolCall(id="c", name="write_file", arguments={"},{content": "Inspect it."})
    )

    assert "cannot be a parameter name" in why


def test_an_argument_that_is_present_is_not_reported_as_lost() -> None:
    """Text that merely ends this way, with the argument really there."""

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
    """Narrow on purpose: this recognises an accident, it does not read text."""

    assert swallowed_name(value) == expected


# --- repairing what is recoverable -------------------------------------------


def test_the_value_gets_its_own_tail_back() -> None:
    """`content` really did end at the page, and that much is certain."""

    mended = repaired(call(content=f"{PAGE},path:"))

    assert mended.arguments["content"] == PAGE


def test_the_lost_argument_is_not_invented() -> None:
    """Its value went into the next name. Guessing a filename is not a repair."""

    assert "path" not in repaired(call(content=f"{PAGE},path:")).arguments


# --- and the turn carries on --------------------------------------------------


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
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def whole_call(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c2",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def drain(made: OpenAICompatibleBackend, messages):
    events = [event async for event in made.stream(messages)]
    return [event for event in events if isinstance(event, CompletionDone)][-1].completion


async def test_a_corrupt_streamed_call_is_asked_for_again() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append("stream" if body.get("stream") else "whole")
        if body.get("stream"):
            return httpx.Response(
                200,
                text=streamed_call({"content": f"{PAGE},path:"}),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=whole_call({"path": "snake.html", "content": PAGE}))

    finished = await drain(backend(handler), [user("write a page")])

    # The second request was not streamed, and what the loop receives is the
    # call the model meant to make.
    assert seen == ["stream", "whole"]
    assert finished.tool_calls[0].arguments == {"path": "snake.html", "content": PAGE}


async def test_a_good_streamed_call_is_never_asked_for_twice() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            text=streamed_call({"path": "snake.html", "content": PAGE}),
            headers={"content-type": "text/event-stream"},
        )

    finished = await drain(backend(handler), [user("write a page")])

    assert len(seen) == 1
    assert finished.tool_calls[0].arguments["path"] == "snake.html"


async def test_a_second_corruption_is_repaired_and_delivered_rather_than_retried() -> None:
    """One retry, not a loop. A tool error the model can read is the floor."""

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append("stream" if body.get("stream") else "whole")
        if body.get("stream"):
            return httpx.Response(
                200,
                text=streamed_call({"content": f"{PAGE},path:"}),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=whole_call({"content": f"{PAGE},path:"}))

    finished = await drain(backend(handler), [user("write a page")])

    assert seen == ["stream", "whole"]
    assert finished.tool_calls[0].arguments == {"content": PAGE}


async def test_the_text_of_a_corrupt_completion_still_reached_the_reader() -> None:
    """A preview already shown is not unsaid; only the tool call is replaced."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("stream"):
            return httpx.Response(
                200,
                text=(
                    'data: {"choices":[{"delta":{"content":"Writing it now."}}]}\n\n'
                    + streamed_call({"content": f"{PAGE},path:"})
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=whole_call({"path": "snake.html", "content": PAGE}))

    made = backend(handler)
    events = [event async for event in made.stream([user("write a page")])]

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "Writing it now."
    ]
