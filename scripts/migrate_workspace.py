"""Move a single-user workspace under its owner's directory. Run once.

Before user scope, every agent shared one workspace root. Each person now gets
their own directory inside it, so the files that are already there have to be
given to the person who made them — the local profile's user.

This is a script rather than something that happens on start-up. The database
carries `PRAGMA user_version` and can say what shape it is in; a directory
cannot, so the alternative would be guessing from whatever happens to be lying
in it. Moving someone's files is not a good place to guess.

    .venv\\Scripts\\python.exe scripts/migrate_workspace.py [--apply]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.runtime import user_workspace
from app.config import AgentSettings
from app.memory import LOCAL_USER_ID


def plan(root: Path, owner: str) -> tuple[Path, list[Path]]:
    """The destination and everything that has to move into it."""

    destination = user_workspace(root, owner)
    movable = [
        entry
        for entry in sorted(root.iterdir())
        if entry.resolve() != destination.resolve()
    ]
    return destination, movable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="move the files")
    parser.add_argument("--owner", default=LOCAL_USER_ID, help="who the files belong to")
    parser.add_argument("--workspace", default=None, help="workspace root to migrate")
    arguments = parser.parse_args()

    root = Path(arguments.workspace or AgentSettings().workspace).resolve()
    if not root.is_dir():
        print(f"nothing to do: {root} does not exist")
        return 0

    destination, movable = plan(root, arguments.owner)
    if destination.exists() and not movable:
        print(f"already migrated: everything is under {destination}")
        return 0
    if not movable:
        print(f"nothing to move in {root}")
        return 0

    print(f"workspace: {root}")
    print(f"owner:     {arguments.owner}")
    print(f"target:    {destination}")
    for entry in movable:
        print(f"  {entry.name}{'/' if entry.is_dir() else ''}")
    if not arguments.apply:
        print(f"\n{len(movable)} entries would move. Re-run with --apply to do it.")
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    for entry in movable:
        target = destination / entry.name
        if target.exists():
            print(f"refusing to overwrite {target}")
            return 1
        shutil.move(str(entry), str(target))
    print(f"\nmoved {len(movable)} entries into {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
