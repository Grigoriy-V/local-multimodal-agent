"""Measure what a deployed command costs in waiting: cold start against warm.

    .venv\\Scripts\\python.exe -m scripts.measure_command_cold_start
    .venv\\Scripts\\python.exe -m scripts.measure_command_cold_start --runs 3

Invokes the deployed `run_command` Function (`deploy/modal/control_app.py`)
on a probe workspace of its own inside the Volume, first after the container
has been idle past its 180 s scaledown window, then again at once, and
prints for each the wall time the worker would have waited beside the
command's own seconds. The difference is the container: scheduling, image
pull, import. Step 5's acceptance asks for this number before anything is
built on it (`reports/2026-09-04_v2_isolated_execution_review.md` §5).

Every invocation starts a container — a product-runtime worker — and needs
permission at the time. It touches nothing but `/workspaces/cold-start-probe`.
"""

from __future__ import annotations

import argparse
import sys
import time

import modal

APP = "assistant-control"
FUNCTION = "run_command"
WORKSPACE = "cold-start-probe"
COMMAND = "echo probe && python3 --version && node --version && git --version"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=2, help="invocations; the first is the cold one")
    args = parser.parse_args()

    function = modal.Function.from_name(APP, FUNCTION)
    for index in range(max(1, args.runs)):
        started = time.perf_counter()
        result = function.remote(WORKSPACE, COMMAND, 60.0)
        waited = time.perf_counter() - started
        failure = result.get("failure")
        if failure:
            print(f"run {index + 1}: FAILED {failure['code']}: {failure['message']}")
            return 1
        label = "cold" if result["fresh"] else "warm"
        overhead = waited - float(result["seconds"])
        print(
            f"run {index + 1}: {label:4}  waited {waited:6.2f} s   command {float(result['seconds']):5.2f} s"
            f"   container {overhead:6.2f} s   exit {result['exit_code']}"
        )
        for line in str(result["output"]).strip().splitlines():
            print(f"        {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
