"""Each person's files are their own.

The workspace is the permission boundary for the file tools, so a boundary two
people share is not a boundary. These tests fix that at the level the tools
actually see: a real toolbox built the way `Agent` builds it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.runtime import user_workspace
from app.config import AgentSettings
from app.memory import LOCAL_USER_ID
from app.models import ToolCall
from app.tools import CapabilityRegistry
from scripts.migrate_workspace import plan

ALICE = "0e5c4f11-2b6a-4a3f-9a1e-000000000001"
BOB = "0e5c4f11-2b6a-4a3f-9a1e-000000000002"


def toolbox_at(root: Path):
    """The conversational toolbox, rooted the way `Agent` roots it."""

    registry = CapabilityRegistry(root)
    return registry.toolbox(registry.grant())


def read(box, path: str) -> str:
    return box.run(ToolCall("c", "read_file", {"path": path})).content[0].text or ""


def listing(box, path: str = ".") -> str:
    return box.run(ToolCall("c", "list_files", {"path": path})).content[0].text or ""


# --- the roots ---------------------------------------------------------------


def test_two_people_get_two_directories(tmp_path: Path) -> None:
    assert user_workspace(tmp_path, ALICE) != user_workspace(tmp_path, BOB)


def test_a_root_is_stable_for_one_person(tmp_path: Path) -> None:
    assert user_workspace(tmp_path, ALICE) == user_workspace(tmp_path, ALICE)


def test_a_readable_identifier_is_kept_readable(tmp_path: Path) -> None:
    assert user_workspace(tmp_path, LOCAL_USER_ID).name == LOCAL_USER_ID


@pytest.mark.parametrize(
    "user_id",
    ["../escape", "..", ".", "with/slash", "with\\backslash", "", "x" * 300, "ünïcode"],
)
def test_an_awkward_identifier_cannot_escape(tmp_path: Path, user_id: str) -> None:
    root = tmp_path.resolve()

    derived = user_workspace(root, user_id)

    assert derived.parent == root
    assert root in derived.parents


def test_identifiers_that_are_not_directory_safe_do_not_collide(tmp_path: Path) -> None:
    """Substituting bad characters would merge two people; hashing does not."""

    assert user_workspace(tmp_path, "a/b") != user_workspace(tmp_path, "a\\b")


# --- what the tools can reach ------------------------------------------------


def test_one_person_cannot_read_another_s_files(tmp_path: Path) -> None:
    alice_root = user_workspace(tmp_path, ALICE)
    bob_root = user_workspace(tmp_path, BOB)
    alice_root.mkdir(parents=True)
    bob_root.mkdir(parents=True)
    (alice_root / "secret.txt").write_text("Alice private notes", encoding="utf-8")

    box = toolbox_at(bob_root)

    assert "Alice private notes" not in listing(box)
    assert "outside the allowed root" in read(box, f"../{alice_root.name}/secret.txt")


def test_a_task_directory_is_not_visible_across_people(tmp_path: Path) -> None:
    alice_root = user_workspace(tmp_path, ALICE)
    bob_root = user_workspace(tmp_path, BOB)
    (alice_root / "tasks" / "abc123").mkdir(parents=True)
    (alice_root / "tasks" / "abc123" / "notes.txt").write_text("hers", encoding="utf-8")
    bob_root.mkdir(parents=True)

    box = toolbox_at(bob_root)

    assert "error:" in listing(box, "tasks")
    assert "hers" not in read(box, "tasks/abc123/notes.txt")


def test_the_agent_factory_roots_each_user_separately(tmp_path: Path) -> None:
    from app.agent.runtime import create_agent

    settings = AgentSettings(
        database=str(tmp_path / "m.sqlite3"), workspace=str(tmp_path / "ws")
    )
    alice = create_agent(agent_settings=settings, user_id=ALICE)
    bob = create_agent(agent_settings=settings, user_id=BOB)
    try:
        assert alice.workspace != bob.workspace
        assert alice.workspace.is_dir() and bob.workspace.is_dir()
        assert alice.workspace.parent == bob.workspace.parent
    finally:
        alice.store.close()
        bob.store.close()


# --- the one-time migration --------------------------------------------------


def test_the_migration_plans_to_move_existing_files(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "old").mkdir(parents=True)
    (root / "index.html").write_text("<html>", encoding="utf-8")

    destination, movable = plan(root, LOCAL_USER_ID)

    assert destination == user_workspace(root, LOCAL_USER_ID)
    assert {entry.name for entry in movable} == {"old", "index.html"}


def test_the_migration_leaves_an_already_migrated_workspace_alone(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    user_workspace(root, LOCAL_USER_ID).mkdir(parents=True)

    _destination, movable = plan(root, LOCAL_USER_ID)

    assert movable == []
