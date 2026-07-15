from __future__ import annotations


class Router:
    def __init__(self, policies: dict):
        routing = policies.get("implementation", {})
        self.low_risk_executor = routing.get("low_risk", "claude_code")
        self.high_risk_executor = routing.get("high_risk", "codex")
        self.default_executor = routing.get("default", "codex")
        self.high_risk_keywords = [
            str(item).lower() for item in policies.get("high_risk_keywords", [])
        ]

    def classify(self, task: str, architecture: dict) -> str:
        declared = str(architecture.get("risk", "")).lower()
        if declared in {"low", "high"}:
            return declared

        haystack = " ".join(
            [task, str(architecture.get("summary", ""))]
            + [str(item) for item in architecture.get("relevant_files", [])]
        ).lower()
        if any(keyword in haystack for keyword in self.high_risk_keywords):
            return "high"
        return "unknown"

    def implementation_executor(self, task: str, architecture: dict) -> str:
        risk = self.classify(task, architecture)
        if risk == "low":
            return self.low_risk_executor
        if risk == "high":
            return self.high_risk_executor
        return self.default_executor

    def fix_executor(self, review: dict, initial_executor: str) -> str:
        if str(review.get("risk", "low")).lower() == "high":
            return self.high_risk_executor
        return initial_executor

