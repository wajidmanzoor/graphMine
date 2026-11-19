"""The admin console API. Every route shares the active-admin dependency."""

import json
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from . import admin_events, admin_lifecycle
from .account_api import administrator
from .identity import AccountError, Principal, identity_scope
from .studio_sync import sync_account


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(Body):
    username: str = Field(min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=12, max_length=128)
    role: Literal["admin", "user"] = "user"
    daily_token_limit: int | None = Field(default=None, ge=0, strict=True)
    storage_limit: int | None = Field(default=None, gt=0, le=2**53 - 1, strict=True)
    graphmine_access: bool = True
    studio_access: bool = False
    must_change_password: bool = True


class UserPatch(Body):
    username: str | None = Field(default=None, min_length=3, max_length=64)
    role: Literal["admin", "user"] | None = None
    daily_token_limit: int | None = Field(default=None, ge=0, strict=True)
    storage_limit: int | None = Field(default=None, gt=0, le=2**53 - 1, strict=True)
    graphmine_access: bool | None = None
    studio_access: bool | None = None
    must_change_password: bool | None = None


class PasswordReset(Body):
    password: str | None = Field(default=None, min_length=12, max_length=128)
    must_change_password: bool = True


class UserDelete(Body):
    data: Literal["transfer", "erase"]
    confirm: bool = Field(strict=True)
    confirm_username: str


class SupportRequest(Body):
    conversation_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    duration: Literal["hour", "session"] = "hour"


class ModelSettings(Body):
    values: dict


class Confirm(Body):
    confirm: bool = Field(strict=True)


def register_admin_routes(app):
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(administrator)])

    @router.get("/badges")
    def badges(request: Request):
        runtime = request.app.state.runtime
        with runtime.database._connect() as db:
            users = db.execute("SELECT count(*) FROM accounts WHERE login_disabled=0").fetchone()[0]
            jobs = db.execute("SELECT count(*) FROM account_leases WHERE kind IN ('model','job') AND expires_at>?", (runtime.accounts.clock(),)).fetchone()[0]
        waiting = len(runtime.accounts.waiting.get("model", []))
        health = request.app.state.admin_monitor.cached
        return {"users": users, "jobs": jobs + waiting, "health": health["attention"] if health else None, "now": runtime.accounts.clock(),
                "health_reason": None if health else "Health checks have not run yet"}

    @router.get("/overview")
    async def overview(request: Request):
        from .admin_summary import overview as summary
        data = await run_in_threadpool(summary, request.app.state.runtime)
        data["health"] = await request.app.state.admin_monitor.snapshot()
        return data

    @router.get("/overview/export")
    def overview_csv(request: Request):
        from .admin_summary import overview as summary
        data = summary(request.app.state.runtime)
        rows = [{"metric": key, "value": value} for key, value in data.items() if not isinstance(value, (dict, list))]
        return Response(admin_events.csv_text(rows, ("metric", "value")), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="graphmine-summary.csv"'})

    @router.get("/health")
    async def health(request: Request, refresh: bool = False):
        return await request.app.state.admin_monitor.snapshot(force=refresh)

    @router.get("/health/logs")
    async def agent_logs(request: Request):
        return await request.app.state.admin_monitor.logs()

    @router.get("/health/selftest")
    def selftest_status(request: Request):
        return {"result": request.app.state.admin_monitor.state("selftest")}

    @router.post("/health/selftest", status_code=202)
    async def selftest(request: Request):
        from .admin_selftest import begin
        return begin(request.app)

    @router.post("/services/{service}/restart", status_code=202)
    async def restart_service(service: Literal["agent", "model"], body: Confirm, request: Request):
        return await request.app.state.admin_monitor.restart(service, body.confirm)

    @router.get("/model")
    async def model(request: Request):
        return await request.app.state.admin_monitor.model()

    @router.patch("/model/settings")
    def model_settings(body: ModelSettings, request: Request):
        from .admin_settings import save
        return save(request.app.state.runtime, body.values)

    @router.get("/jobs")
    async def jobs(request: Request, view: Literal["active", "finished", "failed"] = "active"):
        from .admin_jobs import snapshot
        return snapshot(request.app.state.runtime, view)

    @router.get("/jobs/{kind}/{identifier}")
    async def job_details(kind: Literal["workflow", "job"], identifier: str, request: Request):
        from .admin_jobs import detail
        return detail(request.app.state.runtime, kind, identifier)

    @router.post("/jobs/{kind}/{identifier}/cancel")
    async def cancel_job(kind: Literal["workflow", "job"], identifier: str, request: Request):
        from .admin_jobs import cancel
        return await cancel(request.app.state.runtime, kind, identifier)

    @router.post("/model-calls/{identifier}/cancel")
    async def cancel_model_call(identifier: str, request: Request):
        from .admin_model_calls import cancel
        return await cancel(request.app.state.runtime.accounts, identifier)

    @router.get("/usage")
    def usage(request: Request, days: int = 14):
        from .admin_usage import usage as summary
        return summary(request.app.state.runtime, days)

    @router.get("/usage/export")
    def usage_csv(request: Request, days: int = 14):
        from .admin_usage import usage as summary
        data = summary(request.app.state.runtime, days)
        rows = [{"section": "summary", "metric": key, "value": value, "previous": data["previous"].get(key)} for key, value in data["summary"].items()]
        for section, columns in (("daily", ("questions", "calculations", "median_ms", "p95_ms")), ("time_breakdown", ("seconds",)), ("errors", ("count",)), ("tokens_by_user", ("tokens", "missing")), ("datasets", ("count",))):
            for row in data[section]:
                label = next((row[k] for k in ("day", "stage", "type", "user", "dataset") if k in row), "")
                rows.extend({"section": section, "metric": f"{label}: {key}", "value": row[key]} for key in columns)
        return Response(admin_events.csv_text(rows, ("section", "metric", "value", "previous")), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="graphmine-usage.csv"'})

    @router.get("/users")
    def users(request: Request):
        return request.app.state.runtime.accounts.admin_users()

    @router.get("/users/export")
    def users_csv(request: Request):
        rows = request.app.state.runtime.accounts.admin_users()["items"]
        return Response(admin_events.csv_text(rows, ("username", "role", "status", "created_at", "last_active", "questions_7d", "daily_token_limit", "storage_limit", "graphmine_access", "studio_access")),
                        media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="graphmine-users.csv"'})

    @router.post("/users", status_code=201)
    def create_user(body: UserCreate, request: Request):
        accounts = request.app.state.runtime.accounts
        password = body.password or secrets.token_urlsafe(18)
        data = body.model_dump(exclude={"password", "role"})
        accounts.create_user(password=password, admin=body.role == "admin", **data)
        user = accounts.user(body.username)
        return {"user": user, "studio": sync_account(accounts, user),
                **({"temporary_password": password} if body.password is None else {})}

    @router.patch("/users/{username}")
    def edit_user(username: str, body: UserPatch, request: Request):
        accounts = request.app.state.runtime.accounts
        changes = body.model_dump(exclude_unset=True)
        if any(value is None and key not in {"daily_token_limit", "storage_limit"} for key, value in changes.items()):
            raise ValueError("Role, username and access cannot be empty.")
        user = accounts.update_user(username, changes)
        return {"user": user, "studio": sync_account(accounts, user, old_username=username, revoke_sessions=True)}

    @router.get("/users/{username}/delete-preview")
    def delete_preview(username: str, request: Request):
        return admin_lifecycle.preview(request.app.state.runtime, username)

    @router.delete("/users/{username}")
    def delete_user(username: str, body: UserDelete, request: Request):
        return admin_lifecycle.delete_user(request.app.state.runtime, username, **body.model_dump())

    @router.post("/users/{username}/reset-password")
    def reset_password(username: str, body: PasswordReset, request: Request):
        accounts = request.app.state.runtime.accounts
        password = body.password or secrets.token_urlsafe(18)
        accounts.reset_password(username, password, must_change_password=body.must_change_password)
        return {"password_reset": True, "studio": sync_account(accounts, accounts.user(username), revoke_sessions=True),
                **({"temporary_password": password} if body.password is None else {})}

    @router.post("/users/{username}/reset-tokens")
    def reset_tokens(username: str, request: Request):
        return request.app.state.runtime.accounts.reset_daily_tokens(username)

    @router.post("/users/{username}/force-signout")
    def force_signout(username: str, request: Request):
        accounts = request.app.state.runtime.accounts
        return {**accounts.force_signout(username), "studio": sync_account(accounts, accounts.user(username), revoke_sessions=True)}

    @router.post("/studio-sync/{user_id}/retry")
    def retry_pending_studio(user_id: str, request: Request):
        accounts = request.app.state.runtime.accounts
        with accounts.database._connect() as db:
            row = db.execute("SELECT payload,options FROM studio_sync_pending WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("No pending Studio update.")
        return {"studio": sync_account(accounts, json.loads(row[0]), **json.loads(row[1]))}

    @router.post("/users/{username}/disable")
    def disable(username: str, request: Request):
        accounts = request.app.state.runtime.accounts
        accounts.disable(username)
        return {"user": accounts.user(username), "studio": sync_account(accounts, accounts.user(username))}

    @router.post("/users/{username}/enable")
    def enable(username: str, request: Request):
        accounts = request.app.state.runtime.accounts
        accounts.enable(username)
        return {"user": accounts.user(username), "studio": sync_account(accounts, accounts.user(username))}

    @router.post("/users/{username}/studio-sync")
    def retry_studio(username: str, request: Request):
        accounts = request.app.state.runtime.accounts
        user = accounts.user(username)
        previous = json.loads(user["studio_sync_error"]) if user["studio_sync_error"] else {}
        return {"studio": sync_account(accounts, user, old_username=previous.get("old_username"))}

    @router.get("/activity")
    def activity(request: Request, before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=200),
                 user_id: str | None = None, kind: Literal["question", "calculation", "sign_in", "error", "admin_change", "support_access"] | None = None,
                 start: float | None = None, end: float | None = None, search: str = Query("", max_length=200)):
        return admin_events.query(request.app.state.runtime.database, before=before, limit=limit, user_id=user_id,
                                  kind=kind, start=start, end=end, search=search)

    @router.get("/activity/export")
    def activity_csv(request: Request, user_id: str | None = None, kind: str | None = None,
                     start: float | None = None, end: float | None = None, search: str = Query("", max_length=200)):
        rows = []
        cursor = None
        while True:
            result = admin_events.query(request.app.state.runtime.database, before=cursor, limit=1000,
                                        user_id=user_id, kind=kind, start=start, end=end, search=search)
            rows.extend(result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
        return Response(admin_events.csv_text(rows, ("ts", "username", "type", "summary", "outcome", "duration_ms", "request_id", "details")),
                        media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="graphmine-activity.csv"'})

    @router.post("/support-access", status_code=201)
    def grant_support(body: SupportRequest, request: Request):
        return request.app.state.runtime.accounts.grant_support(body.conversation_id, body.reason, body.duration)

    @router.get("/support-access/{grant_id}/conversation")
    def support_conversation(grant_id: str, request: Request):
        runtime = request.app.state.runtime
        grant = runtime.accounts.support_grant(grant_id)
        with identity_scope(Principal(grant["user_id"], "support viewer", runtime.accounts)):
            conversation = runtime.database.get_session(grant["conversation_id"])
            transcript = runtime.database.conversation_transcript(grant["conversation_id"])
        return {"grant": grant, "read_only": True, "title": conversation.title,
                "messages": [{key: item[key] for key in ("role", "message", "summary", "created_at") if key in item} for item in transcript]}

    app.include_router(router)
