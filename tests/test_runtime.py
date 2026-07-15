import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from CodeForge.runtime.config import load_config
from CodeForge.runtime.context import (
    ContextBuilder,
    capture_git_tree,
    extract_result,
    markdown_from_result,
)
from CodeForge.runtime.router import Router
from CodeForge.runtime.state import TaskState


class RuntimeTests(unittest.TestCase):
    def test_extract_result_separates_markdown_and_json(self):
        markdown, result = extract_result(
            "Human report\n<CODEFORGE_RESULT>\n"
            '{"verdict":"passed"}\n</CODEFORGE_RESULT>'
        )
        self.assertEqual(markdown, "Human report")
        self.assertEqual(result, {"verdict": "passed"})

    def test_extract_result_rejects_missing_block(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            extract_result("plain output")

    def test_router_uses_policy_signals_and_safe_default(self):
        router = Router(
            {
                "implementation": {
                    "low_risk": "claude_code",
                    "high_risk": "codex",
                    "default": "codex",
                },
                "high_risk_keywords": ["database schema"],
                "recognized_high_risk_factors": ["architecture_change"],
                "low_risk_max_files": 3,
            }
        )
        self.assertEqual(
            router.implementation_executor(
                "edit copy", {"risk": "high", "planned_files": ["copy.md"]}
            ),
            "claude_code",
        )
        self.assertEqual(
            router.implementation_executor(
                "small edit",
                {
                    "planned_files": ["x.py"],
                    "risk_factors": ["architecture_change"],
                },
            ),
            "codex",
        )
        self.assertEqual(
            router.implementation_executor("change database schema", {}), "codex"
        )
        self.assertEqual(router.implementation_executor("ambiguous", {}), "codex")
        self.assertEqual(
            router.fix_executor({"risk": "high"}, "claude_code"), "codex"
        )

    def test_markdown_can_be_generated_from_json_without_an_agent(self):
        markdown = markdown_from_result(
            "implementation-1",
            {
                "summary": "Created the CLI.",
                "files_changed": ["hello.py"],
                "checks": ["tests passed"],
            },
        )
        self.assertIn("# Implementation 1", markdown)
        self.assertIn("Created the CLI.", markdown)
        self.assertIn("- hello.py", markdown)

    def test_git_tree_baseline_excludes_preexisting_dirty_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "CodeForge Test"],
                cwd=repo, check=True,
            )
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "base"], cwd=repo, check=True
            )

            (repo / "base.txt").write_text("preexisting dirty\n", encoding="utf-8")
            (repo / "unrelated.txt").write_text("preexisting\n", encoding="utf-8")
            baseline = capture_git_tree(repo)
            self.assertIsNotNone(baseline)

            (repo / "task.txt").write_text("task output\n", encoding="utf-8")
            diff = ContextBuilder(repo, repo, baseline).git_diff()
            self.assertIn("task.txt", diff)
            self.assertNotIn("preexisting dirty", diff)
            self.assertNotIn("unrelated.txt", diff)

    def test_state_is_durable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = TaskState("task-1")
            state.transition(path, "review", status="running", iteration=1)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["stage"], "review")
            self.assertEqual(saved["iteration"], 1)
            self.assertIn("git_commit_before", saved)
            self.assertIn("git_tree_before", saved)

    def test_config_is_json_compatible_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text('{"max_iterations": 2}', encoding="utf-8")
            self.assertEqual(load_config(path)["max_iterations"], 2)

    def test_relevant_file_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            roles = repo / "roles"
            roles.mkdir()
            (roles / "implementer.md").write_text("role", encoding="utf-8")
            prompt = ContextBuilder(repo, roles).implementer(
                "task", "plan", {"relevant_files": ["../secret.txt"]}
            )
            self.assertIn("skipped: outside repository", prompt)


if __name__ == "__main__":
    unittest.main()
