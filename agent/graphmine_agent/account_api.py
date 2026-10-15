"""Cookie login, API credentials, CSRF protection and request admission."""

import asyncio
import base64
import binascii
from http.cookies import CookieError, SimpleCookie

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers

from .analytics_planning import PLANNING_DEADLINE_SECONDS
from .identity import AccountError, current_principal, identity_scope

COOKIE = "graphmine_session"
# Request limits only backstop the work: the planner reports its own timeout
# to the conversation, so its limit must outlast the planner deadline.
REQUEST_SECONDS = 300
PLANNING_REQUEST_SECONDS = PLANNING_DEADLINE_SECONDS + 60


def account_response(error):
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {
                "code": error.code,
                "message": str(error),
                **({"details": error.details} if error.details is not None else {}),
            }
        },
        headers={
            "Cache-Control": "no-store",
            **({"Retry-After": str(error.retry_after)} if error.retry_after else {}),
        },
    )


class AccountMiddleware:
    """Pure ASGI keeps the identity available to endpoints and their tasks."""

    def __init__(self, app):
        self.app = app
        self.shared_slots = asyncio.Semaphore(2)

    async def __call__(self, scope, receive, send):
        # Hold admission through the final response byte, including public
        # downloads to slow clients. A shared snapshot can be much larger than
        # a graph preview and must not allocate an unbounded set of responses.
        if (
            scope["type"] == "http"
            and scope.get("path") == "/api/shared/read"
            and scope.get("method") == "POST"
        ):
            if self.shared_slots.locked():
                await account_response(
                    AccountError(
                        "Shared previews are busy. Retry shortly.", "busy", 429
                    )
                )(scope, receive, send)
                return
            async with self.shared_slots:
                await self._call(scope, receive, send)
            return
        await self._call(scope, receive, send)

    async def _call(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"} or not scope.get(
            "path", ""
        ).startswith("/api/"):
            await self.app(scope, receive, send)
            return
        runtime = scope["app"].state.runtime
        if not runtime.settings.accounts_enabled or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        websocket = scope["type"] == "websocket"
        method, path = scope.get("method", "GET"), scope["path"]
        public = not websocket and (method, path) in {
            ("GET", "/api/auth/config"),
            ("POST", "/api/auth/login"),
            ("POST", "/api/shared/read"),
        }
        lease = None
        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            origin = headers.get("origin")
            scheme = scope.get("scheme", "http").replace("ws", "http")
            allowed = {
                *runtime.settings.allowed_origins,
                f"{scheme}://{headers.get('host', '')}",
            }
            if (
                (websocket or method not in {"GET", "HEAD"})
                and origin
                and origin not in allowed
            ):
                raise AccountError(
                    "This browser origin is not allowed.", "invalid_origin", 403
                )
            principal = None
            if not public:
                bearer = headers.get("authorization", "")
                cookie = SimpleCookie()
                try:
                    cookie.load(headers.get("cookie", ""))
                except CookieError:
                    cookie = SimpleCookie()
                token = (
                    bearer[7:].strip() if bearer.lower().startswith("bearer ") else None
                )
                if websocket and not token:
                    for protocol in scope.get("subprotocols", []):
                        if protocol.startswith("graphmine.token."):
                            try:
                                encoded = protocol.removeprefix("graphmine.token.")
                                token = base64.urlsafe_b64decode(
                                    encoded + "=" * (-len(encoded) % 4)
                                ).decode()
                            except (ValueError, UnicodeError, binascii.Error):
                                raise AccountError(
                                    "Invalid login credential.", "unauthorized", 401
                                )
                cookie_auth = token is None
                if cookie_auth and COOKIE in cookie:
                    token = cookie[COOKIE].value
                principal = runtime.accounts.authenticate(token)
                if principal is None:
                    raise AccountError(
                        "Please sign in to continue.", "unauthorized", 401
                    )
                if (
                    cookie_auth
                    and method not in {"GET", "HEAD"}
                    and headers.get("x-graphmine-request") != "1"
                ):
                    raise AccountError(
                        "Missing browser request verification.", "csrf_required", 403
                    )
            if path == "/api/auth/login" and headers.get("x-graphmine-request") != "1":
                raise AccountError(
                    "Missing browser request verification.", "csrf_required", 403
                )

            maximum = 4096 if path == "/api/auth/login" else 128 * 1024
            if (
                path.endswith(("/files", "/files/preview"))
                or path == "/api/connectors/sqlite"
            ) and method == "POST":
                maximum = (
                    min(
                        runtime.settings.max_upload_bytes,
                        runtime.settings.account_upload_bytes,
                    )
                    + 65536
                )
            length = headers.get("content-length")
            if length and (not length.isdecimal() or int(length) > maximum):
                raise AccountError(
                    "The request exceeds the upload/request size limit.",
                    "request_too_large",
                    413,
                )
            consumed = 0

            async def bounded_receive():
                nonlocal consumed
                message = await receive()
                if message["type"] == "http.request":
                    consumed += len(message.get("body", b""))
                    if consumed > maximum:
                        raise AccountError(
                            "The request exceeds the upload/request size limit.",
                            "request_too_large",
                            413,
                        )
                return message

            # Separate slots per kind of work: a long planning request must not
            # block previews, uploads or approvals. Capabilities are cached and
            # shared server-wide, so they need no slot.
            kind = per_user = None
            limit = REQUEST_SECONDS
            if not public and path != "/api/auth/logout":
                if (
                    path.endswith("/graph-preview")
                    or (
                        method == "GET"
                        and path.endswith("/graph")
                        and "/groups/" in path
                    )
                    or (
                        method == "POST"
                        and path.endswith("/memberships")
                        and "/ports/" in path
                    )
                ):
                    kind, per_user = "preview", 2
                elif method == "POST" and path.endswith(
                    ("/plan", "/chat", "/interpret")
                ):
                    kind, per_user = "planning", 1
                    limit = PLANNING_REQUEST_SECONDS
                elif method == "POST" or path.endswith(
                    ("/history/archive", "/report", "/csv")
                ):
                    kind, per_user = "request", 1
            costly = kind is not None
            if websocket:
                lease = runtime.accounts.acquire(
                    principal.user_id, "websocket", 200, 2, 3630
                )
            elif costly:
                lease = runtime.accounts.acquire(
                    principal.user_id, kind, 8, per_user, ttl=limit + 30
                )
            with identity_scope(principal):
                # Polls, cancellation and logout remain usable during expensive work.
                if costly or websocket:
                    async with asyncio.timeout(3600 if websocket else limit):
                        await self.app(scope, bounded_receive, tracked_send)
                else:
                    await self.app(scope, bounded_receive, tracked_send)
        except AccountError as error:
            if response_started:
                # Streaming headers are already committed; close the response
                # through the server instead of emitting a second status line.
                raise
            if websocket:
                await send(
                    {
                        "type": "websocket.close",
                        "code": 4401 if error.status == 401 else 4403,
                        "reason": str(error),
                    }
                )
            else:
                await account_response(error)(scope, receive, send)
        except TimeoutError:
            if response_started:
                raise
            if websocket:
                await send(
                    {
                        "type": "websocket.close",
                        "code": 1000,
                        "reason": "Reconnect to renew this connection.",
                    }
                )
            else:
                await account_response(
                    AccountError(
                        "The request exceeded its time allowance.",
                        "request_time_limit",
                        429,
                    )
                )(scope, receive, send)
        finally:
            if lease:
                runtime.accounts.release(lease)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    issue_token: bool = False


class AccountPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12, max_length=128)


class AccountCreate(AccountPassword):
    username: str = Field(min_length=3, max_length=64)
    daily_token_limit: int | None = Field(default=None, ge=0, strict=True)


class AccountTokenLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_token_limit: int | None = Field(ge=0, strict=True)


class AccountPasswordChange(AccountPassword):
    current_password: str = Field(min_length=1, max_length=128)


def public_user(principal):
    return {
        "id": principal.user_id,
        "username": principal.username,
        "role": "admin" if principal.is_admin else "user",
    }


def administrator():
    principal = current_principal.get()
    if principal is None or not principal.is_admin:
        raise AccountError("Administrator access is required.", "admin_required", 403)
    return principal


def register_account_routes(app):
    router = APIRouter(prefix="/api/auth")
    login_slots = asyncio.Semaphore(2)

    @router.get("/config")
    async def configuration(request: Request):
        return {
            "enabled": request.app.state.runtime.settings.accounts_enabled,
            "registration_enabled": False,
        }

    @router.post("/login")
    async def login(body: LoginRequest, request: Request, response: Response):
        runtime = request.app.state.runtime
        if not runtime.settings.accounts_enabled:
            raise AccountError("Account login is disabled.", "accounts_disabled", 404)
        if login_slots.locked():
            raise AccountError(
                "Sign-in is busy. Please try again shortly.",
                "login_busy",
                retry_after=2,
            )
        async with login_slots:
            token, principal = await run_in_threadpool(
                runtime.accounts.login,
                body.username,
                body.password,
                request.client.host if request.client else "unknown",
            )
        response.set_cookie(
            COOKIE,
            token,
            max_age=runtime.settings.account_session_seconds,
            httponly=True,
            secure=runtime.settings.account_cookie_secure,
            samesite="strict",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        result = {
            "user": public_user(principal),
            "quota": runtime.accounts.usage(principal.user_id),
        }
        if body.issue_token:
            result.update(
                access_token=token,
                token_type="bearer",
                expires_in=runtime.settings.account_session_seconds,
            )
        return result

    @router.get("/me")
    async def me(response: Response):
        principal = current_principal.get()
        if principal is None:
            raise AccountError("Please sign in.", "unauthorized", 401)
        response.headers["Cache-Control"] = "no-store"
        return {
            "user": public_user(principal),
            "quota": principal.accounts.usage(principal.user_id),
        }

    @router.post("/logout", status_code=204)
    async def logout(response: Response):
        principal = current_principal.get()
        if principal is None:
            raise AccountError("Please sign in.", "unauthorized", 401)
        principal.accounts.logout(principal)
        response.delete_cookie(
            COOKIE,
            path="/",
            secure=principal.accounts.settings.account_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.headers["Cache-Control"] = "no-store"

    async def password_operation(operation, *args):
        if login_slots.locked():
            raise AccountError(
                "Account management is busy. Please try again shortly.",
                "login_busy",
                retry_after=2,
            )
        async with login_slots:
            return await run_in_threadpool(operation, *args)

    @router.get("/admin/activity")
    async def admin_activity(
        response: Response, before: int | None = None, limit: int = 100
    ):
        principal = administrator()
        if not 1 <= limit <= 200 or (before is not None and before < 1):
            raise AccountError("Invalid activity page limits.", "invalid_request", 422)
        response.headers["Cache-Control"] = "no-store"
        return principal.accounts.activity(before, limit)

    @router.get("/admin/users")
    async def users(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return administrator().accounts.list_users()

    @router.post("/password", status_code=204)
    async def change_password(body: AccountPasswordChange, response: Response):
        principal = current_principal.get()
        if principal is None:
            raise AccountError("Please sign in.", "unauthorized", 401)
        await password_operation(
            principal.accounts.change_password,
            principal.user_id,
            body.current_password,
            body.password,
        )
        response.delete_cookie(
            COOKIE,
            path="/",
            secure=principal.accounts.settings.account_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.headers["Cache-Control"] = "no-store"

    @router.post("/admin/users", status_code=201)
    async def create_user(body: AccountCreate, response: Response):
        principal = administrator()
        response.headers["Cache-Control"] = "no-store"
        return await password_operation(
            principal.accounts.create_user,
            body.username,
            body.password,
            body.daily_token_limit,
        )

    @router.post("/admin/users/{username}/token-limit")
    async def token_limit(username: str, body: AccountTokenLimit, response: Response):
        principal = administrator()
        response.headers["Cache-Control"] = "no-store"
        return principal.accounts.set_token_limit(username, body.daily_token_limit)

    @router.post("/admin/users/{username}/reset-tokens")
    async def reset_tokens(username: str, response: Response):
        principal = administrator()
        response.headers["Cache-Control"] = "no-store"
        return principal.accounts.reset_tokens(username)

    @router.post("/admin/users/{username}/reset-password", status_code=204)
    async def reset_password(username: str, body: AccountPassword, response: Response):
        principal = administrator()
        await password_operation(
            principal.accounts.reset_password, username, body.password
        )
        response.headers["Cache-Control"] = "no-store"

    @router.post("/admin/users/{username}/disable", status_code=204)
    async def disable_user(username: str, response: Response):
        principal = administrator()
        if principal.accounts.username(username) == principal.username:
            raise AccountError(
                "You cannot disable your own administrator account.",
                "self_disable",
                403,
            )
        principal.accounts.disable(username)
        response.headers["Cache-Control"] = "no-store"

    @router.post("/admin/users/{username}/enable", status_code=204)
    async def enable_user(username: str, response: Response):
        administrator().accounts.enable(username)
        response.headers["Cache-Control"] = "no-store"

    app.include_router(router)
