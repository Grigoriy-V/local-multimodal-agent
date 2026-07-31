"""Report whether the local environment can run this project.

Reports; never installs, downloads, or starts anything.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

REQUIRED_PYTHON = (3, 12)
DEFAULT_ENDPOINT = "http://127.0.0.1:8000/v1"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def check_python() -> Check:
    version = sys.version_info
    ok = (version.major, version.minor) == REQUIRED_PYTHON
    return Check(
        "python",
        ok,
        f"{platform.python_version()} (expected {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]})",
    )


def check_torch() -> list[Check]:
    try:
        import torch
    except ImportError:
        return [Check("torch", False, "not installed")]

    checks = [Check("torch", True, torch.__version__)]
    available = torch.cuda.is_available()
    checks.append(
        Check("cuda", available, torch.version.cuda or "unavailable" if available else "unavailable")
    )
    if available:
        free, total = torch.cuda.mem_get_info()
        gib = 1024**3
        checks.append(
            Check(
                "gpu",
                free >= 20 * gib,
                f"{torch.cuda.get_device_name(0)}, {free / gib:.1f} of {total / gib:.1f} GiB free",
            )
        )
    return checks


def check_endpoint(endpoint: str, timeout: float) -> Check:
    url = f"{endpoint.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Check("endpoint", False, f"{url} unreachable: {error}")
    except json.JSONDecodeError:
        return Check("endpoint", False, f"{url} returned a non-JSON body")

    served = [item.get("id", "?") for item in payload.get("data", [])]
    return Check("endpoint", bool(served), f"{url} serving {served or 'nothing'}")


def check_credentials() -> Check:
    names = [name for name in ("MODEL_API_KEY", "OPENAI_API_KEY") if os.environ.get(name)]
    return Check("credentials", True, f"present: {names}" if names else "none set (may be fine)")


def run(endpoint: str, timeout: float) -> list[Check]:
    return [check_python(), *check_torch(), check_endpoint(endpoint, timeout), check_credentials()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("MODEL_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    arguments = parser.parse_args()

    checks = run(arguments.endpoint, arguments.timeout)
    if arguments.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        for check in checks:
            print(f"[{'ok' if check.ok else '--'}] {check.name}: {check.detail}")

    # A missing endpoint is expected until the human starts the server, so it
    # does not fail the run; only the interpreter itself does.
    return 0 if checks[0].ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
