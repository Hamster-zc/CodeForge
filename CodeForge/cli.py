from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .executors import ClaudeCodeExecutor, CodexExecutor
from .executors.base import CliExecutor, ExecutorError
from .runtime.config import load_config
from .runtime.context import ContextBuilder, extract_result
from .runtime.router import Router
from .runtime.state import TaskState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeforge")
    parser.add_argument("--version", action="version", version="CodeForge 0.1.1")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run a task through the workflow")
    run.add_argument("task", type=Path, help="path to the task Markdown file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        try:
            return run_task(args.task)
        except (ExecutorError, OSError, ValueError) as exc:
            print(f"CodeForge error: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nCodeForge interrupted.", file=sys.stderr)
            return 130
    return 1


def run_task(task_path: Path, repo: Path | None = None) -> int:
    repo = (repo or Path.cwd()).resolve()
    task_path = task_path.resolve()
    if not task_path.is_file():
        raise ValueError(f"Task file does not exist: {task_path}")

    forge_dir = repo / ".agentforge"
    config = load_config(forge_dir / "config.yaml")
    workflow = load_config(forge_dir / "workflow.yaml")
    policies = load_config(forge_dir / "policies.yaml")
    task_text = task_path.read_text(encoding="utf-8", errors="replace")
    if not task_text.strip():
        raise ValueError("Task file is empty")

    task_id = _task_id(task_path)
    workspace = repo / "tasks" / task_id
    artifacts = workspace / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(task_path, workspace / "task.md")
    state_path = workspace / "state.json"
    state = TaskState(task_id=task_id, git_commit_before=_git_head(repo))
    state.save(state_path)

    executors = _build_executors(config)
    context = ContextBuilder(repo, forge_dir / "roles")
    router = Router(policies)
    max_iterations = max(1, int(workflow.get("max_iterations", 2)))

    try:
        state.transition(state_path, "architect", status="running")
        architecture_md, architecture = _invoke_artifact(
            executors["codex"], context.architect(task_text), repo,
            artifacts, "architecture", state_path, "architect"
        )
        _require_fields(
            architecture,
            "architecture",
            {"summary", "risk", "relevant_files", "acceptance_criteria"},
        )
        state.executors["architect"] = "codex"
        state.save(state_path)

        print("\nArchitecture plan generated:\n")
        print(architecture_md)
        state.transition(state_path, "human_approval")
        if not _request_approval():
            state.transition(state_path, "cancelled", status="cancelled", approved=False)
            print(f"Task cancelled. Artifacts: {workspace}")
            return 2
        state.transition(state_path, "implementation", approved=True)

        implementation_executor = router.implementation_executor(task_text, architecture)
        if implementation_executor not in executors:
            raise ValueError(f"Unknown routed executor: {implementation_executor}")
        state.executors["implementer"] = implementation_executor
        implementation_md, _ = _invoke_artifact(
            executors[implementation_executor],
            context.implementer(task_text, architecture_md, architecture),
            repo, artifacts, "implementation-1", state_path, "implementation",
        )

        review: dict = {}
        review_md = ""
        for iteration in range(1, max_iterations + 1):
            state.transition(state_path, "review", iteration=iteration)
            review_md, review = _invoke_artifact(
                executors["codex"], context.reviewer(task_text, architecture_md),
                repo, artifacts, f"review-{iteration}", state_path, "review",
            )
            _require_fields(review, "review", {"verdict", "risk", "issues"})
            state.executors[f"reviewer_{iteration}"] = "codex"
            state.save(state_path)
            if review.get("verdict") == "approved":
                break
            if iteration >= max_iterations:
                break

            state.transition(state_path, "fix", iteration=iteration)
            fix_executor = router.fix_executor(review, implementation_executor)
            state.executors[f"fix_{iteration}"] = fix_executor
            implementation_md, _ = _invoke_artifact(
                executors[fix_executor],
                context.implementer(task_text, architecture_md, architecture, review_md),
                repo, artifacts, f"implementation-{iteration + 1}",
                state_path, "fix",
            )

        # Keep iteration history and expose the stable v0.1 artifact names.
        shutil.copyfile(artifacts / f"review-{state.iteration}.md", artifacts / "review.md")
        shutil.copyfile(artifacts / f"review-{state.iteration}.json", artifacts / "review.json")

        state.transition(state_path, "verification")
        test_result, tests_passed = _run_tests(repo, config.get("test", {}))
        verification_md, verification = _invoke_artifact(
            executors["codex"],
            context.verifier(task_text, architecture, review_md, test_result),
            repo, artifacts, "verification", state_path, "verification",
        )
        _require_fields(verification, "verification", {"verdict", "summary"})
        state.executors["verifier"] = "codex"
        succeeded = (
            review.get("verdict") == "approved"
            and tests_passed
            and verification.get("verdict") == "passed"
        )
        final_status = "done" if succeeded else "failed"
        state.transition(
            state_path,
            final_status,
            status=final_status,
            git_commit_after=_git_head(repo),
        )

        print("\nVerification result:\n")
        print(verification_md)
        print(f"\nTask {final_status}. Artifacts: {workspace}")
        return 0 if succeeded else 3
    except Exception as exc:
        state.transition(state_path, "failed", status="failed", error=str(exc))
        raise


def _build_executors(config: dict) -> dict[str, CliExecutor]:
    values = config.get("executors", {})
    if not isinstance(values, dict):
        raise ValueError("config.yaml executors must be an object")
    try:
        return {
            "codex": CodexExecutor.from_config("codex", values["codex"]),
            "claude_code": ClaudeCodeExecutor.from_config(
                "claude_code", values["claude_code"]
            ),
        }
    except KeyError as exc:
        raise ValueError(f"Missing executor configuration: {exc.args[0]}") from exc


def _invoke_artifact(executor: CliExecutor, prompt: str, repo: Path,
                     artifacts: Path, name: str, state_path: Path,
                     stage: str) -> tuple[str, dict]:
    output = executor.run(
        prompt, repo, approval_state_path=state_path, stage=stage
    )
    markdown, result = extract_result(output)
    (artifacts / f"{name}.md").write_text(markdown + "\n", encoding="utf-8")
    (artifacts / f"{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return markdown, result


def _request_approval() -> bool:
    while True:
        answer = input("\nContinue? [y/n] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y or n.")


def _run_tests(repo: Path, test_config: dict) -> tuple[str, bool]:
    command = test_config.get("command", []) if isinstance(test_config, dict) else []
    if not command:
        return "No test command configured; verification must use other evidence.", True
    if not isinstance(command, list):
        raise ValueError("test.command must be an array")
    timeout = int(test_config.get("timeout_seconds", 600))
    try:
        completed = subprocess.run(
            [str(item) for item in command], cwd=repo, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
            timeout=timeout, check=False,
        )
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        report = f"Command: {command}\nExit code: {completed.returncode}\n{output}"
        return report[-80_000:], completed.returncode == 0
    except FileNotFoundError as exc:
        return f"Test command not found: {command[0]} ({exc})", False
    except subprocess.TimeoutExpired:
        return f"Tests timed out after {timeout} seconds", False


def _require_fields(value: dict, artifact: str, required: set[str]) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"{artifact} result is missing fields: {', '.join(missing)}")


def _task_id(path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", path.stem).strip("-").lower() or "task"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{slug[:40]}"


def _git_head(repo: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
        encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None
