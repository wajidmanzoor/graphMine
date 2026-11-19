"""Secret-free operational events, distinct from private conversation history."""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from .identity import current_principal

request_id: ContextVar[str | None] = ContextVar("admin_request_id", default=None)
EVENT_TYPES = ("question", "calculation", "sign_in", "error", "admin_change", "support_access")


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
            user_id TEXT, type TEXT NOT NULL CHECK(type IN
              ('question','calculation','sign_in','error','admin_change','support_access')),
            summary TEXT NOT NULL, outcome TEXT NOT NULL, duration_ms REAL,
            details_json TEXT NOT NULL, request_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS admin_events_ts ON events(ts);
        CREATE INDEX IF NOT EXISTS admin_events_user_ts ON events(user_id,ts);
        CREATE INDEX IF NOT EXISTS admin_events_type_ts ON events(type,ts);
    """)


def insert(db, kind, summary, *, user_id=None, outcome="ok", duration_ms=None,
           details=None, correlation=None, ts=None):
    if kind not in EVENT_TYPES:
        raise ValueError("Unknown event type")
    principal = current_principal.get()
    cursor = db.execute(
        "INSERT INTO events(ts,user_id,type,summary,outcome,duration_ms,details_json,request_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (time.time() if ts is None else ts, user_id or (principal.user_id if principal else None),
         kind, summary, outcome, duration_ms, json.dumps(details or {}, separators=(",", ":")),
         correlation or request_id.get() or uuid.uuid4().hex),
    )
    return cursor.lastrowid


def record(database, kind, summary, **kwargs):
    with database._connect() as db:
        return insert(db, kind, summary, **kwargs)


def conversation_event(db, event):
    """Project only operational metadata from private, completed work."""
    data = event.payload
    if data.get("evaluation_id"):
        return
    owner = db.execute("SELECT owner_id FROM sessions WHERE id=?", (event.session_id,)).fetchone()
    user_id = owner[0] if owner else None
    details = {"conversation_id": event.session_id}
    if event.type == "workflow.chat" and data.get("role") == "assistant":
        turn = data.get("turn_id")
        first = db.execute("SELECT created_at FROM conversation_events WHERE session_id=? AND type='workflow.chat' AND json_extract(payload,'$.role')='user' AND json_extract(payload,'$.turn_id')=? ORDER BY sequence LIMIT 1", (event.session_id, turn)).fetchone()
        diagnostics = [json.loads(row[0]) for row in db.execute("SELECT payload FROM conversation_events WHERE session_id=? AND type='workflow.diagnostics' AND json_extract(payload,'$.turn_id')=?", (event.session_id, turn))]
        elapsed = (event.created_at - datetime.fromisoformat(first[0])).total_seconds() * 1000 if first else None
        stages = {}
        tokens, reasoning, usage_count = 0, 0, 0
        reasoning_count = 0
        for call in diagnostics:
            if isinstance(call.get("seconds"), (int, float)):
                stages[call.get("stage", "unknown")] = stages.get(call.get("stage", "unknown"), 0) + call["seconds"] * 1000
            usage = call.get("usage") or {}
            if isinstance(usage.get("total_tokens"), int):
                tokens += usage["total_tokens"]
                usage_count += 1
            value = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            if isinstance(value, int):
                reasoning += value
                reasoning_count += 1
        outcome = data.get("status", "ok")
        details.update(turn_id=turn, stage_ms=stages, tokens=tokens if usage_count and usage_count == len(diagnostics) else None,
                       tokens_recorded=tokens, token_calls_recorded=usage_count, model_calls=len(diagnostics),
                       reasoning_tokens=reasoning if reasoning_count and reasoning_count == len(diagnostics) else None, model_queue_ms=None,
                       timing_reason="Model queue time was not separately recorded", workflow_id=data.get("workflow_id"))
        insert(db, "question", "Question completed" if outcome not in {"failed", "cancelled"} else "Question " + outcome,
               user_id=user_id, outcome=outcome, duration_ms=elapsed, details=details,
               ts=event.created_at.timestamp(), correlation=turn)
    elif event.type == "workflow.finished":
        details.update({key: data.get(key) for key in ("workflow_id", "revision", "operation", "dataset", "operations", "datasets", "error_code")})
        insert(db, "calculation", "Calculation " + data.get("status", "finished"), user_id=user_id,
               outcome=data.get("status", "finished"), duration_ms=data.get("duration_ms"), details=details,
               ts=event.created_at.timestamp())
        if data.get("status") == "failed":
            code = data.get("error_code") or "workflow_failure"
            insert(db, "error", code.replace("_", " "), user_id=user_id, outcome=code,
                   details={**details, "code": code}, ts=event.created_at.timestamp())
    elif event.type in {"job.completed", "job.failed", "job.cancelled"}:
        saved = db.execute("SELECT payload FROM jobs WHERE id=?", (event.job_id or data.get("job_id"),)).fetchone()
        if not saved:
            return
        job = json.loads(saved[0])
        plan = job["plan"]
        error = job.get("error") or {}
        details.update(job_id=job["id"], operation=plan["operation_id"], dataset=plan["graph_id"], error_code=error.get("code"))
        elapsed = ((datetime.fromisoformat(job["finished_at"]) - datetime.fromisoformat(job["started_at"])).total_seconds() * 1000
                   if job.get("finished_at") and job.get("started_at") else None)
        insert(db, "calculation", "Calculation " + job["status"], user_id=user_id, outcome=job["status"], duration_ms=elapsed,
               details=details, ts=event.created_at.timestamp())
        if job["status"] == "failed":
            code = error.get("code", "execution_error")
            insert(db, "error", code.replace("_", " "), user_id=user_id, outcome=code,
                   details={**details, "code": code}, ts=event.created_at.timestamp())


def truncate_ip(address):
    if ":" in address:
        return ":".join(address.split(":")[:2]) + ":x:x"
    parts = address.split(".")
    return ".".join(parts[:2]) + ".x.x" if len(parts) == 4 else "unavailable"


def query(database, *, before=None, limit=50, user_id=None, kind=None, start=None,
          end=None, search=""):
    clauses, values = ["1=1"], []
    for clause, value in (("e.user_id=?", user_id), ("e.ts>=?", start), ("e.ts<?", end)):
        if value is not None:
            clauses.append(clause)
            values.append(value)
    if search:
        clauses.append("(e.summary LIKE ? ESCAPE '\\' OR a.username LIKE ? ESCAPE '\\' OR e.request_id=?)")
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.extend([f"%{escaped}%", f"%{escaped}%", search])
    where = " AND ".join(clauses)
    with database._connect() as db:
        counts = {row[0]: row[1] for row in db.execute(
            f"SELECT e.type,count(*) FROM events e LEFT JOIN accounts a ON a.id=e.user_id WHERE {where} GROUP BY e.type", values)}
        if kind:
            clauses.append("e.type=?")
            values.append(kind)
        if before:
            clauses.append("e.id<?")
            values.append(before)
        rows = db.execute(
            "SELECT e.*,a.username FROM events e LEFT JOIN accounts a ON a.id=e.user_id WHERE "
            + " AND ".join(clauses) + " ORDER BY e.id DESC LIMIT ?", [*values, limit + 1]).fetchall()
    items = [dict(row) for row in rows[:limit]]
    for item in items:
        item["details"] = json.loads(item.pop("details_json"))
    return {"items": items, "counts": {key: counts.get(key, 0) for key in EVENT_TYPES},
            "total": sum(counts.values()), "next_cursor": items[-1]["id"] if len(rows) > limit else None}


def csv_text(rows, columns):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        values = []
        for key in columns:
            value = row.get(key)
            if key == "ts" and value is not None:
                value = datetime.fromtimestamp(value, timezone.utc).isoformat()
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            value = "" if value is None else str(value)
            # Prevent spreadsheet formulas in exported user-controlled names.
            values.append("'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value)
        writer.writerow(values)
    return output.getvalue()
