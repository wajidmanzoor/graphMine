"""Repeatable local CPU gate. Does not start the deployed services or GPU jobs."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from graphmine_agent.cli import SCHEMAS
from graphmine_agent.history import HistoryStore
from graphmine_agent.models import utc_now

ROOT = Path(__file__).resolve().parents[2]


def sources():
    paths = set()
    for folder in ("graphmine_agent", "tests", "browser_tests", "scripts", "schemas"):
        paths.update(
            path
            for path in (ROOT / "agent" / folder).rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".js", ".css", ".html", ".json"}
            and "__pycache__" not in path.parts
            and "vendor" not in path.parts
        )
    paths.update(
        (ROOT / "agent" / name) for name in ("pyproject.toml", "constraints-cpu.txt")
    )
    paths.update((ROOT / "deploy").glob("*.sh"))
    paths.update((ROOT / "agent/graphmine_agent/static/vendor").glob("vega*"))
    paths.update(
        path for path in (ROOT / "agent/visualization").glob("*") if path.is_file()
    )
    return {
        str(path.relative_to(ROOT)): HistoryStore.digest(path) for path in sorted(paths)
    }


def run(output: Path, *, browser: bool):
    # Reserve first, so a typo cannot overwrite previous evidence after running.
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        handle.write('{"status":"in_progress"}\n')
    report = {
        "version": "graphmine-cpu-verification-v1",
        "started_at": utc_now().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sources": sources(),
        "checks": [],
        "browser_requested": browser,
        "passed": False,
        "native_execution": "not_run",
        "model_inference": "not_run",
    }
    packages = [
        line.split("==")[0]
        for line in (ROOT / "agent/constraints-cpu.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    report["installed_dependencies"] = {
        name: importlib.metadata.version(name) for name in packages
    }
    environment = dict(os.environ)
    for name in ("GRAPHMINE_REPAIRED_TEST_BINARY", "GRAPHMINE_EXPANSION_TEST_BINARY"):
        environment.pop(name, None)
    # Prevent inherited pytest options from enabling extra plugins/test paths.
    environment.pop("PYTEST_ADDOPTS", None)

    def command(label, arguments, junit=None):
        print(f"Checking {label}...", flush=True)
        started = time.monotonic()
        completed = subprocess.run(
            arguments,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        row = {
            "name": label,
            "command": arguments,
            "exit_code": completed.returncode,
            "seconds": time.monotonic() - started,
            "output_tail": (completed.stdout + completed.stderr)[-16000:],
        }
        if junit and junit.is_file():
            suites = ET.parse(junit).getroot().iter("testsuite")
            totals = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
            for suite in suites:
                for name in totals:
                    totals[name] += int(suite.attrib.get(name, 0))
            row["tests"] = totals
            # A requested browser gate cannot pass by skipping every scenario.
            if label == "browser" and (not totals["tests"] or totals["skipped"]):
                row["exit_code"] = 1
        report["checks"].append(row)
        print(row["output_tail"], flush=True)

    try:
        mismatches = [
            name
            for name, model in SCHEMAS.items()
            if json.loads((ROOT / "agent/schemas" / f"{name}.schema.json").read_text())
            != model.model_json_schema()
        ]
        report["checks"].append(
            {
                "name": "public_schemas",
                "count": len(SCHEMAS),
                "mismatches": mismatches,
                "exit_code": int(bool(mismatches)),
            }
        )
        command(
            "lint",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "agent/graphmine_agent",
                "agent/tests",
                "agent/scripts",
            ],
        )
        command(
            "frontend_syntax",
            ["node", "--check", "agent/graphmine_agent/static/app.js"],
        )
        for script in sorted((ROOT / "deploy").glob("*.sh")):
            command(f"shell_syntax:{script.name}", ["bash", "-n", str(script)])
        command("whitespace", ["git", "diff", "--check"])
        with tempfile.TemporaryDirectory(prefix="graphmine-verify-") as temporary:
            junit = Path(temporary) / "cpu.xml"
            command(
                "cpu",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "agent/tests",
                    "-q",
                    f"--junitxml={junit}",
                ],
                junit,
            )
            if browser:
                junit = Path(temporary) / "browser.xml"
                command(
                    "browser",
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "agent/browser_tests",
                        "-q",
                        f"--junitxml={junit}",
                    ],
                    junit,
                )
        report["checks"].append(
            {
                "name": "sources_unchanged_during_checks",
                "exit_code": int(sources() != report["sources"]),
            }
        )
        report["passed"] = all(row["exit_code"] == 0 for row in report["checks"])
    finally:
        report["finished_at"] = utc_now().isoformat()
        HistoryStore.write(output, report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new report path")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="also require Firefox/geckodriver acceptance tests",
    )
    args = parser.parse_args()
    raise SystemExit(run(args.output, browser=args.browser))
