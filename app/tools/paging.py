"""Reading a long text in parts.

A result is capped before it reaches the model, and until 2026-09-03 the
middle of anything past the cap was out of reach for good: `read_file` cut a
file at its limit with "truncated", and there was no way to ask for the rest.
The cap is right — one result must not take the request — but the reach was
not. `page` is the one shape every capped reader now shares: a window on the
text, and a sentence at the end that says exactly what to call to keep going.
"""

from __future__ import annotations

from app.tools.base import BAD_ARGUMENTS, ToolError


def page(text: str, offset: int, size: int, more: str) -> str:
    """`size` characters of `text` from `offset`, and how to get the next ones.

    `more` names the call for the rest, with `{offset}` where the next offset
    goes — "read_file again with offset={offset}". The sentence is only added
    when there is a rest.
    """

    if offset < 0:
        raise ToolError("offset must be zero or more", code=BAD_ARGUMENTS)
    if offset and offset >= len(text):
        raise ToolError(
            f"offset {offset} is past the end: the text is {len(text)} characters",
            code=BAD_ARGUMENTS,
        )
    body = text[offset : offset + size]
    end = offset + len(body)
    if end >= len(text):
        return body
    call = more.format(offset=end)
    return (
        f"{body}\n... showing characters {offset}-{end} of {len(text)}; "
        f"for the rest, {call}"
    )
