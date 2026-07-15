from __future__ import annotations

import os
import re
import shlex
import shutil
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
        agent_command = (
            self.build_command() if self.interactive_approvals else list(self.command)
        )
        command = self.prepare_command(agent_command)
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

    @staticmethod
    def prepare_command(command: Sequence[str]) -> list[str]:
        """Resolve executables and make Windows npm .cmd shims runnable.

        PowerShell applies PATHEXT and can launch npm-generated .cmd files, but
        Windows CreateProcess (used by subprocess with shell=False) cannot run a
        batch file directly. npm shims are unwrapped to their native executable
        or Node.js entry point so JSON/TOML arguments keep their exact quoting.
        Unknown batch files fall back to cmd.exe.
        """
        prepared = [str(part) for part in command]
        if not prepared:
            return prepared
        resolved = shutil.which(prepared[0])
        if resolved:
            prepared[0] = resolved
        elif Path(prepared[0]).is_file():
            prepared[0] = str(Path(prepared[0]).resolve())

        suffix = Path(prepared[0]).suffix.lower()
        if os.name == "nt" and suffix in {".cmd", ".bat"}:
            npm_target = CliExecutor._unwrap_npm_shim(Path(prepared[0]))
            if npm_target:
                return npm_target + prepared[1:]
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            return [
                comspec,
                "/d",
                "/s",
                "/c",
                subprocess.list2cmdline(prepared),
            ]
        return prepared

    @staticmethod
    def _unwrap_npm_shim(shim: Path) -> list[str] | None:
        """Return the executable behind a standard npm Windows shim."""
        try:
            content = shim.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        matches = re.findall(
            r'"%dp0%[\\/]([^"\r\n]+\.(?:exe|js))"', content, re.IGNORECASE
        )
        if not matches:
            return None
        target = (shim.parent / matches[-1].replace("\\", os.sep)).resolve()
        if not target.is_file():
            return None
        if target.suffix.lower() == ".exe":
            return [str(target)]
        local_node = shim.parent / "node.exe"
        node = str(local_node) if local_node.is_file() else (shutil.which("node") or "node")
        return [node, str(target)]

    def approval_hook_command(self) -> str:
        executable = str(Path(sys.executable).resolve())
        return f'"{executable}" -m CodeForge.runtime.approval_hook'
