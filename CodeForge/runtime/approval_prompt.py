from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 2:
        return 2
    request_path, response_path = map(Path, args)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    _set_title("CodeForge permission required")
    approved = ask_user(request)
    response_path.write_text(
        json.dumps({"decision": "allow" if approved else "deny"}),
        encoding="utf-8",
    )
    return 0


def ask_user(request: dict) -> bool:
    print("=" * 72)
    print("CodeForge requires your approval")
    print("=" * 72)
    print(f"Executor : {request.get('executor', 'agent')}")
    print(f"Stage    : {request.get('stage', 'agent')}")
    print(f"Tool     : {request.get('tool_name', 'unknown')}")
    if request.get("description"):
        print(f"Reason   : {request['description']}")
    print("\nRequested input:\n")
    print(request.get("input_preview", "(not provided)"))
    print("\nThe agent is paused until you decide.")
    while True:
        answer = input("Allow this action? [y/n] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y or n.")


def _set_title(title: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except (AttributeError, OSError):
        pass


if __name__ == "__main__":
    raise SystemExit(main())
