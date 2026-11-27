#!/usr/bin/env python3
"""Run the author's W1–W24 queries on local Qwen with supervised native requests.

Original queries and quality scorers are retained. Every workload gets a record,
including absent data, unavailable quality references, call limits and timeouts.
"""

import argparse
import ast
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "third_party/tento/ladybug/scripts/paper"


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def scorer(data_root):
    path = PAPER / "make_eval_table.py"
    # Only load the original definitions through quality(); no paper-writing
    # code is executed. Replace input locations, not scoring logic or truth.
    tree = ast.parse(path.read_text())
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "E": node.value = ast.Constant(str(data_root / "paper_eval"))
            if name == "FASHION": node.value = ast.Constant(str(data_root / "ecomm_sf500/products.json"))
        body.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "quality": break
    tree.body = body
    namespace = {"__file__": str(path), "__name__": "graphmine_paper_quality"}
    exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), namespace)
    return namespace["quality"]


def child(args):
    from graphmine_agent.semantic_engine import load_engine, require_live_controls
    from graphmine_agent.semantic_worker import classify
    require_live_controls()
    engine = load_engine()  # Pin the imported module before the paper runner alters sys.path.
    sys.path.insert(0, str(PAPER))
    runner = module(PAPER / "run_tento.py", "graphmine_original_paper_runner")
    runner.MODELS["graphmine_local"] = {"model": args.model, "base_url": args.base_url, "threads": 1, "platform": "graphmine_local"}
    runner.ladybug = SimpleNamespace(
        Database=lambda path: engine.module.Database(path, buffer_pool_size=256 * 1024 * 1024, max_num_threads=2, backend="pybind"),
        Connection=engine.module.Connection)
    last = []
    original = runner.execute
    def observed(connection, statement):
        last[:] = [connection]
        return original(connection, statement)
    runner.execute = observed
    spec = runner.QUERIES[args.child]
    options = SimpleNamespace(work=str(args.output / "work"), data=str(args.data_root / "demo"))
    extra = {"posts": runner.posts(options, spec)} if "posts" in spec else {}
    record = runner.run_one(options, args.child, spec, "default", "graphmine_local", 1,
                            engine.manifest["commit"], extra)
    if "error" in record:
        usage = {}
        if last:
            try: usage = runner.usage(last[0])
            except Exception: pass
        record["error"] = classify(RuntimeError(record["error"]), usage)
        record["usage"] = usage
    record["engine"] = engine.manifest
    record["effective_controls"] = {"thinking": "off", "strict_json": True, "temperature": 0,
                                    "max_output_tokens": 4096, "threads": 1, "batch_size": 16,
                                    "total_http_request_limit": args.call_limit, "parent_admission": True}
    args.record.write_text(json.dumps(record, indent=2) + "\n")


def run(args):
    from fastapi.testclient import TestClient
    from starlette.concurrency import run_in_threadpool
    from graphmine_agent.api import create_app
    from graphmine_agent.config import Settings
    from graphmine_agent.semantic_admission import admit
    from graphmine_agent.semantic_engine import require_live_controls
    from graphmine_agent.semantic_providers import ProviderInput
    from acceptance import inventory
    require_live_controls(); ProviderInput(name="local benchmark", base_url=args.base_url)
    args.output.mkdir(parents=True, exist_ok=True)
    report = inventory(ROOT / "third_party/tento", args.data_root, args.model)
    report.update(kind="local_qwen_workload_measurements", status="running", completed_workloads=0, failed_workloads=0,
                  blocked_workloads=0, started_at=datetime.now(timezone.utc).isoformat())
    try:
        quality = scorer(args.data_root)
    except FileNotFoundError as error:
        quality = None
        report["scoring_inputs_missing"] = [str(error.filename)]
    for row in report["workloads"]:
        row["blockers"] = [b for b in row["blockers"] if b not in {
            "live_measurement_required", "local_model_missing_from_paper_runner", "quality_reference_missing"}]
        if row["query"] not in args.queries: row["blockers"].append("not_selected_in_this_run")
    report["model"]["verified_live"] = False
    report["model"]["verification_scope"] = "Successful requests establish the served model ID; weight revision is not exposed by this server."
    report["live_flow"] = {"status": "not_measured_by_workload_runner", "input_version": None, "output_version": None, "blockers": []}
    report["runner"]["adapter"] = str(Path(__file__).resolve())
    report["runner"]["adapter_sha256"] = __import__("hashlib").sha256(Path(__file__).read_bytes()).hexdigest()
    provider = {"id": "graphmine", "base_url": args.base_url, "revision": 1}
    settings = replace(Settings.from_env(ROOT), data_root=args.output / "runtime", accounts_enabled=False,
                       api_token="local-benchmark", llm_enabled=False, llm_base_url=args.base_url,
                       llm_model=args.model, semantic_mode="live", database_sources_file=None)
    app = create_app(settings)
    def measure(row):
        with admit(app.state.runtime, provider, [args.model], settings.llm_api_key) as (socket, gate):
            record_path = args.output / (row["query"] + ".json")
            record_path.unlink(missing_ok=True)
            env = {k: os.environ[k] for k in ("PATH", "LANG", "LD_LIBRARY_PATH") if k in os.environ}
            env.update(GRAPHMINE_TENTO_STRICT="1", GRAPHMINE_TENTO_REQUEST_LIMIT=str(args.call_limit),
                       GRAPHMINE_TENTO_ADMISSION=socket, LLM_API_KEY=settings.llm_api_key, TENTO_MAX_CALLS="1000000000")
            command = [sys.executable, str(Path(__file__).resolve()), "--child", row["query"],
                       "--data-root", str(args.data_root), "--output", str(args.output), "--record", str(record_path),
                       "--base-url", args.base_url, "--model", args.model, "--call-limit", str(args.call_limit)]
            started = time.monotonic()
            process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            timed_out = False
            try:
                try: process.wait(timeout=args.timeout)
                except subprocess.TimeoutExpired: timed_out = True
            finally:
                if process.poll() is None: process.kill()
                process.wait()
            record = json.loads(record_path.read_text()) if record_path.exists() else {}
            row.update(execution_started=True, timeout_seconds=args.timeout, request_limit=args.call_limit, duration_seconds=round(time.monotonic() - started, 3),
                       usage=record.get("usage", gate.usage), effective_settings=record.get("effective_controls"),
                       provider_requests_sent=gate.usage["http_requests"],
                       status="timeout" if timed_out else "failed" if process.returncode or "error" in record or gate.error else "completed")
            if timed_out: row["error"] = {"code": "workload_timeout", "timeout_seconds": args.timeout}
            elif gate.error is not None: row["error"] = {"code": gate.error.code, "message": str(gate.error)}
            elif "error" in record: row["error"] = record["error"]
            elif process.returncode: row["error"] = {"code": "workload_process_failed", "returncode": process.returncode}
            row["record"] = record_path.name if record_path.exists() else None
            if row["status"] == "completed":
                rows = record["results"][-1][-1]["rows"]
                try:
                    score = quality(row["query"], rows) if quality is not None else None
                except (FileNotFoundError, KeyError, ZeroDivisionError, IndexError, ValueError, TypeError) as error:
                    score = None
                    row["quality"]["error_type"] = type(error).__name__
                row["quality"]["score"] = score
                row["quality"]["status"] = "measured" if score is not None else "reference_unavailable" if row["quality"]["metric"] else "not_scored_by_paper_systems_table"
            return row
    @app.post("/api/local-paper-workload")
    async def one(body: dict):
        row = next(row for row in report["workloads"] if row["query"] == body["query"])
        return await run_in_threadpool(measure, row)
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        for row in report["workloads"]:
            if row["blockers"]:
                row["status"] = "blocked"
            else:
                response = client.post("/api/local-paper-workload", json={"query": row["query"]}, headers={"Authorization": "Bearer local-benchmark"})
                if response.status_code != 200: raise RuntimeError("Workload supervisor failed")
                row.update(response.json())
                report["runner"]["invoked"] = True
                if row["status"] == "completed" and row["provider_requests_sent"]:
                    report["model"]["verified_live"] = True
            report["completed_workloads"] = sum(r["status"] == "completed" for r in report["workloads"])
            report["failed_workloads"] = sum(r["status"] in {"failed", "timeout"} for r in report["workloads"])
            report["blocked_workloads"] = sum(r["status"] == "blocked" for r in report["workloads"])
            report["provider_requests_sent"] = sum(r["provider_requests_sent"] for r in report["workloads"])
            (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(row["query"], row["status"], row["provider_requests_sent"], row["quality"]["score"], flush=True)
    report["status"] = "complete" if report["completed_workloads"] == 24 else "partial"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--call-limit", type=int, default=1000)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--queries", nargs="+", default=[f"W{i}" for i in range(1, 25)])
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--record", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.call_limit <= 10000 or not 1 <= args.timeout <= 7200: parser.error("Invalid workload limits")
    args.data_root = args.data_root.resolve(); args.output = args.output.resolve()
    if args.child: child(args)
    else: raise SystemExit(run(args))
