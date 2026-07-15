import json
import os
import tempfile
import unittest
from pathlib import Path

from CodeForge.executors.claude_code import ClaudeCodeExecutor
from CodeForge.executors.codex import CodexExecutor
from CodeForge.executors.base import CliExecutor


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

    @unittest.skipUnless(os.name == "nt", "Windows batch shim behavior")
    def test_windows_cmd_shim_is_resolved_and_receives_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "agent.cmd"
            shim.write_text("@echo off\r\nmore\r\n", encoding="utf-8")
            executor = CliExecutor(
                name="test_agent",
                command=[str(shim)],
                interactive_approvals=False,
                timeout_seconds=10,
            )
            self.assertIn("hello from CodeForge", executor.run("hello from CodeForge", Path(tmp)))

    @unittest.skipUnless(os.name == "nt", "Windows batch shim behavior")
    def test_windows_bare_npm_command_resolves_to_launchable_target(self):
        prepared = CliExecutor.prepare_command(["codex", "--version"])
        # This machine may have either a native executable or an npm shim. Both
        # must resolve to something CreateProcess can launch directly.
        resolved = __import__("shutil").which("codex")
        if resolved and Path(resolved).suffix.lower() == ".cmd":
            self.assertNotEqual(Path(prepared[0]).suffix.lower(), ".cmd")

    @unittest.skipUnless(os.name == "nt", "Windows npm shim behavior")
    def test_npm_node_shim_is_unwrapped_without_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "node_modules" / "pkg" / "cli.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("", encoding="utf-8")
            shim = root / "agent.cmd"
            shim.write_text(
                '@echo off\r\nnode "%dp0%\\node_modules\\pkg\\cli.js" %*\r\n',
                encoding="utf-8",
            )
            prepared = CliExecutor.prepare_command([str(shim), "--settings", '{"x":1}'])
            self.assertEqual(Path(prepared[1]), entry)
            self.assertEqual(prepared[-1], '{"x":1}')
            self.assertNotEqual(Path(prepared[0]).name.lower(), "cmd.exe")

    @unittest.skipUnless(os.name == "nt", "Windows npm shim behavior")
    def test_npm_native_exe_shim_is_unwrapped_without_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "node_modules" / "pkg" / "agent.exe"
            entry.parent.mkdir(parents=True)
            entry.write_bytes(b"placeholder")
            shim = root / "agent.cmd"
            shim.write_text(
                '@echo off\r\n"%dp0%\\node_modules\\pkg\\agent.exe" %*\r\n',
                encoding="utf-8",
            )
            prepared = CliExecutor.prepare_command([str(shim), "--version"])
            self.assertEqual(Path(prepared[0]), entry)
            self.assertEqual(prepared[1], "--version")


if __name__ == "__main__":
    unittest.main()
