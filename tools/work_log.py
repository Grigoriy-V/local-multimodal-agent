#!/usr/bin/env python3
"""Small, dependency-free append-only work journals for this repository."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any


SCHEMA_VERSION = 1
JOURNALS = {
    "agent": Path("reports/agent_tasks.jsonl"),
    "ml": Path("reports/ml_work.jsonl"),
}


def run_git(root: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=root, text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=False,
        )
    except OSError:
        return None
    return completed.stdout.rstrip("\r\n") if completed.returncode == 0 else None


def repository_context() -> tuple[Path, dict[str, Any]]:
    script_root = Path(__file__).resolve().parent.parent
    git_root = run_git(script_root, "rev-parse", "--show-toplevel")
    if not git_root:
        return script_root, {
            "git_available": False,
            "branch": None,
            "head": None,
            "changed_files": [],
            "metadata_note": "Git metadata unavailable; using the tool directory as repository root.",
        }

    root = Path(git_root).resolve()
    status = run_git(root, "status", "--porcelain=v1", "-z") or ""
    entries = status.split("\0")
    changed: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        path = entry[3:]
        changed.append(path.replace("\\", "/"))
        if entry[:1] in {"R", "C"} and index < len(entries):
            index += 1  # Rename/copy source path; the current path is enough.
    return root, {
        "git_available": True,
        "branch": run_git(root, "branch", "--show-current"),
        "head": run_git(root, "rev-parse", "HEAD"),
        "changed_files": sorted(set(changed)),
    }


def relative_path(value: str, root: Path, label: str) -> str:
    candidate = PurePath(value)
    if not value or candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must be a non-empty repository-relative path that does not escape the repository: {value!r}")
    normalized = Path(value)
    try:
        resolved = (root / normalized).resolve()
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} must stay inside the repository: {value!r}") from error
    return normalized.as_posix()


def record_metadata(root: Path, git: dict[str, Any]) -> dict[str, Any]:
    try:
        workdir = Path.cwd().resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        workdir = str(Path.cwd().resolve())
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_root": str(root),
        "workdir": workdir,
        **git,
    }


def append_record(kind: str, record: dict[str, Any], root: Path) -> Path:
    journal = root / JOURNALS[kind]
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        output.flush()
    return journal


def read_records(kind: str, root: Path) -> list[dict[str, Any]]:
    journal = root / JOURNALS[kind]
    if not journal.exists():
        return []
    records = []
    for number, line in enumerate(journal.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"Cannot read {journal} line {number}: invalid JSON ({error.msg}).") from error
    return records


def display(record: dict[str, Any], kind: str) -> str:
    fields = [
        ("Record ID", record["record_id"]), ("Timestamp (UTC)", record["timestamp_utc"]),
        ("Repository root", record["repository_root"]), ("Workdir", record["workdir"]),
        ("Git branch", record.get("branch") or "not available"), ("Git HEAD", record.get("head") or "not available"),
        ("Changed/untracked files", ", ".join(record.get("changed_files", [])) or "none"),
    ]
    if kind == "agent":
        fields[2:2] = [("Agent", record["agent"]), ("Task", record["task"]), ("Status", record["status"]),
                        ("Result", record["result"]), ("Checks", record["checks"])]
    else:
        fields[2:2] = [("Summary", record["summary"]), ("Result", record["result"]),
                        ("Decision", record["decision"]), ("Links", ", ".join(record.get("links", [])) or "none")]
    if record.get("metadata_note"):
        fields.append(("Metadata note", record["metadata_note"]))
    return "\n".join(f"{label}: {value}" for label, value in fields)


def command_add(arguments: argparse.Namespace) -> int:
    root, git = repository_context()
    record = record_metadata(root, git)
    if arguments.kind == "agent":
        record.update(agent=arguments.agent, task=arguments.task, status=arguments.status,
                      result=arguments.result, checks=arguments.checks)
    else:
        try:
            links = [relative_path(link, root, "--link") for link in arguments.link]
        except ValueError as error:
            raise ValueError(str(error)) from error
        record.update(summary=arguments.summary, result=arguments.result, decision=arguments.decision, links=links)
    journal = append_record(arguments.kind, record, root)
    print(f"Added {arguments.kind} record {record['record_id']} to {journal.relative_to(root).as_posix()}.")
    return 0


def command_list(arguments: argparse.Namespace) -> int:
    root, _ = repository_context()
    records = read_records(arguments.kind, root)
    if arguments.kind == "agent" and arguments.status:
        records = [record for record in records if record.get("status") == arguments.status]
    if not records:
        print(f"No {arguments.kind} records found.")
        return 0
    for record in records:
        label = record.get("task") if arguments.kind == "agent" else record.get("summary")
        status = record.get("status", "recorded")
        print(f"{record['record_id']} | {record['timestamp_utc']} | {status} | {label}")
    return 0


def command_show(arguments: argparse.Namespace) -> int:
    root, _ = repository_context()
    records = read_records(arguments.kind, root)
    record = next((item for item in records if item.get("record_id") == arguments.record_id), None)
    if not record:
        raise ValueError(f"No {arguments.kind} record found with ID {arguments.record_id!r}.")
    print(display(record, arguments.kind))
    return 0


def command_search(arguments: argparse.Namespace) -> int:
    root, _ = repository_context()
    file_filter = getattr(arguments, "file", None)
    if file_filter:
        file_filter = relative_path(file_filter, root, "--file")
    needle = (arguments.text or "").casefold()
    records = read_records(arguments.kind, root)
    matches = []
    for record in records:
        text = json.dumps(record, ensure_ascii=False).casefold()
        files = record.get("changed_files", [])
        if needle in text and (not file_filter or file_filter in files):
            matches.append(record)
    if not matches:
        print(f"No matching {arguments.kind} records found.")
        return 0
    for record in matches:
        print(display(record, arguments.kind))
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append and search simple agent and ML work journals.",
        epilog=("Examples:\n  python tools/work_log.py agent add --agent terra_worker --task \"Update docs\" "
                "--status completed --result \"Updated docs.\" --checks \"python -m unittest: passed\"\n"
                "  python tools/work_log.py ml add --summary \"Checked baseline\" --result \"Stable.\" "
                "--decision \"Keep baseline.\" --link reports/check.md\n"
                "  python tools/work_log.py agent search roadmap --file PROJECT_ROADMAP.md"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    kinds = parser.add_subparsers(dest="kind", required=True)
    for kind in ("agent", "ml"):
        example = (
            "Example:\n  python tools/work_log.py agent add --agent terra_worker --task \"Update docs\" "
            "--status completed --result \"Updated docs.\" --checks \"python -m unittest: passed\""
            if kind == "agent" else
            "Example:\n  python tools/work_log.py ml add --summary \"Checked baseline\" --result \"Stable.\" "
            "--decision \"Keep baseline.\" --link reports/check.md"
        )
        kind_parser = kinds.add_parser(kind, help=f"manage {kind} records", epilog=example,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
        commands = kind_parser.add_subparsers(dest="command", required=True)
        add = commands.add_parser("add", help="append one final record")
        if kind == "agent":
            add.add_argument("--agent", required=True); add.add_argument("--task", required=True)
            add.add_argument("--status", required=True, choices=("completed", "failed", "interrupted"))
            add.add_argument("--result", required=True); add.add_argument("--checks", required=True)
        else:
            add.add_argument("--summary", required=True); add.add_argument("--result", required=True)
            add.add_argument("--decision", required=True); add.add_argument("--link", action="append", default=[])
        add.set_defaults(handler=command_add)
        listing = commands.add_parser("list", help="list records")
        if kind == "agent":
            listing.add_argument("--status", choices=("completed", "failed", "interrupted"))
        listing.set_defaults(handler=command_list)
        show = commands.add_parser("show", help="show one record")
        show.add_argument("record_id"); show.set_defaults(handler=command_show)
        search = commands.add_parser("search", help="search records")
        search.add_argument("text", nargs="?", default="")
        if kind == "agent":
            search.add_argument("--file", help="changed repository-relative file")
        search.set_defaults(handler=command_search)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    try:
        return arguments.handler(arguments)
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    sys.exit(main())
