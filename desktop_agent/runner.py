from __future__ import annotations

from pathlib import Path
from typing import Any
import time

from .artifact import load_artifact
from .backends import ControlInfo, DesktopBackend, WindowInfo
from .models import ActionRecord, Evidence, ExecutionReport, StepResult, now_iso, new_id


class TestRunner:
    def __init__(self, backend: DesktopBackend, evidence_dir: str | Path) -> None:
        self.backend = backend
        self.evidence_dir = Path(evidence_dir)
        self.actions: list[ActionRecord] = []
        self.cleanup_actions: list[ActionRecord] = []
        self.owned_windows: set[int] = set()

    def run_artifact(self, artifact_path: str | Path) -> ExecutionReport:
        artifact = load_artifact(artifact_path)
        spec = artifact["spec"]
        policy = spec.get("policy", {})
        step_results = {
            step["id"]: StepResult(step["id"], step["action"], step["expected"])
            for step in spec["steps"]
        }
        started = now_iso()
        status = "pass"

        try:
            for op in artifact.get("operations", []):
                step_id = op.get("step_id")
                if op.get("op") == "note":
                    continue
                if step_id and step_results[step_id].status == "blocked":
                    continue
                record = self._perform(op, policy)
                self.actions.append(record)
                if step_id:
                    step = step_results[step_id]
                    step.interpreted_route.append(self._route_summary(op, record))
                    step.evidence.extend(record.evidence)
                    if record.status in {"fail", "blocked", "incomplete"}:
                        step.status = record.status
                        step.notes.append(record.error or record.observed_consequence or "Operation did not pass.")
                        status = "fail"
                        self._mark_dependents_skipped(artifact, step_results, step_id)
                        break
        except Exception as exc:
            status = "fail"
            rec = ActionRecord(new_id("action"), None, "replay", "runner exception")
            rec.finish("fail", error=str(exc))
            self.actions.append(rec)

        for step in step_results.values():
            if step.status == "incomplete":
                checks = [a for a in self.actions if a.step_id == step.step_id and a.status == "pass"]
                step.status = "pass" if checks else "skipped"
                if step.status == "skipped":
                    status = "fail"
                    step.notes.append("No successful operation was recorded for this required step.")

        self._cleanup(artifact)
        if any(action.status != "pass" for action in self.cleanup_actions):
            status = "fail"

        report = ExecutionReport(
            report_id=new_id("report"),
            spec_id=spec["id"],
            artifact_path=str(Path(artifact_path).resolve()),
            phase="replay",
            status=status,
            policy=policy,
            started_at=started,
            ended_at=now_iso(),
            step_results=list(step_results.values()),
            actions=self.actions,
            cleanup=self.cleanup_actions,
            metrics={
                "operation_count": len(self.actions),
                "cleanup_operation_count": len(self.cleanup_actions),
            },
        )
        return report

    def _perform(self, op: dict[str, Any], policy: dict[str, Any]) -> ActionRecord:
        step_id = op.get("step_id")
        record = ActionRecord(new_id("action"), step_id, "replay", op.get("intent", op["op"]))
        try:
            name = op["op"]
            if name == "launch":
                pid = self.backend.launch(op["command"], op.get("cwd"))
                record.attempted_action = "launch"
                record.delivered_input = {"command": op["command"], "pid": pid}
                record.finish("pass", f"Launch requested for pid {pid}.")
            elif name == "wait_for_window":
                window = self._wait_for_window(op["title_contains"], op.get("timeout", policy.get("max_wait_seconds", 10)))
                self.owned_windows.add(window.handle)
                record.evidence.append(self._window_evidence(window))
                record.finish("pass", f"Observed window '{window.title}'.")
            elif name == "click_relative":
                self._check_policy(policy, "relative_click", op)
                window = self._find_window(op["window_title_contains"])
                self.backend.focus_window(window.handle)
                x = window.rect[0] + int(op["x"])
                y = window.rect[1] + int(op["y"])
                record.attempted_action = "click_relative"
                record.delivered_input = {"x": x, "y": y, "anchor_window": window.title}
                record.evidence.append(self._window_evidence(window))
                self.backend.click(x, y)
                record.finish("pass", f"Clicked relative to observed window '{window.title}'.")
            elif name == "click_control":
                window = self._find_window(op["window_title_contains"])
                control = self._find_control(window, op["control_text"])
                self.backend.focus_window(window.handle)
                x = (control.rect[0] + control.rect[2]) // 2
                y = (control.rect[1] + control.rect[3]) // 2
                record.attempted_action = "click_control"
                record.delivered_input = {"control_text": control.text, "class_name": control.class_name, "x": x, "y": y}
                record.evidence.append(self._control_evidence(window, control))
                self.backend.click(x, y)
                record.finish("pass", f"Clicked observed control '{control.text}'.")
            elif name == "type_text":
                text = op["text"]
                record.attempted_action = "type_text"
                record.delivered_input = {"literal_text": text}
                self.backend.type_text(text)
                record.finish("pass", "Literal text delivery requested; correctness requires a later readback or assertion.")
            elif name == "wait_for_file":
                path = Path(op["path"])
                min_mtime = op.get("not_before")
                evidence = self._wait_for_file(path, op.get("timeout", policy.get("max_wait_seconds", 10)), min_mtime)
                record.evidence.append(evidence)
                record.finish("pass", f"Observed output file '{path}'.")
            elif name == "remove_file":
                path = Path(op["path"])
                existed = path.exists()
                if existed:
                    path.unlink()
                ok = not path.exists()
                record.attempted_action = "remove_file"
                record.delivered_input = {"path": str(path), "existed_before": existed}
                record.finish("pass" if ok else "fail", f"File absence checked for {path}.")
            elif name == "assert_file_contains":
                self._check_policy(policy, "file_read", op)
                path = Path(op["path"])
                expected = op["text"]
                content = path.read_text(encoding=op.get("encoding", "utf-8"))
                ok = expected in content
                record.evidence.append(Evidence("file-content", f"Read {len(content)} characters from {path}.", {"path": str(path), "expected_text": expected}))
                record.finish("pass" if ok else "fail", "Expected text was present." if ok else "Expected text was not present.")
            elif name == "assert_window_text":
                window = self._find_window(op["window_title_contains"])
                haystack = "\n".join([window.title, *[c.text for c in window.controls]])
                expected = op["text"]
                ok = expected in haystack
                record.evidence.append(self._window_evidence(window))
                record.finish("pass" if ok else "fail", "Expected visible text was present." if ok else "Expected visible text was not observed.")
            elif name == "screenshot":
                path = self.evidence_dir / f"{new_id('screenshot')}.png"
                self.backend.screenshot(path)
                record.evidence.append(Evidence("screenshot", "Captured desktop screenshot.", path=str(path)))
                record.finish("pass", "Screenshot captured as diagnostic evidence, not by itself a functional assertion.")
            else:
                record.finish("blocked", error=f"Unsupported operation '{name}'.")
        except Exception as exc:
            record.finish("fail", error=str(exc))
        return record

    def _cleanup(self, artifact: dict[str, Any]) -> None:
        for op in artifact.get("cleanup", []):
            rec = ActionRecord(new_id("cleanup"), op.get("step_id"), "cleanup", op.get("intent", op["op"]))
            try:
                if op["op"] == "close_owned_windows":
                    for handle in list(self.owned_windows):
                        self.backend.close_window(handle)
                    time.sleep(float(op.get("wait", 0.5)))
                    remaining = {w.handle for w in self.backend.windows()}
                    open_owned = self.owned_windows & remaining
                    if open_owned:
                        rec.finish("fail", f"Owned windows still visible: {sorted(open_owned)}")
                    else:
                        rec.finish("pass", "Owned windows closed and disappearance was verified.")
                elif op["op"] == "remove_file":
                    path = Path(op["path"])
                    if path.exists():
                        path.unlink()
                    rec.finish("pass" if not path.exists() else "fail", f"File removal checked for {path}.")
                else:
                    rec.finish("blocked", error=f"Unsupported cleanup operation '{op['op']}'.")
            except Exception as exc:
                rec.finish("fail", error=str(exc))
            self.cleanup_actions.append(rec)

    def _find_window(self, title_contains: str) -> WindowInfo:
        matches = [w for w in self.backend.windows() if title_contains in w.title]
        if not matches:
            raise LookupError(f"No visible window title contained '{title_contains}'.")
        if len(matches) > 1:
            titles = [m.title for m in matches]
            raise LookupError(f"Ambiguous window target for '{title_contains}': {titles}")
        return matches[0]

    def _wait_for_window(self, title_contains: str, timeout: float) -> WindowInfo:
        deadline = time.time() + float(timeout)
        last_titles: list[str] = []
        while time.time() < deadline:
            windows = self.backend.windows()
            last_titles = [w.title for w in windows]
            matches = [w for w in windows if title_contains in w.title]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise LookupError(f"Ambiguous window target for '{title_contains}': {[m.title for m in matches]}")
            time.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for window containing '{title_contains}'. Last titles: {last_titles}")

    def _find_control(self, window: WindowInfo, text: str) -> ControlInfo:
        matches = [c for c in window.controls if c.text == text]
        if not matches:
            raise LookupError(f"No visible child control named '{text}' in '{window.title}'.")
        if len(matches) > 1:
            raise LookupError(f"Ambiguous control target '{text}' in '{window.title}'.")
        return matches[0]

    def _wait_for_file(self, path: Path, timeout: float, not_before: float | None) -> Evidence:
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if path.exists():
                stat = path.stat()
                if not_before is None or stat.st_mtime >= float(not_before):
                    return Evidence("file", f"Observed fresh file {path}.", {"path": str(path), "mtime": stat.st_mtime, "size": stat.st_size})
            time.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for fresh file {path}.")

    def _check_policy(self, policy: dict[str, Any], action: str, op: dict[str, Any]) -> None:
        if action == "relative_click" and not policy.get("allow_relative_coordinates", True):
            raise PermissionError("Relative coordinate interaction is forbidden by policy.")
        if action == "file_read" and not policy.get("allow_file_read_verification", True):
            raise PermissionError("Read-only file verification is forbidden by policy.")
        if op.get("fallback") and policy.get("visible_controls_only", True) and action == "relative_click":
            raise PermissionError("Fallback relative click is forbidden under visible-controls-only policy.")

    def _window_evidence(self, window: WindowInfo) -> Evidence:
        return Evidence(
            "window",
            f"Observed window '{window.title}' with {len(window.controls)} visible child controls.",
            {
                "handle": window.handle,
                "title": window.title,
                "class_name": window.class_name,
                "rect": window.rect,
                "controls": [control.__dict__ for control in window.controls[:50]],
            },
        )

    def _control_evidence(self, window: WindowInfo, control: ControlInfo) -> Evidence:
        return Evidence(
            "control",
            f"Observed control '{control.text}' in '{window.title}'.",
            {"window": window.title, "control": control.__dict__},
        )

    def _route_summary(self, op: dict[str, Any], record: ActionRecord) -> str:
        return f"{op['op']}: {record.observed_consequence or record.error or record.status}"

    def _mark_dependents_skipped(self, artifact: dict[str, Any], step_results: dict[str, StepResult], failed_step_id: str) -> None:
        seen = False
        for step in artifact["spec"]["steps"]:
            if step["id"] == failed_step_id:
                seen = True
                continue
            if seen and step_results[step["id"]].status == "incomplete":
                step_results[step["id"]].status = "skipped"
                step_results[step["id"]].notes.append(f"Skipped because required earlier step {failed_step_id} did not pass.")
