"""Ordinary Markdown, rendered into the small subset Telegram actually has.

The assistant writes ordinary Markdown. That is the canonical answer, it is
what gets persisted, and it is what a second interface would render its own
way. This module is the Telegram half of that: it turns those few constructs
that materially help a reader — headings, emphasis, lists, quotes, code and
links — into Telegram's HTML, and leaves everything else as readable text.

Two properties are load-bearing.

*Every block stands alone.* The result is a list of `(html, plain)` pairs, each
independently valid, because Telegram refuses a message whose tags are cut in
half and a long answer has to be split somewhere. Splitting between blocks can
never cut a tag; splitting inside one can, so it is never done.

*Nothing here can lose an answer.* Unbalanced markup is emitted as text rather
than as a tag, an unparseable link stays literal, and `render` is called behind
a `try` in `api.py` that falls back to the plain rendering. Formatting is
presentation polish, and polish must not become a way for a reply to disappear.

Standard library only, like `wire.py`, so importing it costs nothing.
"""

from __future__ import annotations

import re
from html import escape

# Telegram's own limit is 4096 characters for the whole message. A fenced code
# block is the one construct that can exceed it on its own, so it is cut into
# several blocks; the margin leaves room for the wrapper tags and for the block
# to be packed alongside a neighbour.
MAX_CODE_CHARS = 3400

# How deeply inline emphasis may nest before the rest is treated as text. Real
# prose never approaches this; a pathological run of asterisks would otherwise
# recurse once per pair.
MAX_INLINE_DEPTH = 6

# The tags this renderer emits, which is also the set `api.py` validates
# against. Telegram supports a few more; adding one here means teaching the
# renderer to close it correctly.
ALLOWED_TAGS = frozenset({"b", "i", "s", "u", "code", "pre", "a", "blockquote"})

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(```+|~~~+)\s*([^\s`]*)\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_LINK = re.compile(r"\[([^\]\n]*)\]\(([^()\s]+)\)")
_LANGUAGE = re.compile(r"^[A-Za-z0-9+#._-]{1,20}$")
_TAG = re.compile(r"<(/?)([a-z]+)(?:\s[^>]*)?>")

# Schemes a link may use. Anything else stays literal text: a rendered link is
# something a person is invited to tap, and `javascript:` or `file:` is not an
# invitation this project extends on the model's behalf.
SAFE_SCHEMES = ("http://", "https://", "tg://", "mailto:")


def render(text: str) -> list[tuple[str, str]]:
    """Render Markdown into independently valid `(html, plain)` blocks."""

    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = _FENCE.match(line)
        if fence:
            index, block = _read_fence(lines, index, fence)
            blocks.extend(block)
            continue

        heading = _HEADING.match(line)
        if heading:
            html, plain = _inline(heading.group(2))
            if plain.strip():
                blocks.append((f"<b>{html}</b>", plain))
            index += 1
            continue

        if _QUOTE.match(line):
            index, block = _read_quote(lines, index)
            blocks.append(block)
            continue

        if _BULLET.match(line) or _NUMBER.match(line):
            index, block = _read_list(lines, index)
            blocks.append(block)
            continue

        index, block = _read_paragraph(lines, index)
        blocks.append(block)

    return [block for block in blocks if block[0] or block[1]]


# --- blocks ------------------------------------------------------------------


def _read_fence(
    lines: list[str], index: int, fence: re.Match[str]
) -> tuple[int, list[tuple[str, str]]]:
    """Read a fenced code block, which is the one block that may be split."""

    marker = fence.group(1)[0] * 3
    language = fence.group(2) if _LANGUAGE.match(fence.group(2) or "") else ""
    body: list[str] = []
    index += 1
    while index < len(lines):
        closing = _FENCE.match(lines[index])
        if closing and closing.group(1).startswith(marker) and not closing.group(2):
            index += 1
            break
        body.append(lines[index])
        index += 1
    code = "\n".join(body)
    if not code.strip():
        return index, []

    blocks: list[tuple[str, str]] = []
    for chunk in _chunk(code, MAX_CODE_CHARS):
        opening = f'<pre><code class="language-{language}">' if language else "<pre>"
        closing_tag = "</code></pre>" if language else "</pre>"
        blocks.append((f"{opening}{escape(chunk, quote=False)}{closing_tag}", chunk))
    return index, blocks


def _read_quote(lines: list[str], index: int) -> tuple[int, tuple[str, str]]:
    body: list[str] = []
    while index < len(lines):
        quoted = _QUOTE.match(lines[index])
        if not quoted:
            break
        body.append(quoted.group(1))
        index += 1
    html, plain = _inline("\n".join(body))
    return index, (f"<blockquote>{html}</blockquote>", "\n".join(f"> {p}" for p in plain.split("\n")))


def _read_list(lines: list[str], index: int) -> tuple[int, tuple[str, str]]:
    """Read one run of list items.

    Telegram has no list markup, so the shape is carried by the text itself: a
    bullet character, or the number the author wrote. Indentation is kept so a
    nested list still reads as one.
    """

    html_items: list[str] = []
    plain_items: list[str] = []
    while index < len(lines):
        line = lines[index]
        bullet, number = _BULLET.match(line), _NUMBER.match(line)
        if bullet:
            indent, marker, content = bullet.group(1), "•", bullet.group(2)
        elif number:
            indent, marker, content = number.group(1), f"{number.group(2)}.", number.group(3)
        else:
            break
        html, plain = _inline(content)
        pad = " " * min(len(indent), 8)
        html_items.append(f"{pad}{marker} {html}")
        plain_items.append(f"{pad}{marker} {plain}")
        index += 1
    return index, ("\n".join(html_items), "\n".join(plain_items))


def _read_paragraph(lines: list[str], index: int) -> tuple[int, tuple[str, str]]:
    body: list[str] = []
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            break
        if _FENCE.match(line) or _HEADING.match(line) or _QUOTE.match(line):
            break
        if _BULLET.match(line) or _NUMBER.match(line):
            break
        body.append(line.rstrip())
        index += 1
    return index, _inline("\n".join(body))


def _chunk(text: str, limit: int) -> list[str]:
    """Cut text at line boundaries, hard-cutting only a single overlong line."""

    pieces: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [text]


# --- inline ------------------------------------------------------------------


def _inline(text: str, depth: int = 0) -> tuple[str, str]:
    """Render one span of text, returning its HTML and its plain reading.

    Both are produced in the same pass so they cannot describe different
    content: the plain form is what gets sent when Telegram refuses the HTML,
    and a fallback that said something else would be worse than no fallback.
    """

    marked: list[str] = []
    plain: list[str] = []
    position, end = 0, len(text)
    while position < end:
        character = text[position]
        consumed = 0

        if character == "`":
            consumed = _code_span(text, position, marked, plain)
        elif character == "[":
            consumed = _link(text, position, marked, plain, depth)
        elif text.startswith("**", position) or text.startswith("__", position):
            consumed = _paired(text, position, text[position : position + 2], "b", marked, plain, depth)
        elif text.startswith("~~", position):
            consumed = _paired(text, position, "~~", "s", marked, plain, depth)
        elif character in "*_":
            consumed = _emphasis(text, position, character, marked, plain, depth)

        if consumed:
            position += consumed
            continue
        marked.append(escape(character, quote=False))
        plain.append(character)
        position += 1
    return "".join(marked), "".join(plain)


def _code_span(text: str, position: int, marked: list[str], plain: list[str]) -> int:
    rest = text[position:]
    run = len(rest) - len(rest.lstrip("`"))
    closing = text.find("`" * run, position + run)
    if closing == -1:
        return 0
    inner = text[position + run : closing]
    if not inner:
        return 0
    marked.append(f"<code>{escape(inner, quote=False)}</code>")
    plain.append(inner)
    return closing + run - position


def _link(text: str, position: int, marked: list[str], plain: list[str], depth: int) -> int:
    found = _LINK.match(text, position)
    if not found:
        return 0
    url = found.group(2)
    if not url.lower().startswith(SAFE_SCHEMES):
        return 0
    label_html, label_plain = _inline(found.group(1), depth + 1)
    if not label_plain.strip():
        label_html, label_plain = escape(url, quote=False), url
    marked.append(f'<a href="{escape(url, quote=True)}">{label_html}</a>')
    plain.append(label_plain if label_plain == url else f"{label_plain} ({url})")
    return found.end() - position


def _paired(
    text: str,
    position: int,
    marker: str,
    tag: str,
    marked: list[str],
    plain: list[str],
    depth: int,
) -> int:
    if depth >= MAX_INLINE_DEPTH:
        return 0
    start = position + len(marker)
    closing = text.find(marker, start)
    if closing <= start:
        return 0
    inner_html, inner_plain = _inline(text[start:closing], depth + 1)
    marked.append(f"<{tag}>{inner_html}</{tag}>")
    plain.append(inner_plain)
    return closing + len(marker) - position


def _emphasis(
    text: str, position: int, marker: str, marked: list[str], plain: list[str], depth: int
) -> int:
    """Single `*` or `_`, which is emphasis only where it cannot be punctuation.

    `snake_case` and `a * b` are far more common in an assistant's output than
    single-underscore italics, so the guards are deliberately strict: a marker
    that would open inside a word, or close after a space, stays literal.
    """

    if depth >= MAX_INLINE_DEPTH:
        return 0
    before = text[position - 1] if position else ""
    if marker == "_" and (before.isalnum() or before == "_"):
        return 0
    after = text[position + 1 : position + 2]
    if not after or after.isspace() or after == marker:
        return 0

    search = position + 1
    while True:
        closing = text.find(marker, search)
        if closing == -1 or closing == position + 1:
            return 0
        if text[closing - 1].isspace():
            search = closing + 1
            continue
        following = text[closing + 1 : closing + 2]
        if marker == "_" and (following.isalnum() or following == "_"):
            search = closing + 1
            continue
        break

    inner_html, inner_plain = _inline(text[position + 1 : closing], depth + 1)
    marked.append(f"<i>{inner_html}</i>")
    plain.append(inner_plain)
    return closing + 1 - position


# --- the safety net ----------------------------------------------------------


def balanced(html: str) -> bool:
    """Is every tag in this fragment one Telegram knows, opened and closed?

    Cheap, and checked on every block before it is sent. The renderer is meant
    to be correct; this is what makes "meant to be" not the last word.
    """

    open_tags: list[str] = []
    for match in _TAG.finditer(html):
        name = match.group(2)
        if name not in ALLOWED_TAGS:
            return False
        if match.group(1):
            if not open_tags or open_tags.pop() != name:
                return False
        else:
            open_tags.append(name)
    return not open_tags
