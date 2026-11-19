"""Record operational outcomes without retaining request/response content."""

import json
import time
import uuid

from starlette.concurrency import run_in_threadpool

from . import admin_events


class OperationalMiddleware:
    def __init__(self, app):
        self.app = app
        self.last_cleanup = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        correlation = uuid.uuid4().hex
        token = admin_events.request_id.set(correlation)
        started, status, error_body = time.monotonic(), 500, bytearray()

        async def observe(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message, headers=[*message.get("headers", []), (b"x-request-id", correlation.encode())])
            elif message["type"] == "http.response.body" and status >= 400 and len(error_body) < 16384:
                error_body.extend(message.get("body", b"")[:16384 - len(error_body)])
            await send(message)

        try:
            await self.app(scope, receive, observe)
        finally:
            runtime = getattr(scope["app"].state, "runtime", None)
            principal = scope.get("graphmine_principal")
            if runtime is not None:
                def save():
                    now = runtime.accounts.clock()
                    with runtime.database._connect() as db:
                        if status >= 400:
                            try:
                                detail = json.loads(error_body).get("error", {})
                                code = detail.get("code", "validation_failure" if status == 422 else f"http_{status}")
                            except (ValueError, AttributeError):
                                code = f"http_{status}"
                            admin_events.insert(db, "error", code.replace("_", " "), ts=now,
                                                user_id=principal.user_id if principal else None, outcome=code,
                                                duration_ms=(time.monotonic() - started) * 1000,
                                                correlation=correlation, details={"code": code, "status": status})
                            if scope["path"] == "/api/auth/login" and not db.execute("SELECT 1 FROM events WHERE type='sign_in' AND request_id=?", (correlation,)).fetchone():
                                admin_events.insert(db, "sign_in", "Sign-in failed", ts=now, outcome=code,
                                                    correlation=correlation,
                                                    details={"ip": admin_events.truncate_ip((scope.get("client") or ("unknown",))[0])})
                        if principal and status < 400 and scope["path"] not in {"/api/auth/me", "/api/admin/badges"}:
                            db.execute("UPDATE accounts SET last_active=? WHERE id=?", (now, principal.user_id))
                        if now - self.last_cleanup > 3600:
                            retention = runtime.settings.admin_event_retention_days
                            db.execute("DELETE FROM events WHERE ts<?", (now - retention * 86400,))
                            self.last_cleanup = now
                await run_in_threadpool(save)
            admin_events.request_id.reset(token)
