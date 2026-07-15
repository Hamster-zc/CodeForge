from .base import CliExecutor


class CodexExecutor(CliExecutor):
    """Codex CLI adapter."""

    def build_command(self) -> list[str]:
        command = list(self.command)
        hook = self.approval_hook_command().replace("'", "''")
        timeout = self.approval_timeout_seconds
        hooks_value = (
            "[{ matcher = '*', hooks = [{ type = 'command', "
            f"command_windows = '{hook}', command = '{hook}', "
            f"timeout = {timeout}, statusMessage = 'Waiting for CodeForge approval'"
            " }] }]"
        )
        additions = [
            "--dangerously-bypass-hook-trust",
            "-c",
            "approval_policy='on-request'",
            "-c",
            f"hooks.PermissionRequest={hooks_value}",
        ]
        insert_at = len(command) - 1 if command and command[-1] == "-" else len(command)
        return command[:insert_at] + additions + command[insert_at:]
