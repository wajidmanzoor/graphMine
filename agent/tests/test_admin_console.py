"""Admin acceptance: real authorization, SQLite transactions and Studio files."""

import fcntl
import json
import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from graphmine_agent.api import create_app
from graphmine_agent.database import Database
from graphmine_agent.identity import AccountError, identity_scope
from graphmine_agent.models import ConversationEvent, SessionRecord
from test_accounts import PASSWORD, login


@pytest.fixture
def console(settings, tmp_path, monkeypatch):
    directory = tmp_path / "studio" / "auth"
    directory.mkdir(parents=True)
    (directory / "users.json").write_text(json.dumps({"version": 1, "users": {"studio-owner": {"role": "admin", "disabled": False}}}))
    monkeypatch.setenv("GRAPHMINE_STUDIO_AUTH_DIR", str(directory))
    with TestClient(create_app(replace(settings, accounts_enabled=True, account_cookie_secure=False))) as client:
        accounts = client.app.state.runtime.accounts
        accounts.create_user("owner", PASSWORD, admin=True)
        accounts.create_user("member", PASSWORD)
        admin = login(client, "owner")
        yield client, accounts, admin, directory


def test_every_admin_route_rejects_member_and_signed_out_before_validation(console):
    client, _, _, _ = console
    member = login(client, "member")
    routes = {path: value for path, value in client.app.openapi()["paths"].items() if path.startswith("/api/admin/")}
    assert len(routes) >= 15
    for template, methods in routes.items():
        path = template.replace("{username}", "member").replace("{grant_id}", "missing")
        for method in methods.keys() - {"parameters", "head", "options"}:
            for headers in ({}, member):
                response = client.request(method, path, headers=headers)
                assert response.status_code == 403, (method, path, response.text)
    assert client.get("/admin").status_code == 200


def test_user_lifecycle_roles_access_limits_and_secret_free_audit(console):
    client, accounts, admin, directory = console
    created = client.post("/api/admin/users", headers=admin, json={"username": "new-member", "studio_access": True})
    assert created.status_code == 201, created.text
    password = created.json()["temporary_password"]
    assert len(password) >= 12
    user = created.json()["user"]
    assert user["must_change_password"] and user["role"] == "user"
    assert json.loads((directory / "users.json").read_text())["users"]["new-member"]["graphmine"]["id"] == user["id"]
    headers = login(client, "new-member", password)
    denied = client.post("/api/sessions", headers=headers, json={"domain_id": "general"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "password_change_required"
    assert client.post("/api/auth/password", headers=headers, json={"current_password": password, "password": PASSWORD}).status_code == 204
    headers = login(client, "new-member")
    assert client.get("/api/auth/me", headers=headers).json()["user"]["must_change_password"] is False
    edited = client.patch("/api/admin/users/new-member", headers=admin, json={"role": "admin", "storage_limit": 1024, "daily_token_limit": 500})
    assert edited.status_code == 200, edited.text
    assert accounts.storage_usage(user["id"])["limit"] == 1024
    assert json.loads((directory / "users.json").read_text())["users"]["new-member"]["role"] == "admin"
    assert client.get("/api/auth/me", headers=headers).status_code == 401  # role change revokes sessions
    assert client.post("/api/admin/users/new-member/disable", headers=admin).status_code == 200
    assert json.loads((directory / "users.json").read_text())["users"]["new-member"]["disabled"]
    assert client.post("/api/admin/users/new-member/enable", headers=admin).status_code == 200
    changed = client.patch("/api/admin/users/new-member", headers=admin, json={"studio_access": False})
    assert changed.status_code == 200
    assert "new-member" not in json.loads((directory / "users.json").read_text())["users"]
    for path in ("/api/admin/users", "/api/admin/activity", "/api/admin/activity/export"):
        response = client.get(path, headers=admin)
        assert password not in response.text and "scrypt$" not in response.text
    with accounts.database._connect() as db:
        for row in db.execute('SELECT action,"before","after" FROM admin_activity'):
            assert isinstance(json.loads(row[1]), dict) and isinstance(json.loads(row[2]), dict)
        changes = [json.loads(row[0]) for row in db.execute("SELECT details_json FROM events WHERE type='admin_change'")]
        assert any(row["before"].get("role") == "user" and row["after"].get("role") == "admin" for row in changes)


def test_last_active_admin_is_protected_in_core_and_api(console):
    client, accounts, admin, _ = console
    for method, path, body in (
        ("PATCH", "/api/admin/users/owner", {"role": "user"}),
        ("PATCH", "/api/admin/users/owner", {"graphmine_access": False}),
        ("POST", "/api/admin/users/owner/disable", {}),
        ("DELETE", "/api/admin/users/owner", {"data": "erase", "confirm": True, "confirm_username": "owner"}),
    ):
        response = client.request(method, path, json=body, headers=admin)
        assert response.status_code == 409 and response.json()["error"]["code"] == "last_admin", response.text
    with pytest.raises(AccountError, match="at least one"):
        accounts.disable("owner")
    accounts.create_user("disabled-admin", PASSWORD, admin=True)
    accounts.disable("disabled-admin")
    with pytest.raises(AccountError, match="at least one"):
        accounts.update_user("owner", {"role": "user"})


def test_force_signout_and_password_reset_revoke_existing_credentials(console):
    client, accounts, admin, _ = console
    first, second = login(client, "member"), login(client, "member")
    result = client.post("/api/admin/users/member/force-signout", headers=admin)
    assert result.status_code == 200 and result.json()["sessions_removed"] == 2
    assert client.get("/api/auth/me", headers=first).status_code == 401
    assert client.get("/api/auth/me", headers=second).status_code == 401
    member = login(client, "member")
    result = client.post("/api/admin/users/member/reset-password", headers=admin, json={})
    assert result.status_code == 200 and result.json()["temporary_password"]
    assert client.get("/api/auth/me", headers=member).status_code == 401
    assert accounts.user("member")["must_change_password"]


def test_support_is_read_only_session_bound_expiring_and_visible_to_owner(console):
    client, accounts, admin, _ = console
    member = login(client, "member")
    session = client.post("/api/sessions", headers=member, json={"domain_id": "general", "title": "Private conversation"}).json()
    sid = session["id"]
    accounts.database.add_event(ConversationEvent(session_id=sid, type="workflow.chat", payload={"role": "user", "turn_id": "private-turn", "message": "private question text"}))
    accounts.database.add_event(ConversationEvent(session_id=sid, type="workflow.chat", payload={"role": "assistant", "turn_id": "private-turn", "message": "private answer"}))
    assert client.get(f"/api/sessions/{sid}", headers=admin).status_code == 404
    assert "private question text" not in client.get("/api/admin/activity", headers=admin).text
    missing = client.post("/api/admin/support-access", headers=admin, json={"conversation_id": sid, "reason": " ", "duration": "hour"})
    assert missing.status_code == 422
    grant = client.post("/api/admin/support-access", headers=admin, json={"conversation_id": sid, "reason": "Troubleshoot a missing answer", "duration": "hour"})
    assert grant.status_code == 201, grant.text
    gid = grant.json()["id"]
    path = f"/api/admin/support-access/{gid}/conversation"
    result = client.get(path, headers=admin)
    assert result.status_code == 200 and result.json()["read_only"]
    assert "private question text" in result.text
    assert client.post(path, headers=admin, json={}).status_code == 405
    another_session = login(client, "owner")
    assert client.get(path, headers=another_session).status_code == 403
    history = client.get("/api/auth/history", headers=member).json()["support_access"]
    assert history[0]["reason"] == "Troubleshoot a missing answer"
    accounts.clock = lambda: grant.json()["expires_at"] + 1
    assert client.get(path, headers=admin).status_code == 403


@pytest.mark.parametrize("mode", ["transfer", "erase"])
def test_delete_user_moves_or_erases_real_owned_data(console, triangle_graph, mode):
    client, accounts, admin, directory = console
    member = login(client, "member")
    runtime = client.app.state.runtime
    sid = client.post("/api/sessions", headers=member, json={"domain_id": "general"}).json()["id"]
    upload = client.post(f"/api/sessions/{sid}/files", headers=member, files={"file": ("graph.json", triangle_graph, "application/json")})
    assert upload.status_code == 201
    runtime.analytics._save({"id": "saved-test", "session_id": sid, "status": "completed", "revision": 1})
    artifact = runtime.analytics.root / "saved-test" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"result":true}')
    preview = client.get("/api/admin/users/member/delete-preview", headers=admin).json()
    assert preview["conversations"] == preview["uploaded_files"] == preview["saved_analyses"] == 1
    refused = client.request("DELETE", "/api/admin/users/member", headers=admin, json={"data": mode, "confirm": False, "confirm_username": "member"})
    assert refused.status_code == 422
    result = client.request("DELETE", "/api/admin/users/member", headers=admin, json={"data": mode, "confirm": True, "confirm_username": "member"})
    assert result.status_code == 200, result.text
    assert client.get("/api/auth/me", headers=member).status_code == 401
    assert client.get(f"/api/sessions/{sid}", headers=admin).status_code == (200 if mode == "transfer" else 404)
    assert artifact.exists() == (mode == "transfer")
    assert "member" not in json.loads((directory / "users.json").read_text())["users"]
    with accounts.database._connect() as db:
        assert not db.execute("SELECT 1 FROM accounts WHERE username='member'").fetchone()


def test_studio_locked_or_missing_still_commits_graphmine_and_can_retry(console):
    client, accounts, admin, directory = console
    with (directory / "users.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = client.post("/api/admin/users", headers=admin, json={"username": "retry-user", "studio_access": True})
        assert response.status_code == 201 and not response.json()["studio"]["ok"]
    assert accounts.user("retry-user")["studio_sync_error"]
    response = client.post("/api/admin/users/retry-user/studio-sync", headers=admin)
    assert response.status_code == 200 and response.json()["studio"]["ok"]
    (directory / "users.json").unlink()
    response = client.post("/api/admin/users/retry-user/disable", headers=admin)
    assert response.status_code == 200 and "Studio not updated" in response.text
    assert accounts.user("retry-user")["disabled"]


def test_deleted_account_studio_retry_survives_account_removal(console):
    client, accounts, admin, directory = console
    created = client.post("/api/admin/users", headers=admin, json={"username": "remove-later", "studio_access": True}).json()
    uid = created["user"]["id"]
    with (directory / "users.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = client.request("DELETE", "/api/admin/users/remove-later", headers=admin,
                                json={"data": "transfer", "confirm": True, "confirm_username": "remove-later"})
    assert result.status_code == 200 and not result.json()["studio"]["ok"]
    pending = client.get("/api/admin/users", headers=admin).json()["studio_pending"]
    assert any(row["id"] == uid for row in pending)
    retried = client.post(f"/api/admin/studio-sync/{uid}/retry", headers=admin)
    assert retried.status_code == 200 and retried.json()["studio"]["ok"]
    assert "remove-later" not in json.loads((directory / "users.json").read_text())["users"]


def test_concurrent_demotions_cannot_remove_last_admin(console):
    from concurrent.futures import ThreadPoolExecutor
    _, accounts, _, _ = console
    for username in ("admin-two", "admin-three"):
        accounts.create_user(username, PASSWORD, admin=True)

    def demote(username):
        try:
            accounts.update_user(username, {"role": "user"})
            return "changed"
        except AccountError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(demote, ("owner", "admin-two", "admin-three")))
    assert outcomes.count("changed") == 2 and outcomes.count("last_admin") == 1


def test_saving_own_limits_keeps_session_when_identity_does_not_change(console):
    client, _, admin, _ = console
    response = client.patch("/api/admin/users/owner", headers=admin,
                            json={"username": "owner", "role": "admin", "graphmine_access": True, "daily_token_limit": 1000})
    assert response.status_code == 200
    assert client.get("/api/admin/users", headers=admin).status_code == 200


def test_events_have_documented_fields_and_never_contain_credentials(console):
    client, accounts, admin, _ = console
    member = login(client, "member")
    client.post("/api/auth/login", headers={"X-GraphMine-Request": "1"}, json={"username": "member", "password": "incorrect-password"})
    client.patch("/api/admin/users/member", headers=admin, json={"storage_limit": -10})
    sid = client.post("/api/sessions", headers=member, json={"domain_id": "general"}).json()["id"]
    accounts.database.add_event(ConversationEvent(session_id=sid, type="workflow.chat", payload={"role": "assistant", "turn_id": "question", "message": "private"}))
    accounts.database.add_event(ConversationEvent(session_id=sid, type="workflow.finished", payload={"workflow_id": "test", "status": "failed", "error_code": "queue_full"}))
    client.post("/api/admin/support-access", headers=admin, json={"conversation_id": sid, "reason": "Help", "duration": "session"})
    with accounts.database._connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM events")]
    assert {row["type"] for row in rows} == {"question", "calculation", "sign_in", "error", "admin_change", "support_access"}
    for row in rows:
        assert set(row) == {"id", "ts", "user_id", "type", "summary", "outcome", "duration_ms", "details_json", "request_id"}
        assert row["request_id"] and row["ts"] and isinstance(json.loads(row["details_json"]), dict)
    assert PASSWORD not in json.dumps(rows) and "incorrect-password" not in json.dumps(rows)


def test_private_event_migration_preserves_sequence_and_conversation_timeline(settings):
    database = Database(settings.database_path)
    session = database.create_session(SessionRecord(domain_id="general"))
    original = database.add_event(ConversationEvent(session_id=session.id, type="workflow.chat", payload={"role": "user", "turn_id": "legacy-turn", "message": "Preserve this private message"}))
    with database._connect() as db:
        db.execute("DROP TABLE events")
        db.execute("ALTER TABLE conversation_events RENAME TO events")
        db.execute("PRAGMA user_version=11")
    migrated = Database(settings.database_path)
    with migrated._connect() as db:
        assert "session_id" in {row[1] for row in db.execute("PRAGMA table_info(conversation_events)")}
        assert "details_json" in {row[1] for row in db.execute("PRAGMA table_info(events)")}
        assert db.execute("PRAGMA user_version").fetchone()[0] == 12
    events = migrated.events(session.id)
    assert events[0].sequence == original.sequence
    assert events[0].payload["message"] == "Preserve this private message"
    assert any(row["message"] == "Preserve this private message" for row in migrated.conversation_transcript(session.id))


def test_admin_routes_are_not_available_in_legacy_token_mode(settings):
    with TestClient(create_app(replace(settings, accounts_enabled=False, api_token="legacy-secret"))) as client:
        for path in ("/api/admin/users", "/api/admin/llm/power", "/api/admin/activity"):
            assert client.get(path, headers={"Authorization": "Bearer legacy-secret"}).status_code == 403


def test_browser_admin_mutations_still_require_csrf_header(console):
    client, _, _, _ = console
    response = client.post("/api/auth/login", headers={"X-GraphMine-Request": "1"}, json={"username": "owner", "password": PASSWORD})
    assert response.status_code == 200
    denied = client.post("/api/admin/users", json={"username": "csrf-user"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "csrf_required"
    allowed = client.post("/api/admin/users", headers={"X-GraphMine-Request": "1"}, json={"username": "csrf-user"})
    assert allowed.status_code == 201


def test_all_account_mutations_write_before_and_after(console):
    client, accounts, admin, _ = console
    actions = [
        ("POST", "/api/admin/users", {"username": "audit-user", "password": PASSWORD, "must_change_password": False}, "account.created"),
        ("PATCH", "/api/admin/users/audit-user", {"daily_token_limit": 750}, "account.updated"),
        ("POST", "/api/admin/users/audit-user/reset-password", {}, "password.reset"),
        ("POST", "/api/admin/users/audit-user/reset-tokens", {}, "tokens.reset"),
        ("POST", "/api/admin/users/audit-user/force-signout", {}, "account.signed_out"),
        ("POST", "/api/admin/users/audit-user/disable", {}, "account.disabled"),
        ("POST", "/api/admin/users/audit-user/enable", {}, "account.enabled"),
        ("POST", "/api/admin/users/audit-user/studio-sync", {}, "studio.synced"),
        ("DELETE", "/api/admin/users/audit-user", {"data": "transfer", "confirm": True, "confirm_username": "audit-user"}, "account.deleted"),
    ]
    for method, path, body, expected in actions:
        with accounts.database._connect() as db:
            before_id = db.execute("SELECT coalesce(max(sequence),0) FROM admin_activity").fetchone()[0]
        result = client.request(method, path, headers=admin, json=body)
        assert result.status_code in {200, 201}, result.text
        with accounts.database._connect() as db:
            row = db.execute('SELECT * FROM admin_activity WHERE sequence>? AND action=?', (before_id, expected)).fetchone()
        assert row is not None, (method, path, expected)
        assert row["actor"] == "owner" and row["at"] and row["target"] == "audit-user"
        assert isinstance(json.loads(row["before"]), dict) and isinstance(json.loads(row["after"]), dict)
