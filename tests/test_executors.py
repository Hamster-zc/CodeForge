import json
import unittest

from CodeForge.executors.claude_code import ClaudeCodeExecutor
from CodeForge.executors.codex import CodexExecutor


class ExecutorCommandTests(unittest.TestCase):
    def test_codex_injects_permission_request_hook(self):
        executor = CodexExecutor(
            name="codex", command=["codex", "exec", "-"],
            approval_timeout_seconds=321,
        )
        command = executor.build_command()
        joined = " ".join(command)
        self.assertIn("--dangerously-bypass-hook-trust", command)
        self.assertIn("approval_policy='on-request'", command)
        self.assertIn("hooks.PermissionRequest=", joined)
        self.assertIn("timeout = 321", joined)
        self.assertEqual(command[-1], "-")

    def test_claude_injects_permission_request_hook_settings(self):
        executor = ClaudeCodeExecutor(
            name="claude_code", command=["claude", "--print"],
            approval_timeout_seconds=456,
        )
        command = executor.build_command()
        settings = json.loads(command[command.index("--settings") + 1])
        hook = settings["hooks"]["PermissionRequest"][0]["hooks"][0]
        self.assertEqual(hook["timeout"], 456)
        self.assertIn("CodeForge.runtime.approval_hook", hook["command"])


if __name__ == "__main__":
    unittest.main()
