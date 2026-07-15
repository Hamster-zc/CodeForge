import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from CodeForge.runtime.approval_hook import _hook_response, handle_request
from CodeForge.runtime.approval_prompt import ask_user
from CodeForge.runtime.state import TaskState


class ApprovalTests(unittest.TestCase):
    def test_approval_updates_durable_task_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = TaskState("task-1", status="running", stage="implementation")
            state.save(state_path)
            payload = {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python -m pip install example",
                    "description": "Install a dependency",
                },
            }
            with patch.dict(
                "os.environ",
                {
                    "CODEFORGE_APPROVAL_STATE": str(state_path),
                    "CODEFORGE_APPROVAL_EXECUTOR": "claude_code",
                    "CODEFORGE_APPROVAL_STAGE": "implementation",
                },
            ):
                approved = handle_request(payload, decision_fn=lambda request: True)

            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(approved)
            self.assertEqual(saved["status"], "running")
            self.assertIsNone(saved["pending_approval"])
            self.assertEqual(saved["approval_history"][0]["decision"], "allow")
            self.assertEqual(saved["approval_history"][0]["tool_name"], "Bash")

            # A later orchestrator transition must preserve hook-written history.
            state.transition(state_path, "review")
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["approval_history"]), 1)

    def test_hook_response_uses_shared_permission_request_shape(self):
        allowed = _hook_response(True)
        denied = _hook_response(False)
        self.assertEqual(
            allowed["hookSpecificOutput"]["decision"]["behavior"], "allow"
        )
        self.assertEqual(
            denied["hookSpecificOutput"]["decision"]["behavior"], "deny"
        )

    def test_terminal_prompt_repeats_until_valid_answer(self):
        with patch("builtins.input", side_effect=["maybe", "y"]):
            self.assertTrue(ask_user({"tool_name": "Bash", "input_preview": "x"}))


if __name__ == "__main__":
    unittest.main()

