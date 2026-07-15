from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class ExecutorError(RuntimeError):
    """Raised when an external coding-agent CLI cannot complete a request."""


@dataclass
class CliExecutor:
    name: str
    command: Sequence[str]
    timeout_seconds: int = 1800
    interactive_approvals: bool = True
    approval_timeout_seconds: int = 1800

    @classmethod
    def from_config(cls, name: str, config: dict) -> "CliExecutor":
        command = config.get("command")
        if isinstance(command, str):
            command = shlex.split(command, posix=os.name != "nt")
        if not command or not isinstance(command, list):
            raise ValueError(f"Executor {name!r} needs a non-empty command")
        return cls(
            name=name,
            command=[str(part) for part in command],
            timeout_seconds=int(config.get("timeout_seconds", 1800)),
            interactive_approvals=bool(config.get("interactive_approvals", True)),
            approval_timeout_seconds=int(
                config.get("approval_timeout_seconds", 1800)
            ),
        )

    def run(
        self,
        prompt: str,
        cwd: Path,
        approval_state_path: Path | None = None,
        stage: str | None = None,
    ) -> str:
        command = self.build_command() if self.interactive_approvals else list(self.command)
        environment = os.environ.copy()
        if self.interactive_approvals:
            environment.update(
                {
                    "CODEFORGE_APPROVAL_EXECUTOR": self.name,
                    "CODEFORGE_APPROVAL_STAGE": stage or "agent",
                    "CODEFORGE_APPROVAL_TIMEOUT": str(self.approval_timeout_seconds),
                }
            )
            if approval_state_path is not None:
                environment["CODEFORGE_APPROVAL_STATE"] = str(approval_state_path)
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                cwd=cwd,
                env=environment,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ExecutorError(
                f"{self.name} command was not found: {self.command[0]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExecutorError(
                f"{self.name} timed out after {self.timeout_seconds} seconds"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ExecutorError(
                f"{self.name} exited with code {completed.returncode}: {detail}"
            )
        if not completed.stdout.strip():
            raise ExecutorError(f"{self.name} returned no output")
        return completed.stdout.strip()

    def build_command(self) -> list[str]:
        return list(self.command)

    def approval_hook_command(self) -> str:
        executable = str(Path(sys.executable).resolve())
        return f'"{executable}" -m CodeForge.runtime.approval_hook'
