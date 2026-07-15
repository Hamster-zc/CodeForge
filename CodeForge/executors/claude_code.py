import json

from .base import CliExecutor


class ClaudeCodeExecutor(CliExecutor):
    """Claude Code CLI adapter."""

    def build_command(self) -> list[str]:
        settings = {
            "hooks": {
                "PermissionRequest": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": self.approval_hook_command(),
                                "timeout": self.approval_timeout_seconds,
                                "statusMessage": "Waiting for CodeForge approval",
                            }
                        ],
                    }
                ]
            }
        }
        return list(self.command) + [
            "--settings",
            json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
        ]
