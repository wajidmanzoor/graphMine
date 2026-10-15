import asyncio
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from graphmine_agent import account_api
from graphmine_agent.accounts import DAY, Accounts, model_post
from graphmine_agent.analytics_planning import (
    PLANNING_DEADLINE_SECONDS,
    AnalyticsPlanner,
)
from graphmine_agent.api import create_app, enforce_retention
from graphmine_agent.database import Database
from graphmine_agent.identity import AccountError, Principal, identity_scope
from graphmine_agent.models import ConversationEvent, SessionRecord
from starlette.websockets import WebSocketDisconnect

PASSWORD = "long-test-password-42"


@pytest.fixture
def account_settings(settings):
    return replace(settings, accounts_enabled=True, account_cookie_secure=False)


def login(client, username="alice", password=PASSWORD):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "issue_token": True},
        headers={"X-GraphMine-Request": "1"},
    )
    assert response.status_code == 200, response.text
    client.cookies.clear()
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def store(settings, now=None):
    database = Database(settings.database_path)
    accounts = Accounts(
        settings, database, **({"clock": lambda: now[0]} if now else {})
    )
    return accounts, database


def test_login_cookie_csrf_and_legacy_token_rejected(account_settings):
    with TestClient(create_app(account_settings)) as client:
        accounts = client.app.state.runtime.accounts
        accounts.create_user("alice", PASSWORD)
        assert client.get("/api/auth/config").json() == {
            "enabled": True,
            "registration_enabled": False,
        }
        assert client.get("/api/domains").status_code == 401
        assert (
            client.get(
                "/api/domains", headers={"Authorization": "Bearer test-secret"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"username": "alice", "password": PASSWORD}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "alice", "password": PASSWORD},
                headers={"X-GraphMine-Request": "1", "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": PASSWORD},
            headers={"X-GraphMine-Request": "1"},
        )
        assert response.status_code == 200
        assert "access_token" not in response.json()
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").json()["user"]["username"] == "alice"
        assert (
            client.post("/api/sessions", json={"domain_id": "general"}).status_code
            == 403
        )
        assert (
            client.post(
                "/api/sessions",
                json={"domain_id": "general"},
                headers={"X-GraphMine-Request": "1"},
            ).status_code
            == 201
        )
        assert not any(
            getattr(route, "path", "") == "/api/auth/register"
            for route in client.app.routes
        )
        assert (
            client.post(
                "/api/auth/logout", headers={"X-GraphMine-Request": "1"}
            ).status_code
            == 204
        )
        assert client.get("/api/auth/me").status_code == 401


def test_accounts_own_sessions_files_workflows_and_websockets(
    account_settings, triangle_graph
):
    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        for username in ("alice", "bob"):
            runtime.accounts.create_user(username, PASSWORD)
        legacy = runtime.database.create_session(SessionRecord(domain_id="general"))
        alice, bob = login(client), login(client, "bob")
        session = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=alice
        ).json()
        sid = session["id"]
        upload = client.post(
            f"/api/sessions/{sid}/files",
            files={"file": ("graph.json", triangle_graph, "application/json")},
            headers=alice,
        )
        assert upload.status_code == 201, upload.text
        fid = upload.json()["id"]
        runtime.analytics._save(
            {
                "id": "owned-workflow",
                "session_id": sid,
                "revision": 1,
                "status": "ready",
            }
        )
        assert [s["id"] for s in client.get("/api/sessions", headers=alice).json()] == [
            sid
        ]
        assert client.get("/api/sessions", headers=bob).json() == []
        for path in (
            f"/api/sessions/{sid}",
            f"/api/sessions/{sid}/workspace",
            f"/api/sessions/{sid}/files",
            f"/api/sessions/{sid}/history/archive",
            f"/api/sessions/{sid}/events",
            f"/api/sessions/{sid}/workflows",
            f"/api/sessions/{sid}/analytics/examples",
            f"/api/files/{fid}/graph-preview",
            "/api/workflows/owned-workflow",
            "/api/workflows/owned-workflow/result",
            "/api/workflows/owned-workflow/example-review",
            f"/api/sessions/{legacy.id}",
        ):
            assert client.get(path, headers=bob).status_code == 404, path
        assert (
            client.delete("/api/workflows/owned-workflow", headers=bob).status_code
            == 404
        )
        with (
            pytest.raises(WebSocketDisconnect) as error,
            client.websocket_connect(f"/api/sessions/{sid}/events/ws", headers=bob),
        ):
            pass
        assert error.value.code == 4404
        with client.websocket_connect(f"/api/sessions/{sid}/events/ws", headers=alice):
            pass
        own = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=bob
        ).json()["id"]
        response = client.post(
            f"/api/sessions/{own}/workflows",
            headers=bob,
            json={"mode": "expert", "plan": {}, "inputs": {"main": {"file_id": fid}}},
        )
        assert response.status_code == 404
        assert runtime.accounts.adopt_legacy("alice") == 1
        assert (
            client.get(f"/api/sessions/{legacy.id}", headers=alice).status_code == 200
        )
        assert client.get(f"/api/sessions/{legacy.id}", headers=bob).status_code == 404


def test_hashed_passwords_revocation_expiry_and_no_quota_reset(account_settings):
    now = [1000000.0]
    accounts, db = store(account_settings, now)
    user = accounts.create_user("Alice", PASSWORD)
    token, _principal = accounts.login("ALICE", PASSWORD, "test")
    assert accounts.authenticate(token).user_id == user["id"]
    reservation = accounts.reserve_tokens(user["id"], 500)
    accounts.settle_tokens(reservation, 200)
    with db._connect() as connection:
        saved = connection.execute("SELECT password_hash FROM accounts").fetchone()[0]
        assert PASSWORD not in saved and saved.startswith("scrypt$")
        saved_token = connection.execute(
            "SELECT token_hash FROM account_sessions"
        ).fetchone()[0]
        assert saved_token == hashlib.sha256(token.encode()).hexdigest()
    accounts.reset_password("alice", PASSWORD + "-new")
    assert accounts.authenticate(token) is None
    assert accounts.usage(user["id"])["tokens_used"] == 200
    token, _ = accounts.login("alice", PASSWORD + "-new", "test")
    now[0] += account_settings.account_session_seconds
    assert accounts.authenticate(token) is None
    token, _ = accounts.login("alice", PASSWORD + "-new", "test")
    accounts.disable("alice")
    assert accounts.authenticate(token) is None
    with pytest.raises(AccountError, match="Incorrect"):
        accounts.login("alice", PASSWORD + "-new", "test")


def test_login_rate_limit_and_account_cap(account_settings):
    accounts, _ = store(replace(account_settings, max_accounts=1))
    accounts.create_user("alice", PASSWORD)
    with pytest.raises(ValueError, match="Account limit"):
        accounts.create_user("bob", PASSWORD)
    for _ in range(10):
        with pytest.raises(AccountError) as failure:
            accounts.login("alice", "wrong-password", "test")
        assert failure.value.code == "invalid_credentials"
    with pytest.raises(AccountError) as failure:
        accounts.login("alice", PASSWORD, "test")
    assert failure.value.code == "login_rate_limit" and failure.value.retry_after > 0


def test_quota_persists_and_resets_after_24_hours(account_settings):
    now = [1000000.0]
    accounts, db = store(account_settings, now)
    user = accounts.create_user("alice", PASSWORD)["id"]
    lease = accounts.reserve_tokens(user, 4000)
    accounts.settle_tokens(lease, 1500)
    job = accounts.admit_jobs(user)
    accounts.release(job)
    accounts = Accounts(account_settings, Database(db.path), clock=lambda: now[0])
    before = accounts.usage(user)
    assert (before["tokens_used"], before["jobs_used"]) == (1500, 1)
    now[0] += DAY - 1
    assert accounts.usage(user)["tokens_used"] == 1500
    now[0] += 1
    after = accounts.usage(user)
    assert (after["tokens_used"], after["jobs_used"]) == (0, 0)
    assert before["resets_at"] != after["resets_at"]


def test_atomic_shared_budget_and_concurrency_across_connections(account_settings):
    settings = replace(
        account_settings, account_daily_tokens=100, server_daily_tokens=150
    )
    accounts, db = store(settings)
    other = Accounts(settings, Database(db.path))

    def reserve(pair):
        instance, user = pair
        try:
            return instance.reserve_tokens(user, 100)
        except AccountError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, [(accounts, "alice"), (other, "bob")]))
    assert outcomes.count("daily_tokens_limit") == 1
    winner = next(value for value in outcomes if value != "daily_tokens_limit")
    accounts.settle_tokens(winner, 100)
    assert accounts.usage("alice")["server_tokens_remaining"] == 50
    first = accounts.acquire("alice", "request", 8)
    with pytest.raises(AccountError, match="busy"):
        other.acquire("alice", "request", 8)
    accounts.release(first)
    other.release(other.acquire("alice", "request", 8))


def test_usage_reports_recent_questions_and_reserved_tokens(account_settings):
    accounts, database = store(account_settings)
    user = accounts.create_user("alice", PASSWORD)["id"]
    with identity_scope(Principal(user, "alice", accounts)):
        session = database.create_session(SessionRecord(domain_id="general"))
    for turn, tokens in (("t1", 3000), ("t1", 1000), ("t2", 6000)):
        database.add_event(
            ConversationEvent(
                session_id=session.id,
                type="workflow.diagnostics",
                payload={"turn_id": turn, "usage": {"total_tokens": tokens}},
            )
        )
    lease = accounts.reserve_tokens(user, 2500)
    usage = accounts.usage(user)
    assert usage["tokens_reserved"] == 2500
    assert sorted(turn["tokens"] for turn in usage["recent_questions"]) == [4000, 6000]
    assert usage["average_question_tokens"] == 5000
    assert usage["questions_left"] == (50000 - 2500) // 5000
    accounts.settle_tokens(lease, 100)
    assert accounts.usage(user)["tokens_reserved"] == 0


def test_settlement_cannot_refund_next_days_allowance(account_settings):
    now = [1000000.0]
    accounts, _ = store(account_settings, now)
    lease = accounts.reserve_tokens("alice", 5000)
    now[0] += DAY
    assert accounts.usage("alice")["tokens_used"] == 0
    accounts.settle_tokens(lease, 1000)
    assert accounts.usage("alice")["tokens_used"] == 0


@pytest.mark.asyncio
async def test_model_calls_charge_usage_and_unknown_usage_conservatively(
    account_settings,
):
    accounts, _ = store(account_settings)
    principal = Principal("alice", "alice", accounts)
    responses = [
        {"usage": {"prompt_tokens": 100, "completion_tokens": 25}, "choices": []},
        {"choices": []},
    ]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=responses.pop(0))
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://model.test"
    ) as client:
        with identity_scope(principal):
            await model_post(
                client,
                "/chat/completions",
                json={"messages": [], "max_completion_tokens": 100},
            )
            assert accounts.usage("alice")["tokens_used"] == 125
            await model_post(
                client,
                "/chat/completions",
                json={"messages": [], "max_completion_tokens": 100},
            )
            assert accounts.usage("alice")["tokens_used"] > 125 + 100


@pytest.mark.asyncio
async def test_exhausted_quota_never_calls_model_and_cancellation_is_charged(
    account_settings,
):
    accounts, _ = store(replace(account_settings, account_daily_tokens=1))
    client = AsyncMock()
    with identity_scope(Principal("alice", "alice", accounts)):
        with pytest.raises(AccountError) as failure:
            await model_post(client, "/chat/completions", json={"messages": []})
        assert failure.value.code == "daily_tokens_limit"
    client.post.assert_not_called()
    accounts, _ = store(account_settings)
    client.post.side_effect = asyncio.CancelledError
    with (
        identity_scope(Principal("alice", "alice", accounts)),
        pytest.raises(asyncio.CancelledError),
    ):
        await model_post(client, "/chat/completions", json={"messages": []})
    assert accounts.usage("alice")["tokens_used"] > 0
    lease = accounts.reserve_tokens("alice", 1)
    accounts.settle_tokens(lease, 0)


@pytest.mark.asyncio
async def test_server_side_model_failures_are_refunded(account_settings):
    accounts, _ = store(account_settings)
    request = {"messages": [], "max_completion_tokens": 1000}

    async def call(client):
        with identity_scope(Principal("alice", "alice", accounts)):
            return await model_post(client, "/chat/completions", json=request)

    def unreachable(_request):
        raise httpx.ConnectError("refused")

    for handler in (unreachable, lambda _request: httpx.Response(503, json={})):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://model.test"
        ) as client:
            with (
                pytest.raises(httpx.ConnectError)
                if handler is unreachable
                else (nullcontext())
            ):
                await call(client)
        assert accounts.usage("alice")["tokens_used"] == 0
    # A timeout charges the counted input, not the unused output allowance.
    client = AsyncMock()
    client.post.side_effect = httpx.ReadTimeout("slow")
    with pytest.raises(httpx.ReadTimeout):
        await call(client)
    estimate = len(json.dumps(request, ensure_ascii=False).encode()) + 1024
    assert accounts.usage("alice")["tokens_used"] == estimate


@pytest.mark.asyncio
async def test_graph_jobs_are_bounded_independently_of_ai_tokens(account_settings):
    accounts, _ = store(
        replace(account_settings, account_daily_jobs=1, account_running_jobs=1)
    )
    lease = accounts.admit_jobs("alice")
    with pytest.raises(AccountError) as failure:
        accounts.admit_jobs("alice")
    assert failure.value.code == "concurrency_limit"
    accounts.release(lease)
    with pytest.raises(AccountError) as failure:
        accounts.admit_jobs("alice")
    assert failure.value.code == "daily_jobs_limit"
    assert accounts.usage("alice")["tokens_used"] == 0
    running, maximum = 0, 0

    async def work(user):
        nonlocal running, maximum
        async with accounts.execution_slot(user):
            running += 1
            maximum = max(maximum, running)
            await asyncio.sleep(0.03)
            running -= 1

    await asyncio.gather(work("alice"), work("bob"))
    assert maximum == 1


def test_request_and_per_account_storage_limits(account_settings, triangle_graph):
    settings = replace(account_settings, account_storage_bytes=len(triangle_graph))
    with TestClient(create_app(settings)) as client:
        client.app.state.runtime.accounts.create_user("alice", PASSWORD)
        auth = login(client)
        sid = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=auth
        ).json()["id"]
        path = f"/api/sessions/{sid}/files"
        assert (
            client.post(
                path, files={"file": ("graph.json", triangle_graph)}, headers=auth
            ).status_code
            == 201
        )
        assert (
            client.post(
                path, files={"file": ("graph2.json", triangle_graph)}, headers=auth
            ).status_code
            == 429
        )
        assert (
            client.post(
                "/api/sessions", content="x" * (128 * 1024 + 1), headers=auth
            ).status_code
            == 413
        )
        assert len(client.get(f"/api/sessions/{sid}/files", headers=auth).json()) == 1


def test_planning_does_not_block_previews_uploads_or_capabilities(
    account_settings, triangle_graph
):
    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        user = runtime.accounts.create_user("alice", PASSWORD)["id"]
        runtime.analytics.capabilities = AsyncMock(return_value={"operations": []})
        auth = login(client)
        sid = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=auth
        ).json()["id"]
        files = f"/api/sessions/{sid}/files"
        fid = client.post(
            files, files={"file": ("graph.json", triangle_graph)}, headers=auth
        ).json()["id"]
        # A long planning request holds only the planning slot.
        planning = runtime.accounts.acquire(user, "planning", 8)
        preview = f"/api/files/{fid}/graph-preview"
        assert client.get(preview, headers=auth).status_code == 200
        assert client.get("/api/analytics/capabilities", headers=auth).json() == {
            "operations": []
        }
        assert (
            client.post(
                files, files={"file": ("again.json", triangle_graph)}, headers=auth
            ).status_code
            == 201
        )
        second = client.post(
            f"/api/sessions/{sid}/analytics/plan", json={}, headers=auth
        )
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "concurrency_limit"
        runtime.accounts.release(planning)
        # Previews still have a bounded per-account slot of their own.
        held = [runtime.accounts.acquire(user, "preview", 8, 2) for _ in range(2)]
        assert client.get(preview, headers=auth).status_code == 429
        for lease in held:
            runtime.accounts.release(lease)
        assert client.get(preview, headers=auth).status_code == 200


def test_planning_request_limit_outlasts_the_planner_deadline(
    account_settings, monkeypatch
):
    assert account_api.PLANNING_REQUEST_SECONDS > PLANNING_DEADLINE_SECONDS
    # Shortened limits keep the test fast; the ordering is what matters.

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        return {"status": "ready"}

    monkeypatch.setattr(AnalyticsPlanner, "plan", slow)
    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        runtime.accounts.create_user("alice", PASSWORD)
        runtime.analytics.create = slow
        auth = login(client)
        sid = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=auth
        ).json()["id"]
        # Tightened only after setup, so ordinary setup requests are unaffected.
        monkeypatch.setattr(account_api, "REQUEST_SECONDS", 0.05)
        monkeypatch.setattr(account_api, "PLANNING_REQUEST_SECONDS", 5)
        planned = client.post(
            f"/api/sessions/{sid}/analytics/plan",
            json={"message": "Count triangles", "inputs": {"main": {"file_id": "f"}}},
            headers=auth,
        )
        assert planned.status_code == 200, planned.text
        ordinary = client.post(
            f"/api/sessions/{sid}/workflows",
            json={"mode": "expert", "plan": {}, "inputs": {"main": {"file_id": "f"}}},
            headers=auth,
        )
        assert ordinary.json()["error"]["code"] == "request_time_limit"


def test_conversations_can_be_renamed_archived_and_deleted(
    account_settings, triangle_graph
):
    settings = replace(account_settings, account_storage_bytes=len(triangle_graph))
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        for username in ("alice", "bob"):
            runtime.accounts.create_user(username, PASSWORD)
        alice, bob = login(client), login(client, "bob")
        sid = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=alice
        ).json()["id"]
        files = f"/api/sessions/{sid}/files"
        fid = client.post(
            files, files={"file": ("graph.json", triangle_graph)}, headers=alice
        ).json()["id"]
        renamed = client.patch(
            f"/api/sessions/{sid}",
            json={"title": "Team groups", "archived": True},
            headers=alice,
        ).json()
        assert (renamed["title"], renamed["archived"]) == ("Team groups", True)
        assert (
            client.patch(
                f"/api/sessions/{sid}", json={"title": "x"}, headers=bob
            ).status_code
            == 404
        )
        assert client.delete(f"/api/sessions/{sid}", headers=bob).status_code == 404
        # A file read by a running analysis cannot be removed.
        runtime.analytics._save(
            {
                "id": "running-workflow",
                "session_id": sid,
                "status": "running",
                "input_files": {"main": {"file_id": fid}},
            }
        )
        assert client.delete(f"/api/files/{fid}", headers=alice).status_code == 409
        assert client.delete(f"/api/sessions/{sid}", headers=alice).status_code == 409
        runtime.analytics._save(
            {
                "id": "running-workflow",
                "session_id": sid,
                "status": "completed",
                "input_files": {"main": {"file_id": fid}},
            }
        )
        # Deleting a file frees the account's storage for a new upload.
        assert client.delete(f"/api/files/{fid}", headers=alice).status_code == 204
        assert client.get(files, headers=alice).json() == []
        assert (
            client.post(
                files, files={"file": ("again.json", triangle_graph)}, headers=alice
            ).status_code
            == 201
        )
        folder = settings.data_root / "sessions" / sid
        history = runtime.database.history.session_path(sid)
        assert folder.exists()
        assert client.delete(f"/api/sessions/{sid}", headers=alice).status_code == 204
        assert client.get(f"/api/sessions/{sid}", headers=alice).status_code == 404
        assert not folder.exists() and not history.exists()
        assert runtime.analytics._all(sid) == []


def test_saved_analyses_count_toward_storage(account_settings, triangle_graph):
    settings = replace(account_settings, account_storage_bytes=len(triangle_graph) * 3)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        user = runtime.accounts.create_user("alice", PASSWORD)["id"]
        auth = login(client)
        sid = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=auth
        ).json()["id"]
        client.post(
            f"/api/sessions/{sid}/files",
            files={"file": ("graph.json", triangle_graph)},
            headers=auth,
        )
        record = {"id": "w1", "session_id": sid, "revision": 1, "status": "completed"}
        runtime.analytics._save(record)
        runtime.analytics._write(
            runtime.analytics._directory(record) / "result.json",
            "x" * (len(triangle_graph) * 2),
        )
        storage = runtime.accounts.usage(user)["storage"]
        assert storage["uploads"] == len(triangle_graph)
        assert storage["results"] >= 2 * len(triangle_graph)
        assert runtime.accounts.upload_remaining(user) == 0
        refused = client.post(
            f"/api/sessions/{sid}/files",
            files={"file": ("again.json", triangle_graph)},
            headers=auth,
        )
        assert refused.json()["error"]["code"] == "storage_limit"


def test_retention_deletes_idle_conversations_but_not_running_work(account_settings):
    with TestClient(create_app(replace(account_settings, retention_days=30))) as client:
        runtime = client.app.state.runtime
        idle, busy, fresh = (
            runtime.database.create_session(SessionRecord(domain_id="general")).id
            for _ in range(3)
        )
        old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        with runtime.database._connect() as db:
            db.execute(
                "UPDATE sessions SET updated_at=? WHERE id IN (?,?)", (old, idle, busy)
            )
        runtime.analytics._save(
            {"id": "busy-work", "session_id": busy, "revision": 1, "status": "running"}
        )

        async def one_sweep():
            sweep = asyncio.create_task(enforce_retention(runtime, interval=3600))
            await asyncio.sleep(0.2)
            sweep.cancel()

        asyncio.run(one_sweep())
        remaining = {session.id for session in runtime.database.list_sessions()}
        assert idle not in remaining
        assert {busy, fresh} <= remaining


def test_online_backup_restores_accounts_conversations_and_analyses(
    account_settings, triangle_graph, tmp_path
):
    from graphmine_agent.backup import (
        online_snapshot,
        restore_snapshot,
        rotate_snapshots,
    )

    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        runtime.accounts.create_user("alice", PASSWORD)
        auth = login(client)
        sid = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=auth
        ).json()["id"]
        client.post(
            f"/api/sessions/{sid}/files",
            files={"file": ("graph.json", triangle_graph)},
            headers=auth,
        )
        record = {"id": "kept", "session_id": sid, "revision": 1, "status": "completed"}
        runtime.analytics._save(record)
        runtime.analytics._write(
            runtime.analytics._directory(record) / "result.json", {"steps": {}}
        )
        # Taken while the API is running and holds its store locks.
        snapshot = tmp_path / "backups" / "graphmine-1"
        snapshot.parent.mkdir()
        manifest = online_snapshot(account_settings.data_root, snapshot)
        assert (
            manifest["database"]["sessions"] == 1 and manifest["database"]["files"] == 1
        )
    restored = restore_snapshot(snapshot, tmp_path / "restored")
    data = Path(restored["data_root"])
    store = Database(data / "agent.sqlite3")
    assert [
        row["username"]
        for row in Accounts(
            replace(account_settings, data_root=data), store
        ).list_users()
    ] == ["alice"]
    assert [session.id for session in store.list_sessions()] == [sid]
    with sqlite3.connect(data / "analytics/workflows.sqlite3") as ledger:
        assert ledger.execute("SELECT id FROM workflows").fetchall() == [("kept",)]
    assert (data / "analytics/kept/revision-1/result.json").is_file()
    for name in ("graphmine-2", "graphmine-3"):
        (snapshot.parent / name).mkdir()
    rotate_snapshots(snapshot.parent, keep=2)
    assert sorted(p.name for p in snapshot.parent.iterdir()) == [
        "graphmine-2",
        "graphmine-3",
    ]


def test_quota_http_errors_do_not_invoke_model(account_settings):
    app = create_app(replace(account_settings, account_daily_tokens=100))
    transport = AsyncMock()

    @app.post("/api/test-model")
    async def test_model():
        await model_post(transport, "/chat/completions", json={"messages": []})

    # create_app installs its static catch-all last; put the test API ahead of it.
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        app.state.runtime.accounts.create_user("alice", PASSWORD)
        response = client.post("/api/test-model", headers=login(client))
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "daily_tokens_limit"
        details = response.json()["error"]["details"]
        assert details["remaining_tokens"] == 100
        assert details["required_tokens"] > 100
        assert details["count_method"] == "conservative_estimate"
        assert int(response.headers["Retry-After"]) > 0
        transport.post.assert_not_called()


def test_background_jobs_use_owner_and_results_stay_private(
    account_settings, triangle_graph, monkeypatch
):
    import time

    from graphmine_agent.identity import current_principal

    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        alice_id = runtime.accounts.create_user("alice", PASSWORD)["id"]
        runtime.accounts.create_user("bob", PASSWORD)
        alice, bob = login(client), login(client, "bob")
        session = client.post(
            "/api/sessions", json={"domain_id": "general"}, headers=alice
        ).json()["id"]
        graph = client.post(
            f"/api/sessions/{session}/files",
            files={"file": ("graph.json", triangle_graph)},
            headers=alice,
        ).json()["id"]
        owners = []

        async def interpret(result, plan):
            principal = current_principal.get()
            owners.append(principal.user_id)
            lease = principal.accounts.reserve_tokens(principal.user_id, 100)
            principal.accounts.settle_tokens(lease, 75)
            return result

        monkeypatch.setattr(runtime.jobs, "result_handler", interpret)
        response = client.post(
            "/api/jobs",
            headers=alice,
            json={
                "session_id": session,
                "graph_id": graph,
                "problem_id": "maximal_clique_enumeration",
                "operation_id": "maximal-cliques",
                "backend_id": "rdmce",
            },
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        for _ in range(150):
            job = client.get(f"/api/jobs/{job_id}", headers=alice).json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert job["status"] == "completed", job
        assert owners == [alice_id]
        assert (
            client.get("/api/auth/me", headers=alice).json()["quota"]["tokens_used"]
            == 75
        )
        assert client.get("/api/jobs", headers=bob).json() == []
        assert client.get(f"/api/jobs/{job_id}", headers=bob).status_code == 404
        assert client.delete(f"/api/jobs/{job_id}", headers=bob).status_code == 404
        for ending in ("", "/report", "/query"):
            assert (
                client.get(
                    f"/api/results/{job['result_id']}{ending}", headers=bob
                ).status_code
                == 404
            )
        assert (
            client.post(
                f"/api/results/{job['result_id']}/interpret",
                headers=bob,
                json={"message": "Explain"},
            ).status_code
            == 404
        )


@pytest.mark.asyncio
async def test_model_concurrency_and_job_timeout_release_capacity(account_settings):
    accounts, _ = store(replace(account_settings, account_job_seconds=1))
    one = accounts.reserve_tokens("alice", 100)
    two = accounts.reserve_tokens("bob", 100)
    with pytest.raises(AccountError) as failure:
        accounts.reserve_tokens("carol", 100)
    assert failure.value.code == "concurrency_limit"
    accounts.settle_tokens(one, 50)
    accounts.settle_tokens(two, 50)
    with pytest.raises(AccountError) as failure:
        async with accounts.execution_slot("alice"):
            await asyncio.sleep(2)
    assert failure.value.code == "job_time_limit"
    async with accounts.execution_slot("bob"):
        pass


@pytest.mark.asyncio
async def test_queue_wait_has_its_own_limit_and_unstarted_jobs_are_refunded(
    account_settings,
):
    accounts, _ = store(
        replace(
            account_settings,
            account_queue_seconds=1,
            account_job_seconds=1,
            account_running_jobs=1,
        )
    )
    busy = accounts.acquire("bob", "execution", 1)
    admission = accounts.admit_jobs("alice")
    assert accounts.usage("alice")["jobs_used"] == 1
    with pytest.raises(AccountError) as failure:
        async with accounts.execution_slot("alice", admission):
            pass
    assert failure.value.code == "queue_time_limit"
    assert accounts.usage("alice")["jobs_used"] == 0
    # Cancelling a job that is still waiting is refunded too.
    admission = accounts.admit_jobs("carol")

    async def wait():
        async with accounts.execution_slot("carol", admission):
            pass

    waiting = asyncio.create_task(wait())
    await asyncio.sleep(0.3)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert accounts.usage("carol")["jobs_used"] == 0
    # Waiting longer than the run limit does not use the run allowance.
    accounts = Accounts(
        replace(
            account_settings,
            account_queue_seconds=5,
            account_job_seconds=1,
            account_running_jobs=1,
        ),
        accounts.database,
    )
    admission = accounts.admit_jobs("dave")
    asyncio.get_running_loop().call_later(1.5, accounts.release, busy)
    async with accounts.execution_slot("dave", admission):
        pass
    assert accounts.usage("dave")["jobs_used"] == 1


@pytest.mark.asyncio
async def test_slots_are_taken_in_arrival_order_without_head_of_line_blocking(
    account_settings,
):
    accounts, _ = store(account_settings)
    order = []

    async def wait(user):
        lease = await accounts.wait_slot(user, "execution", 1, 1, 60, 10)
        order.append(user)
        return lease

    held = accounts.acquire("zoe", "execution", 1)
    waiters = {user: asyncio.create_task(wait(user)) for user in ("ann", "ben", "cy")}
    await asyncio.sleep(0.3)
    assert order == []
    for user in ("ann", "ben", "cy"):
        accounts.release(held)
        held = await asyncio.wait_for(waiters[user], 5)
    assert order == ["ann", "ben", "cy"]
    accounts.release(held)
    # An account at its own limit does not hold up someone queued behind it.
    mine = accounts.acquire("ann", "execution", 2)
    first = asyncio.create_task(accounts.wait_slot("ann", "execution", 2, 1, 60, 10))
    await asyncio.sleep(0.3)
    second = await asyncio.wait_for(
        accounts.wait_slot("ben", "execution", 2, 1, 60, 10), 5
    )
    assert not first.done()
    accounts.release(second)
    accounts.release(mine)
    accounts.release(await asyncio.wait_for(first, 5))
    busy = accounts.acquire("cy", "execution", 1)
    with pytest.raises(TimeoutError):
        await accounts.wait_slot("dee", "execution", 1, 1, 60, 0.5)
    accounts.release(busy)


def test_account_cli_prompts_for_password_and_uses_selected_store(
    account_settings, monkeypatch, capsys
):
    import argparse

    from graphmine_agent.accounts_cli import run_accounts

    monkeypatch.setattr(
        "graphmine_agent.accounts_cli.getpass.getpass", lambda _: PASSWORD
    )
    arguments = argparse.Namespace(
        data_root=account_settings.data_root, account_action="create", username="alice"
    )
    assert run_accounts(arguments, account_settings) == 0
    assert PASSWORD not in capsys.readouterr().out
    accounts, _ = store(account_settings)
    assert accounts.login("alice", PASSWORD, "test")[1].username == "alice"


def test_server_restart_releases_abandoned_jobs_without_resetting_usage(
    account_settings,
):
    app = create_app(account_settings)
    with TestClient(app) as client:
        accounts = app.state.runtime.accounts
        user = accounts.create_user("alice", PASSWORD)["id"]
        accounts.admit_jobs(user)
        assert accounts.usage(user)["jobs_used"] == 1
    with TestClient(create_app(account_settings)) as client:
        accounts = client.app.state.runtime.accounts
        assert accounts.usage(user)["jobs_used"] == 1
        new = accounts.admit_jobs(user)
        accounts.release(new)
        assert accounts.usage(user)["jobs_used"] == 2


def test_expert_workflow_consumes_jobs_without_model_tokens(
    account_settings, triangle_graph, monkeypatch
):
    import time

    from graphmine_agent.identity import current_principal

    with TestClient(
        create_app(replace(account_settings, account_daily_jobs=1))
    ) as client:
        runtime = client.app.state.runtime
        user = runtime.accounts.create_user("alice", PASSWORD)["id"]
        auth = login(client)
        sid = client.post("/api/sessions", headers=auth, json={}).json()["id"]
        fid = client.post(
            f"/api/sessions/{sid}/files",
            headers=auth,
            files={"file": ("graph.json", triangle_graph)},
        ).json()["id"]
        owners = []

        async def worker(request, **_kwargs):
            if request["command"] == "validate":
                return {
                    "workflow_hash": "a" * 64,
                    "plan": {
                        "device": "cpu",
                        "steps": [
                            {
                                "id": "answer",
                                "operation": "triangle-counting",
                                "device": "cpu",
                            }
                        ],
                    },
                }
            assert request["command"] == "run"
            owners.append(current_principal.get().user_id)
            return {
                "workflow_hash": "a" * 64,
                "status": "completed",
                "complete": True,
                "steps": {},
            }

        monkeypatch.setattr(runtime.analytics, "_call", worker)
        response = client.post(
            f"/api/sessions/{sid}/workflows",
            headers=auth,
            json={"mode": "expert", "plan": {}, "inputs": {"main": {"file_id": fid}}},
        )
        assert response.status_code == 201, response.text
        wid = response.json()["id"]
        approval = {"workflow_hash": "a" * 64, "expected_revision": 1}
        response = client.post(f"/api/workflows/{wid}/run", headers=auth, json=approval)
        assert response.status_code == 202, response.text
        for _ in range(150):
            result = client.get(f"/api/workflows/{wid}", headers=auth).json()
            if result["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert result["status"] == "completed", result
        assert owners == [user]
        assert runtime.accounts.usage(user)["tokens_used"] == 0
        assert runtime.accounts.usage(user)["jobs_used"] == 1
        response = client.post(f"/api/workflows/{wid}/run", headers=auth, json=approval)
        assert response.status_code == 429, response.text
        assert response.json()["error"]["code"] == "daily_jobs_limit"


def test_restart_does_not_resume_unadmitted_account_queue(account_settings):
    from graphmine_agent.models import ExecutionPlan, JobRecord

    accounts, db = store(account_settings)
    user = accounts.create_user("alice", PASSWORD)["id"]
    with identity_scope(Principal(user, "alice", accounts)):
        session = db.create_session(SessionRecord())
        accounts.admit_jobs(user)
        plan = ExecutionPlan(
            session_id=session.id,
            graph_id="unused",
            problem_id="maximal_clique_enumeration",
            operation_id="maximal-cliques",
            backend_id="rdmce",
        )
        job = db.save_job(JobRecord(session_id=session.id, plan=plan))
    with TestClient(create_app(account_settings)) as client:
        assert (
            client.app.state.runtime.database.get_job(job.id).error["code"]
            == "server_restarted"
        )
        assert client.app.state.runtime.accounts.usage(user)["jobs_used"] == 1


def test_graph_execution_timeout_is_visible_and_releases_capacity(
    account_settings, triangle_graph, monkeypatch
):
    import time

    with TestClient(
        create_app(replace(account_settings, account_job_seconds=1))
    ) as client:
        runtime = client.app.state.runtime
        user = runtime.accounts.create_user("alice", PASSWORD)["id"]
        auth = login(client)
        sid = client.post("/api/sessions", headers=auth, json={}).json()["id"]
        fid = client.post(
            f"/api/sessions/{sid}/files",
            headers=auth,
            files={"file": ("graph.json", triangle_graph)},
        ).json()["id"]
        stopped = []

        async def slow_execution(*_args):
            try:
                await asyncio.sleep(5)
            finally:
                stopped.append(True)

        monkeypatch.setattr(runtime.runner, "execute", slow_execution)
        response = client.post(
            "/api/jobs",
            headers=auth,
            json={
                "session_id": sid,
                "graph_id": fid,
                "problem_id": "maximal_clique_enumeration",
                "operation_id": "maximal-cliques",
                "backend_id": "rdmce",
            },
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        for _ in range(150):
            job = client.get(f"/api/jobs/{job_id}", headers=auth).json()
            if job["status"] == "failed":
                break
            time.sleep(0.02)
        assert job["status"] == "failed", job
        assert job["error"]["code"] == "job_time_limit"
        assert stopped == [True]
        admission = runtime.accounts.admit_jobs(user)
        runtime.accounts.release(admission)


def test_https_login_uses_secure_cookie(account_settings):
    with TestClient(
        create_app(replace(account_settings, account_cookie_secure=True)),
        base_url="https://testserver",
    ) as client:
        client.app.state.runtime.accounts.create_user("alice", PASSWORD)
        response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": PASSWORD},
            headers={"X-GraphMine-Request": "1"},
        )
        assert response.status_code == 200
        assert "; Secure" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").status_code == 200


def test_serve_passes_tls_and_warns_about_unencrypted_logins(
    account_settings, monkeypatch, tmp_path, capsys
):
    from graphmine_agent import cli

    with pytest.raises(ValueError, match="GRAPHMINE_TLS_KEYFILE"):
        replace(account_settings, tls_certfile=tmp_path / "graphmine.crt")
    launched = []
    monkeypatch.setattr(cli, "create_app", lambda settings: settings)
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app, **kwargs: launched.append(kwargs)
    )
    monkeypatch.setattr(
        cli.Settings, "from_env", lambda: replace(account_settings, api_host="0.0.0.0")
    )
    assert cli.main(["serve"]) == 0
    assert "travel unencrypted" in capsys.readouterr().err
    secure = replace(
        account_settings,
        api_host="0.0.0.0",
        account_cookie_secure=True,
        tls_certfile=tmp_path / "graphmine.crt",
        tls_keyfile=tmp_path / "graphmine.key",
    )
    monkeypatch.setattr(cli.Settings, "from_env", lambda: secure)
    assert cli.main(["serve"]) == 0
    assert "travel unencrypted" not in capsys.readouterr().err
    assert launched[-1]["ssl_certfile"] == tmp_path / "graphmine.crt"
    assert launched[-1]["ssl_keyfile"] == tmp_path / "graphmine.key"


def test_only_admin_can_manage_users_and_password_policy_is_preserved(account_settings):
    with TestClient(create_app(account_settings)) as client:
        accounts = client.app.state.runtime.accounts
        accounts.create_user("owner", PASSWORD, admin=True)
        accounts.create_user("alice", PASSWORD)
        admin, alice = login(client, "owner"), login(client)
        assert (
            client.get("/api/auth/me", headers=admin).json()["user"]["role"] == "admin"
        )
        endpoint = "/api/auth/admin/users"
        assert client.get(endpoint).status_code == 401
        assert client.get(endpoint, headers=alice).status_code == 403
        assert (
            client.post(
                endpoint, headers=alice, json={"username": "bob", "password": PASSWORD}
            ).status_code
            == 403
        )
        for operation in ("disable", "enable", "reset-password"):
            assert (
                client.post(
                    f"{endpoint}/owner/{operation}",
                    headers=alice,
                    json={"password": PASSWORD},
                ).status_code
                == 403
            )
        assert (
            client.post(
                endpoint,
                headers=admin,
                json={"username": "short", "password": "Eight!42"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                endpoint,
                headers=admin,
                json={"username": "another", "password": PASSWORD, "role": "admin"},
            ).status_code
            == 422
        )
        created = client.post(
            endpoint, headers=admin, json={"username": "bob", "password": PASSWORD}
        )
        assert created.status_code == 201, created.text
        assert created.json()["role"] == "user"
        rows = client.get(endpoint, headers=admin).json()
        assert {row["username"] for row in rows} == {"alice", "bob", "owner"}
        assert all("password_hash" not in row for row in rows)
        bob = login(client, "bob")
        assert (
            client.post(
                f"{endpoint}/bob/reset-password",
                headers=admin,
                json={"password": PASSWORD + "-new"},
            ).status_code
            == 204
        )
        assert client.get("/api/auth/me", headers=bob).status_code == 401
        bob = login(client, "bob", PASSWORD + "-new")
        assert client.post(f"{endpoint}/bob/disable", headers=admin).status_code == 204
        assert client.get("/api/auth/me", headers=bob).status_code == 401
        assert client.post(f"{endpoint}/bob/enable", headers=admin).status_code == 204
        bob = login(client, "bob", PASSWORD + "-new")
        assert client.get("/api/auth/me", headers=bob).status_code == 200
        assert (
            client.post(f"{endpoint}/owner/disable", headers=admin).status_code == 403
        )
        sid = client.post("/api/sessions", headers=alice, json={}).json()["id"]
        assert client.get(f"/api/sessions/{sid}", headers=admin).status_code == 404


def test_custom_token_limits_persist_and_are_enforced(account_settings):
    now = [1000000.0]
    settings = replace(
        account_settings, account_daily_tokens=1000, server_daily_tokens=5000
    )
    accounts, database = store(settings, now)
    alice = accounts.create_user("alice", PASSWORD, 600)["id"]
    bob = accounts.create_user("bob", PASSWORD)["id"]
    lease = accounts.reserve_tokens(alice, 500)
    accounts.settle_tokens(lease, 400)
    with pytest.raises(AccountError, match="allowance"):
        accounts.reserve_tokens(alice, 201)
    accounts.set_token_limit("alice", 300)
    assert accounts.usage(alice)["tokens_remaining"] == 0
    accounts.set_token_limit("alice", 900)
    assert accounts.usage(alice)["tokens_used"] == 400
    assert accounts.usage(bob)["token_limit"] == 1000
    restarted = Accounts(settings, Database(database.path), clock=lambda: now[0])
    assert restarted.usage(alice)["token_limit"] == 900
    now[0] += DAY
    assert restarted.usage(alice)["tokens_remaining"] == 900
    restarted.set_token_limit("alice", 0)
    with pytest.raises(AccountError):
        restarted.reserve_tokens(alice, 1)
    restarted.set_token_limit("alice", None)
    assert restarted.usage(alice)["token_limit"] == 1000


def test_manual_token_reset_keeps_server_jobs_schedule_and_inflight_accounting(
    account_settings,
):
    now = [1000000.0]
    accounts, _ = store(account_settings, now)
    user = accounts.create_user("alice", PASSWORD)["id"]
    accounts.release(accounts.admit_jobs(user))
    lease = accounts.reserve_tokens(user, 500)
    with pytest.raises(AccountError) as busy:
        accounts.reset_tokens("alice")
    assert busy.value.code == "tokens_in_use"
    before = accounts.usage(user)
    now[0] += 241
    reset = accounts.reset_tokens("alice")
    assert reset["tokens_used"] == 0
    assert reset["jobs_used"] == 1
    assert reset["resets_at"] == before["resets_at"]
    assert reset["server_tokens_remaining"] == before["server_tokens_remaining"]
    accounts.settle_tokens(lease, 200)
    after = accounts.usage(user)
    assert after["tokens_used"] == 0
    assert after["server_tokens_used"] == 200
    lease = accounts.reserve_tokens(user, 400)
    accounts.settle_tokens(lease, 300)
    accounts.reset_tokens("alice")
    assert accounts.usage(user)["server_tokens_used"] == 500


def test_admin_quota_api_and_validation(account_settings):
    with TestClient(create_app(account_settings)) as client:
        accounts = client.app.state.runtime.accounts
        accounts.create_user("owner", PASSWORD, admin=True)
        accounts.create_user("alice", PASSWORD)
        admin, alice = login(client, "owner"), login(client)
        base = "/api/auth/admin/users"
        response = client.post(
            base,
            headers=admin,
            json={
                "username": "bob",
                "password": PASSWORD,
                "daily_token_limit": 12345,
            },
        )
        assert response.status_code == 201, response.text
        bob = response.json()["id"]
        assert accounts.usage(bob)["token_limit"] == 12345
        accounts.settle_tokens(accounts.reserve_tokens(bob, 1000), 750)
        for operation, body in (
            ("token-limit", {"daily_token_limit": 20000}),
            ("reset-tokens", {}),
        ):
            assert (
                client.post(
                    f"{base}/bob/{operation}", headers=alice, json=body
                ).status_code
                == 403
            )
        for invalid in (
            -1,
            True,
            1.5,
            "1000",
            account_settings.server_daily_tokens + 1,
        ):
            assert client.post(
                f"{base}/bob/token-limit",
                headers=admin,
                json={"daily_token_limit": invalid},
            ).status_code in {400, 422}
        updated = client.post(
            f"{base}/bob/token-limit", headers=admin, json={"daily_token_limit": 30000}
        )
        assert updated.status_code == 200
        assert updated.json()["tokens_remaining"] == 29250
        reset = client.post(f"{base}/bob/reset-tokens", headers=admin)
        assert reset.status_code == 200
        assert reset.json()["tokens_used"] == 0
        assert reset.json()["server_tokens_used"] == 750
        rows = client.get(base, headers=admin).json()
        row = next(row for row in rows if row["username"] == "bob")
        assert row["quota"]["token_limit"] == 30000
        assert all("password_hash" not in row for row in rows)


def test_change_own_password_requires_current_password_and_revokes_logins(
    account_settings,
):
    with TestClient(create_app(account_settings)) as client:
        accounts = client.app.state.runtime.accounts
        user = accounts.create_user("alice", PASSWORD)["id"]
        first, second = login(client), login(client)
        accounts.settle_tokens(accounts.reserve_tokens(user, 500), 250)
        endpoint = "/api/auth/password"
        wrong = client.post(
            endpoint,
            headers=first,
            json={"current_password": "wrong", "password": PASSWORD + "-new"},
        )
        assert wrong.status_code == 400
        assert client.get("/api/auth/me", headers=first).status_code == 200
        assert (
            client.post(
                endpoint,
                headers=first,
                json={"current_password": PASSWORD, "password": "too-short"},
            ).status_code
            == 422
        )
        changed = client.post(
            endpoint,
            headers=first,
            json={"current_password": PASSWORD, "password": PASSWORD + "-new"},
        )
        assert changed.status_code == 204
        assert client.get("/api/auth/me", headers=first).status_code == 401
        assert client.get("/api/auth/me", headers=second).status_code == 401
        fresh = login(client, password=PASSWORD + "-new")
        assert (
            client.get("/api/auth/me", headers=fresh).json()["quota"]["tokens_used"]
            == 250
        )


@pytest.mark.asyncio
async def test_large_schema_uses_tokenizer_not_request_bytes(account_settings):
    accounts, _ = store(account_settings)
    accounts.settle_tokens(accounts.reserve_tokens("alice", 8000), 7814)
    payload = {
        "model": "graphmine-planner-v2",
        "messages": [
            {"role": "user", "content": "Find groups of closely related characters."}
        ],
        "max_completion_tokens": 3072,
        "reasoning_effort": "none",
        "response_format": {
            "type": "json_schema",
            "json_schema": {"schema": {"description": "schema metadata " * 8000}},
        },
    }
    paths = []

    def respond(request):
        paths.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path == "/tokenize":
            assert body["messages"] == payload["messages"]
            assert body["chat_template_kwargs"] == {
                "reasoning_effort": "none",
                "enable_thinking": False,
            }
            assert "response_format" not in body
            assert accounts.usage("alice")["tokens_used"] == 7814
            return httpx.Response(200, json={"count": 8192})
        assert body == payload
        assert accounts.usage("alice")["tokens_used"] == 7814 + 8192 + 3072
        return httpx.Response(
            200, json={"usage": {"prompt_tokens": 8192, "completion_tokens": 8}}
        )

    async with httpx.AsyncClient(
        base_url="http://model.test/v1", transport=httpx.MockTransport(respond)
    ) as client:
        with identity_scope(Principal("alice", "alice", accounts)):
            await model_post(client, "/chat/completions", json=payload)
    assert paths == ["/tokenize", "/v1/chat/completions"]
    assert accounts.usage("alice")["tokens_used"] == 16014


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["user", "server"])
async def test_exact_count_still_enforces_limits_and_explains_required_tokens(
    account_settings, scope
):
    settings = replace(
        account_settings,
        account_daily_tokens=1000 if scope == "user" else 5000,
        server_daily_tokens=1000,
    )
    accounts, database = store(settings)
    paths = []

    def respond(request):
        paths.append(request.url.path)
        assert request.url.path == "/tokenize"
        return httpx.Response(200, json={"count": 1200})

    async with httpx.AsyncClient(
        base_url="http://model.test/v1", transport=httpx.MockTransport(respond)
    ) as client:
        with (
            identity_scope(Principal("alice", "alice", accounts)),
            pytest.raises(AccountError) as failure,
        ):
            await model_post(
                client,
                "/chat/completions",
                json={"model": "test", "messages": [], "max_completion_tokens": 100},
            )
    assert paths == ["/tokenize"]
    assert "1,300" in str(failure.value) and "1,000" in str(failure.value)
    assert failure.value.details["required_tokens"] == 1300
    assert failure.value.details["remaining_tokens"] == 1000
    assert failure.value.details["scope"] == scope
    assert failure.value.details["count_method"] == "model_tokenizer"
    assert accounts.usage("alice")["tokens_used"] == 0
    with database._connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM account_leases WHERE kind='model'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tokenizer_reply", [None, {"count": True}, {"count": -1}, {"count": "10"}]
)
async def test_unsupported_or_invalid_tokenizer_keeps_conservative_reservation(
    account_settings, tokenizer_reply
):
    accounts, _ = store(account_settings)
    payload = {
        "model": "test",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 100,
    }
    fallback = len(json.dumps(payload, ensure_ascii=False).encode()) + 1024 + 100

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(
                200 if tokenizer_reply is not None else 404, json=tokenizer_reply
            )
        assert accounts.usage("alice")["tokens_used"] == fallback
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(
        base_url="http://model.test/v1", transport=httpx.MockTransport(respond)
    ) as client:
        with identity_scope(Principal("alice", "alice", accounts)):
            await model_post(client, "/chat/completions", json=payload)
    assert accounts.usage("alice")["tokens_used"] == fallback


@pytest.mark.asyncio
async def test_tokenizer_cancellation_releases_slot_without_charging(account_settings):
    accounts, database = store(account_settings)

    async def respond(request):
        assert request.url.path == "/prefix/tokenize"
        body = json.loads(request.content)
        assert body["chat_template_kwargs"] == {
            "reasoning_effort": "high",
            "enable_thinking": False,
        }
        raise asyncio.CancelledError

    async with httpx.AsyncClient(
        base_url="http://model.test/prefix/v1", transport=httpx.MockTransport(respond)
    ) as client:
        with (
            identity_scope(Principal("alice", "alice", accounts)),
            pytest.raises(asyncio.CancelledError),
        ):
            await model_post(
                client,
                "/chat/completions",
                json={
                    "model": "test",
                    "messages": [],
                    "reasoning_effort": "high",
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
    assert accounts.usage("alice")["tokens_used"] == 0
    with database._connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM account_leases WHERE kind='model'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_error", [True, False])
async def test_planning_history_keeps_quota_explanation_but_hides_internal_errors(
    account_settings, quota_error
):
    from graphmine_agent.analytics_planning import AnalyticsPlanner, PlanningRequest
    from graphmine_agent.jobs import EventBus

    database = Database(account_settings.database_path)
    session = database.create_session(SessionRecord(domain_id="general"))
    planner = AnalyticsPlanner(
        account_settings, SimpleNamespace(database=database), EventBus(database)
    )
    explanation = "This request needs 6,204 tokens, but only 1,000 remain."
    error = (
        AccountError(explanation, "daily_tokens_limit")
        if quota_error
        else RuntimeError("private internal path")
    )
    planner._plan = AsyncMock(side_effect=error)
    with pytest.raises(type(error)):
        await planner.plan(
            session.id,
            PlanningRequest(
                message="Find groups", inputs={"main": {"file_id": "placeholder"}}
            ),
        )
    saved = database.events(session.id)[-1].payload
    assert saved["status"] == "failed"
    assert saved["message"] == (
        explanation if quota_error else "Planning failed. Please try again."
    )
