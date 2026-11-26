"""Administrator queue metadata and audited cancellation through existing workers."""

import json
from datetime import datetime, timezone

from . import admin_model_calls
from .accounts import MODEL_QUEUE_SECONDS
from .admin_summary import queues
from .identity import AccountError, Principal, identity_scope
from .neo4j_records import visible


def seconds(value):
    return datetime.fromisoformat(value).timestamp() if value else None


def records(runtime):
    with runtime.database._connect() as db:
        owners = {r[0]: {"user_id": r[1], "username": r[2]} for r in db.execute(
            "SELECT s.id,s.owner_id,a.username FROM sessions s LEFT JOIN accounts a ON a.id=s.owner_id")}
        jobs = [json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs")]
    rows = []
    for kind, source in (("workflow", runtime.analytics._all()), ("job", jobs)):
        for item in source:
            if not visible(item, runtime.settings):
                continue
            if kind == "workflow":
                plan = item.get("validation", {}).get("plan", {})
                steps = [{k: s[k] for k in ("id", "problem", "device", "backend", "parameters", "budget") if k in s} for s in plan.get("steps", [])]
                inputs = [{"name": p.get("file_snapshot", {}).get("name"), **p.get("file_snapshot", {}).get("graph", {})} for p in item.get("input_provenance", {}).values()]
                device = (item.get("allocation") or {}).get("device") or plan.get("device")
                log = [{"step": k, **{field: v[field] for field in ("status", "seconds", "backend", "complete", "error") if field in v}} for k, v in item.get("steps", {}).items()]
                queued = item.get("approved_at")
                cancellable = item["id"] in runtime.analytics.tasks
            else:
                plan = item["plan"]
                steps = [{"id": str(item.get("step_index", 0)), "problem": plan["problem_id"], "parameters": plan.get("parameters", {}), "backend": plan.get("backend_id")}]
                inputs = [{"name": plan["graph_id"], "vertex_count": None, "edge_count": None}]
                device = plan.get("backend_id")
                log = []
                queued = item.get("created_at")
                cancellable = item["id"] in runtime.jobs._quota_jobs
            if item["status"] in {"draft", "validated"}:
                continue
            now = runtime.accounts.clock()
            start, end, queued_at = seconds(item.get("started_at")), seconds(item.get("finished_at")), seconds(queued)
            rows.append({"id": item["id"], "kind": kind, "status": item["status"], "session_id": item["session_id"],
                         **owners.get(item["session_id"], {"user_id": None, "username": None}), "problems": [s["problem"] for s in steps],
                         "inputs": inputs, "device": device, "queued_at": queued_at, "started_at": start, "finished_at": end,
                         "waited_seconds": max(0, (start or end or now) - queued_at) if queued_at else None,
                         "running_seconds": max(0, (end or now) - start) if start else None,
                         "cancellable": cancellable and item["status"] in {"queued", "running", "interpreting"},
                         "error": item.get("error"), "plan": steps, "log": log})
    return rows


def snapshot(runtime, view="active"):
    all_rows = records(runtime)
    midnight = datetime.fromtimestamp(runtime.accounts.clock(), timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    selected = [r for r in all_rows if (r["status"] in {"queued", "running", "interpreting"} if view == "active" else
                r["status"] == "failed" if view == "failed" else (r["finished_at"] or 0) >= midnight)]
    selected.sort(key=lambda r: r["queued_at"] or 0, reverse=view != "active")
    leases = runtime.analytics.scheduler.snapshot()
    gpu = []
    for lease in leases:
        if lease["device"] == "gpu":
            owner = next((r for r in all_rows if r["kind"] == "workflow" and r["status"] == "running" and r["device"] == "gpu"), None)
            gpu.append({**lease, "username": owner["username"] if owner else None,
                        "problems": owner["problems"] if owner else [], "seconds": owner["running_seconds"] if owner else None})
    queue = queues(runtime)
    pending = [r for r in all_rows if r["status"] == "queued"]
    queue["job"].update(running=sum(r["status"] in {"running", "interpreting"} for r in all_rows), waiting=len(pending),
                        oldest_wait_seconds=max((r["waited_seconds"] or 0 for r in pending), default=0))
    return {"now": runtime.accounts.clock(), "queues": queue, "model_calls": admin_model_calls.snapshot(runtime.accounts),
            "model_wait_seconds": getattr(runtime.settings, "model_queue_seconds", MODEL_QUEUE_SECONDS),
            "per_user": getattr(runtime.settings, "account_user_running_jobs", 1),
            "cpu": {"busy": sum(l["device"] == "cpu" for l in leases), "total": runtime.settings.analytics_cpu_workers,
                    "pending_limit": runtime.settings.max_pending_jobs}, "gpu_leases": gpu,
            "calculations": [{k: v for k, v in r.items() if k not in {"plan", "log"}} for r in selected[:500]],
            "total": len(selected), "limit": 500}


def detail(runtime, kind, identifier):
    row = next((r for r in records(runtime) if r["kind"] == kind and r["id"] == identifier), None)
    if not row:
        raise AccountError("Calculation not found", "not_found", 404)
    return row


async def cancel(runtime, kind, identifier):
    # Serialize against a workflow being re-approved while cancellation awaits its worker.
    async with runtime.analytics.edit_lock:
        row = detail(runtime, kind, identifier)
        if not row["cancellable"]:
            raise AccountError("This calculation has already finished or is no longer owned by this agent.", "work_finished", 409)
        accounts = runtime.accounts
        lease = runtime.analytics.admissions.get(identifier) if kind == "workflow" else runtime.jobs._quota_jobs.get(identifier)
        before = {k: row[k] for k in ("id", "kind", "status", "user_id")}
        with runtime.database._connect() as db:
            accounts._audit(db, "calculation.cancelled", identifier, before=before,
                            after={**before, "status": "cancel_requested", "daily_job_refunded": bool(lease), "message": "Cancelled by an administrator"})
        if lease:
            if kind == "job":
                runtime.jobs.admin_refunded.add(identifier)
            accounts._refund_jobs(lease, 1)
        # The administrator is already authorized. Owner identity is needed only
        # for the existing private-record checks, including for disabled owners.
        with identity_scope(Principal(row["user_id"], row["username"] or "Deleted account", accounts)):
            if kind == "workflow":
                await runtime.analytics.cancel(identifier, admin=True)
            else:
                await runtime.jobs.cancel(identifier, admin=True)
        return {"status": "cancelled", "daily_job_refunded": bool(lease), "message": "Cancelled by an administrator"}
