import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "work_log.py"


class WorkLogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "tools").mkdir()
        shutil.copy2(SOURCE, self.root / "tools" / "work_log.py")

    def tearDown(self):
        self.tempdir.cleanup()

    def cli(self, *args, expect=0):
        completed = subprocess.run([sys.executable, "tools/work_log.py", *args], cwd=self.root,
                                   text=True, capture_output=True, encoding="utf-8")
        self.assertEqual(completed.returncode, expect, completed.stderr)
        return completed

    def records(self, kind):
        journal = self.root / "reports" / ("agent_tasks.jsonl" if kind == "agent" else "ml_work.jsonl")
        return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]

    def make_git_repository(self):
        for command in (
            ["git", "init"], ["git", "config", "user.email", "test@example.invalid"],
            ["git", "config", "user.name", "Test"], ["git", "add", "tools/work_log.py"],
            ["git", "commit", "-m", "initial"],
        ):
            completed = subprocess.run(command, cwd=self.root, text=True, capture_output=True, encoding="utf-8")
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_agent_add_and_retrieval(self):
        self.assertIn("agent add --agent", self.cli("agent", "--help").stdout)
        self.cli("agent", "add", "--agent", "terra_worker", "--task", "Update roadmap", "--status", "completed",
                 "--result", "Updated the approved state.", "--checks", "unittest: passed")
        record = self.records("agent")[0]
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["agent"], "terra_worker")
        self.assertEqual(record["status"], "completed")
        self.assertTrue(record["record_id"])
        self.assertTrue(record["timestamp_utc"].endswith("Z"))
        self.assertFalse(record["git_available"])
        self.assertIn("repository root", record["metadata_note"].lower())
        listing = self.cli("agent", "list", "--status", "completed").stdout
        self.assertIn(record["record_id"], listing)
        self.assertIn("Update roadmap", listing)
        shown = self.cli("agent", "show", record["record_id"]).stdout
        self.assertIn("Checks: unittest: passed", shown)
        search = self.cli("agent", "search", "roadmap").stdout
        self.assertIn(record["record_id"], search)

    def test_ml_add_search_and_link_validation(self):
        self.cli("ml", "add", "--summary", "Evaluate baseline", "--result", "Stable.", "--decision", "Keep it.",
                 "--link", "reports/evaluation.md", "--link", "artifacts/plot.png")
        record = self.records("ml")[0]
        self.assertEqual(record["links"], ["reports/evaluation.md", "artifacts/plot.png"])
        self.assertIn(record["record_id"], self.cli("ml", "search", "baseline").stdout)
        invalid = self.cli("ml", "add", "--summary", "Bad", "--result", "Bad", "--decision", "Bad",
                           "--link", "../outside.md", expect=2)
        self.assertIn("repository-relative", invalid.stderr)

    def test_agent_file_filter_and_invalid_path(self):
        self.cli("agent", "add", "--agent", "worker", "--task", "Task", "--status", "failed",
                 "--result", "Stopped.", "--checks", "not run")
        record = self.records("agent")[0]
        # The fallback has no Git state, so a file filter safely finds no records.
        self.assertIn("No matching", self.cli("agent", "search", "task", "--file", "docs/report.md").stdout)
        invalid = self.cli("agent", "search", "task", "--file", "C:/outside.md", expect=2)
        self.assertIn("repository-relative", invalid.stderr)
        self.assertIn(record["record_id"], self.cli("agent", "list").stdout)

    def test_git_metadata_and_file_filter(self):
        self.make_git_repository()
        (self.root / "PROJECT_ROADMAP.md").write_text("changed\n", encoding="utf-8")
        self.cli("agent", "add", "--agent", "worker", "--task", "Update roadmap", "--status", "completed",
                 "--result", "Updated.", "--checks", "passed")
        record = self.records("agent")[0]
        self.assertTrue(record["git_available"])
        self.assertTrue(record["head"])
        self.assertIn("PROJECT_ROADMAP.md", record["changed_files"])
        filtered = self.cli("agent", "search", "roadmap", "--file", "PROJECT_ROADMAP.md").stdout
        self.assertIn(record["record_id"], filtered)


if __name__ == "__main__":
    unittest.main()
