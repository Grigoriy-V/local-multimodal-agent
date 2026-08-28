"""Offline checks for the acceptance-oriented endpoint wake measurement."""

from __future__ import annotations

import json

import pytest

from scripts import measure_endpoint_wake as measurement


def payload(text: str) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }
    ).encode()


def test_completion_refuses_an_http_failure(monkeypatch):
    monkeypatch.setattr(measurement, "request", lambda *args: (500, b"broken"))

    with pytest.raises(measurement.VerificationError, match="HTTP 500"):
        measurement.completion("https://example", {}, "hello", "text", expected=("ok",))


def test_completion_refuses_a_semantically_wrong_answer(monkeypatch):
    monkeypatch.setattr(measurement, "request", lambda *args: (200, payload("blue square")))

    with pytest.raises(measurement.VerificationError, match="red"):
        measurement.completion(
            "https://example",
            {},
            "hello",
            "image",
            expected=("red", "circle"),
        )


def test_completion_refuses_an_invalid_success_payload(monkeypatch):
    monkeypatch.setattr(measurement, "request", lambda *args: (200, b"{}"))

    with pytest.raises(measurement.VerificationError, match="invalid completion"):
        measurement.completion("https://example", {}, "hello", "text", expected=("ok",))


def test_completion_accepts_all_expected_terms(monkeypatch):
    monkeypatch.setattr(
        measurement,
        "request",
        lambda *args: (200, payload("A red circle.")),
    )

    measurement.completion(
        "https://example",
        {},
        "hello",
        "image",
        expected=("red", "circle"),
    )


def test_fixture_is_required(monkeypatch, tmp_path):
    monkeypatch.setattr(measurement, "FIXTURES", tmp_path)

    with pytest.raises(measurement.VerificationError, match="required fixture"):
        measurement.fixture("missing.wav")


def test_wake_uses_one_long_request(monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, b"{}"

    monkeypatch.setattr(measurement, "request", request)

    measurement.wake("https://example", {})

    assert len(calls) == 1
    assert calls[0][1]["timeout"] == measurement.WAKE_BUDGET


def test_wake_accepts_an_explicit_short_budget(monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, b"{}"

    monkeypatch.setattr(measurement, "request", request)

    measurement.wake("https://example", {}, timeout=60.0)

    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 60.0


def test_wake_does_not_retry_an_ambiguous_transport_failure(monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return 0, b"timed out"

    monkeypatch.setattr(measurement, "request", request)

    with pytest.raises(SystemExit, match="not retrying"):
        measurement.wake("https://example", {})

    assert len(calls) == 1
