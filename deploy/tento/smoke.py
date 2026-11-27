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


def live_check(base_url, model):
    from dataclasses import replace
    import tempfile
    from fastapi.testclient import TestClient
    from starlette.concurrency import run_in_threadpool
    from graphmine_agent.api import create_app
    from graphmine_agent.config import Settings
    from graphmine_agent.semantic_admission import admit
    from graphmine_agent.semantic_worker import run_worker

    with tempfile.TemporaryDirectory(prefix="gm-semantic-smoke-") as temporary:
        settings = replace(Settings.from_env(Path(__file__).resolve().parents[2]),
                           data_root=Path(temporary), accounts_enabled=False, api_token="smoke-local",
                           llm_enabled=False, llm_base_url=base_url, llm_model=model,
                           semantic_mode="live", database_sources_file=None)
        app = create_app(settings)
        provider = {"id": "graphmine", "base_url": base_url, "revision": 1}
        body = {"statement": "RETURN llm('qwen','Is two plus two equal to four? {answer BOOLEAN}') AS answer",
                "model": "qwen", "call_limit": 1, "projection": "elements", "reuse_answers": False}
        graph = {"graph": {"id": "smoke", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [], "edges": []}

        @app.post("/api/local-semantic-smoke")
        async def run():
            def work():
                with admit(app.state.runtime, provider, [model], settings.llm_api_key) as (path, gate):
                    try:
                        result = run_worker(graph, body, timeout=30,
                            execution={"provider": provider, "aliases": {"qwen": model}, "batch_size": 1, "timeout_seconds": 30},
                            environment={"GRAPHMINE_TENTO_STRICT": "1", "GRAPHMINE_TENTO_REQUEST_LIMIT": "1",
                                         "GRAPHMINE_TENTO_ADMISSION": path, "LLM_API_KEY": settings.llm_api_key})
                        if gate.error is not None:
                            raise gate.error
                        return result
                    except Exception:
                        if gate.error is not None: raise gate.error from None
                        raise
            return await run_in_threadpool(work)

        # This in-process test route must precede the application's SPA mount.
        app.router.routes.insert(0, app.router.routes.pop())
        with TestClient(app) as client:
            response = client.post("/api/local-semantic-smoke", headers={"Authorization": "Bearer smoke-local"})
            if response.status_code != 200:
                from graphmine_agent.errors import AnalyticsError
                error = response.json().get("error", {})
                raise AnalyticsError(error.get("message", "Live smoke failed"), error.get("code", "semantic_smoke_failed"), response.status_code)
            result = response.json()
        if result["value"]["rows"] != [{"answer": True}]:
            raise ValueError("The live smoke returned an incorrect structured answer")
        return {"status": "passed", "requests_sent": result["usage"]["http_requests"], "usage": result["usage"],
                "model": model, "settings": result["effective_settings"], "answer": True}


def check(live=False, base_url=None, model=None):
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
            if not base_url or not model:
                raise AnalyticsError("Supply --base-url and --model for the live smoke.", "semantic_live_configuration", 503)
            from graphmine_agent.semantic_providers import ProviderInput, AliasInput
            ProviderInput(name="smoke", base_url=base_url)
            AliasInput(alias="qwen", provider_id="graphmine", model_id=model)
            report["live"] = {"status": "running", "requests_sent": None}
            report["live"] = live_check(base_url, model)
        report["status"] = "passed"
        return report, 0
    except AnalyticsError as error:
        if report["live"]["status"] == "running": report["live"]["status"] = "failed"
        report["status"] = "blocked" if error.code in {"semantic_controls_unsupported", "semantic_live_configuration"} else "failed"
        report["error"] = {"code": error.code, "message": str(error)}
        return report, 2 if report["status"] == "blocked" else 1
    except Exception as error:
        if report["live"]["status"] == "running": report["live"]["status"] = "failed"
        report["error"] = {"code": "semantic_smoke_failed", "type": type(error).__name__}
        return report, 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Also run one bounded, supervised live completion")
    parser.add_argument("--base-url", help="Explicit OpenAI-compatible base URL for --live")
    parser.add_argument("--model", help="Explicit model ID for --live")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.child:
        report, code = check(args.live, args.base_url, args.model)
        print(json.dumps(report))
        return code
    env = os.environ.copy()
    for name in ("OPENROUTER_API_KEY", "LLM_API_KEY", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    if not args.live:
        env.pop("GRAPHMINE_LLM_API_KEY", None)
    command = [sys.executable, str(Path(__file__).resolve()), "--child"]
    if args.live:
        command.append("--live")
    if args.base_url: command.extend(["--base-url", args.base_url])
    if args.model: command.extend(["--model", args.model])
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
