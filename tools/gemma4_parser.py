"""The served model's tool-argument parser, and a corrected copy of it.

Gemma 4 does not emit JSON tool arguments. It emits a compact form of its own,
in which a string is wrapped in the delimiter token `<|"|>`:

    path:<|"|>page.html<|"|>,count:42,items:[<|"|>a<|"|>,<|"|>b<|"|>]

`vllm/parser/gemma4.py` turns that back into a dict. **The model does not always
use the delimiter.** When it writes a string as an ordinary quoted literal
instead, the parser has no idea a string has begun: it reads until the next
comma or brace, so a value containing either one runs into the following keys
and takes them with it. That is vLLM issue 51284, and it is what produced a
`write_file` call in this project holding another tool's fields and no `path`
— twice live, and once in a measured scenario run.

This module holds two things and no policy:

- `vendored_args` / `vendored_array`: copied verbatim from vLLM 0.26.0
  (Apache-2.0), so the failure can be reproduced offline instead of argued
  about. The only change is the removal of vLLM's logger.
- `fixed_args` / `fixed_array`: the same functions with the delimiter no longer
  the only way to write a string. A value that opens with `"` or `'` is read as
  a quoted literal, honouring backslash escapes, and the quotes are stripped.

Nothing here runs in the product. It exists to prove which of the two parsers
turns real model output into the corrupted call this project recorded, and to
be the thing a served-side fix is tested against before anything is redeployed.
"""

from __future__ import annotations

from typing import Any

STRING_DELIM = '<|"|>'
_DELIM_LEN = len(STRING_DELIM)
_QUOTES = ('"', "'")

_PARTIAL_DELIM_SUFFIXES = tuple(STRING_DELIM[:k] for k in range(len(STRING_DELIM), 0, -1))


def _strip_partial_delim(value: str) -> str:
    for suffix in _PARTIAL_DELIM_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


# --- vendored from vllm/parser/gemma4.py at v0.26.0, Apache-2.0 --------------


def vendored_args(args_str: str, *, partial: bool = False) -> dict:
    if not args_str or not args_str.strip():
        return {}

    result: dict = {}
    i = 0
    n = len(args_str)

    while i < n:
        while i < n and args_str[i] in (" ", ",", "\n", "\t"):
            i += 1
        if i >= n:
            break

        key_start = i
        while i < n and args_str[i] != ":":
            i += 1
        if i >= n:
            break
        key = args_str[key_start:i].strip()
        if key.startswith(STRING_DELIM) and key.endswith(STRING_DELIM):
            key = key[_DELIM_LEN:-_DELIM_LEN]
        i += 1

        if i >= n:
            if not partial:
                result[key] = ""
            break

        while i < n and args_str[i] in (" ", "\n", "\t"):
            i += 1
        if i >= n:
            if not partial:
                result[key] = ""
            break

        if args_str[i : i + _DELIM_LEN] == STRING_DELIM:
            i += _DELIM_LEN
            val_start = i
            end_pos = args_str.find(STRING_DELIM, i)
            if end_pos == -1:
                value = args_str[val_start:]
                if partial:
                    value = _strip_partial_delim(value)
                result[key] = value
                break
            result[key] = args_str[val_start:end_pos]
            i = end_pos + _DELIM_LEN

        elif args_str[i] == "{":
            depth = 1
            obj_start = i + 1
            i += 1
            while i < n and depth > 0:
                if args_str[i : i + _DELIM_LEN] == STRING_DELIM:
                    i += _DELIM_LEN
                    next_delim = args_str.find(STRING_DELIM, i)
                    i = n if next_delim == -1 else next_delim + _DELIM_LEN
                    continue
                if args_str[i] == "{":
                    depth += 1
                elif args_str[i] == "}":
                    depth -= 1
                i += 1
            if depth > 0:
                result[key] = vendored_args(args_str[obj_start:i], partial=True)
            else:
                result[key] = vendored_args(args_str[obj_start : i - 1])

        elif args_str[i] == "[":
            depth = 1
            arr_start = i + 1
            i += 1
            while i < n and depth > 0:
                if args_str[i : i + _DELIM_LEN] == STRING_DELIM:
                    i += _DELIM_LEN
                    next_delim = args_str.find(STRING_DELIM, i)
                    i = n if next_delim == -1 else next_delim + _DELIM_LEN
                    continue
                if args_str[i] == "[":
                    depth += 1
                elif args_str[i] == "]":
                    depth -= 1
                i += 1
            if depth > 0:
                result[key] = vendored_array(args_str[arr_start:i], partial=True)
            else:
                result[key] = vendored_array(args_str[arr_start : i - 1])

        else:
            val_start = i
            while i < n and args_str[i] not in (",", "}", "]"):
                i += 1
            if partial and i >= n:
                break
            if i == val_start:
                break
            raw_val = args_str[val_start:i].strip()
            if partial and raw_val.endswith("."):
                break
            result[key] = raw_val

    return result


def vendored_array(arr_str: str, *, partial: bool = False) -> list:
    items: list = []
    i = 0
    n = len(arr_str)

    while i < n:
        while i < n and arr_str[i] in (" ", ",", "\n", "\t"):
            i += 1
        if i >= n:
            break

        if arr_str[i : i + _DELIM_LEN] == STRING_DELIM:
            i += _DELIM_LEN
            end_pos = arr_str.find(STRING_DELIM, i)
            if end_pos == -1:
                items.append(arr_str[i:])
                break
            items.append(arr_str[i:end_pos])
            i = end_pos + _DELIM_LEN

        elif arr_str[i] == "{":
            depth = 1
            obj_start = i + 1
            i += 1
            while i < n and depth > 0:
                if arr_str[i : i + _DELIM_LEN] == STRING_DELIM:
                    i += _DELIM_LEN
                    nd = arr_str.find(STRING_DELIM, i)
                    i = nd + _DELIM_LEN if nd != -1 else n
                    continue
                if arr_str[i] == "{":
                    depth += 1
                elif arr_str[i] == "}":
                    depth -= 1
                i += 1
            if depth > 0:
                items.append(vendored_args(arr_str[obj_start:i], partial=True))
            else:
                items.append(vendored_args(arr_str[obj_start : i - 1]))

        elif arr_str[i] == "[":
            depth = 1
            sub_start = i + 1
            i += 1
            while i < n and depth > 0:
                if arr_str[i : i + _DELIM_LEN] == STRING_DELIM:
                    i += _DELIM_LEN
                    nd = arr_str.find(STRING_DELIM, i)
                    i = nd + _DELIM_LEN if nd != -1 else n
                    continue
                if arr_str[i] == "[":
                    depth += 1
                elif arr_str[i] == "]":
                    depth -= 1
                i += 1
            if depth > 0:
                items.append(vendored_array(arr_str[sub_start:i], partial=True))
            else:
                items.append(vendored_array(arr_str[sub_start : i - 1]))

        else:
            val_start = i
            while i < n and arr_str[i] not in (",", "]"):
                i += 1
            if partial and i >= n:
                break
            if i == val_start:
                break
            raw_val = arr_str[val_start:i].strip()
            if partial and raw_val.endswith("."):
                break
            items.append(raw_val)

    return items


# --- the correction ----------------------------------------------------------


def read_quoted(text: str, start: int) -> tuple[str, int]:
    """Read one ordinary quoted literal, returning its value and where it ends.

    The delimiter form cannot contain its own terminator, so the vendored code
    can find the end with `str.find`. A quoted literal can: `"</div>\\"x\\""` is
    one string, and stopping at the first inner quote is how a value spills into
    the keys after it. So this walks the string and honours the backslash.
    """

    quote = text[start]
    out: list[str] = []
    i = start + 1
    n = len(text)
    while i < n:
        char = text[i]
        if char == "\\" and i + 1 < n:
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            i += 2
            continue
        if char == quote:
            return "".join(out), i + 1
        out.append(char)
        i += 1
    # Unterminated: everything that arrived is the value. Streaming ends here
    # legitimately, and a truncated emission is better read as a long string
    # than as a key nobody wrote.
    return "".join(out), n


def fixed_args(args_str: str, *, partial: bool = False) -> dict[str, Any]:
    """`vendored_args` with quoted literals recognised as strings."""

    if not args_str or not args_str.strip():
        return {}

    result: dict[str, Any] = {}
    i = 0
    n = len(args_str)

    while i < n:
        while i < n and args_str[i] in (" ", ",", "\n", "\t"):
            i += 1
        if i >= n:
            break

        # A key may itself be quoted, which the vendored parser only handles
        # for the delimiter form.
        if args_str[i] in _QUOTES:
            key, i = read_quoted(args_str, i)
            while i < n and args_str[i] in (" ", "\n", "\t"):
                i += 1
            if i >= n or args_str[i] != ":":
                break
            i += 1
        else:
            key_start = i
            while i < n and args_str[i] != ":":
                i += 1
            if i >= n:
                break
            key = args_str[key_start:i].strip()
            if key.startswith(STRING_DELIM) and key.endswith(STRING_DELIM):
                key = key[_DELIM_LEN:-_DELIM_LEN]
            i += 1

        if i >= n:
            if not partial:
                result[key] = ""
            break

        while i < n and args_str[i] in (" ", "\n", "\t"):
            i += 1
        if i >= n:
            if not partial:
                result[key] = ""
            break

        value, i, ok = _fixed_value(args_str, i, partial)
        if not ok:
            break
        result[key] = value

    return result


def _fixed_value(text: str, i: int, partial: bool) -> tuple[Any, int, bool]:
    """One value of any Gemma 4 form. `False` means stop, as the vendored code does."""

    n = len(text)
    if text[i : i + _DELIM_LEN] == STRING_DELIM:
        i += _DELIM_LEN
        end_pos = text.find(STRING_DELIM, i)
        if end_pos == -1:
            value = text[i:]
            if partial:
                value = _strip_partial_delim(value)
            return value, n, True
        return text[i:end_pos], end_pos + _DELIM_LEN, True

    if text[i] in _QUOTES:
        value, i = read_quoted(text, i)
        return value, i, True

    if text[i] in "{[":
        closing = "}" if text[i] == "{" else "]"
        opening = text[i]
        depth = 1
        start = i + 1
        i += 1
        while i < n and depth > 0:
            if text[i : i + _DELIM_LEN] == STRING_DELIM:
                i += _DELIM_LEN
                nd = text.find(STRING_DELIM, i)
                i = n if nd == -1 else nd + _DELIM_LEN
                continue
            if text[i] in _QUOTES:
                # The whole reason this exists: a brace inside a quoted string
                # is not a brace. `{"css":"a{b}"}` used to close early.
                _, i = read_quoted(text, i)
                continue
            if text[i] == opening:
                depth += 1
            elif text[i] == closing:
                depth -= 1
            i += 1
        inner = text[start:i] if depth > 0 else text[start : i - 1]
        reader = fixed_args if opening == "{" else fixed_array
        return reader(inner, partial=depth > 0), i, True

    val_start = i
    while i < n and text[i] not in (",", "}", "]"):
        i += 1
    if partial and i >= n:
        return None, i, False
    if i == val_start:
        return None, i, False
    raw_val = text[val_start:i].strip()
    if partial and raw_val.endswith("."):
        return None, i, False
    return raw_val, i, True


def fixed_array(arr_str: str, *, partial: bool = False) -> list[Any]:
    """`vendored_array` with quoted literals recognised as strings."""

    items: list[Any] = []
    i = 0
    n = len(arr_str)

    while i < n:
        while i < n and arr_str[i] in (" ", ",", "\n", "\t"):
            i += 1
        if i >= n:
            break
        if arr_str[i : i + _DELIM_LEN] == STRING_DELIM:
            i += _DELIM_LEN
            end_pos = arr_str.find(STRING_DELIM, i)
            if end_pos == -1:
                items.append(arr_str[i:])
                break
            items.append(arr_str[i:end_pos])
            i = end_pos + _DELIM_LEN
            continue
        if arr_str[i] in _QUOTES:
            value, i = read_quoted(arr_str, i)
            items.append(value)
            continue
        value, i, ok = _fixed_value(arr_str, i, partial)
        if not ok:
            break
        items.append(value)

    return items


# --- extracting the calls themselves (issue 53431) ---------------------------

TOOL_CALL_START = "<|tool_call>"
TOOL_CALL_END = "<tool_call|>"
# Some Gemma 4 checkpoints close a call with the end-of-turn tag instead.
TOOL_CALL_ALT_END = "<turn|>"

# `<|tool_call>call:name{…}` is the documented opener. The model also emits
# `<|tool_call>:name{…}`, and the shipped grammar has one transition out of the
# preamble that requires the literal `call:` — so the bare form is consumed and
# dropped in silence, with no call, no error and no fallback to text. Both are
# accepted here, which is issue 53431's whole content.
_OPENERS = ("call:", ":")


def extract_calls(text: str) -> list[tuple[str, str]]:
    """Every `(name, raw arguments)` in one decoded completion.

    Scanned rather than matched with a regular expression: an argument span
    contains braces of its own — a page with CSS in it, an object, an array —
    and a lazy brace pattern ends the call at the first of them.
    """

    found: list[tuple[str, str]] = []
    position = 0
    while True:
        start = text.find(TOOL_CALL_START, position)
        if start == -1:
            return found
        cursor = start + len(TOOL_CALL_START)
        for opener in _OPENERS:
            if text[cursor : cursor + len(opener)] == opener:
                cursor += len(opener)
                break
        else:
            position = cursor
            continue
        name_start = cursor
        while cursor < len(text) and (text[cursor].isalnum() or text[cursor] == "_"):
            cursor += 1
        name = text[name_start:cursor]
        if not name or cursor >= len(text) or text[cursor] != "{":
            position = cursor
            continue
        args, cursor = _balanced(text, cursor)
        found.append((name, args))
        for ending in (TOOL_CALL_END, TOOL_CALL_ALT_END):
            if text[cursor : cursor + len(ending)] == ending:
                cursor += len(ending)
                break
        position = cursor


def _balanced(text: str, start: int) -> tuple[str, int]:
    """The contents of the brace at `start`, respecting strings and quotes."""

    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text[i : i + _DELIM_LEN] == STRING_DELIM:
            i += _DELIM_LEN
            nd = text.find(STRING_DELIM, i)
            i = n if nd == -1 else nd + _DELIM_LEN
            continue
        if text[i] in _QUOTES:
            _, i = read_quoted(text, i)
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return text[start + 1 :], n


# --- refusing a call the model did not make ----------------------------------


class CorruptArguments(ValueError):
    """The argument span cannot be read as the arguments of one call."""


# A key is a parameter name. The model writes them from the schema, so they are
# short identifiers; a key holding a brace, a newline or the string delimiter
# means the scan lost its place and is reading somebody's value as a name.
_IMPOSSIBLE_IN_A_KEY = ("{", "}", "[", "]", "\n", "\t", STRING_DELIM)


def implausible(key: str) -> bool:
    return not key or any(mark in key for mark in _IMPOSSIBLE_IN_A_KEY)


def parse_arguments(args_str: str, *, partial: bool = False) -> dict[str, Any]:
    """Read one call's arguments, or refuse the call.

    The refusal is the point. When a span is corrupt the vendored parser still
    returns a dict — a plausible-looking call the model never made, missing the
    arguments a tool requires. Downstream that becomes a tool error the model
    cannot act on, and it retried it eight times. A call that cannot be read
    should not be delivered at all.
    """

    parsed = fixed_args(args_str, partial=partial)
    if partial:
        return parsed
    bad = [key for key in parsed if implausible(key)]
    if bad:
        raise CorruptArguments(
            f"{len(bad)} argument name(s) cannot be parameter names; "
            "the argument span is corrupt"
        )
    return parsed
