"""Read one measured turn, or list recent ones.

    python tools/show_run.py <run_id>
    python tools/show_run.py --last 20
    python tools/show_run.py --failed
    python tools/show_run.py --user 123456789 --last 10

It opens whatever the application would open: the local SQLite file by default,
and the deployed database when `AGENT_DATABASE_URL` is set. One notion of where
telemetry lives, so a trace read here is the trace the product wrote.

Read-only. It never migrates a schema and never starts anything.
"""

import argparse
import sys

from app.config import AgentSettings
from app.telemetry.cost import A10_USD_PER_SECOND, IDLE_WINDOW_SECONDS
from app.telemetry.inspect import render_listing, render_run
from app.telemetry.open import open_telemetry


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?", help="the run to render in full")
    parser.add_argument("--last", type=int, default=20, help="how many runs to list")
    parser.add_argument(
        "--failed",
        action="store_true",
        help="only runs that failed or never finished at all",
    )
    parser.add_argument("--user", default=None, help="restrict the listing to one user")
    parser.add_argument(
        "--idle-window",
        type=float,
        default=IDLE_WINDOW_SECONDS,
        help="seconds the GPU stays warm after a request, for the cost estimate",
    )
    parser.add_argument(
        "--gpu-rate",
        type=float,
        default=A10_USD_PER_SECOND,
        help="dollars per GPU second, for the cost estimate",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = parse(sys.argv[1:] if argv is None else argv)
    telemetry = open_telemetry(AgentSettings())
    store = telemetry.store
    if store is None:
        print("telemetry is off (AGENT_TELEMETRY=0); there is nothing to read")
        return 2
    try:
        if options.run_id:
            run = store.get_turn(options.run_id)
            if run is None:
                print(f"no run {options.run_id}")
                return 1
            print(
                render_run(
                    run,
                    store.events(options.run_id),
                    idle_window_seconds=options.idle_window,
                    rate_per_second=options.gpu_rate,
                )
            )
            return 0
        print(
            render_listing(
                store.recent_runs(
                    limit=options.last,
                    user_id=options.user,
                    unsuccessful=options.failed,
                )
            )
        )
        return 0
    finally:
        telemetry.close()


if __name__ == "__main__":
    raise SystemExit(main())
