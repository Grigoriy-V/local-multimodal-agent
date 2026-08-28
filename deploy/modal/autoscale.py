"""Change how long the GPU stays warm, without deploying anything.

`scaledown_window` is an autoscaler setting, and Modal can update those on a
running app over the network. No image is rebuilt, no weights are re-read, the
GPU application is not re-versioned. This exists so that trying a different
idle window costs seconds rather than a deploy.

One caveat, straight from the documentation: these settings **revert to the
values in the decorator the next time the app is deployed**. So this script is
for experiments. A window worth keeping belongs in `SCALEDOWN_WINDOW` in
`model_app.py`, which is the thing a deploy restores.

    python deploy/modal/autoscale.py            # show the current setting
    python deploy/modal/autoscale.py --window 300
"""

from __future__ import annotations

import argparse

import modal
from model_app import APP_NAME, SCALEDOWN_WINDOW

SERVER_NAME = "Server"

# A window shorter than this cannot cover the pause a person takes to read a
# plan and press a button. Measured the hard way: with 10 s, one approval became
# two cold starts, because the container scaled to zero while the plan was being
# read. Not a refusal — a short window is right for a throughput measurement, and
# an adaptive window is planned — but it is never right by accident.
INTERACTIVE_FLOOR = 20


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        type=int,
        default=None,
        help="seconds the GPU stays warm after the last request (Modal allows 2-1200)",
    )
    parser.add_argument("--app", default=APP_NAME)
    parser.add_argument("--name", default=SERVER_NAME)
    arguments = parser.parse_args()

    if arguments.window is None:
        print(f"app:              {arguments.app}")
        print(f"deployed default: {SCALEDOWN_WINDOW}s (from model_app.py)")
        print("\nPass --window to change it on the running app.")
        return 0

    if not 2 <= arguments.window <= 1200:
        print(f"refusing {arguments.window}s: Modal accepts 2-1200")
        return 1

    if arguments.window < INTERACTIVE_FLOOR:
        print(
            f"warning: {arguments.window}s is below the {INTERACTIVE_FLOOR}s a waiting "
            "approval needs. An interactive turn that stops for a button will pay a "
            "second cold start. Fine for a measurement, wrong for use."
        )

    # The autoscaler belongs to the class instance, not to a method. Two earlier
    # spellings are rejected by the 1.5 client and are recorded here so they are
    # not retried: `Function.from_name(app, "Server.serve")` raises
    # `Invalid Function name`, and reaching the method off the instance raises
    # `Cannot call .update_autoscaler() on a method`.
    server = modal.Cls.from_name(arguments.app, arguments.name)()
    server.update_autoscaler(scaledown_window=arguments.window)
    print(f"{arguments.app}.{arguments.name}: scaledown_window is now {arguments.window}s")
    print("The next deploy resets it to SCALEDOWN_WINDOW in model_app.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
