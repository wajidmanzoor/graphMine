#!/usr/bin/env python3
"""Local release gate: tests, browser workflows, wheels and a fresh-install smoke.

Run with the development Python environment. Requires uv, Firefox/geckodriver,
Node for syntax checks, and the repository's already verified native artifacts.
Package dependencies are resolved into a separate environment; no service is
restarted and production storage is never opened.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = [
    "test_projects",
    "test_connectors",
    "test_managed_connectors",
    "test_datasets",
    "test_csv_import",
    "test_workflow_templates",
    "test_exports_and_activity",
    "test_analytics_workflows",
    "test_analytics_planning",
    "test_analytics_group_views",
    "test_analytics_projection",
    "test_accounts",
    "test_graph_store_and_database",
    "test_backup_recovery",
    "test_upload_resources",
    "test_queue_capacity",
    "test_evidence_cache",
    "test_deploy_launchers",
]
BROWSER = [
    "test_projects_and_connectors",
    "test_connection_setup",
    "test_workspace_loading",
    "test_workspace_conversation_graph",
    "test_workspace_recovery_views",
    "test_workspace_library",
    "test_workspace_templates",
    "test_workspace_expert",
    "test_workspace_device_quality",
    "test_accounts_browser",
    "test_analytics_workspace",
]


def inventory():
    paths = list((ROOT / "agent/graphmine_agent").rglob("*.py"))
    paths += [
        path
        for path in (ROOT / "agent/graphmine_agent/static").rglob("*")
        if path.suffix in {".js", ".html", ".css"}
    ]
    paths += list((ROOT / "agent/tests").glob("*.py")) + list(
        (ROOT / "agent/browser_tests").glob("*.py")
    )
    paths += [
        Path(__file__),
        ROOT / "tools/smoke_installed_workspace.py",
        ROOT / "agent/pyproject.toml",
        ROOT / "catalog/native_execution_evidence.json",
    ]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("Install uv before running the release gate")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "CPU native workflows and account/storage contracts; Firefox workflows; package builds; fresh Python install and bounded HTTP load. Native compilation and live-model accuracy are separate gates.",
        "steps": [],
        "sources": inventory(),
        "passed": False,
    }
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "agent"),
        "UV_CACHE_DIR": str(output / "cache"),
    }
    # GPU-specific checks remain explicitly skipped in this CPU release gate.
    env.pop("GRAPHMINE_ANALYTICS_TEST_GPUS", None)
    env.pop("GRAPHMINE_TEST_GRAPH_GPU_UUID", None)

    def run(name, command, *, environment=env):
        started = time.monotonic()
        print(f"{name}: running", flush=True)
        with (output / f"{name}.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        step = {
            "name": name,
            "command": [str(value) for value in command],
            "exit_code": result.returncode,
            "seconds": round(time.monotonic() - started, 2),
        }
        report["steps"].append(step)
        print(
            f"{name}: {'passed' if result.returncode == 0 else 'FAILED'} ({step['seconds']}s)",
            flush=True,
        )
        if result.returncode:
            raise RuntimeError(f"{name} failed; see {output / (name + '.log')}")

    try:
        run(
            "backend",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *[f"agent/tests/{name}.py" for name in BACKEND],
                "--junitxml",
                str(output / "backend.xml"),
            ],
        )
        run(
            "browser",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *[f"agent/browser_tests/{name}.py" for name in BROWSER],
                "--junitxml",
                str(output / "browser.xml"),
            ],
        )
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node is required for JavaScript syntax checks")
        for path in sorted((ROOT / "agent/graphmine_agent/static").glob("*.js")):
            run(path.stem, [node, "--check", str(path)])
        wheels = output / "wheels"
        run("build-agent", [uv, "build", "agent", "--wheel", "--out-dir", str(wheels)])
        run(
            "build-library",
            [uv, "build", "python/graphmine", "--wheel", "--out-dir", str(wheels)],
        )
        environment = output / "installed"
        run(
            "create-environment",
            [uv, "venv", "--python", sys.executable, str(environment)],
        )
        python = environment / "bin/python"
        run(
            "install-wheels",
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                *map(str, wheels.glob("*.whl")),
            ],
        )
        isolated = {
            k: v for k, v in env.items() if k not in {"PYTHONPATH", "PYTHONHOME"}
        }
        run(
            "installed-smoke",
            [
                str(python),
                str(ROOT / "tools/smoke_installed_workspace.py"),
                "--repository",
                str(ROOT),
                "--output",
                str(output / "installed-smoke.json"),
            ],
            environment=isolated,
        )
        run("installed-packages", [uv, "pip", "freeze", "--python", str(python)])
        report["wheel_hashes"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in wheels.glob("*.whl")
        }
        if inventory() != report["sources"]:
            raise RuntimeError(
                "Source files changed during the gate; run it again on a stable checkout"
            )
        report["passed"] = True
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Release gate passed: {output / 'summary.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory for logs, reports, wheels and the isolated environment",
    )
    arguments = parser.parse_args()
    main(arguments.output.resolve())
