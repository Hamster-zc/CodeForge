import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from CodeForge.cli import run_task


def response(markdown, result):
    return (
        f"{markdown}\n<CODEFORGE_RESULT>\n"
        f"{json.dumps(result)}\n</CODEFORGE_RESULT>"
    )


class FakeExecutor:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def run(self, prompt, cwd, approval_state_path=None, stage=None):
        if not self.outputs:
            raise AssertionError("unexpected executor call")
        return self.outputs.pop(0)


class CliWorkflowTests(unittest.TestCase):
    def make_repo(self, root):
        repo = Path(root)
        forge = repo / ".agentforge"
        roles = forge / "roles"
        roles.mkdir(parents=True)
        (repo / "tasks").mkdir()
        for role in ("architect", "implementer", "reviewer", "verifier"):
            (roles / f"{role}.md").write_text(role, encoding="utf-8")
        (forge / "config.yaml").write_text(
            '{"executors":{"codex":{"command":["unused"]},'
            '"claude_code":{"command":["unused"]}},"test":{}}',
            encoding="utf-8",
        )
        (forge / "workflow.yaml").write_text(
            '{"max_iterations":2}', encoding="utf-8"
        )
        (forge / "policies.yaml").write_text(
            '{"implementation":{"low_risk":"claude_code",'
            '"high_risk":"codex","default":"codex"},'
            '"recognized_high_risk_factors":["architecture_change"],'
            '"low_risk_max_files":8}',
            encoding="utf-8",
        )
        task = repo / "request.md"
        task.write_text("# Task\nChange a small file.", encoding="utf-8")
        return repo, task

    def test_full_approved_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, task = self.make_repo(tmp)
            codex = FakeExecutor(
                [
                    response("Plan", {
                        "summary": "small change", "risk": "low",
                        "risk_factors": [], "planned_files": ["small.py"],
                        "relevant_files": [], "acceptance_criteria": ["done"],
                    }),
                    response("Looks good", {
                        "verdict": "approved", "risk": "low", "issues": [],
                    }),
                    response("Verified", {
                        "verdict": "passed", "summary": "done", "evidence": [],
                    }),
                ]
            )
            claude = FakeExecutor(
                [response("Implemented", {
                    "summary": "done", "files_changed": [], "checks": [],
                })]
            )
            with patch("CodeForge.cli._build_executors", return_value={
                "codex": codex, "claude_code": claude,
            }), patch("builtins.input", return_value="y"), patch(
                "CodeForge.cli._run_tests", return_value=("tests passed", True)
            ):
                code = run_task(task, repo)

            self.assertEqual(code, 0)
            workspaces = [path for path in (repo / "tasks").iterdir() if path.is_dir()]
            self.assertEqual(len(workspaces), 1)
            state = json.loads((workspaces[0] / "state.json").read_text())
            self.assertEqual(state["status"], "done")
            self.assertEqual(state["executors"]["implementer"], "claude_code")
            self.assertTrue((workspaces[0] / "artifacts" / "review.json").is_file())
            self.assertTrue((workspaces[0] / "artifacts" / "verification.json").is_file())

    def test_human_rejection_stops_before_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, task = self.make_repo(tmp)
            codex = FakeExecutor([response("Plan", {
                "summary": "plan", "risk": "high", "relevant_files": [],
                "risk_factors": ["architecture_change"], "planned_files": [],
                "acceptance_criteria": [],
            })])
            with patch("CodeForge.cli._build_executors", return_value={
                "codex": codex, "claude_code": FakeExecutor([]),
            }), patch("builtins.input", return_value="n"):
                code = run_task(task, repo)
            self.assertEqual(code, 2)
            workspace = next(path for path in (repo / "tasks").iterdir() if path.is_dir())
            state = json.loads((workspace / "state.json").read_text())
            self.assertEqual(state["status"], "cancelled")
            self.assertFalse(state["approved"])

    def test_review_requests_one_bounded_fix_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, task = self.make_repo(tmp)
            codex = FakeExecutor(
                [
                    response("Plan", {
                        "summary": "small", "risk": "low",
                        "risk_factors": [], "planned_files": ["small.py"],
                        "relevant_files": [], "acceptance_criteria": [],
                    }),
                    response("Fix one issue", {
                        "verdict": "changes_requested", "risk": "low",
                        "issues": [{"severity": "low", "file": "x", "description": "fix"}],
                    }),
                    response("Approved", {
                        "verdict": "approved", "risk": "low", "issues": [],
                    }),
                    response("Verified", {
                        "verdict": "passed", "summary": "done", "evidence": [],
                    }),
                ]
            )
            implementation = response("Implemented", {
                "summary": "done", "files_changed": [], "checks": [],
            })
            claude = FakeExecutor([implementation, implementation])
            with patch("CodeForge.cli._build_executors", return_value={
                "codex": codex, "claude_code": claude,
            }), patch("builtins.input", return_value="y"), patch(
                "CodeForge.cli._run_tests", return_value=("tests passed", True)
            ):
                code = run_task(task, repo)

            self.assertEqual(code, 0)
            workspace = next(path for path in (repo / "tasks").iterdir() if path.is_dir())
            state = json.loads((workspace / "state.json").read_text())
            self.assertEqual(state["iteration"], 2)
            self.assertEqual(state["executors"]["fix_1"], "claude_code")
            self.assertTrue((workspace / "artifacts" / "implementation-2.json").is_file())

    def test_json_only_agent_output_generates_markdown_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, task = self.make_repo(tmp)
            codex = FakeExecutor(
                [
                    response("Plan", {
                        "summary": "small", "risk": "low", "risk_factors": [],
                        "planned_files": ["small.py"], "relevant_files": [],
                        "acceptance_criteria": [],
                    }),
                    response("Approved", {
                        "verdict": "approved", "risk": "low", "issues": [],
                    }),
                    response("Verified", {
                        "verdict": "passed", "summary": "done", "evidence": [],
                    }),
                ]
            )
            claude = FakeExecutor([response("", {
                "summary": "JSON-only implementation",
                "files_changed": ["small.py"], "checks": [],
            })])
            with patch("CodeForge.cli._build_executors", return_value={
                "codex": codex, "claude_code": claude,
            }), patch("builtins.input", return_value="y"), patch(
                "CodeForge.cli._run_tests", return_value=("tests passed", True)
            ):
                self.assertEqual(run_task(task, repo), 0)

            workspace = next(path for path in (repo / "tasks").iterdir() if path.is_dir())
            markdown = (
                workspace / "artifacts" / "implementation-1.md"
            ).read_text(encoding="utf-8")
            self.assertIn("JSON-only implementation", markdown)
            self.assertIn("small.py", markdown)


if __name__ == "__main__":
    unittest.main()
