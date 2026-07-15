from __future__ import annotations

import json
import subprocess
from pathlib import Path


MAX_FILE_CHARS = 30_000
MAX_DIFF_CHARS = 80_000


class ContextBuilder:
    def __init__(self, repo: Path, roles_dir: Path):
        self.repo = repo.resolve()
        self.roles_dir = roles_dir

    def architect(self, task: str) -> str:
        return self._compose(
            "architect",
            {
                "TASK": task,
                "REPOSITORY STRUCTURE": self._tree(),
                "README": self._read_optional(self.repo / "README.md"),
                "PROJECT METADATA": self._metadata(),
            },
        )

    def implementer(self, task: str, architecture_md: str, architecture: dict,
                    review_md: str | None = None) -> str:
        sections = {
            "TASK": task,
            "APPROVED ARCHITECTURE": architecture_md,
            "RELEVANT FILES": self._relevant_files(architecture),
        }
        if review_md:
            sections["REVIEW TO FIX"] = review_md
        return self._compose("implementer", sections)

    def reviewer(self, task: str, architecture_md: str) -> str:
        return self._compose(
            "reviewer",
            {
                "TASK": task,
                "APPROVED ARCHITECTURE": architecture_md,
                "GIT DIFF": self.git_diff(),
            },
        )

    def verifier(self, task: str, architecture: dict, review_md: str,
                 test_result: str) -> str:
        criteria = architecture.get("acceptance_criteria", [])
        criteria_text = "\n".join(f"- {item}" for item in criteria)
        return self._compose(
            "verifier",
            {
                "TASK": task,
                "ACCEPTANCE CRITERIA": criteria_text or "(none declared)",
                "TEST RESULT": test_result,
                "REVIEW RESULT": review_md,
            },
        )

    def git_diff(self) -> str:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--no-ext-diff", "--", "."],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return f"git diff unavailable: {result.stderr.strip()}"
        chunks = [result.stdout]
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if untracked.returncode == 0:
            for raw in untracked.stdout.splitlines():
                candidate = (self.repo / raw).resolve()
                try:
                    candidate.relative_to(self.repo)
                except ValueError:
                    continue
                if candidate.is_file():
                    content = self._read_optional(candidate)
                    chunks.append(f"\n--- /dev/null\n+++ b/{raw}\n{content}")
        combined = "".join(chunks)
        return combined[-MAX_DIFF_CHARS:] or "(no changes)"

    def _compose(self, role: str, sections: dict[str, str]) -> str:
        role_prompt = (self.roles_dir / f"{role}.md").read_text(encoding="utf-8")
        body = "\n\n".join(f"## {name}\n{value}" for name, value in sections.items())
        return f"{role_prompt.strip()}\n\n{body}\n"

    def _tree(self) -> str:
        ignored = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "tasks"}
        paths: list[str] = []
        for path in self.repo.rglob("*"):
            relative = path.relative_to(self.repo)
            if any(part in ignored for part in relative.parts):
                continue
            paths.append(str(relative) + ("/" if path.is_dir() else ""))
            if len(paths) >= 500:
                paths.append("... (truncated)")
                break
        return "\n".join(paths) or "(empty repository)"

    def _metadata(self) -> str:
        names = ["pyproject.toml", "package.json", "Cargo.toml", "go.mod"]
        chunks = []
        for name in names:
            path = self.repo / name
            if path.is_file():
                chunks.append(f"### {name}\n{self._read_optional(path)}")
        return "\n".join(chunks) or "(none)"

    def _relevant_files(self, architecture: dict) -> str:
        chunks = []
        for raw in architecture.get("relevant_files", []):
            candidate = (self.repo / str(raw)).resolve()
            try:
                candidate.relative_to(self.repo)
            except ValueError:
                chunks.append(f"### {raw}\n(skipped: outside repository)")
                continue
            if candidate.is_file():
                chunks.append(f"### {raw}\n{self._read_optional(candidate)}")
            else:
                chunks.append(f"### {raw}\n(file does not exist yet)")
        return "\n\n".join(chunks) or "(no relevant files declared)"

    @staticmethod
    def _read_optional(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(unavailable)"
        if len(text) > MAX_FILE_CHARS:
            return text[:MAX_FILE_CHARS] + "\n... (truncated)"
        return text


def extract_result(output: str) -> tuple[str, dict]:
    """Extract the machine result while preserving the human-readable response."""
    start_tag = "<CODEFORGE_RESULT>"
    end_tag = "</CODEFORGE_RESULT>"
    start = output.rfind(start_tag)
    end = output.find(end_tag, start + len(start_tag)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise ValueError("Agent output is missing the CODEFORGE_RESULT block")
    raw = output[start + len(start_tag):end].strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Agent returned invalid result JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("Agent result JSON must be an object")
    markdown = (output[:start] + output[end + len(end_tag):]).strip()
    return markdown, result
