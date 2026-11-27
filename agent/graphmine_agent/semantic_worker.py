"""Disposable native worker and its cancellable JSON-lines supervisor.

Only plain reads and explicit mock steps are enabled at the pinned revision.
No provider credentials cross this process boundary while live gates are open.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import tempfile
import threading
import time

from .errors import AnalyticsError


MAX_BYTES = 64 * 1024 * 1024
MAX_CALLS = 1000
TIMEOUT_SECONDS = 120


def check_request(body, *, allowed_aliases=None):
    from .semantic_engine import require_live_controls
    from .semantic_validation import validate_semantic

    steps = validate_semantic(body["statement"], aliases=allowed_aliases)
    if body.get("reuse_answers"):
        raise AnalyticsError("Saved-answer reuse awaits Tentō's independent answer store.", "semantic_cache_unsupported", 503)
    if steps:
        if body.get("model") != "mock" or any(step["model_alias"] not in {"mock", "mock:echo"} for step in steps):
            require_live_controls()
            raise AnalyticsError("Live semantic execution awaits the verified query-wide budget and answer-store contracts.", "semantic_live_unsupported", 503)
    return steps


def classify(error, usage):
    if isinstance(error, AnalyticsError):
        return {"code": error.code, "message": str(error), "status": error.status, "details": {"usage": usage}}
    text = str(error)
    if "llm_max_calls" in text:
        code, message = "semantic_call_limit", "The mock step would exceed its per-expression call limit. No result was published."
    elif any(word in text.lower() for word in ("parser exception", "binder exception", "catalog exception")):
        code, message = "semantic_syntax", "The semantic query does not match the loaded schema or supported syntax."
    elif "memory" in text.lower():
        code, message = "resource_limit", "The semantic query exceeded the worker's available memory."
    else:
        code, message = "semantic_worker_failed", "Semantic execution failed. No result was published."
    details = {"usage": usage}
    position = re.search(r"line\s*:?\s*(\d+)\s*,\s*(offset|column)\s*:?\s*(\d+)", text, re.I)
    if position:
        details.update(line=int(position[1]), column=int(position[3]) + (position[2].lower() == "offset"))
    return {"code": code, "message": message, "status": 422 if code in {"semantic_syntax", "semantic_call_limit", "resource_limit"} else 502, "details": details}


def child(request_path):
    from .semantic_collector import SemanticCollector
    from .semantic_engine import load_engine
    from .semantic_loader import execute, load_graph

    output_lock, totals, stop = threading.Lock(), {}, threading.Event()
    current_stage = "validating"
    def emit(kind, **fields):
        nonlocal current_stage
        with output_lock:
            if kind == "progress":
                current_stage = fields.setdefault("stage", current_stage)
            print(json.dumps({"type": kind, **fields}, allow_nan=False), flush=True)
    def progress(stage, completed=None, total=None):
        emit("progress", stage=stage, completed=completed, total=total)
    def read_usage(connection):
        result = connection.execute("CALL llm_usage() RETURN *")
        try:
            values = dict(zip(result.get_column_names(), result.get_next()))
            for name, value in values.items():
                if type(value) in {int, float}:
                    totals[name] = totals.get(name, 0) + value
        finally:
            result.close()
    db = connection = observer = thread = None
    try:
        payload = json.loads(request_path.read_text())
        # Linux source builds are supported. Reap native work on supervisor
        # death as well as explicit cancellation, so admission locks stay honest.
        if sys.platform.startswith("linux") and payload.get("supervisor_pid"):
            import ctypes
            import signal
            if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
                raise RuntimeError("Worker supervision could not be established")
            if os.getppid() != payload["supervisor_pid"]:
                return 1
        body, graph = payload["request"], payload["graph"]
        execution = payload.get("execution") or {}
        steps = check_request(body)  # repeated at the native trust boundary
        progress("validated")
        engine = load_engine()
        db = engine.module.Database(buffer_pool_size=256 * 1024 * 1024, max_num_threads=2, backend="pybind")
        connection = engine.module.Connection(db, num_threads=2)
        settings = {"llm_base_url": "'http://127.0.0.1:1/v1'", "llm_threads": "1", "llm_batch_size": str(execution.get("batch_size", 16)),
                    "llm_max_calls": str(min(MAX_CALLS, max(1, body["call_limit"]))), "llm_timeout_ms": "10000",
                    "llm_persistent_cache": "false", "semantic_selectivity_samples": "0",
                    "semantic_path_decomposition": "false", "semantic_join_decomposition": "false"}
        for name, value in settings.items():
            execute(connection, f"CALL {name}={value}")
        execute(connection, "CREATE MACRO mock() AS {model:'mock:echo', temperature:0}")
        loaded = load_graph(connection, graph, request_path.parent, progress=progress)
        progress("loaded")
        observer = engine.module.Connection(db, num_threads=1)
        read_usage(observer)
        totals.clear()
        def observe():
            while not stop.wait(0.2):
                try:
                    read_usage(observer)
                    emit("progress", usage=dict(totals))
                except Exception:
                    # Final usage is read again after execution; never invent a count.
                    pass
        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        progress("asking_model" if steps else "querying")
        result = connection.execute(body["statement"], body.get("parameters", {}))
        try:
            progress("building_graph")
            collector = SemanticCollector(loaded, projection=body["projection"], directed=body.get("directed"), weight_property=body.get("weight_property"))
            output = collector.read(result)
        finally:
            result.close()
        stop.set(); thread.join(); thread = None
        read_usage(observer)
        output.update(schema=loaded.schema, usage=dict(totals), engine=engine.manifest, steps=steps,
                      effective_settings={**settings, "provider": "mock" if steps else "none", "model": "mock:echo" if steps else None,
                                          "http_requests": 0, "call_limit_scope": "per_expression", "query_wide_call_limit_supported": False,
                                          "answers_retained": 0, "mock": bool(steps), "admin_policy": execution})
        raw = json.dumps(output, ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > MAX_BYTES:
            raise AnalyticsError("Semantic output exceeds the result byte budget.", "resource_limit")
        destination = request_path.parent / "result.json"
        destination.write_bytes(raw)
        emit("result")
        return 0
    except Exception as error:
        stop.set()
        if thread:
            thread.join(); thread = None
        if observer:
            try:
                read_usage(observer)
            except Exception:
                pass
        emit("error", **classify(error, dict(totals)))
        return 1
    finally:
        stop.set()
        for resource in (observer, connection, db):
            if resource is not None:
                resource.close()


def run_worker(graph, body, *, progress=None, timeout=TIMEOUT_SECONDS, command=None, temporary_root=None, execution=None):
    from .database_job_context import checkpoint

    check_request(body)
    raw = json.dumps({"graph": graph, "request": body, "execution": execution or {}, "supervisor_pid": os.getpid()}, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise AnalyticsError("The snapshot exceeds the semantic worker's 64 MiB input budget.", "resource_limit")
    progress = progress or (lambda event: checkpoint(event.get("stage"), event.get("completed"), event.get("total"), usage=event.get("usage")))
    with tempfile.TemporaryDirectory(prefix="graphmine-semantic-", dir=temporary_root) as temporary:
        directory = Path(temporary)
        request = directory / "request.json"
        request.write_bytes(raw); request.chmod(0o600)
        env = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TZ", "LD_LIBRARY_PATH") if name in os.environ}
        env["PYTHONUNBUFFERED"] = "1"
        argv = command or [sys.executable, "-m", "graphmine_agent.semantic_worker"]
        process = subprocess.Popen([*argv, str(request)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                   env=env, bufsize=0)
        os.set_blocking(process.stdout.fileno(), False)
        started, terminal, usage = time.monotonic(), None, {}
        pending = b""
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    checkpoint()
                    if time.monotonic() - started >= timeout:
                        raise AnalyticsError("Semantic execution timed out. No result was published.", "semantic_timeout", 504, details={"usage": usage})
                    events = selector.select(0.1)
                    if not events:
                        if process.poll() is not None:
                            break
                        continue
                    chunk = os.read(process.stdout.fileno(), 64 * 1024)
                    if not chunk:
                        if pending:
                            raise AnalyticsError("The semantic worker returned an incomplete event.", "semantic_worker_failed", 502)
                        break
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        try:
                            event = json.loads(line)
                        except ValueError:
                            raise AnalyticsError("The semantic worker returned an invalid event.", "semantic_worker_failed", 502) from None
                        if not isinstance(event, dict):
                            raise AnalyticsError("The semantic worker returned an invalid event.", "semantic_worker_failed", 502)
                        if event.get("type") == "progress":
                            usage = event.get("usage", usage)
                            progress(event)
                        elif event.get("type") in {"result", "error"}:
                            terminal = event
                        else:
                            raise AnalyticsError("The semantic worker returned an invalid event.", "semantic_worker_failed", 502)
                    if len(pending) > 64 * 1024:
                        raise AnalyticsError("The semantic worker returned an invalid event.", "semantic_worker_failed", 502)
            process.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
            checkpoint()
            if terminal and terminal["type"] == "error":
                raise AnalyticsError(terminal["message"], terminal["code"], terminal["status"], details=terminal.get("details"))
            result_path = directory / "result.json"
            if process.returncode or terminal is None or not result_path.is_file() or result_path.stat().st_size > MAX_BYTES:
                raise AnalyticsError("The semantic worker stopped without a complete result.", "semantic_worker_failed", 502)
            return json.loads(result_path.read_text())
        except subprocess.TimeoutExpired:
            raise AnalyticsError("Semantic execution timed out.", "semantic_timeout", 504, details={"usage": usage}) from None
        except AnalyticsError as error:
            if error.details is None:
                error.details = {"usage": usage}
            raise
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()


if __name__ == "__main__":
    raise SystemExit(child(Path(sys.argv[1])))
