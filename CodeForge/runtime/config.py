from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_config(path: Path) -> dict[str, Any]:
    """Load JSON-compatible YAML.

    JSON is a subset of YAML. Keeping v0.1 configuration in this subset avoids a
    runtime dependency while retaining familiar .yaml files.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"Missing CodeForge configuration: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} must use JSON-compatible YAML syntax: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object at the top level")
    return value

