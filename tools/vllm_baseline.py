"""Controlled measurement of the deployed model server: prefill, decode, cache.

    python tools/vllm_baseline.py                 # the plan, touching nothing
    python tools/vllm_baseline.py --run --discover
    python tools/vllm_baseline.py --run

**Every network call here wakes a GPU**, including reading `/metrics`, because
the metrics endpoint is served by the same scale-to-zero container as the model.
So the default is a dry run that prints exactly what would be sent and contacts
nothing; `--run` is the deliberate act, and it needs the human's permission for
that run, every time.

The suite is one continuous pass on purpose. The idle window is twelve seconds,
which bounds the pause *between* requests rather than the length of the run, so
nothing is analysed until every snapshot has been saved: requests go out back to
back and the arithmetic happens afterwards, from the file.

What it produces is a JSON file of raw readings under `reports/` plus a printed
summary. The raw file is the evidence; the summary is a convenience.
"""

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import ModelSettings
from app.models.openai_compatible import auth_headers
from app.telemetry.vllm import (
    delta,
    discover,
    missing,
    parse_metrics,
    render_discovery,
    render_measurement,
    restarted,
    summarize,
)

# A cold container may need minutes; a restored one about ten seconds. The
# budget is generous because a timeout here would waste the wake it just paid
# for, which is the expensive part.
TIMEOUT = 600.0

# Roughly four characters to a token. Deliberately an estimate: the size that
# gets reported is the one the engine counted, never this.
CHARS_PER_TOKEN = 4

FILLER = (
    "The quick brown fox jumps over the lazy dog while the river keeps moving. "
)

# Scenario B, in target input tokens. Capped below the 16384-token server
# context so the fixed output still has room; the shortfall against the task
# document's 16k is deliberate and stated in the report.
INPUT_SIZES = (1000, 4000, 8000, 12000)
REPEATS = 3
FIXED_OUTPUT = 64
LONG_OUTPUT = 512
PREFIX_TOKENS = 4000


def filler(tokens: int) -> str:
    """Text of roughly the requested size, from repeated ordinary sentences."""

    return (FILLER * (1 + tokens * CHARS_PER_TOKEN // len(FILLER)))[
        : tokens * CHARS_PER_TOKEN
    ]


def request(prompt: str, max_tokens: int) -> dict[str, object]:
    return {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }


def plan(tag: str = "dry-run") -> list[dict[str, object]]:
    """Every request the suite would send, in order.

    Built before anything is contacted so a dry run shows precisely what a real
    one costs, and so the run itself is a loop over a list rather than a program
    making decisions while the meter runs.

    **Every prompt except C's pair begins with a marker nothing else shares.**
    Prefix caching matches blocks from position zero, so three identical B
    prompts would measure the cache twice and prefill once, and a C prefix that
    B had already sent would measure nothing at all. The marker carries a
    per-run tag as well, because the container may still hold the previous
    invocation's blocks.
    """

    steps: list[dict[str, object]] = [
        {
            "scenario": "A short input, long output",
            "label": "A",
            "prompt": f"[{tag}-A] Write a detailed description of a sunrise over a harbour.",
            "max_tokens": LONG_OUTPUT,
        }
    ]
    for size in INPUT_SIZES:
        for repeat in range(REPEATS):
            steps.append(
                {
                    "scenario": f"B long input {size} tokens, fixed output",
                    "label": f"B{size}.{repeat + 1}",
                    "prompt": f"[{tag}-B{size}-{repeat}] {filler(size)}"
                    "\n\nSummarise the text above in one sentence.",
                    "max_tokens": FIXED_OUTPUT,
                }
            )
    # The one deliberately shared prefix in the suite: C1 pays for it, C2 should
    # not, and the difference between them is the measurement.
    prefix = f"[{tag}-C] {filler(PREFIX_TOKENS)}"
    for repeat, question in enumerate(
        ("Name one animal in the text.", "Name one place in the text.")
    ):
        steps.append(
            {
                "scenario": "C repeated prefix",
                "label": f"C{repeat + 1}",
                "prompt": f"{prefix}\n\n{question}",
                "max_tokens": FIXED_OUTPUT,
            }
        )
    return steps


def base_url(endpoint: str) -> str:
    trimmed = endpoint.rstrip("/")
    return trimmed[: -len("/v1")] if trimmed.endswith("/v1") else trimmed


def read_metrics(client: httpx.Client, base: str) -> str:
    response = client.get(f"{base}/metrics")
    response.raise_for_status()
    return response.text


def send(client: httpx.Client, base: str, model: str, step: dict[str, object]) -> dict:
    started = time.monotonic()
    response = client.post(
        f"{base}/v1/chat/completions",
        json={"model": model, **request(str(step["prompt"]), int(step["max_tokens"]))},
    )
    elapsed = (time.monotonic() - started) * 1000
    response.raise_for_status()
    payload = response.json()
    return {
        "client_ms": elapsed,
        "usage": payload.get("usage", {}),
        "finish_reason": (payload.get("choices") or [{}])[0].get("finish_reason"),
    }


def describe(steps: list[dict[str, object]]) -> str:
    lines = ["What a real run would send", ""]
    for step in steps:
        prompt = str(step["prompt"])
        lines.append(
            f"  {str(step['label']):<8}{len(prompt):>7} chars"
            f" (~{len(prompt) // CHARS_PER_TOKEN} tokens)"
            f" -> {step['max_tokens']} output tokens   {step['scenario']}"
        )
    generated = sum(int(step["max_tokens"]) for step in steps)
    lines += [
        "",
        f"  {len(steps)} requests, {generated} output tokens in total.",
        "  At the measured ~16 tok/s that is roughly "
        f"{generated / 16:.0f} s of generation, plus prefill and one wake.",
        "",
        "  Input sizes above are estimates at four characters to a token. What"
        " gets reported is the count the engine itself made.",
        "  Only C1 and C2 share a prefix; every other prompt starts with a"
        " marker no other request in the run repeats.",
        "",
        "Nothing was contacted. Add --run to actually measure, which wakes the GPU.",
    ]
    return "\n".join(lines)


def measure(settings: ModelSettings, steps: list[dict[str, object]], discovery_only: bool) -> dict:
    base = base_url(settings.endpoint)
    readings: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint": base,
        "model": settings.name,
        "steps": [],
    }
    with httpx.Client(timeout=TIMEOUT, headers=auth_headers(settings)) as client:
        readings["opening"] = read_metrics(client, base)
        if discovery_only:
            return readings
        for step in steps:
            before = read_metrics(client, base)
            result = send(client, base, settings.name, step)
            after = read_metrics(client, base)
            readings["steps"].append(
                {
                    "label": step["label"],
                    "scenario": step["scenario"],
                    "prompt_chars": len(str(step["prompt"])),
                    "max_tokens": step["max_tokens"],
                    "result": result,
                    "before": before,
                    "after": after,
                }
            )
        readings["closing"] = read_metrics(client, base)
    return readings


def report(readings: dict) -> str:
    """The arithmetic, done afterwards from the saved readings."""

    opening = parse_metrics(str(readings.get("opening", "")))
    found = discover(opening)
    lines = [render_discovery(opening, found), ""]
    absent = missing(found)
    if absent:
        lines.append(
            "Concepts below are absent, so the numbers they would produce are "
            "reported as unknown rather than as zero."
        )
        lines.append("")
    for step in readings.get("steps", []):
        before, after = parse_metrics(step["before"]), parse_metrics(step["after"])
        if restarted(before, after):
            lines.append(
                f"{step['label']}  REFUSED: the engine restarted between the two "
                "readings, so this delta describes two different containers."
            )
            continue
        measured = summarize(found, delta(before, after))
        usage = step["result"].get("usage", {})
        lines.append(
            render_measurement(f"{step['label']}  {step['scenario']}", measured)
        )
        lines.append(
            f"  client observed     {step['result']['client_ms']:,.0f} ms"
            f"   reported usage {usage.get('prompt_tokens', '-')}"
            f" in / {usage.get('completion_tokens', '-')} out"
        )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="actually contact the endpoint; this wakes the GPU and costs money",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="read /metrics once and stop, without sending any model request",
    )
    parser.add_argument(
        "--from-file", help="re-render a saved run instead of measuring anything"
    )
    parser.add_argument("--out", default="reports", help="where to save the readings")
    options = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if options.from_file:
        print(report(json.loads(Path(options.from_file).read_text(encoding="utf-8"))))
        return 0

    if not options.run:
        print(describe(plan()))
        return 0

    # A tag of this run's own, so a container still holding the previous
    # invocation's blocks cannot make a cold request look cached.
    steps = plan(uuid.uuid4().hex[:8])
    settings = ModelSettings()
    readings = measure(settings, steps, options.discover)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = Path(options.out) / f"vllm_baseline_{stamp}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(readings, indent=1), encoding="utf-8")
    print(f"raw readings saved to {target}\n")
    print(report(readings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
