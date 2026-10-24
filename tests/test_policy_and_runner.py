from pathlib import Path
import json
import unittest

from desktop_agent.backends import ControlInfo, MemoryDesktopBackend, WindowInfo
from desktop_agent.runner import TestRunner


class RunnerHonestyTests(unittest.TestCase):
    def test_ambiguous_window_fails_without_clicking_first_match(self) -> None:
        backend = MemoryDesktopBackend(
            [
                WindowInfo(1, "Same", "Wnd", (0, 0, 100, 100)),
                WindowInfo(2, "Same copy", "Wnd", (100, 0, 200, 100)),
            ]
        )
        artifact = self._artifact(
            [
                {"op": "click_relative", "step_id": "S1", "window_title_contains": "Same", "x": 10, "y": 10}
            ]
        )
        report = self._run(backend, artifact)
        self.assertEqual(report.status, "fail")
        self.assertNotIn(("click", (10, 10)), backend.actions)
        self.assertEqual(report.step_results[0].status, "fail")

    def test_policy_violation_is_reported_as_failure(self) -> None:
        backend = MemoryDesktopBackend([WindowInfo(1, "Target", "Wnd", (0, 0, 100, 100))])
        artifact = self._artifact(
            [{"op": "click_relative", "step_id": "S1", "window_title_contains": "Target", "x": 10, "y": 10}],
            policy={"allow_relative_coordinates": False, "allow_file_read_verification": True},
        )
        report = self._run(backend, artifact)
        self.assertEqual(report.status, "fail")
        self.assertIn("forbidden", report.actions[0].error)

    def test_dependent_step_is_skipped_after_failure(self) -> None:
        backend = MemoryDesktopBackend([])
        artifact = self._artifact(
            [
                {"op": "wait_for_window", "step_id": "S1", "title_contains": "Missing", "timeout": 0.1},
                {"op": "type_text", "step_id": "S2", "text": "must not type"},
            ]
        )
        report = self._run(backend, artifact)
        self.assertEqual(report.step_results[0].status, "fail")
        self.assertEqual(report.step_results[1].status, "skipped")
        self.assertNotIn(("type", "must not type"), backend.actions)

    def test_stale_missing_file_does_not_pass(self) -> None:
        backend = MemoryDesktopBackend([])
        artifact = self._artifact(
            [{"op": "wait_for_file", "step_id": "S1", "path": "runs/does-not-exist.txt", "timeout": 0.1}]
        )
        report = self._run(backend, artifact)
        self.assertEqual(report.status, "fail")
        self.assertIn("Timed out", report.actions[0].error)

    def test_cleanup_verification_reports_owned_window_left_open(self) -> None:
        backend = MemoryDesktopBackend([WindowInfo(1, "Target", "Wnd", (0, 0, 100, 100))])
        artifact = self._artifact(
            [{"op": "wait_for_window", "step_id": "S1", "title_contains": "Target", "timeout": 0.1}],
            cleanup=[{"op": "close_owned_windows", "wait": 0}],
        )
        report = self._run(backend, artifact)
        self.assertEqual(report.status, "fail")
        self.assertEqual(report.cleanup[0].status, "fail")

    def test_observed_control_click_records_target_evidence(self) -> None:
        backend = MemoryDesktopBackend(
            [
                WindowInfo(
                    1,
                    "Target",
                    "Wnd",
                    (0, 0, 200, 200),
                    [ControlInfo(3, "OK", "Button", (20, 20, 80, 50))],
                )
            ]
        )
        artifact = self._artifact(
            [{"op": "click_control", "step_id": "S1", "window_title_contains": "Target", "control_text": "OK"}]
        )
        report = self._run(backend, artifact)
        self.assertEqual(report.status, "pass")
        self.assertIn(("click", (50, 35)), backend.actions)
        self.assertEqual(report.actions[0].evidence[0].kind, "control")

    def _artifact(self, operations, policy=None, cleanup=None):
        step_ids = []
        for op in operations:
            step_id = op.get("step_id")
            if step_id and step_id not in step_ids:
                step_ids.append(step_id)
        return {
            "spec": {
                "id": "unit-spec",
                "policy": policy or {"allow_relative_coordinates": True, "allow_file_read_verification": True},
                "steps": [
                    {"id": step_id, "action": f"{step_id} action", "expected": f"{step_id} expected"}
                    for step_id in step_ids
                ],
            },
            "operations": operations,
            "cleanup": cleanup or [],
        }

    def _run(self, backend, artifact):
        path = Path("runs/unit-artifact.json")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(artifact), encoding="utf-8")
        return TestRunner(backend, "runs/unit-evidence").run_artifact(path)


if __name__ == "__main__":
    unittest.main()
