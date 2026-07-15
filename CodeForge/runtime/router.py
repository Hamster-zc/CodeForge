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
        self.high_risk_factors = {
            str(item).lower()
            for item in policies.get("recognized_high_risk_factors", [])
        }
        self.low_risk_max_files = max(
            0, int(policies.get("low_risk_max_files", 8))
        )

    def classify(self, task: str, architecture: dict) -> str:
        haystack = " ".join(
            [task, str(architecture.get("summary", ""))]
            + [str(item) for item in architecture.get("planned_files", [])]
        ).lower()
        if any(keyword in haystack for keyword in self.high_risk_keywords):
            return "high"

        factors = {
            str(item).lower() for item in architecture.get("risk_factors", [])
        }
        if factors & self.high_risk_factors:
            return "high"

        planned_files = architecture.get("planned_files")
        if (
            isinstance(planned_files, list)
            and len(planned_files) <= self.low_risk_max_files
        ):
            return "low"
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
