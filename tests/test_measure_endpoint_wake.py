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
