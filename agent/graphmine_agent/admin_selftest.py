"""A real API smoke test with an account that cannot sign in over the network."""

import asyncio
from contextvars import ContextVar
import json
import secrets
import time

import httpx

from .identity import AccountError

# Set only by the in-process runner. No HTTP header, cookie or request field sets it.
internal_user: ContextVar[str | None] = ContextVar("selftest_internal_user", default=None)


def begin(app):
    monitor = app.state.admin_monitor
    if monitor.selftest_task and not monitor.selftest_task.done():
        raise AccountError("A self-test is already running.", "selftest_busy", 409)
    previous = monitor.state("selftest")
    result = {"status": "running", "started_at": time.time(), "steps": []}
    monitor.set_state("selftest", result)
    with monitor.runtime.database._connect() as db:
        monitor.runtime.accounts._audit(db, "selftest.started", "selftest", before=previous or {}, after=result)
    monitor.selftest_task = asyncio.create_task(run(app, result))
    return result


async def run(app, result):
    monitor = app.state.admin_monitor
    runtime, session, workflow, user_id, context = monitor.runtime, None, None, None, None
    current_step, started = "Sign in", time.monotonic()
    try:
        password = secrets.token_urlsafe(32)
        with runtime.database._connect() as db:
            row = db.execute("SELECT id,login_disabled FROM accounts WHERE username='selftest'").fetchone()
        if row and not row["login_disabled"]:
            raise ValueError("The selftest name belongs to a normal account; rename it before running the test")
        if row:
            user_id = row["id"]
            await asyncio.to_thread(runtime.accounts.reset_password, "selftest", password, must_change_password=False)
        else:
            user = await asyncio.to_thread(runtime.accounts.create_user, "selftest", password, login_disabled=True)
            user_id = user["id"]
        context = internal_user.set(user_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://selftest.internal", headers={"X-GraphMine-Request": "1"}) as client:
            async def request(method, path, **kwargs):
                response = await asyncio.wait_for(client.request(method, path, **kwargs), 90)
                if response.status_code >= 400:
                    code = response.json().get("error", {}).get("code", "http_" + str(response.status_code))
                    raise ValueError("API step failed: " + str(code))
                return response.json() if response.content else None

            def passed():
                result["steps"].append({"name": current_step, "status": "passed", "duration_ms": (time.monotonic() - started) * 1000})
                monitor.set_state("selftest", result)

            await request("POST", "/api/auth/login", json={"username": "selftest", "password": password})
            await request("GET", "/api/auth/me")
            passed()
            current_step, started = "Fixed question", time.monotonic()
            session = (await request("POST", "/api/sessions", json={"domain_id": "general", "title": "Administrator self-test"}))["id"]
            answer = await request("POST", f"/api/sessions/{session}/analytics/plan", json={"message": "What is a k-core?"})
            if answer.get("status") in {"failed", "error", "unavailable"} or answer.get("error"):
                raise ValueError("The fixed question did not complete")
            passed()
            current_step, started = "Calculation", time.monotonic()
            graph = json.dumps({"graph": {"id": "selftest", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
                                "vertices": [{"id": i} for i in range(3)], "edges": [{"id": "01", "source": 0, "target": 1}, {"id": "12", "source": 1, "target": 2}, {"id": "02", "source": 0, "target": 2}]})
            file = await request("POST", f"/api/sessions/{session}/files", files={"file": ("selftest.json", graph, "application/json")}, data={"role": "graph", "directed": "false"})
            record = await request("POST", f"/api/sessions/{session}/workflows", json={"mode": "expert", "plan": {"version": 1, "device": "cpu", "steps": [{"id": "core", "problem": "k-core", "input": {"input": "main"}, "parameters": {"requested_k": 2}}]}, "inputs": {"main": {"file_id": file["id"], "kind": "graph"}}})
            workflow = record["id"]
            await request("POST", f"/api/workflows/{workflow}/run", json={"workflow_hash": record["validation"]["workflow_hash"], "expected_revision": record["revision"]})
            while time.monotonic() - started < 120:
                record = await request("GET", f"/api/workflows/{workflow}")
                if record["status"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(.25)
            if record["status"] != "completed":
                raise ValueError("The fixed CPU calculation did not succeed: " + record["status"])
            passed()
            current_step, started = "Result view", time.monotonic()
            await request("GET", f"/api/workflows/{workflow}/result?summary=true")
            passed()
            result["status"] = "passed"
    except asyncio.CancelledError:
        result["status"] = "interrupted"
        raise
    except Exception as error:
        result["status"] = "failed"
        # Only our explicit messages are safe to surface; underlying exceptions may contain payloads.
        reason = str(error) if type(error) is ValueError else "The step timed out" if isinstance(error, TimeoutError) else "The API step could not complete"
        result["steps"].append({"name": current_step, "status": "failed", "duration_ms": (time.monotonic() - started) * 1000, "reason": reason})
    finally:
        if workflow:
            from .identity import identity_scope
            try:
                with identity_scope(runtime.accounts.session_principal(session)):
                    await runtime.analytics.cancel(workflow)
            except Exception:
                pass
        if user_id:
            with runtime.database._connect() as db:
                db.execute("DELETE FROM account_sessions WHERE user_id=?", (user_id,))
        if context:
            internal_user.reset(context)
        result["finished_at"] = time.time()
        seen = {s["name"] for s in result["steps"]}
        result["steps"].extend({"name": name, "status": "blocked", "duration_ms": None, "reason": "An earlier step did not complete"} for name in ("Sign in", "Fixed question", "Calculation", "Result view") if name not in seen)
        monitor.set_state("selftest", result)
        with runtime.database._connect() as db:
            runtime.accounts._audit(db, "selftest.finished", "selftest", before={"status": "running"}, after=result)
