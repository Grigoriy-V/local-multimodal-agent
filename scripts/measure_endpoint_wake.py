"""Measure what a person actually waits for when the model endpoint is asleep.

Why this exists rather than a `curl` one-liner: Modal's edge can redirect a
request while the container is still coming up. `urllib` follows that redirect,
and the wake probe remains one logical request until the endpoint serves. A
transport timeout is deliberately terminal: the abandoned server-side request
may still be queued, so retrying it would create another paid task without
cancelling the first one.

It also verifies the modalities and the credential form in the same warm window,
because every extra cold start is a paid GPU boot.

    python scripts/measure_endpoint_wake.py --url https://...modal.run --auth headers
    python scripts/measure_endpoint_wake.py --url https://...modal.run --auth bearer

`--auth bearer` sends the proxy token joined by a period as an ordinary bearer
token. That is the property `reports/2026-08-28_v2_step3a_model_endpoint.md`
established for the baseline's `.modal.direct` endpoint and which decides
whether `OpenAICompatibleBackend` needs a change to reach a `.modal.run` one.

The token is read from `MODEL_API_KEY` in the environment or `.env` and is never
printed.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

# Long enough to cover a full cold boot with margin; the observed vLLM start is
# about 170 s and the container adds scheduling and snapshot restore on top.
WAKE_BUDGET = 600.0
REQUEST_TIMEOUT = 60.0


class VerificationError(RuntimeError):
    """The endpoint answered, but an acceptance probe did not pass."""


def read_token() -> str:
    """Take the proxy token from the environment, falling back to `.env`."""

    import os

    token = os.environ.get("MODEL_API_KEY", "").strip()
    if token:
        return token

    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("MODEL_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("MODEL_API_KEY not found in the environment or .env")


def auth_headers(token: str, style: str) -> dict[str, str]:
    if style == "bearer":
        return {"Authorization": f"Bearer {token}"}
    key, _, secret = token.partition(".")
    if not key or not secret:
        raise SystemExit("MODEL_API_KEY is not in the wk-... .ws-... form")
    return {"Modal-Key": key, "Modal-Secret": secret}


def request(
    url: str,
    headers: dict[str, str],
    payload: dict | None = None,
    *,
    timeout: float = REQUEST_TIMEOUT,
):
    """Return (status, body). A transport failure is a status of 0."""

    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=dict(headers))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except Exception as error:  # noqa: BLE001 - any transport failure is a retry
        return 0, str(error).encode()


def wake(url: str, headers: dict[str, str]) -> tuple[float, list[str]]:
    """Wait on one request until the endpoint serves.

    A timed-out HTTP client does not prove that Modal cancelled the queued task.
    Sending another request can therefore create multiple pending tasks for one
    measurement. Any non-success is terminal and must be diagnosed before a new
    separately authorized wake.
    """

    started = time.monotonic()
    status, body = request(
        f"{url}/v1/models",
        headers,
        timeout=WAKE_BUDGET,
    )
    elapsed = time.monotonic() - started
    note = f"{elapsed:6.1f}s  {status}"
    print(f"  {note}", flush=True)

    if status == 200:
        return elapsed, [note]
    if status in (401, 403):
        raise SystemExit(f"refused at the edge with {status}; the GPU was not woken")

    detail = body[:200].decode(errors="replace")
    raise SystemExit(
        f"wake request ended after {elapsed:.1f}s with status {status}: {detail}; "
        "not retrying because the server-side task may still be queued"
    )


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def completion(
    url: str,
    headers: dict[str, str],
    content,
    label: str,
    *,
    expected: tuple[str, ...],
) -> None:
    payload = {
        "model": "gemma-4-12b-it",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 48,
    }
    started = time.monotonic()
    status, body = request(f"{url}/v1/chat/completions", headers, payload)
    elapsed = time.monotonic() - started

    if status != 200:
        detail = body[:200].decode(errors="replace")
        raise VerificationError(f"{label} returned HTTP {status}: {detail}")
    try:
        answer = json.loads(body)
        choice = answer["choices"][0]
        full_text = choice["message"]["content"]
        completion_tokens = answer["usage"]["completion_tokens"]
        prompt_tokens = answer["usage"]["prompt_tokens"]
        finish_reason = choice["finish_reason"]
        if not isinstance(full_text, str):
            raise TypeError("completion content is not text")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise VerificationError(f"{label} returned an invalid completion payload") from error

    normalized = full_text.lower()
    missing = [term for term in expected if term not in normalized]
    if missing:
        raise VerificationError(
            f"{label} answer missed {missing!r}: {full_text[:200]!r}"
        )

    text = full_text.replace("\n", " ")[:90]
    rate = completion_tokens / elapsed if elapsed else 0
    print(
        f"  {label:<8} 200  {elapsed:5.2f}s  "
        f"{prompt_tokens:>4} in / {completion_tokens:>3} out  "
        f"{rate:4.1f} tok/s  {finish_reason}"
    )
    print(f"           {text}")


def fixture(name: str) -> Path:
    path = FIXTURES / name
    if not path.is_file():
        raise VerificationError(f"required fixture is missing: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="endpoint root, without /v1")
    parser.add_argument("--auth", choices=("headers", "bearer"), default="headers")
    parser.add_argument("--skip-modalities", action="store_true")
    arguments = parser.parse_args()

    url = arguments.url.rstrip("/").removesuffix("/v1")
    headers = auth_headers(read_token(), arguments.auth)

    print(f"waking {url} with {arguments.auth} auth")
    elapsed, _ = wake(url, headers)
    print(f"\nREQUEST TO SERVING: {elapsed:.1f}s\n")

    try:
        completion(
            url,
            headers,
            "Name three primary colours.",
            "text",
            expected=("red", "blue", "yellow"),
        )
        if arguments.skip_modalities:
            return 0

        image = fixture("red_circle.png")
        completion(
            url,
            headers,
            [
                {"type": "text", "text": "What shape and colour is this? Answer briefly."},
                {"type": "image_url", "image_url": {"url": data_uri(image, "image/png")}},
            ],
            "image",
            expected=("red", "circle"),
        )

        audio = fixture("speech.wav")
        encoded = base64.b64encode(audio.read_bytes()).decode()
        completion(
            url,
            headers,
            [
                {"type": "text", "text": "Transcribe this audio."},
                {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}},
            ],
            "audio",
            expected=("travel",),
        )
    except VerificationError as error:
        print(f"\nVERIFICATION FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
