from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class TaskState:
    task_id: str
    status: str = "created"
    stage: str = "created"
    iteration: int = 0
    approved: bool | None = None
    git_commit_before: str | None = None
    git_commit_after: str | None = None
    executors: dict[str, str] = field(default_factory=dict)
    pending_approval: dict[str, Any] | None = None
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    updated_at: str = field(default_factory=lambda: _now())

    def save(self, path: Path) -> None:
        # Permission hooks update these fields from a child process while the
        # orchestrator is blocked in the external CLI. Preserve those updates.
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                history = existing.get("approval_history", [])
                if isinstance(history, list) and len(history) > len(self.approval_history):
                    self.approval_history = history
                if existing.get("pending_approval") is not None:
                    self.pending_approval = existing["pending_approval"]
            except (OSError, json.JSONDecodeError):
                pass
        self.updated_at = _now()
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def transition(self, path: Path, stage: str, **updates: Any) -> None:
        self.stage = stage
        for key, value in updates.items():
            if not hasattr(self, key):
                raise AttributeError(f"Unknown task state field: {key}")
            setattr(self, key, value)
        self.save(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
