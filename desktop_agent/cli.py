from __future__ import annotations

from pathlib import Path
import argparse
import json

from .artifact import scaffold_artifact, write_artifact
from .backends import Win32DesktopBackend
from .models import TestSpec
from .runner import TestRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desktop-agent", description="Author and replay evidence-backed desktop GUI tests.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("scaffold", help="Create an inspectable saved-test skeleton from a JSON testcase.")
    init.add_argument("spec")
    init.add_argument("output")

    inspect = sub.add_parser("inspect", help="List currently visible windows and observed child controls.")
    inspect.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="Run a saved desktop test artifact.")
    run.add_argument("artifact")
    run.add_argument("--evidence-dir", default="runs/evidence")
    run.add_argument("--report", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "scaffold":
        spec = TestSpec.from_json_file(args.spec)
        write_artifact(args.output, scaffold_artifact(spec))
        print(f"Wrote scaffold artifact: {Path(args.output).resolve()}")
        return 0

    if args.cmd == "inspect":
        backend = Win32DesktopBackend()
        windows = backend.windows()
        payload = [
            {
                "handle": w.handle,
                "title": w.title,
                "class_name": w.class_name,
                "rect": w.rect,
                "controls": [c.__dict__ for c in w.controls],
            }
            for w in windows
        ]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for w in windows:
                print(f"{w.handle}: {w.title} [{w.class_name}] {w.rect}")
                for c in w.controls[:20]:
                    if c.text:
                        print(f"  - {c.text!r} [{c.class_name}] {c.rect}")
        return 0

    if args.cmd == "run":
        runner = TestRunner(Win32DesktopBackend(), args.evidence_dir)
        report = runner.run_artifact(args.artifact)
        report_path = args.report or f"runs/{report.report_id}.json"
        report.write(report_path)
        print(f"{report.status.upper()} report: {Path(report_path).resolve()}")
        for step in report.step_results:
            print(f"{step.step_id}: {step.status} - {step.original_expected}")
        return 0 if report.status == "pass" else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
