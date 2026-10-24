from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from .models import TestSpec, new_id


def load_artifact(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_artifact(path: str | Path, artifact: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(artifact, indent=2), encoding="utf-8")


def scaffold_artifact(spec: TestSpec) -> dict[str, Any]:
    """Create an inspectable saved-test skeleton from a human testcase."""

    return {
        "artifact_version": 1,
        "id": new_id("test"),
        "spec": spec.to_dict(),
        "environment_assumptions": [
            "The target desktop session is already available and unlocked.",
            "The reusable backend may observe top-level windows and deliver ordinary GUI input.",
            "Generated tests must interact through the GUI route required by each human step.",
        ],
        "operations": [
            {
                "op": "note",
                "phase": "planning",
                "message": "Replace this scaffold with demonstrated GUI operations before claiming replay success.",
            }
        ],
        "cleanup": [],
    }
