"""The served parser's defects, reproduced offline, and a corrected copy.

Gemma 4 tool arguments are not JSON. `vllm/parser/gemma4.py` reads a compact
format in which a string is wrapped in the token `<|"|>`, and `tools/
gemma4_parser.py` holds that code verbatim beside a corrected copy. Everything
here runs on strings. No model, no server, no GPU.

Three subjects:

- **51284** — the model writes a string as an ordinary quoted literal instead of
  using the delimiter, and the parser reads until the next comma or brace, so
  the value swallows what follows it.
- **53431** — the model opens a call with `<|tool_call>:name{…}` instead of
  `<|tool_call>call:name{…}`, and the shipped grammar drops it in silence.
- **this project's own failure**, which is neither: an argument span in which
  one string's closing delimiter is also the next one's opening delimiter. It
  is reproduced from the page the model really wrote, and the corrected parser
  refuses it instead of inventing a call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.gemma4_parser import (
    CorruptArguments,
    STRING_DELIM,
    extract_calls,
    fixed_args,
    parse_arguments,
    read_quoted,
    vendored_args,
    vendored_array,
)

MERGED = Path("tests/fixtures/gemma4_merged_call.txt")


def wrapped(value: str) -> str:
    return f"{STRING_DELIM}{value}{STRING_DELIM}"


# --- what the format is, and what both parsers agree about -------------------


def test_the_delimiter_form_reads_the_same_in_both() -> None:
    span = f"path:{wrapped('page.html')},count:42"

    assert vendored_args(span) == {"path": "page.html", "count": "42"}
    assert parse_arguments(span) == {"path": "page.html", "count": "42"}


def test_a_delimited_string_may_hold_anything_at_all() -> None:
    """Which is why the delimiter exists: it cannot occur inside itself."""

    page = '<style>body{margin:0}</style><p class="x">a, b</p>'
    span = f"content:{wrapped(page)},path:{wrapped('p.html')}"

    assert vendored_args(span) == {"content": page, "path": "p.html"}
    assert parse_arguments(span) == {"content": page, "path": "p.html"}


def test_nested_objects_and_arrays_survive_the_delimiter_form() -> None:
    """The `todos` shape, which was blamed for the live failure and is fine."""

    span = (
        f"todos:[{{content:{wrapped('write it')},status:{wrapped('completed')}}},"
        f"{{content:{wrapped('look at it')},status:{wrapped('pending')}}}]"
    )

    expected = [
        {"content": "write it", "status": "completed"},
        {"content": "look at it", "status": "pending"},
    ]
    assert vendored_args(span) == {"todos": expected}
    assert parse_arguments(span) == {"todos": expected}


# --- issue 51284: a string written as an ordinary quoted literal -------------


def test_a_quoted_value_containing_a_comma_swallows_the_next_argument() -> None:
    span = 'content:"a, b",path:"page.html"'

    spoiled = vendored_args(span)
    assert spoiled["content"] == '"a'
    assert "path" not in spoiled

    assert parse_arguments(span) == {"content": "a, b", "path": "page.html"}


def test_a_quoted_value_containing_a_brace_ends_the_object_early() -> None:
    """The object closes on the page's own brace, so the value is cut in half.

    Here the damage stays inside one value rather than eating the next
    argument, which is the same defect at a different cost.
    """

    span = 'style:{css:"body{margin:0}"},path:"p.html"'

    assert vendored_args(span)["style"] == {"css": '"body{margin:0'}
    assert parse_arguments(span) == {"style": {"css": "body{margin:0}"}, "path": "p.html"}


def test_quotes_are_content_to_the_vendored_array_parser() -> None:
    """51284's own example: the quotes end up inside the value."""

    assert vendored_array('"ds_152a4bfd970b4313"') == ['"ds_152a4bfd970b4313"']


def test_an_escaped_quote_does_not_end_the_string() -> None:
    span = 'content:"he said \\"no\\", then left",path:"a.txt"'

    assert parse_arguments(span) == {
        "content": 'he said "no", then left',
        "path": "a.txt",
    }


def test_an_unterminated_quoted_string_is_a_value_and_not_a_key() -> None:
    value, position = read_quoted('"half a pag', 0)

    assert value == "half a pag"
    assert position == len('"half a pag')


def test_a_quoted_key_is_read_as_a_key() -> None:
    assert fixed_args('"path":"a.txt"') == {"path": "a.txt"}


# --- issue 53431: the opener the grammar does not know -----------------------


def test_the_documented_opener_is_read() -> None:
    text = f"<|tool_call>call:get_weather{{city:{wrapped('Tokyo')}}}<tool_call|>"

    assert extract_calls(text) == [("get_weather", f"city:{wrapped('Tokyo')}")]


def test_the_bare_opener_is_read_too() -> None:
    """`<|tool_call>:name{…}`, which the shipped grammar discards in silence."""

    text = f"<|tool_call>:get_weather{{city:{wrapped('Tokyo')}}}<tool_call|>"

    assert extract_calls(text) == [("get_weather", f"city:{wrapped('Tokyo')}")]


def test_a_call_closed_with_the_turn_tag_is_still_a_call() -> None:
    text = f"<|tool_call>call:ping{{}}<turn|>"

    assert extract_calls(text) == [("ping", "")]


def test_two_calls_stay_two_calls() -> None:
    text = (
        f"<|tool_call>call:write_file{{path:{wrapped('a.html')}}}<tool_call|>"
        f"<|tool_call>call:todo_write{{todos:[]}}<tool_call|>"
    )

    assert [name for name, _ in extract_calls(text)] == ["write_file", "todo_write"]


def test_a_call_whose_arguments_contain_braces_is_not_cut_short() -> None:
    """A lazy `{(.*?)}` ends this call inside the page's own CSS."""

    page = "<style>body{margin:0}</style>"
    text = f"<|tool_call>call:write_file{{content:{wrapped(page)}}}<tool_call|>"

    name, args = extract_calls(text)[0]
    assert name == "write_file"
    assert parse_arguments(args) == {"content": page}


# --- this project's own failure ----------------------------------------------


def test_the_live_corruption_is_reproduced_from_the_page_the_model_wrote() -> None:
    """The recorded call, rebuilt and re-derived rather than described.

    The fixture is a reconstruction, not a captured emission: vLLM hands over
    parsed arguments and never the text behind them. It is the reconstruction
    that reproduces the stored call exactly — one span in which the closing
    delimiter of `content` is also the opening delimiter of the next string —
    which is the evidence that this is what the parser was given.
    """

    span = MERGED.read_text(encoding="utf-8")

    spoiled = vendored_args(span)

    keys = list(spoiled)
    assert keys[0] == "content"
    assert spoiled["content"].startswith("<!DOCTYPE html>")
    # The two keys that are not parameter names, exactly as recorded live.
    assert keys[1] == (
        "Create snake_game.html with a basic snake game implementation."
        f"{STRING_DELIM},status"
    )
    assert keys[2] == "},{content"
    assert spoiled[keys[2]] == "Inspect the game to ensure it works."
    # And the argument the tool actually needs is gone.
    assert "path" not in spoiled


def test_the_corrected_parser_refuses_that_span_instead_of_inventing_a_call() -> None:
    """A call nobody made is worse than no call.

    The quoted-literal fix does not rescue this input and is not meant to: the
    delimiter that would have ended the string is already lost, so no reading
    of it is the model's intent. What can be said is that a parameter name
    never contains a brace or a delimiter — and a span whose names do is not a
    call.
    """

    with pytest.raises(CorruptArguments):
        parse_arguments(MERGED.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "span",
    [
        # A closing delimiter read as an opening one, in miniature.
        f"content:{wrapped('x')}a{STRING_DELIM},status:{wrapped('done')}",
        # An object's contents read as top-level names.
        f"a:{wrapped('1')}}},{{b:{wrapped('2')}",
    ],
)
def test_a_name_that_cannot_be_a_parameter_name_refuses_the_call(span: str) -> None:
    with pytest.raises(CorruptArguments):
        parse_arguments(span)


def test_an_ordinary_call_is_not_refused_by_the_guard() -> None:
    """The guard must not cost anything on the calls that work."""

    span = f"path:{wrapped('Снейк_Гейм.html')},content:{wrapped('<h1>hi</h1>')}"

    assert parse_arguments(span) == {
        "path": "Снейк_Гейм.html",
        "content": "<h1>hi</h1>",
    }


def test_a_streaming_fragment_is_never_refused() -> None:
    """Half a span is not corrupt; it is half a span."""

    assert parse_arguments("content:{half:", partial=True) is not None
