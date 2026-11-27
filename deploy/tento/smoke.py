#!/usr/bin/env python3
"""Check the installed Tentō wheel in a bounded child; no model traffic by default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def query(connection, statement):
    result = connection.execute(statement)
    try:
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        return {"columns": result.get_column_names(), "rows": rows}
    finally:
        result.close()


def check(live=False):
    # The application is installed into the target virtualenv along with its
    # semantic extra. No source-path injection or upstream-package fallback.
    from graphmine_agent.errors import AnalyticsError
    from graphmine_agent.semantic_engine import engine_lock, load_engine, require_live_controls

    report = {"status": "failed", "mock": {"status": "not_run"}, "live": {"status": "not_requested"}}
    try:
        engine = load_engine()
        report["engine"] = engine.manifest
        lock = engine_lock()
        db = engine.module.Database(buffer_pool_size=128 * 1024 * 1024, max_num_threads=2, backend="pybind")
        try:
            connection = engine.module.Connection(db, num_threads=2)
            try:
                for setting in ("llm_base_url='http://127.0.0.1:1/v1'", "llm_threads=1",
                                "semantic_selectivity_samples=0", "semantic_path_decomposition=false",
                                "semantic_join_decomposition=false"):
                    query(connection, "CALL " + setting)
                functions = query(connection, "CALL show_functions() RETURN *")
                name_index = functions["columns"].index("name")
                names = {row[name_index].upper() for row in functions["rows"]}
                missing = set(lock["required_functions"]) - names
                if missing:
                    raise ValueError("The built engine lacks required semantic functions")
                report["functions"] = sorted(set(lock["required_functions"]) & names)
                result = query(connection,
                    "UNWIND ['alpha'] AS text RETURN llm('mock:echo', 'Echo {{text}} {answer STRING}') AS answer")
                if len(result["rows"]) != 1 or json.loads(result["rows"][0][0]) != ["alpha"]:
                    raise ValueError("Unexpected mock result")
                report["mock"] = {"status": "passed", "result": result}
            finally:
                connection.close()
        finally:
            db.close()
        if live:
            report["live"] = {"status": "blocked", "blockers": lock["live_blockers"], "requests_sent": 0}
            require_live_controls()
            # The author revision must define the provider-control API before
            # adding its live call here. Never infer that clearing a flag is enough.
            raise ValueError("The live provider smoke requires an author-supported request contract")
        report["status"] = "passed"
        return report, 0
    except AnalyticsError as error:
        report["status"] = "blocked" if error.code == "semantic_controls_unsupported" else "failed"
        report["error"] = {"code": error.code, "message": str(error)}
        return report, 2 if report["status"] == "blocked" else 1
    except Exception as error:
        report["error"] = {"code": "semantic_smoke_failed", "type": type(error).__name__}
        return report, 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Also check the live gate; currently blocked, exit 2, no HTTP call")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.child:
        report, code = check(args.live)
        print(json.dumps(report))
        return code
    env = os.environ.copy()
    for name in ("OPENROUTER_API_KEY", "LLM_API_KEY", "GRAPHMINE_LLM_API_KEY", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    command = [sys.executable, str(Path(__file__).resolve()), "--child"]
    if args.live:
        command.append("--live")
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=args.timeout)
        report = json.loads(result.stdout)
        code = result.returncode
    except subprocess.TimeoutExpired:
        report, code = {"status": "failed", "error": {"code": "semantic_smoke_timeout"}}, 1
    except (ValueError, OSError):
        # Native-loader stderr can contain paths or environment details.
        report, code = {"status": "failed", "error": {"code": "semantic_smoke_process_failed"}}, 1
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
