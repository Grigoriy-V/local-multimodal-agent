"""Render a stored conversation as Markdown, with the pictures and files it holds.

    python tools/showcase.py chat-r chat-s --user loop-live-check --out reports/showcase

The evidence of what the assistant does is already in the database: every
message of a thread, every tool call with its arguments, every result the
model read — including the picture it looked at and the file it sent, which
the store keeps as media — and, in telemetry, what the turn cost. This turns
one thread into a page a person can read without a screenshot: the request,
the calls in order, what came back, the answer, the numbers. Media is written
beside the page and embedded.

Read-only. It opens whatever the application would open (the local SQLite
files, or the deployed database when `AGENT_DATABASE_URL` is set), migrates
nothing and starts nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.config import AgentSettings
from app.memory import open_store
from app.models import Message
from app.telemetry.base import TurnRun
from app.telemetry.open import open_telemetry

# How much of a tool result or an argument the page shows. The point is the
# shape of the work, not the whole of every file the model wrote.
RESULT_CHARS = 700
ARGUMENT_CHARS = 400

SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf"}


def _text(message: Message) -> str:
    return "\n".join(part.text for part in message.content if part.kind == "text" and part.text)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + f"\n… ({len(text) - limit} more characters)"


def _argument(value: object) -> str:
    if isinstance(value, str):
        return _clip(value, ARGUMENT_CHARS)
    return _clip(json.dumps(value, ensure_ascii=False), ARGUMENT_CHARS)


def _media(message: Message, out: Path, thread_id: str) -> list[str]:
    """Write the message's pictures and files beside the page; return Markdown lines."""

    lines: list[str] = []
    for part in message.content:
        if part.kind == "text" or not part.data:
            continue
        digest = hashlib.sha256(part.data).hexdigest()[:8]
        suffix = SUFFIX.get(part.media_type or "", Path(part.name or "").suffix or ".bin")
        stem = Path(part.name or part.kind).stem or part.kind
        target = out / f"{thread_id}-{stem}-{digest}{suffix}"
        target.write_bytes(part.data)
        if part.kind == "image":
            lines.append(f"![{part.name or 'picture'}]({target.name})")
        else:
            lines.append(f"[{part.name or target.name}]({target.name}) ({len(part.data)} bytes)")
        lines.append("")
    return lines


def render_thread(thread_id: str, messages: list[Message], out: Path) -> list[str]:
    lines: list[str] = []
    for message in messages:
        if message.role == "user":
            lines += [f"**Person:** {_text(message)}", ""]
        elif message.role == "assistant":
            for call in message.tool_calls:
                lines.append(f"`{call.name}`")
                for key, value in call.arguments.items():
                    rendered = _argument(value)
                    if "\n" in rendered:
                        lines += [f"- {key}:", "", "  ```", *("  " + line for line in rendered.splitlines()), "  ```"]
                    else:
                        lines.append(f"- {key}: `{rendered}`")
                lines.append("")
            text = _text(message)
            if text:
                lines += ["**Assistant:**", "", *("> " + line for line in text.splitlines()), ""]
        elif message.role == "tool":
            failure = getattr(message, "failure", None)
            label = f"result, `{failure.code}`" if failure else "result"
            text = _text(message)
            if text:
                lines += [f"<details><summary>{label}</summary>", "", "```text", _clip(text, RESULT_CHARS), "```", "", "</details>", ""]
            lines += _media(message, out, thread_id)
    return lines


def render_run(run: TurnRun) -> list[str]:
    total = f"{run.total_ms / 1000:.1f} s" if run.total_ms else "-"
    return [
        f"Run `{run.run_id}`: {run.model_calls} model calls, {run.tool_calls} tool calls, "
        f"{run.input_tokens} tokens in / {run.output_tokens} out, {total}, outcome {run.outcome}.",
        "",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("threads", nargs="+", help="thread ids to render")
    parser.add_argument("--user", default="", help="whose runs to look up in telemetry")
    parser.add_argument("--out", default="reports/showcase", help="where the pages and media go")
    options = parser.parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = AgentSettings()
    store = open_store(settings)
    telemetry = open_telemetry(settings)
    try:
        runs = telemetry.store.recent_runs(limit=500, user_id=options.user or None) if telemetry.store else []
        for thread_id in options.threads:
            messages = store.messages(thread_id)
            if not messages:
                print(f"{thread_id}: no messages", file=sys.stderr)
                continue
            lines = [f"# {thread_id}", ""]
            for run in runs:
                if run.thread_id == thread_id:
                    lines += render_run(run)
                    break
            lines += render_thread(thread_id, messages, out)
            page = out / f"{thread_id}.md"
            page.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"{thread_id}: {len(messages)} messages -> {page}")
    finally:
        store.close()
        telemetry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
