#!/usr/bin/env python3
"""Local release gate: tests, browser workflows, wheels and a fresh-install smoke.

Run with the development Python environment. Requires uv, Firefox/geckodriver,
Node for syntax checks, and the repository's already verified native artifacts.
Package dependencies are resolved into a separate environment; no service is
restarted and production storage is never opened.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
BACKEND = [
    "test_api_contracts",
    "test_studio_exchange",
    "test_projects",
    "test_connectors",
    "test_managed_connectors",
    "test_datasets",
    "test_dataset_paging",
    "test_csv_import",
    "test_workflow_templates",
    "test_exports_and_activity",
    "test_domain_ingestion_reports",
    "test_history_and_terminal",
    "test_storage_recovery",
    "test_export_streams",
    "test_result_cache",
    "test_pilot_feedback",
    "test_workspace_commands",
    "test_conversation_timeline",
    "test_analytics_workflows",
    "test_analytics_planning",
    "test_analytics_taxonomy",
    "test_catalog_and_planning",
    "test_analytics_group_views",
    "test_analytics_projection",
    "test_accounts",
    "test_graph_store_and_database",
    "test_session_search",
    "test_exploration",
    "test_workspace_recent",
    "test_query_previews",
    "test_backup_recovery",
    "test_upload_resources",
    "test_queue_capacity",
    "test_evidence_cache",
    "test_deploy_launchers",
    "test_release_gate",
    "test_review_regressions",
    "test_analytics_answers",
]
BROWSER = [
    "test_result_exploration",
    "test_projects_and_connectors",
    "test_connection_setup",
    "test_workspace_loading",
    "test_workspace_navigation",
    "test_workspace_polling",
    "test_workspace_history",
    "test_query_previews",
    "test_workspace_conversation_graph",
    "test_query_drafts",
    "test_workspace_recovery_views",
    "test_workspace_library",
    "test_workspace_templates",
    "test_workspace_expert",
    "test_workspace_device_quality",
    "test_workspace_shell",
    "test_workspace_commands",
    "test_accounts_browser",
    "test_analytics_workspace",
]

DATABASE_BACKEND = ["test_database_integration", "test_database_pool_integration", "test_database_sync_integration"]
DATABASE_BROWSER = ["test_database_roundtrip", "test_data_source_workspace"]


def discover(directory, patterns):
    return {path.stem for pattern in patterns for path in directory.glob(pattern)}


# New database/query/workspace regressions join the gate automatically. Live
# suites stay explicit because they synchronize the disposable database demo.
BACKEND = sorted(set(BACKEND) | (discover(ROOT / "agent/tests", (
    "test_database*.py", "test_benchmark*.py", "test_query*.py", "test_*mapping*.py",
    "test_result_views.py", "test_result_resources.py", "test_result_context.py", "test_result_index.py",
)) - set(DATABASE_BACKEND)))
BROWSER = sorted(set(BROWSER) | (discover(ROOT / "agent/browser_tests", (
    "test_database*.py", "test_data_source*.py", "test_query*.py", "test_workspace*.py",
)) - set(DATABASE_BROWSER)))


def suite_plan(*, databases=False, benchmarks=False, gpus=False):
    return {
        "backend": [f"agent/tests/{name}.py" for name in BACKEND],
        "browser": [f"agent/browser_tests/{name}.py" for name in BROWSER],
        "database_backend": [f"agent/tests/{name}.py" for name in DATABASE_BACKEND] if databases else [],
        "database_browser": [f"agent/browser_tests/{name}.py" for name in DATABASE_BROWSER] if databases else [],
        "benchmark_checks": benchmarks,
        "gpu": ["agent/tests/test_analytics_workflows.py::test_live_configured_gpu_workflow"] if gpus else [],
    }


def local_environment(output, environ=None):
    env = {
        **(os.environ if environ is None else environ),
        "PYTHONPATH": os.pathsep.join((str(ROOT / "agent"), str(ROOT / "python/graphmine"))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_CACHE_DIR": str(output / "cache"),
    }
    # Running a CPU gate never opts into destructive demo synchronization or GPU
    # work just because a developer's shell has integration variables set.
    for name in ("GRAPHMINE_ANALYTICS_TEST_GPUS", "GRAPHMINE_TEST_GRAPH_GPU_UUID", "GRAPHMINE_TEST_DATABASE_INTEGRATION", "GRAPHMINE_TEST_BENCHMARK_INTEGRATION", "GRAPHMINE_TEST_SYNC_NEO4J", "GRAPHMINE_TEST_SYNC_NEO4J_URI", "GRAPHMINE_TEST_SYNC_NEO4J_PASSWORD"):
        env.pop(name, None)
    return env


def prerequisites(*, databases=False, benchmarks=False, gpus=False):
    problems = []
    native_root = Path(os.getenv("GRAPHMINE_RUNTIME_REPOSITORY", str(ROOT))).expanduser()
    for module in ("pytest", "selenium", "neo4j", "psycopg", "psycopg_pool"):
        if importlib.util.find_spec(module) is None:
            problems.append(f"Install agent[test,databases]: missing {module}")
    for command in ("uv", "node"):
        if not shutil.which(command):
            problems.append(f"Missing executable: {command}")
    for package in ("typescript", "openapi-typescript"):
        if not (ROOT / "agent/frontend/node_modules" / package / "package.json").is_file():
            problems.append(f"Install frontend development tools with npm ci in agent/frontend: missing {package}")
    for path in (Path("/snap/firefox/current/usr/lib/firefox/firefox"), Path("/snap/firefox/current/usr/lib/firefox/geckodriver"),
                 Path(os.getenv("GRAPHMINE_ANALYTICS_PYTHON", str(native_root / ".venv-analytics/bin/python"))),
                 Path(os.getenv("GRAPHMINE_NATIVE_BINARY", str(native_root / "library/build/runtime/graphmine-native"))),
                 Path(os.getenv("GRAPHMINE_NATIVE_LIBRARY", str(native_root / "library/build/runtime/libgraphmine_runtime.so")))):
        path = path.expanduser()
        if not path.is_file():
            problems.append(f"Required browser/native artifact is missing: {path}")
    if databases and not os.getenv("GRAPHMINE_DATABASE_SOURCES_FILE"):
        problems.append("Live database checks require GRAPHMINE_DATABASE_SOURCES_FILE for the disposable demo")
    if databases and not shutil.which("postgres") and not list(Path("/usr/lib/postgresql").glob("*/bin/postgres")):
        problems.append("Temporary PostgreSQL pool checks require PostgreSQL server binaries")
    if benchmarks and not databases:
        problems.append("Benchmark checks require --with-databases")
    devices = os.getenv("GRAPHMINE_ANALYTICS_TEST_GPUS", "").split(",")
    if gpus and (len(devices) != 2 or not all(device.strip() for device in devices)):
        problems.append("GPU checks require two UUIDs in GRAPHMINE_ANALYTICS_TEST_GPUS")
    return problems


def junit_summary(path):
    cases = list(ElementTree.parse(path).iter("testcase"))
    return {
        "collected": len(cases),
        "passed": sum(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases),
        "skipped": [f"{case.get('classname')}.{case.get('name')}" for case in cases if case.find("skipped") is not None],
    }


def inventory():
    paths = list((ROOT / "agent/graphmine_agent").rglob("*.py"))
    paths += [path for path in (ROOT / "agent/frontend").rglob("*") if path.is_file() and "node_modules" not in path.parts and path.suffix in {".js", ".mjs", ".cjs", ".ts", ".json"}]
    paths.append(ROOT / "tools/export_api_schema.py")
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
        ROOT / "catalog/family.json",
        ROOT / "catalog/problems.json",
        ROOT / "catalog/algo.json",
    ]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def main(output, *, databases=False, benchmarks=False, gpus=False):
    output.mkdir(parents=True, exist_ok=False)
    uv = shutil.which("uv")
    plan = suite_plan(databases=databases, benchmarks=benchmarks, gpus=gpus)
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "CPU native workflows, database/mapping/query fixtures and account/storage contracts; Firefox workflows; package builds and installed smoke. Live database, benchmark and GPU checks run only when explicitly requested. Native compilation and live-model accuracy are separate gates.",
        "steps": [],
        "sources": inventory(),
        "passed": False,
        "suites": plan,
        "integrations": {"databases": "pending" if databases else "not requested", "benchmarks": "pending" if benchmarks else "not requested", "gpus": "pending" if gpus else "not requested"},
    }
    env = local_environment(output)

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
        report["prerequisite_errors"] = prerequisites(databases=databases, benchmarks=benchmarks, gpus=gpus)
        if report["prerequisite_errors"]:
            raise RuntimeError("Release prerequisites are incomplete:\n" + "\n".join(report["prerequisite_errors"]))
        run(
            "backend",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *plan["backend"],
                "--junitxml",
                str(output / "backend.xml"),
            ],
        )
        report["steps"][-1]["tests"] = junit_summary(output / "backend.xml")
        run(
            "taxonomy",
            [sys.executable, "-m", "pytest", "-q", "library/tests/test_family_taxonomy.py",
             "--junitxml", str(output / "taxonomy.xml")],
        )
        report["steps"][-1]["tests"] = junit_summary(output / "taxonomy.xml")
        run(
            "browser",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *plan["browser"],
                "--junitxml",
                str(output / "browser.xml"),
            ],
        )
        report["steps"][-1]["tests"] = junit_summary(output / "browser.xml")
        if databases:
            report["integrations"]["databases"] = "running"
            if benchmarks:
                report["integrations"]["benchmarks"] = "running"
            integration_env = {**env, "GRAPHMINE_TEST_DATABASE_INTEGRATION": "1"}
            if benchmarks:
                integration_env["GRAPHMINE_TEST_BENCHMARK_INTEGRATION"] = "1"
            for phase in ("database_backend", "database_browser"):
                report_path = output / f"{phase}.xml"
                run(phase, [sys.executable, "-m", "pytest", "-q", *plan[phase], "--junitxml", str(report_path)], environment=integration_env)
                report["steps"][-1]["tests"] = junit_summary(report_path)
                if not report["steps"][-1]["tests"]["passed"]:
                    raise RuntimeError(f"{phase} did not execute any passing checks")
            report["integrations"]["databases"] = "passed"
            if benchmarks:
                report["integrations"]["benchmarks"] = "passed"
        if gpus:
            report["integrations"]["gpus"] = "running"
            gpu_env = {**env, "GRAPHMINE_ANALYTICS_TEST_GPUS": os.environ["GRAPHMINE_ANALYTICS_TEST_GPUS"]}
            run("gpu", [sys.executable, "-m", "pytest", "-q", *plan["gpu"], "--junitxml", str(output / "gpu.xml")], environment=gpu_env)
            report["steps"][-1]["tests"] = junit_summary(output / "gpu.xml")
            if report["steps"][-1]["tests"]["passed"] != 2:
                raise RuntimeError("Both configured GPU checks must execute and pass")
            report["integrations"]["gpus"] = "passed"
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
                "--constraint",
                str(ROOT / "agent/requirements.lock"),
                "--python",
                str(python),
                *[
                    f"graphmine-agent[databases] @ {path.as_uri()}"
                    if path.name.startswith("graphmine_agent-") else str(path)
                    for path in wheels.glob("*.whl")
                ],
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
    except BaseException:
        for name, status in report["integrations"].items():
            if status in {"pending", "running"}:
                report["integrations"][name] = "failed" if status == "running" else "not run"
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Release gate passed: {output / 'summary.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="New directory for logs, reports, wheels and the isolated environment",
    )
    parser.add_argument("--list", action="store_true", help="Print the planned suites without running checks")
    parser.add_argument("--with-databases", action="store_true", help="Run against the configured disposable PostgreSQL/Neo4j demo (synchronizes its mapped graph)")
    parser.add_argument("--with-benchmarks", action="store_true", help="Also check the completed benchmark import; requires --with-databases")
    parser.add_argument("--with-gpus", action="store_true", help="Run the two explicitly configured application GPU checks")
    arguments = parser.parse_args()
    options = {"databases": arguments.with_databases, "benchmarks": arguments.with_benchmarks, "gpus": arguments.with_gpus}
    if arguments.with_benchmarks and not arguments.with_databases:
        parser.error("--with-benchmarks requires --with-databases")
    if arguments.list:
        print(json.dumps(suite_plan(**options), indent=2))
    elif arguments.output is None:
        parser.error("--output is required unless --list is used")
    else:
        main(arguments.output.resolve(), **options)
