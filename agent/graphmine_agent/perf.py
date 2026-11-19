"""Opt-in, correlated performance observations. No prompts, SQL or credentials.

An unavailable measurement is JSON null, never an inferred zero. The recorder
does no I/O when disabled; a failed recording must not fail an application call.
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

FIELDS = {
    "http": "method route status duration_ms response_bytes",
    "turn_start": "mode outcome error_code total_ms",
    "turn_end": "mode outcome error_code total_ms",
    "model_queue": "stage wait_ms outcome",
    "model_call": "stage model duration_ms time_to_first_token_ms prompt_tokens completion_tokens reasoning_tokens retries validation_failed thinking",
    "llm_wake": "duration_ms trigger",
    "llm_sleep": "duration_ms trigger",
    "job_queue": "wait_ms outcome",
    "job_run": "operation device input_vertices input_edges duration_ms outcome peak_gpu_mb",
    "result_view": "profile duration_ms response_bytes vertices edges",
    "exploration_save": "payload_bytes duration_ms outcome",
    "db": "operation duration_ms lock_wait_ms",
    "error": "error_code where message",
}
IDS = ("request_id", "turn_id", "workflow_id", "user_id", "session_id", "run_id")
_context = contextvars.ContextVar("graphmine_perf_context", default=None)
_model = contextvars.ContextVar("graphmine_perf_model", default=None)
_recorders = {}
_lock = threading.Lock()


class Recorder:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else None
        self.warned = False

    def emit(self, event, **values):
        if self.directory is None:
            return
        context = _context.get() or {}
        from .identity import current_principal
        principal = current_principal.get()
        now = datetime.now(timezone.utc)
        row = {"ts": now.isoformat(), "event": event,
               **{key: context.get(key) for key in IDS},
               **{key: None for key in FIELDS[event].split()}, **values}
        if principal is not None and row["user_id"] is None:
            row["user_id"] = principal.user_id
        try:
            data = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()
            with _lock:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(self.directory / f"events-{now:%Y%m%d}.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
        except (OSError, ValueError, TypeError):
            if not self.warned:
                logging.getLogger(__name__).warning("Performance event could not be recorded", exc_info=True)
                self.warned = True


def recorder(settings):
    if not settings.perf_log:
        return _OFF
    path = settings.perf_directory or settings.repository_root / "var/perf"
    key = str(path.resolve())
    with _lock:
        return _recorders.setdefault(key, Recorder(path))


_OFF = Recorder()


def enabled():
    return bool(_context.get() and _context.get()["recorder"].directory)


def emit(event, **values):
    context = _context.get()
    if context:
        context["recorder"].emit(event, **values)


def annotate(**values):
    if _context.get() is not None:
        _context.get().update(values)


def identifiers():
    return {key: (_context.get() or {}).get(key) for key in IDS}


@contextmanager
def scope(settings=None, **values):
    context = dict(_context.get() or {})
    if settings is not None:
        context["recorder"] = recorder(settings)
    context.update(values)
    token = _context.set(context if "recorder" in context else None)
    try:
        yield context
    finally:
        _context.reset(token)


def error(exc, where):
    code = getattr(exc, "code", type(exc).__name__)
    if where == "model_call" and (isinstance(exc, TimeoutError) or type(exc).__name__ in {"ReadTimeout","ConnectTimeout","PoolTimeout"}):
        code = "model_timeout"
    emit("error", error_code=code, where=where,
         message=str(exc)[:1000])


def turn(function):
    """Trace a complete planning turn, retaining the app's existing turn ID."""
    @functools.wraps(function)
    async def wrapped(self, session_id, body=None, *args, **kwargs):
        if body is None and "request" in kwargs:
            body = kwargs.pop("request")
        if not self.settings.perf_log or (_context.get() or {}).get("turn_active"):
            return await function(self, session_id, body, *args, **kwargs)
        turn_id = str(getattr(body, "request_id", None) or uuid4())
        annotate(turn_id=turn_id, session_id=session_id)
        with scope(self.settings, turn_id=turn_id, session_id=session_id, turn_active=True):
            started = time.monotonic()
            mode = getattr(getattr(body, "mode", "normal"), "value", getattr(body, "mode", "normal"))
            outcome, code = "error", None
            emit("turn_start", mode=mode, outcome=None, error_code=None, total_ms=0)
            try:
                result = await function(self, session_id, body, *args, **kwargs)
                status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
                outcome = {"needs_information": "asked_clarification", "options": "choice_offered",
                           "cancelled": "error", "failed": "error", "unsupported": "error"}.get(status, "answered")
                if isinstance(result, dict) and result.get("options"):
                    outcome = "choice_offered"
                code = status if outcome == "error" else None
                return result
            except BaseException as exc:
                code = getattr(exc, "code", type(exc).__name__)
                error(exc, "turn")
                raise
            finally:
                emit("turn_end", mode=mode, outcome=outcome, error_code=code,
                     total_ms=(time.monotonic() - started) * 1000)
    return wrapped


def turn_id():
    return (_context.get() or {}).get("turn_id")


def trigger(default="request"):
    return (_context.get() or {}).get("trigger", default)


@contextmanager
def model_scope(stage):
    if not enabled():
        yield
        return
    observations = {"stage": "analyst" if stage == "answer" else stage, "calls": []}
    token = _model.set(observations)
    try:
        yield
    except BaseException as exc:
        validation_failed(getattr(exc, "code", "") in {"planner_invalid_output", "planner_truncated"}
                          or isinstance(exc, (ValueError, TypeError, KeyError)))
        raise
    finally:
        for attempt, row in enumerate(observations["calls"]):
            emit("model_call", stage=observations["stage"], retries=attempt, **row)
        _model.reset(token)


def validation_failed(failed=True):
    trace = _model.get()
    if trace and trace["calls"]:
        trace["calls"][-1]["validation_failed"] = bool(failed)


def stage_name():
    return (_model.get() or {}).get("stage", "unknown")


@contextmanager
def transport(payload):
    """Transport timing excludes the account queue and tokenizer reservation."""
    if not enabled():
        yield None
        return
    row = {"model": payload.get("model"), "duration_ms": None,
           "time_to_first_token_ms": None, "prompt_tokens": None,
           "completion_tokens": None, "reasoning_tokens": None,
           "validation_failed": False,
           "thinking": "off" if payload.get("chat_template_kwargs", {}).get("enable_thinking") is False
           or payload.get("reasoning_effort") == "none" else "on"}
    started = time.monotonic()
    observation = {"row": row, "started": started}
    try:
        yield observation
    except BaseException as exc:
        error(exc, "model_call")
        raise
    finally:
        row["duration_ms"] = (time.monotonic() - started) * 1000
        trace = _model.get()
        if trace is not None:
            trace["calls"].append(row)
        else:
            emit("model_call", stage="unknown", retries=0, **row)


def first_token(observation):
    if observation and observation["row"]["time_to_first_token_ms"] is None:
        observation["row"]["time_to_first_token_ms"] = (time.monotonic() - observation["started"]) * 1000


def usage(observation, body):
    if not observation or not isinstance(body, dict):
        return
    values = body.get("usage") or {}
    row = observation["row"]
    for key in ("prompt_tokens", "completion_tokens"):
        row[key] = values.get(key)
    row["reasoning_tokens"] = (values.get("completion_tokens_details") or {}).get("reasoning_tokens", values.get("reasoning_tokens"))


def thinking(settings, stage, payload):
    """The unset setting preserves the exact existing provider request."""
    if settings.llm_thinking_stages is not None and stage not in settings.llm_thinking_stages:
        payload["reasoning_effort"] = "none"
        payload["chat_template_kwargs"] = {**payload.get("chat_template_kwargs", {}), "enable_thinking": False}
        payload.pop("thinking_token_budget", None)


class PerfMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, asgi_scope, receive, send):
        runtime = getattr(asgi_scope.get("app"), "state", None)
        runtime = getattr(runtime, "runtime", None)
        if asgi_scope["type"] != "http" or runtime is None or not runtime.settings.perf_log:
            return await self.app(asgi_scope, receive, send)
        headers = dict(asgi_scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", supplied) else str(uuid4())
        run_id = headers.get(b"x-perf-run-id", b"").decode("latin-1")
        run_id = run_id if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", run_id) else None
        started, status, size, captured = time.monotonic(), 500, 0, bytearray()
        with scope(runtime.settings, request_id=request_id, run_id=run_id) as context:
            asgi_scope["perf_context"] = context
            context["request_bytes"] = 0
            async def observed_receive():
                message = await receive()
                if message["type"] == "http.request":
                    context["request_bytes"] += len(message.get("body", b""))
                return message
            async def observed_send(message):
                nonlocal status, size
                if message["type"] == "http.response.start":
                    status = message["status"]
                    message = {**message, "headers": [*(h for h in message.get("headers", []) if h[0].lower() != b"x-request-id"),
                                                       (b"x-request-id", request_id.encode())]}
                elif message["type"] == "http.response.body":
                    body = message.get("body", b"")
                    size += len(body)
                    if status >= 400 and len(captured) < 8192:
                        captured.extend(body[:8192-len(captured)])
                await send(message)
            try:
                await self.app(asgi_scope, observed_receive, observed_send)
            except BaseException as exc:
                error(exc, "http")
                raise
            finally:
                params = asgi_scope.get("path_params", {})
                annotate(**{key: params[key] for key in ("session_id", "workflow_id") if key in params})
                route = getattr(asgi_scope.get("route"), "path", None)
                if route is None:
                    # Authentication can reject before routing. Match templates
                    # without logging private path components or query strings.
                    from starlette.routing import Match
                    route = next((getattr(r, "path", "<unmatched>") for r in asgi_scope["app"].routes
                                  if r.matches(asgi_scope)[0] == Match.FULL), "<unmatched>")
                if status >= 400:
                    try:
                        detail = json.loads(captured).get("error", {})
                        emit("error", error_code=detail.get("code", f"http_{status}"), where=route,
                             message=str(detail.get("message", f"HTTP {status}"))[:1000])
                    except (ValueError, AttributeError):
                        emit("error", error_code=f"http_{status}", where=route, message=f"HTTP {status}")
                emit("http", method=asgi_scope["method"], route=route, status=status,
                     duration_ms=(time.monotonic()-started)*1000, response_bytes=size)


class TimedSQL:
    def _timed(self, method, sql, *args, **kwargs):
        started = time.monotonic()
        try:
            return method(sql, *args, **kwargs)
        finally:
            duration = (time.monotonic()-started)*1000
            if duration > 50:
                operation = (str(sql).lstrip().split(None, 1) or ["unknown"])[0].upper()
                lock = duration if re.match(r"\s*BEGIN\s+(IMMEDIATE|EXCLUSIVE)\b", str(sql), re.I) else None
                emit("db", operation=operation, duration_ms=duration, lock_wait_ms=lock)

    def execute(self, sql, *args, **kwargs):
        return self._timed(super().execute, sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        return self._timed(super().executemany, sql, *args, **kwargs)

    def executescript(self, sql, *args, **kwargs):
        return self._timed(super().executescript, sql, *args, **kwargs)


class TimedCursor(TimedSQL, sqlite3.Cursor):
    pass


class TimedConnection(TimedSQL, sqlite3.Connection):
    def cursor(self, *args, **kwargs):
        kwargs.setdefault("factory", TimedCursor)
        return super().cursor(*args, **kwargs)

    def commit(self):
        started = time.monotonic()
        try:
            return super().commit()
        finally:
            elapsed = (time.monotonic()-started)*1000
            if elapsed > 50:
                emit("db", operation="COMMIT", duration_ms=elapsed, lock_wait_ms=None)


class TimedRLock:
    """Preserve RLock semantics; record known application lock acquisition time."""
    def __init__(self):
        self.lock = threading.RLock()

    def __enter__(self):
        if not enabled():
            return self.lock.__enter__()
        started = time.monotonic()
        result = self.lock.__enter__()
        elapsed = (time.monotonic()-started)*1000
        if elapsed > 50:
            emit("db", operation="APPLICATION_LOCK", duration_ms=elapsed, lock_wait_ms=elapsed)
        return result

    def __exit__(self, *args):
        return self.lock.__exit__(*args)


def connect(*args, **kwargs):
    if enabled():
        kwargs.setdefault("factory", TimedConnection)
    return sqlite3.connect(*args, **kwargs)


def native_run(row):
    """Reuse the native attempt's measured telemetry, including failed attempts."""
    features = row.get("graph_features") or {}
    peak = (row.get("peak_memory") or {}).get("gpu_bytes")
    device = next((c.get("device") for c in row.get("candidates", []) if c["id"] == row.get("chosen_backend")), None)
    seconds = row.get("runtime_seconds")
    emit("job_run", workflow_id=row.get("workflow_id"), step=row.get("step_id"),
         native_attempt_id=row.get("run_id"), operation=row.get("operation"), device=device,
         input_vertices=features.get("n"), input_edges=features.get("m"),
         duration_ms=seconds*1000 if seconds is not None else None, outcome=row.get("outcome"),
         peak_gpu_mb=peak/1024**2 if peak is not None else None)
    if row.get("error_code"):
        emit("error", error_code=row["error_code"], where="job_run", message=row["error_code"])


def snapshot(runtime):
    now = time.time()
    with runtime.database._connect() as db:
        leases = dict(db.execute("SELECT kind,count(*) FROM account_leases WHERE expires_at>? GROUP BY kind", (now,)))
        sessions = db.execute("SELECT count(*) FROM account_sessions WHERE expires_at>?", (now,)).fetchone()[0]
        jobs = dict(db.execute("SELECT status,count(*) FROM jobs GROUP BY status"))
    workflows = runtime.analytics._all()
    return {"ts": datetime.now(timezone.utc).isoformat(),
            "model": {"waiting": len(runtime.accounts.waiting["model"]), "running": leases.get("model", 0)},
            "jobs": {"waiting": jobs.get("queued", 0)+sum(r["status"] == "queued" for r in workflows),
                     "running": jobs.get("running", 0)+sum(r["status"] == "running" for r in workflows)},
            "active_sessions": sessions,
            "planning_running": leases.get("planning", 0)}
