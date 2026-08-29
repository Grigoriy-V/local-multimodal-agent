"""Ordinary Markdown into Telegram's small HTML subset, and what it degrades to.

The invariant every test here defends is one sentence: formatting is polish,
and polish must never be a way for an answer to go missing. So each case asks
both questions — did it render, and if it could not, is the whole text still
there to read.
"""

from __future__ import annotations

import pytest

from ui.telegram import markdown
from ui.telegram.api import MAX_MESSAGE_CHARS, Formatted, Piece, pack

# One answer with every construct the baseline promises to render.
RICH = """## Findings

The **first** point, the *second* one, and `inline_code` in passing.

1. Ordered one
2. Ordered two

- Bulleted one
- Bulleted two

> A quoted remark.

See [the notes](https://example.com/notes).

```python
print("hello")
```
"""


def html_of(text: str) -> str:
    return Formatted.from_markdown(text).html


def test_every_promised_construct_renders_into_telegram_markup() -> None:
    rendered = html_of(RICH)

    assert "<b>Findings</b>" in rendered
    assert "<b>first</b>" in rendered
    assert "<i>second</i>" in rendered
    assert "<code>inline_code</code>" in rendered
    assert "1. Ordered one" in rendered and "2. Ordered two" in rendered
    assert "• Bulleted one" in rendered
    assert "<blockquote>A quoted remark.</blockquote>" in rendered
    assert '<a href="https://example.com/notes">the notes</a>' in rendered
    assert '<pre><code class="language-python">print(&quot;hello&quot;)' in rendered or (
        '<pre><code class="language-python">print("hello")' in rendered
    )
    assert markdown.balanced(rendered)


def test_no_markdown_punctuation_survives_into_the_rendered_text() -> None:
    """A raw `**` on screen is the whole failure this replaces."""

    rendered = html_of(RICH)

    assert "**" not in rendered
    assert "##" not in rendered
    assert "```" not in rendered


def test_the_plain_reading_keeps_every_word() -> None:
    plain = Formatted.from_markdown(RICH).plain

    for word in ("Findings", "first", "second", "inline_code", "Ordered two", "Bulleted two"):
        assert word in plain
    assert "https://example.com/notes" in plain
    assert 'print("hello")' in plain


@pytest.mark.parametrize(
    "text",
    [
        "**unclosed bold and `unclosed code",
        "a * b * c and 2 ** 3",
        "snake_case_name stays whole",
        "[a link with no target](javascript:alert(1))",
        "<b>markup the model wrote itself</b> & co.",
        "~~~~~~",
        "#",
    ],
)
def test_markup_that_cannot_be_rendered_is_still_delivered_whole(text: str) -> None:
    """Malformed and unsupported input degrades to text, never to a failure."""

    rendered = Formatted.from_markdown(text)

    assert markdown.balanced(rendered.html)
    for word in text.replace("*", " ").replace("`", " ").split():
        if word.isalnum():
            assert word in rendered.plain


def test_an_underscore_inside_a_word_is_not_emphasis() -> None:
    rendered = html_of("call read_file then write_file")

    assert "<i>" not in rendered
    assert "read_file" in rendered and "write_file" in rendered


def test_a_link_the_project_would_not_offer_stays_literal_text() -> None:
    """A rendered link is an invitation to tap, and this does not extend one."""

    rendered = html_of("[click](javascript:alert(1)) and [ok](https://example.com)")

    assert '<a href="javascript' not in rendered
    assert "click" in rendered
    assert '<a href="https://example.com">ok</a>' in rendered


def test_model_written_html_is_escaped_rather_than_trusted() -> None:
    rendered = html_of("The tag <script>alert(1)</script> is not markup here.")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_a_renderer_failure_still_delivers_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last line of defence, asserted rather than assumed."""

    def explode(_text: str) -> list[tuple[str, str]]:
        raise RuntimeError("the renderer is broken")

    monkeypatch.setattr(markdown, "render", explode)
    rendered = Formatted.from_markdown("**important** answer")

    assert rendered.plain == "**important** answer"
    assert markdown.balanced(rendered.html)


def test_unbalanced_markup_is_replaced_by_its_plain_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def half_a_tag(_text: str) -> list[tuple[str, str]]:
        return [("<b>only half", "only half")]

    monkeypatch.setattr(markdown, "render", half_a_tag)

    assert Formatted.from_markdown("only half").html == "only half"


# --- splitting ---------------------------------------------------------------


def test_a_long_answer_is_cut_between_blocks_and_never_inside_one() -> None:
    paragraphs = "\n\n".join(f"**Point {index}** of the answer." for index in range(400))

    pieces = pack(Formatted.from_markdown(paragraphs).blocks)

    assert pieces is not None and len(pieces) > 1
    for piece in pieces:
        assert len(piece.text) <= MAX_MESSAGE_CHARS
        assert markdown.balanced(piece.text)
    assert "Point 399" in "".join(piece.text for piece in pieces)


def test_a_block_too_long_to_send_refuses_rather_than_cutting_a_tag() -> None:
    """Refusing is what makes the caller fall back to complete plain text."""

    assert pack([("<b>" + "x" * MAX_MESSAGE_CHARS + "</b>", "x")]) is None


def test_a_very_long_code_block_stays_formatted_by_becoming_several() -> None:
    code = "\n".join(f"print({index})" for index in range(1500))

    pieces = pack(Formatted.from_markdown(f"```python\n{code}\n```").blocks)

    assert pieces is not None and len(pieces) > 1
    for piece in pieces:
        assert markdown.balanced(piece.text)
        assert piece.text.startswith("<pre>")
    assert "print(1499)" in "".join(piece.text for piece in pieces)


def test_a_piece_carries_the_plain_text_it_means() -> None:
    """Which is what gets sent if Telegram refuses to parse the markup."""

    pieces = pack(Formatted.from_markdown("**bold** words").blocks)

    assert pieces == [Piece("<b>bold</b> words", "bold words")]
