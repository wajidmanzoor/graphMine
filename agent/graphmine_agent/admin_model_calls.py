"""Live metadata for model work, without retaining prompts or generated content."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import uuid4

from .identity import AccountError, current_principal

current_call = ContextVar("admin_model_call", default=None)
STAGES = {"AnalyticsFamily": "family", "AnalyticsProblem": "problem", "AnalyticsRoute": "route",
          "AnalyticsClarify": "clarify", "AnalyticsCandidates": "candidates", "AnalyticsPlan": "plan",
          "AnalyticsAnswer": "explanation", "RouteDecision": "route", "TurnDecision": "clarify",
          "PlanDraft": "plan", "GroundedNarrative": "explanation", "TemplateNarrative": "explanation"}


@asynccontextmanager
async def observe(payload):
    principal = current_principal.get()
    if not principal:
        yield None
        return
    accounts = principal.accounts
    schema = (payload.get("response_format") or {}).get("json_schema") or {}
    row = {"id": uuid4().hex, "user_id": principal.user_id, "username": principal.username,
           "stage": STAGES.get(schema.get("name")), "status": "waiting", "queued_at": accounts.clock(),
           "started_at": None, "tokens": None, "task": asyncio.current_task(), "admin_cancelled": False}
    accounts.model_calls[row["id"]] = row
    token = current_call.set(row)
    try:
        yield row
    except asyncio.CancelledError:
        if row["admin_cancelled"]:
            raise AccountError("Cancelled by an administrator", "admin_cancelled", 409) from None
        raise
    finally:
        current_call.reset(token)
        accounts.model_calls.pop(row["id"], None)


def running(lease, now):
    row = current_call.get()
    if row:
        row.update(status="running", started_at=now, lease=lease)


def usage(value):
    row = current_call.get()
    total = (value or {}).get("total_tokens")
    if row and type(total) is int and total >= 0:
        row["tokens"] = total


def snapshot(accounts):
    now = accounts.clock()
    rows, position = [], 0
    for row in list(accounts.model_calls.values()):
        waiting = row["status"] == "waiting"
        if waiting:
            position += 1
        rows.append({key: value for key, value in row.items() if key not in {"task", "admin_cancelled", "lease"}})
        rows[-1].update(waited_seconds=(row["started_at"] or now) - row["queued_at"],
                        running_seconds=now - row["started_at"] if row["started_at"] else None,
                        position=position if waiting else None, cancellable=not row["admin_cancelled"],
                        tokens_reason="The provider has not reported streaming usage" if row["tokens"] is None else None)
    return rows


async def cancel(accounts, identifier):
    row = accounts.model_calls.get(identifier)
    if not row or row["task"].done():
        raise AccountError("This model call has already finished.", "work_finished", 409)
    before = {key: row[key] for key in ("id", "user_id", "stage", "status")}
    with accounts.database._connect() as db:
        accounts._audit(db, "model_call.cancelled", identifier, before=before,
                        after={**before, "status": "cancel_requested", "message": "Cancelled by an administrator"})
    row["admin_cancelled"] = True
    row["task"].cancel()
    return {"status": "cancel_requested", "message": "Cancelled by an administrator"}
