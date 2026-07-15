from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DecisionFn = Callable[[dict], bool]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        approved = handle_request(payload)
        response = _hook_response(approved)
    except Exception as exc:  # Hooks must fail closed without corrupting stdout.
        response = _hook_response(False, f"CodeForge approval failed: {exc}")
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


def handle_request(payload: dict, decision_fn: DecisionFn | None = None) -> bool:
    request = _approval_request(payload)
    state_path = _state_path()
    _record_pending(state_path, request)
    try:
        approved = (decision_fn or _ask_in_new_console)(request)
    except Exception:
        approved = False
    _record_decision(state_path, request, approved)
    return approved


def _approval_request(payload: dict) -> dict:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {"value": tool_input}
    description = tool_input.get("description") or payload.get("message") or ""
    preview = json.dumps(tool_input, ensure_ascii=False, indent=2, default=str)
    return {
        "id": str(uuid.uuid4()),
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "executor": os.environ.get("CODEFORGE_APPROVAL_EXECUTOR", "agent"),
        "stage": os.environ.get("CODEFORGE_APPROVAL_STAGE", "agent"),
        "tool_name": str(payload.get("tool_name") or "unknown"),
        "description": str(description),
        "input_preview": preview[:4000],
    }


def _ask_in_new_console(request: dict) -> bool:
    timeout = int(os.environ.get("CODEFORGE_APPROVAL_TIMEOUT", "1800"))
    with tempfile.TemporaryDirectory(prefix="codeforge-approval-") as tmp:
        request_path = Path(tmp) / "request.json"
        response_path = Path(tmp) / "response.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        command = [
            sys.executable,
            "-m",
            "CodeForge.runtime.approval_prompt",
            str(request_path),
            str(response_path),
        ]
        kwargs = {"timeout": timeout, "check": False}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        completed = subprocess.run(command, **kwargs)
        if completed.returncode != 0 or not response_path.is_file():
            return False
        response = json.loads(response_path.read_text(encoding="utf-8"))
        return response.get("decision") == "allow"


def _state_path() -> Path | None:
    raw = os.environ.get("CODEFORGE_APPROVAL_STATE")
    return Path(raw) if raw else None


def _record_pending(path: Path | None, request: dict) -> None:
    if path is None or not path.is_file():
        return
    state = _read_json(path)
    state["status"] = "awaiting_approval"
    state["pending_approval"] = request
    _write_json(path, state)


def _record_decision(path: Path | None, request: dict, approved: bool) -> None:
    if path is None or not path.is_file():
        return
    state = _read_json(path)
    history = state.get("approval_history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            **request,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "decision": "allow" if approved else "deny",
        }
    )
    state["approval_history"] = history
    state["pending_approval"] = None
    state["status"] = "running"
    _write_json(path, state)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _hook_response(approved: bool, message: str | None = None) -> dict:
    decision: dict[str, str] = {"behavior": "allow" if approved else "deny"}
    if not approved:
        decision["message"] = message or "User denied the permission request."
    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision,
        }
    }


if __name__ == "__main__":
    raise SystemExit(main())

