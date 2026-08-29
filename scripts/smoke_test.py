"""Exercise every Stage 1 contract item against a running endpoint.

Independent of the agent and the UI: it uses only `ModelBackend`. Each check
asks for something whose answer can be judged automatically, so a request that
succeeds but returns nonsense still fails.

    python -m scripts.smoke_test [--json] [--report PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import ModelSettings
from app.models import ContentPart, Message, TextDelta
from app.models.openai_compatible import OpenAICompatibleBackend

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}

CITY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "city",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "country": {"type": "string"},
                # Bounds are not decoration. An unbounded numeric field lets
                # guided decoding repeat digits until max_tokens is exhausted,
                # which arrives as truncated, unparsable JSON.
                "population_thousands": {"type": "integer", "minimum": 1, "maximum": 30000},
            },
            "required": ["name", "country", "population_thousands"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class Check:
    name: str
    ok: bool
    latency_s: float
    detail: str


def text(value: str) -> ContentPart:
    return ContentPart(kind="text", text=value)


def media(kind: str, filename: str, media_type: str) -> ContentPart:
    return ContentPart(kind=kind, data=(FIXTURES / filename).read_bytes(), media_type=media_type)


def user(*parts: ContentPart) -> Message:
    return Message(role="user", content=list(parts))


def shorten(value: str, limit: int = 90) -> str:
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


Probe = Callable[[OpenAICompatibleBackend], Awaitable[tuple[bool, str]]]


async def text_chat(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    result = await backend.invoke([user(text("Reply with the single word: pong."))])
    return "pong" in result.text.lower(), shorten(result.text)


async def system_prompt(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    messages = [
        Message(
            role="system",
            content=[text("Whatever you are asked, answer with the single word BANANA.")],
        ),
        user(text("What is the capital of France?")),
    ]
    result = await backend.invoke(messages)
    return "banana" in result.text.lower(), shorten(result.text)


async def streaming(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    start = time.perf_counter()
    first = None
    chunks: list[str] = []
    final = None
    async for event in backend.stream([user(text("Count from one to ten in words."))]):
        if isinstance(event, TextDelta):
            if first is None:
                first = time.perf_counter() - start
            chunks.append(event.text)
        else:
            final = event.completion
    joined = "".join(chunks).lower()
    # The assembled completion is what the agent would actually run on, so the
    # check is that it says the same thing the person watching it read.
    ok = (
        len(chunks) > 1
        and "one" in joined
        and "ten" in joined
        and final is not None
        and final.text == "".join(chunks)
    )
    return ok, f"{len(chunks)} chunks, first after {first or 0:.2f} s"


async def single_image(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    message = user(
        text("What shape and what colour is in this image? Answer in three words."),
        media("image", "red_circle.png", "image/png"),
    )
    result = await backend.invoke([message])
    answer = result.text.lower()
    return "red" in answer and "circle" in answer, shorten(result.text)


async def multiple_images(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    message = user(
        text("Two images follow. Name the colour and shape of each, in order."),
        media("image", "red_circle.png", "image/png"),
        media("image", "blue_square.png", "image/png"),
    )
    result = await backend.invoke([message])
    answer = result.text.lower()
    ok = all(word in answer for word in ("red", "circle", "blue", "square"))
    return ok, shorten(result.text)


async def transcribe(backend: OpenAICompatibleBackend, part: ContentPart) -> tuple[bool, str]:
    message = user(text("Transcribe the speech verbatim. Output only the transcript."), part)
    result = await backend.invoke([message])
    return "travel" in result.text.lower(), shorten(result.text)


async def audio_wav(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    return await transcribe(backend, media("audio", "speech.wav", "audio/wav"))


async def audio_flac(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    return await transcribe(backend, media("audio", "speech.flac", "audio/flac"))


async def tool_call(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    message = user(text("What is the weather in Tbilisi right now? Use the tool."))
    result = await backend.invoke([message], tools=[WEATHER_TOOL])
    if not result.tool_calls:
        return False, f"no tool call, finish_reason={result.finish_reason}"
    call = result.tool_calls[0]
    ok = call.name == "get_weather" and "tbilisi" in str(call.arguments.get("city", "")).lower()
    return ok, f"{call.name}{json.dumps(call.arguments)}, finish_reason={result.finish_reason}"


async def structured_json(backend: OpenAICompatibleBackend) -> tuple[bool, str]:
    message = user(text("Describe Tbilisi, Georgia."))
    result = await backend.invoke([message], response_format=CITY_SCHEMA)
    try:
        parsed = json.loads(result.text)
    except json.JSONDecodeError:
        return False, f"not JSON: {shorten(result.text)}"
    population = parsed.get("population_thousands")
    ok = (
        set(parsed) == {"name", "country", "population_thousands"}
        and isinstance(population, int)
        and 1 <= population <= 30000
    )
    return ok, shorten(result.text)


PROBES: list[tuple[str, Probe]] = [
    ("text chat", text_chat),
    ("system prompt", system_prompt),
    ("streaming", streaming),
    ("single image", single_image),
    ("multiple images", multiple_images),
    ("audio wav", audio_wav),
    ("audio flac", audio_flac),
    ("tool call", tool_call),
    ("structured JSON", structured_json),
]


def reserved_vram() -> str:
    """What the driver reports, which is not peak use.

    vLLM claims `gpu_memory_utilization` of the card in one block at startup and
    never releases it, so this number says nothing about the model's real
    consumption. Real weight and KV-cache figures come from the server's own
    startup log.
    """

    if not shutil.which("nvidia-smi"):
        return "nvidia-smi not found"
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as error:
        return f"unavailable: {error}"
    return f"{output} reserved by the driver, not peak use"


async def run(settings: ModelSettings) -> list[Check]:
    checks: list[Check] = []
    async with OpenAICompatibleBackend(settings) as backend:
        for name, probe in PROBES:
            start = time.perf_counter()
            try:
                ok, detail = await probe(backend)
            except Exception as error:  # noqa: BLE001 - a failed probe is a result
                ok, detail = False, f"{type(error).__name__}: {error}"
            checks.append(Check(name, ok, time.perf_counter() - start, detail))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", help="override MODEL_ENDPOINT")
    parser.add_argument("--model", help="override MODEL_NAME")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--report", type=Path, help="also write the JSON result to this path")
    arguments = parser.parse_args()

    overrides = {}
    if arguments.endpoint:
        overrides["endpoint"] = arguments.endpoint
    if arguments.model:
        overrides["name"] = arguments.model
    settings = ModelSettings(**overrides)

    checks = asyncio.run(run(settings))
    vram = reserved_vram()
    failed = [check for check in checks if not check.ok]
    result = {
        "endpoint": settings.endpoint,
        "model": settings.name,
        "vram": vram,
        "failed": len(failed),
        "checks": [asdict(check) for check in checks],
    }

    if arguments.json:
        print(json.dumps(result, indent=2))
    else:
        for check in checks:
            print(f"[{'ok' if check.ok else '--'}] {check.name:<16} {check.latency_s:6.2f} s  {check.detail}")
        print(f"\nvram: {vram}")
        print(f"{len(checks) - len(failed)} of {len(checks)} checks passed")

    if arguments.report:
        arguments.report.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
