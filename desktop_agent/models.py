from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import json
import uuid

Status = Literal["pass", "fail", "blocked", "skipped", "incomplete"]
Phase = Literal["planning", "exploration", "replay", "cleanup", "system-check"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class InteractionPolicy:
    """Explicit permissions for GUI interaction."""

    name: str = "observed-visible-controls"
    visible_controls_only: bool = True
    allow_shortcuts: bool = False
    allow_clipboard: bool = False
    allow_relative_coordinates: bool = True
    allow_file_read_verification: bool = True
    max_wait_seconds: float = 10.0

    def check(self, action: str, *, fallback: bool = False) -> None:
        if action == "shortcut" and not self.allow_shortcuts:
            raise PermissionError("Shortcut use is not permitted by the interaction policy.")
        if action == "clipboard" and not self.allow_clipboard:
            raise PermissionError("Clipboard use is not permitted by the interaction policy.")
        if action == "relative_click" and not self.allow_relative_coordinates:
            raise PermissionError("Relative coordinate clicks are not permitted by the interaction policy.")
        if fallback and self.visible_controls_only and action == "relative_click":
            raise PermissionError("Fallback to relative coordinates violates the visible-controls-only policy.")


@dataclass
class TestStep:
    id: str
    action: str
    expected: str
    data: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)


@dataclass
class TestSpec:
    id: str
    title: str
    application: str
    prerequisites: list[str]
    steps: list[TestStep]
    policy: InteractionPolicy = field(default_factory=InteractionPolicy)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TestSpec":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        policy = InteractionPolicy(**raw.get("policy", {}))
        steps = [TestStep(**step) for step in raw["steps"]]
        return cls(
            id=raw.get("id", new_id("spec")),
            title=raw["title"],
            application=raw.get("application", ""),
            prerequisites=raw.get("prerequisites", []),
            steps=steps,
            policy=policy,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "application": self.application,
            "prerequisites": self.prerequisites,
            "policy": self.policy.__dict__,
            "steps": [step.__dict__ for step in self.steps],
        }


@dataclass
class Evidence:
    kind: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    path: str | None = None
    timestamp: str = field(default_factory=now_iso)


@dataclass
class ActionRecord:
    action_id: str
    step_id: str | None
    phase: Phase
    intended_action: str
    attempted_action: str | None = None
    delivered_input: dict[str, Any] = field(default_factory=dict)
    observed_consequence: str | None = None
    fallback_reason: str | None = None
    status: Status = "incomplete"
    evidence: list[Evidence] = field(default_factory=list)
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    error: str | None = None

    def finish(self, status: Status, consequence: str | None = None, error: str | None = None) -> None:
        self.status = status
        self.observed_consequence = consequence
        self.error = error
        self.ended_at = now_iso()


@dataclass
class StepResult:
    step_id: str
    original_action: str
    original_expected: str
    interpreted_route: list[str] = field(default_factory=list)
    status: Status = "incomplete"
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ExecutionReport:
    report_id: str
    spec_id: str
    artifact_path: str
    phase: Phase
    status: Status
    policy: dict[str, Any]
    started_at: str
    ended_at: str
    step_results: list[StepResult]
    actions: list[ActionRecord]
    cleanup: list[ActionRecord]
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "spec_id": self.spec_id,
            "artifact_path": self.artifact_path,
            "phase": self.phase,
            "status": self.status,
            "policy": self.policy,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "step_results": [_dataclass_to_dict(step) for step in self.step_results],
            "actions": [_dataclass_to_dict(action) for action in self.actions],
            "cleanup": [_dataclass_to_dict(action) for action in self.cleanup],
            "metrics": self.metrics,
        }

    def write(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def _dataclass_to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {key: _dataclass_to_dict(getattr(obj, key)) for key in obj.__dataclass_fields__}
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _dataclass_to_dict(value) for key, value in obj.items()}
    return obj
