"""The doctor must report offline without starting or contacting anything."""

from __future__ import annotations

import json
import sys
import urllib.error

from scripts import doctor


def test_python_check_matches_running_interpreter() -> None:
    check = doctor.check_python()

    assert check.ok is ((sys.version_info.major, sys.version_info.minor) == doctor.REQUIRED_PYTHON)
    assert check.name == "python"


def test_unreachable_endpoint_is_reported_not_raised(monkeypatch) -> None:
    def refuse(url, timeout):  # noqa: ANN001, ARG001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", refuse)

    check = doctor.check_endpoint("http://127.0.0.1:8000/v1", timeout=0.01)

    assert check.ok is False
    assert "unreachable" in check.detail


def test_served_models_are_listed(monkeypatch) -> None:
    class Response:
        def read(self):
            return json.dumps({"data": [{"id": "google/gemma-4-12b-it"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(doctor.urllib.request, "urlopen", lambda url, timeout: Response())

    check = doctor.check_endpoint("http://127.0.0.1:8000/v1", timeout=0.01)

    assert check.ok is True
    assert "google/gemma-4-12b-it" in check.detail


def test_missing_credentials_do_not_fail(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    check = doctor.check_credentials()

    assert check.ok is True
    assert "none set" in check.detail


def test_run_collects_every_check(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "check_endpoint",
        lambda endpoint, timeout: doctor.Check("endpoint", False, "skipped"),
    )

    names = [check.name for check in doctor.run("http://127.0.0.1:8000/v1", timeout=0.01)]

    assert names[0] == "python"
    assert "endpoint" in names
    assert "credentials" in names
