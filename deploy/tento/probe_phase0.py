#!/usr/bin/env python3
"""Probe the unmodified Tentō engine; only mock models and loopback HTTP are used.

Build the supplied engine first, then run with --source /path/to/francis.
Each case runs in its own process. Findings describe observed behavior, including
unsupported requirements; a successful probe does not mean the integration passes.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


CASES = ("functions", "values", "providers", "limits", "cache", "explain", "interrupt", "license")
MEMORY_BYTES = 128 * 1024 * 1024
TEST_KEY = "phase0-local-fixture-not-a-real-key"
OTHER_TEST_KEY = "phase0-local-precedence-fixture"


def json_default(value):
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return {"python_type": type(value).__name__, "iso": value.isoformat()}
    if isinstance(value, bytes):
        return {"python_type": "bytes", "hex": value.hex()}
    return {"python_type": type(value).__name__, "repr": repr(value)}


def type_tree(value):
    if isinstance(value, dict):
        return {"type": "dict", "fields": {str(k): type_tree(v) for k, v in value.items()}}
    if isinstance(value, (list, tuple)):
        return {"type": type(value).__name__, "items": [type_tree(v) for v in value]}
    return type(value).__name__


def engine(source):
    build = source / "ladybug/tools/python_api/build"
    if not list((build / "ladybug").glob("_lbug*.so")):
        raise RuntimeError(f"Build Tentō's pybind module first: {build}")
    sys.path.insert(0, str(build))
    os.environ["LBUG_PYTHON_BACKEND"] = "pybind"
    import ladybug
    from ladybug._backend import get_pybind_module

    native = Path(get_pybind_module().__file__).resolve()
    if not native.is_relative_to(build.resolve()):
        raise RuntimeError("The imported native module is outside the requested Tentō build")
    return ladybug


def execute(conn, statement, parameters=None):
    result = conn.execute(statement, parameters or {})
    if isinstance(result, list):
        raise AssertionError("Probes execute one statement at a time")
    try:
        columns = result.get_column_names()
        data_types = result.get_column_data_types()
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        return {"columns": columns, "data_types": data_types, "rows": rows}
    finally:
        result.close()


def attempt(conn, statement):
    try:
        return {"ok": True, "result": execute(conn, statement)}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


def usage(conn):
    result = execute(conn, "CALL llm_usage() RETURN *")
    return dict(zip(result["columns"], result["rows"][0]))


@contextlib.contextmanager
def database(source, *, path=None):
    ladybug = engine(source)
    options = {"buffer_pool_size": MEMORY_BYTES, "max_num_threads": 2, "backend": "pybind"}
    db = ladybug.Database(**options) if path is None else ladybug.Database(str(path), **options)
    try:
        yield db
    finally:
        db.close()


@contextlib.contextmanager
def connection(db, *, endpoint=None, planning=False):
    import ladybug

    conn = ladybug.Connection(db, num_threads=2)
    try:
        # Never let a probe accidentally use the engine's public provider default.
        execute(conn, f"CALL llm_base_url='{endpoint or 'http://127.0.0.1:1/v1'}'")
        execute(conn, "CALL llm_threads=1")
        if not planning:
            for setting in ("semantic_selectivity_samples=0", "semantic_path_decomposition=false",
                            "semantic_join_decomposition=false"):
                execute(conn, "CALL " + setting)
        yield conn
    finally:
        conn.close()


def seed_reviews(conn):
    execute(conn, "CREATE NODE TABLE Review(gm_id STRING, text STRING, PRIMARY KEY(gm_id))")
    for identifier, text in (("r:1", "bad acting"), ("r:2", "good acting"), ("r:3", "awful ending")):
        execute(conn, "CREATE (:Review {gm_id: $id, text: $text})", {"id": identifier, "text": text})


def scalar_query(model="mock:echo", prompt="Echo"):
    return f"UNWIND ['alpha'] AS text RETURN llm('{model}', '{prompt} {{{{text}}}} {{answer STRING}}') AS answer"


class Recorder:
    """A synthetic OpenAI-compatible endpoint; authorization values are never recorded."""

    def __init__(self, *, reject_schema=False, transient=False, blocked=False):
        self.reject_schema = reject_schema
        self.transient = transient
        self.blocked = blocked
        self.requests = []
        self.lock = threading.Lock()
        self.started = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.schema = {}
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                auth = self.headers.get("Authorization", "")
                record = {"path": self.path, "body": body,
                          "authorization_present": bool(auth),
                          "uses_primary_fixture_key": auth == "Bearer " + TEST_KEY,
                          "uses_precedence_fixture_key": auth == "Bearer " + OTHER_TEST_KEY}
                with fixture.lock:
                    fixture.requests.append(record)
                    index = len(fixture.requests)
                    fixture.active += 1
                fixture.started.set()
                try:
                    schema = body.get("response_format", {}).get("json_schema", {}).get("schema", {})
                    if schema:
                        fixture.schema = schema
                    if fixture.blocked:
                        fixture.release.wait(15)
                    if fixture.reject_schema and index == 1:
                        self.reply(400, {"error": {"message": "Synthetic schema rejection"}})
                        return
                    if fixture.transient and index == 1:
                        self.reply(503, {"error": {"message": "Synthetic retry"}})
                        return
                    user = body["messages"][-1]["content"]
                    match = re.search(r"Rows:\n(\[.*\])\n\nReply with", user, re.S)
                    rows = json.loads(match.group(1)) if match else [{"id": 0}]
                    fields = fixture.schema.get("properties", {}).get("results", {}).get("items", {}).get("properties", {})
                    answers = []
                    for row in rows:
                        answer = {"id": row.get("id", 0)}
                        for name, spec in fields.items():
                            if name != "id":
                                answer[name] = {"boolean": True, "integer": 1, "number": 1.5}.get(spec.get("type"), "fixture")
                        if len(answer) == 1:
                            answer["answer"] = "fixture"
                        answers.append(answer)
                    self.reply(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps({"results": answers})}}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
                finally:
                    with fixture.lock:
                        fixture.active -= 1

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


def functions(source):
    import_info = {}
    with database(source) as db, connection(db) as conn:
        import ladybug
        from ladybug._backend import get_pybind_module

        native = Path(get_pybind_module().__file__)
        import_info = {"python_package": ladybug.__file__, "native_module": str(native),
                       "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                       "reported_engine_version": ladybug.__version__,
                       "source_project_version": re.search(r"project\(Lbug VERSION ([^ ]+)",
                           (source / "ladybug/CMakeLists.txt").read_text()).group(1),
                       "database_path": db.database_path}
        names = {row[0].upper() for row in execute(conn, "CALL show_functions() RETURN name")["rows"]}
        required = {"LLM", "LLM_SCORE", "LLM_AGG", "LLM_PATH_AGG", "LLM_SG_AGG", "SUBGRAPH"}
        assert required <= names, required - names
        echo = execute(conn, scalar_query())
        assert json.loads(echo["rows"][0][0]) == ["alpha"], echo
        return {**import_info, "required_functions": sorted(required),
                "llm_functions": sorted(n for n in names if "LLM" in n), "mock_echo": echo}


def values(source):
    with database(source) as db, connection(db) as conn:
        seed_reviews(conn)
        execute(conn, "CREATE NODE TABLE Person(gm_id STRING, name STRING, tags STRING[], PRIMARY KEY(gm_id))")
        execute(conn, "CREATE (:Person {gm_id: 'p:1', name: 'Ada', tags: ['reader','critic']})")
        execute(conn, "CREATE REL TABLE REVIEWS(FROM Person TO Review, gm_id STRING, weight DOUBLE)")
        for identifier in ("edge:1", "edge:2"):
            execute(conn, "MATCH (p:Person), (r:Review) WHERE p.gm_id='p:1' AND r.gm_id='r:1' CREATE (p)-[:REVIEWS {gm_id: $id, weight: 2.5}]->(r)", {"id": identifier})
        queries = {
            "node": "MATCH (p:Person) RETURN p",
            "relationship": "MATCH (:Person)-[e:REVIEWS]->(:Review) RETURN e ORDER BY e.gm_id",
            "path": "MATCH p=(a:Person)-[e:REVIEWS*1..1]->(b:Review) RETURN p, e",
            "scalar": "RETURN 7 AS n, 3.5 AS f, true AS b, NULL AS missing, [1,2] AS items, {answer:'yes'} AS object, 9007199254740993 AS large_integer",
            "scalar_node_shaped_map": "RETURN {_ID: {offset: 0, `table`: 1}, _LABEL: 'Person', gm_id: 'p:1'} AS pretend",
            "nested_properties": "MATCH (p:Person) RETURN p.tags, p.gm_id",
        }
        results = {}
        for name, query in queries.items():
            result = execute(conn, query)
            results[name] = {"statement": query, **result, "python_types": type_tree(result["rows"])}
        assert len(results["relationship"]["rows"]) == 2
        results["node_multiple_labels"] = attempt(conn, "MATCH (p:Person:Review) RETURN p")
        results["create_multiple_labels"] = attempt(conn, "CREATE (:Person:Review {gm_id: 'both', name: 'Both'})")
        results["relationship_primary_key"] = attempt(conn, "CREATE REL TABLE Keyed(FROM Person TO Review, gm_id STRING, PRIMARY KEY(gm_id))")
        execute(conn, "CREATE NODE TABLE NumericID(gm_id INT64, PRIMARY KEY(gm_id))")
        execute(conn, "CREATE (:NumericID {gm_id: 1})")
        results["integer_identity"] = execute(conn, "MATCH (n:NumericID) RETURN n")
        with tempfile.TemporaryDirectory(prefix="tento-copy-") as directory:
            csv = Path(directory) / "reviews.csv"
            csv.write_text('gm_id,text\ncopy:1,"bad, but watchable"\ncopy:2,"good film"\n')
            execute(conn, "CREATE NODE TABLE Copied(gm_id STRING, text STRING, PRIMARY KEY(gm_id))")
            execute(conn, f"COPY Copied FROM '{csv}' (HEADER=true)")
            results["bulk_copy"] = execute(conn, "MATCH (r:Copied) RETURN r ORDER BY r.gm_id")
            assert len(results["bulk_copy"]["rows"]) == 2
        return results


def providers(source):
    with Recorder() as default, Recorder() as override, database(source) as db:
        with connection(db, endpoint=default.endpoint) as conn:
            execute(conn, f"CREATE MACRO qwen() AS {{model: 'phase0/qwen', temperature: 0, base_url: '{override.endpoint}'}}")
            missing_key = attempt(conn, scalar_query("qwen"))
            assert not missing_key["ok"] and not override.requests
            os.environ["LLM_API_KEY"] = TEST_KEY
            result = execute(conn, scalar_query("qwen"))
            assert result["rows"] == [["fixture"]], result
            execute(conn, scalar_query("phase0/default", "Different"))
            os.environ["OPENROUTER_API_KEY"] = OTHER_TEST_KEY
            execute(conn, scalar_query("qwen", "Precedence"))
            rejected = {}
            for alias, field in (("thinking_a", "reasoning_effort: 'none'"),
                                 ("thinking_b", "enable_thinking: false"),
                                 ("thinking_c", "chat_template_kwargs: {enable_thinking: false}")):
                execute(conn, f"CREATE MACRO {alias}() AS {{model: 'phase0/qwen', {field}}}")
                rejected[field] = attempt(conn, scalar_query(alias))
            return {"missing_key": missing_key, "alias_result": result,
                    "default_endpoint_requests": default.requests,
                    "alias_endpoint_requests": override.requests,
                    "thinking_fields": rejected,
                    "request_thinking_fields": {k: override.requests[0]["body"].get(k) for k in
                                                ("reasoning_effort", "chat_template_kwargs", "enable_thinking")}}


def limits(source):
    with database(source) as db, connection(db) as conn:
        execute(conn, "CALL llm_max_calls=1")
        execute(conn, "CALL llm_batch_size=1")
        execute(conn, "CALL llm_persistent_cache=false")
        usage(conn)
        two = execute(conn, "UNWIND ['alpha'] AS t RETURN llm('mock:echo', 'First {{t}} {a STRING}'), llm('mock:echo', 'Second {{t}} {b STRING}')")
        two_usage = usage(conn)
        reset_usage = usage(conn)
        assert reset_usage["calls"] == 0, reset_usage
        over = attempt(conn, "UNWIND ['alpha', 'beta'] AS t RETURN llm('mock:echo', 'Limit {{t}} {a STRING}')")
        over_usage = usage(conn)
        assert two_usage["calls"] == 2, two_usage
        assert not over["ok"] and "llm_max_calls" in over["error"], over
    os.environ["LLM_API_KEY"] = TEST_KEY
    scenarios = {}
    for name, options in (("schema_fallback", {"reject_schema": True}), ("http_retry", {"transient": True})):
        with Recorder(**options) as server, database(source) as db, connection(db, endpoint=server.endpoint) as conn:
            execute(conn, "CALL llm_max_calls=1")
            usage(conn)
            result = execute(conn, scalar_query("phase0/" + name))
            scenarios[name] = {"result": result, "usage": usage(conn), "requests": server.requests}
            assert len(server.requests) == 2, scenarios[name]
    return {"two_expressions_with_limit_one": two, "two_expression_usage": two_usage,
            "immediate_second_usage_read": reset_usage,
            "single_expression_limit_error": over, "limit_error_usage": over_usage, **scenarios}


def cache_once(source):
    with database(source) as db, connection(db) as conn:
        usage(conn)
        execute(conn, scalar_query())
        return {"usage": usage(conn), "answers": execute(conn, "CALL llm_answers() RETURN *")}


def child_command(source, case, *extra):
    return [sys.executable, str(Path(__file__).resolve()), "--source", str(source), "--case", case, *extra]


def run_child(source, case, *extra, timeout=45):
    run = subprocess.run(child_command(source, case, *extra), capture_output=True, text=True, timeout=timeout)
    if run.returncode:
        raise RuntimeError(f"Probe {case} exited {run.returncode}: {run.stderr[-3000:]} {run.stdout[-3000:]}")
    return json.loads(run.stdout)


def cache(source):
    runs = []
    with database(source) as db:
        for _ in range(2):
            with connection(db) as conn:
                usage(conn)
                execute(conn, scalar_query())
                runs.append({"usage": usage(conn), "answers": execute(conn, "CALL llm_answers() RETURN *")})
    assert runs[0]["usage"]["calls"] == 1 and runs[1]["usage"]["stored_hits"] == 1, runs
    fresh = [run_child(source, "cache_once") for _ in range(2)]
    assert all(r["usage"]["stored_hits"] == 0 and r["usage"]["calls"] == 1 for r in fresh), fresh
    disk = []
    with tempfile.TemporaryDirectory(prefix="tento-cache-positive-control-") as directory:
        for _ in range(2):
            with database(source, path=Path(directory) / "fixture.lbdb") as db, connection(db) as conn:
                usage(conn)
                execute(conn, scalar_query())
                disk.append({"usage": usage(conn), "answers": execute(conn, "CALL llm_answers() RETURN *")})
        files = sorted(p.name for p in Path(directory).iterdir())
    assert disk[1]["usage"]["stored_hits"] == 1, disk
    return {"same_in_memory_database_new_connections": runs, "fresh_worker_processes": fresh,
            "temporary_file_database_positive_control": disk, "positive_control_files_removed": files,
            "answer_table_columns": runs[0]["answers"]["columns"]}


def explain(source):
    os.environ["LLM_API_KEY"] = TEST_KEY
    results = {}
    for planning in (True, False):
        with Recorder() as server, database(source) as db, connection(db, endpoint=server.endpoint, planning=planning) as conn:
            seed_reviews(conn)
            usage(conn)
            query = "EXPLAIN MATCH (r:Review) WHERE llm('phase0/explain', 'Is {{r.text}} negative? {yes BOOLEAN}') AND llm('phase0/explain', 'Is {{r.text}} about acting? {yes BOOLEAN}') RETURN r"
            result = execute(conn, query)
            results["default_planning" if planning else "model_planning_disabled"] = {
                "statement": query, "result": result, "usage": usage(conn), "requests": server.requests}
    assert results["default_planning"]["usage"]["calls"] > 0, results
    assert results["model_planning_disabled"]["usage"]["calls"] == 0, results
    with database(source) as db, connection(db) as conn:
        results["profile"] = execute(conn, "PROFILE " + scalar_query())
    return results


def blocked_worker(source, endpoint):
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+/v1", endpoint):
        raise ValueError("The blocked-call probe only accepts its loopback fixture")
    os.environ["LLM_API_KEY"] = TEST_KEY
    with database(source) as db, connection(db, endpoint=endpoint) as conn:
        execute(conn, scalar_query("phase0/blocked"))


def interrupt(source):
    os.environ["LLM_API_KEY"] = TEST_KEY
    results = {}
    for mode in ("interrupt", "query_timeout"):
        with Recorder(blocked=True) as server, database(source) as db, connection(db, endpoint=server.endpoint) as conn:
            usage(conn)
            if mode == "query_timeout":
                conn.set_query_timeout(100)
            outcome = {}

            def query():
                outcome.update(attempt(conn, scalar_query("phase0/blocked")))

            thread = threading.Thread(target=query, daemon=True)
            thread.start()
            assert server.started.wait(10), "No blocked request reached the fixture"
            with connection(db) as observer:
                live_usage = usage(observer)
            started = time.monotonic()
            if mode == "interrupt":
                conn.interrupt()
            thread.join(0.4)
            still_blocked = thread.is_alive()
            server.release.set()
            thread.join(10)
            assert not thread.is_alive(), "Query did not finish after fixture release"
            results[mode] = {"still_running_after_400ms": still_blocked,
                             "seconds_until_return": round(time.monotonic() - started, 3),
                             "live_usage_from_second_connection": live_usage, "outcome": outcome}
    with Recorder(blocked=True) as server:
        process = subprocess.Popen(child_command(source, "blocked_worker", "--endpoint", server.endpoint),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert server.started.wait(10), "Child did not reach the blocked provider"
            started = time.monotonic()
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            results["hard_kill"] = {"exit_code": process.returncode,
                                    "seconds": round(time.monotonic() - started, 3),
                                    "reaped": process.poll() is not None,
                                    "fixture_still_processing": server.active > 0,
                                    "stdout": stdout, "stderr": stderr}
            assert process.returncode < 0
        finally:
            server.release.set()
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    return results


def license_probe(source):
    path = source / "ladybug/LICENSE"
    content = path.read_bytes()
    return {"path": "ladybug/LICENSE", "sha256": hashlib.sha256(content).hexdigest(),
            "text": content.decode(), "python_declares_mit": 'license = { text = "MIT" }' in
            (source / "ladybug/tools/python_api/pyproject.toml").read_text()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--case", choices=(*CASES, "cache_once", "blocked_worker"))
    parser.add_argument("--endpoint")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.source = args.source.resolve()
    # Discard inherited real credentials before loading any engine code.
    for name in ("OPENROUTER_API_KEY", "LLM_API_KEY"):
        os.environ.pop(name, None)
    dispatch = {"functions": functions, "values": values, "providers": providers,
                "limits": limits, "cache": cache, "cache_once": cache_once,
                "explain": explain, "interrupt": interrupt, "license": license_probe}
    if args.case:
        result = blocked_worker(args.source, args.endpoint) if args.case == "blocked_worker" else dispatch[args.case](args.source)
        print(json.dumps(result, default=json_default))
        return
    commit = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    results = {"source_commit": commit, "python": sys.version,
               "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "captured_at": datetime.datetime.now(datetime.UTC).isoformat(), "cases": {}}
    for case in CASES:
        started = time.monotonic()
        try:
            finding = run_child(args.source, case)
            results["cases"][case] = {"probe_status": "completed", "findings": finding}
            print(f"{case}: completed", file=sys.stderr, flush=True)
        except Exception as exc:
            results["cases"][case] = {"probe_status": "error", "error": str(exc)}
            print(f"{case}: error: {exc}", file=sys.stderr, flush=True)
        results["cases"][case]["duration_seconds"] = round(time.monotonic() - started, 3)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2, default=json_default) + "\n")
    if not args.output:
        print(json.dumps(results, indent=2, default=json_default))
    if any(c["probe_status"] != "completed" for c in results["cases"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
