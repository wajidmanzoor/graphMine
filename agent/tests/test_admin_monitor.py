"""Admin monitoring acceptance: bounded failures and real API work."""

import asyncio
import json
import time
from dataclasses import replace

import pytest

from graphmine_agent import admin_events, admin_settings
from graphmine_agent.admin_selftest import internal_user
from graphmine_agent.identity import AccountError
from test_admin_console import console
from test_accounts import PASSWORD


def test_private_certificate_health_keeps_tls_verification(console, tmp_path, monkeypatch):
    import httpx
    import ssl
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from graphmine_agent.admin_monitor import Monitor

    client, _, _, _ = console
    cert, key = tmp_path / "local.pem", tmp_path / "local.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"https://127.0.0.1:{server.server_port}/"
    monkeypatch.setenv("GRAPHMINE_STUDIO_HEALTH_URL", url)
    runtime = client.app.state.runtime
    runtime.settings = replace(runtime.settings, tls_certfile=cert, tls_keyfile=key)
    async def probe():
        monitor = Monitor(runtime)
        try:
            result = await monitor.studio()
            assert result["status"] == "healthy" and result["http_status"] == 200
            async with httpx.AsyncClient(trust_env=False) as untrusted:
                with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                    await untrusted.get(url)
        finally:
            await monitor.close()
    try:
        client.portal.call(probe)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_overview_reads_measured_events_and_reports_missing_usage(console):
    client, accounts, admin, _ = console
    user = accounts.user("member")
    for duration in (100, 300):
        admin_events.record(accounts.database, "question", "Question completed", user_id=user["id"], duration_ms=duration, details={"tokens": 40})
    admin_events.record(accounts.database, "error", "Queue full", outcome="queue_full", details={"code": "queue_full"})
    response = client.get("/api/admin/overview", headers=admin)
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["questions_today"], data["answer_median_ms"], data["answer_p95_ms"]) == (2, 200, 290)
    assert data["tokens_today"] == 80 and data["top_error"] == "queue_full"
    assert len(data["questions_per_day"]) == 14
    assert data["accounts"] == 2
    admin_events.record(accounts.database, "question", "Legacy question")
    assert client.get("/api/admin/overview", headers=admin).json()["tokens_today"] is None
    assert "questions_today,3" in client.get("/api/admin/overview/export", headers=admin).text


def test_health_hanging_services_timeout_in_parallel_and_cache(console, monkeypatch):
    client, _, admin, _ = console
    monitor = client.app.state.admin_monitor
    monitor.timeout = .04
    calls = []

    async def hang(*args):
        calls.append(1)
        await asyncio.sleep(100)

    for name in ("agent", "vllm", "gpus", "disk", "databases", "studio", "http_check", "tcp"):
        monkeypatch.setattr(monitor, name, hang)
    start = time.monotonic()
    response = client.get("/api/admin/health", headers=admin)
    assert response.status_code == 200, response.text
    assert time.monotonic() - start < 1
    data = response.json()
    assert data["attention"] >= 8
    assert all("timed out" in c["reason"] for c in data["checks"] if c["status"] == "critical")
    count = len(calls)
    assert client.get("/api/admin/health", headers=admin).json() == data
    assert len(calls) == count
    client.get("/api/admin/health?refresh=true", headers=admin)
    assert len(calls) > count
    assert client.get("/api/admin/badges", headers=admin).json()["health"] >= 8


def test_incidents_warning_delay_recovery_and_restart_persistence(console):
    client, _, _, _ = console
    monitor = client.app.state.admin_monitor
    now = [1000]
    monitor.clock = lambda: now[0]
    check = {"id": "disk", "name": "Disk", "status": "warning", "reason": "Over 80%"}
    monitor.persist([check])
    assert monitor.incidents() == []
    now[0] += 899
    monitor.persist([check])
    assert monitor.incidents() == []
    now[0] += 1
    monitor.persist([check])
    assert len(monitor.incidents()) == 1
    now[0] += 1
    monitor.persist([{**check, "status": "critical"}])
    assert len(monitor.incidents()) == 1
    monitor.persist([{**check, "status": "unavailable"}])
    assert monitor.incidents()[0]["closed_at"] is None
    monitor.persist([{**check, "status": "healthy"}])
    assert monitor.incidents()[0]["closed_at"] == now[0]
    monitor.persist([{**check, "status": "critical"}])
    assert len(monitor.incidents()) == 2


@pytest.mark.parametrize("values", [
    {"GRAPHMINE_LLM_IDLE_SLEEP_MINUTES": 11}, {"GRAPHMINE_LLM_IDLE_SLEEP_MINUTES": True},
    {"GRAPHMINE_LLM_SLEEP_MODE": "false"}, {"GRAPHMINE_LLM_THINKING_STAGES": ["route", "route"]},
    {"GRAPHMINE_LLM_THINKING_STAGES": ["unknown"]}, {"GRAPHMINE_LLM_API_KEY": "secret"},
])
def test_model_settings_reject_invalid_values(console, values):
    client, _, admin, _ = console
    response = client.patch("/api/admin/model/settings", json={"values": values}, headers=admin)
    assert response.status_code == 422, response.text


def test_model_settings_apply_live_persist_and_audit(console):
    client, accounts, admin, _ = console
    values = {"GRAPHMINE_LLM_SLEEP_MODE": True, "GRAPHMINE_LLM_IDLE_SLEEP_MINUTES": 60, "GRAPHMINE_LLM_THINKING_STAGES": ["family", "analyst"]}
    response = client.patch("/api/admin/model/settings", json={"values": values}, headers=admin)
    assert response.status_code == 200, response.text
    runtime = client.app.state.runtime
    assert runtime.settings.llm_idle_sleep_minutes == 60
    assert accounts.settings.llm_thinking_stages == ("family", "analyst")
    assert runtime.settings.llm_sleep_mode is False  # pending model restart
    assert response.json()["restart_required"] == ["GRAPHMINE_LLM_SLEEP_MODE"]
    loaded = admin_settings.load(runtime.settings, accounts.database)
    assert loaded.llm_sleep_mode is True
    with accounts.database._connect() as db:
        row = db.execute('SELECT "before","after",actor FROM admin_activity WHERE action=\'settings.updated\'').fetchone()
    assert json.loads(row[1])["GRAPHMINE_LLM_SLEEP_MODE"] is True and row[2] == "owner"
    payload = {"reasoning_effort": "medium", "thinking_token_budget": 384}
    admin_settings.thinking(loaded, "route", payload)
    assert payload["chat_template_kwargs"]["enable_thinking"] is False
    assert "thinking_token_budget" not in payload
    untouched = {"reasoning_effort": "medium"}
    admin_settings.thinking(loaded, "family", untouched)
    assert untouched == {"reasoning_effort": "medium"}
    assert client.get("/api/admin/model", headers=admin).status_code == 200


def test_disabled_selftest_identity_cannot_login_or_use_its_token_externally(console):
    client, accounts, _, _ = console
    user = accounts.create_user("selftest", PASSWORD, login_disabled=True)
    with pytest.raises(AccountError):
        accounts.login("selftest", PASSWORD, "127.0.0.1")
    ctx = internal_user.set(user["id"])
    try:
        token, _ = accounts.login("selftest", PASSWORD, "internal")
        assert accounts.authenticate(token)
    finally:
        internal_user.reset(ctx)
    assert accounts.authenticate(token) is None
    response = client.post("/api/auth/login", json={"username": "selftest", "password": PASSWORD}, headers={"X-GraphMine-Request": "1", "X-GraphMine-Selftest": "1"})
    assert response.status_code == 401


def test_selftest_real_signin_calculation_and_result_with_question_provider_double(console, monkeypatch):
    client, accounts, admin, _ = console
    from graphmine_agent.analytics_planning import AnalyticsPlanner
    from graphmine_agent.identity import current_principal
    question_calls = []

    async def question(self, session, body):
        assert current_principal.get().username == "selftest"
        question_calls.append(body.message)
        return {"status": "answered", "message": "Provider response fixture"}

    monkeypatch.setattr(AnalyticsPlanner, "plan", question)
    response = client.post("/api/admin/health/selftest", headers=admin)
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = client.get("/api/admin/health/selftest", headers=admin).json()["result"]
        if result["status"] != "running":
            break
        time.sleep(.1)
    assert result["status"] == "passed", result
    assert [s["status"] for s in result["steps"]] == ["passed"] * 4
    assert question_calls == ["What is a k-core?"]
    from graphmine_agent.admin_summary import overview
    summary = overview(client.app.state.runtime)
    assert summary["saved_analyses"] == 1 and summary["problems"] == [{"problem": "k-core", "count": 1}]
    with accounts.database._connect() as db:
        user = db.execute("SELECT id,login_disabled FROM accounts WHERE username='selftest'").fetchone()
        assert user["login_disabled"] == 1
        assert db.execute("SELECT count(*) FROM account_sessions WHERE user_id=?", (user["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM admin_activity WHERE action LIKE 'selftest.%'").fetchone()[0] == 2


def test_restart_needs_confirmation_and_only_targets_matching_unit(console, monkeypatch):
    client, accounts, admin, _ = console
    monitor = client.app.state.admin_monitor
    commands = []
    async def unit(service):
        return {"unit": "isolated-test.service", "active": "active", "pid": 123}
    async def command(*args, **kwargs):
        commands.append(args)
        return ""
    monkeypatch.setattr(monitor, "unit", unit)
    monkeypatch.setattr("graphmine_agent.admin_monitor.command", command)
    assert client.post("/api/admin/services/model/restart", headers=admin, json={"confirm": False}).status_code == 422
    assert commands == []
    assert client.post("/api/admin/services/model/restart", headers=admin, json={"confirm": True}).status_code == 202
    assert commands == [("systemctl", "--user", "restart", "--no-block", "isolated-test.service")]
    with accounts.database._connect() as db:
        assert db.execute("SELECT count(*) FROM admin_activity WHERE action LIKE 'service.restart_%'").fetchone()[0] == 2


def test_queue_totals_use_execution_slots_and_measure_oldest_wait(console):
    client, accounts, _, _ = console
    from graphmine_agent.admin_summary import queues
    async def scenario():
        member, owner = accounts.user("member"), accounts.user("owner")
        active = accounts.acquire(owner["id"], "execution", 1)
        waiting = asyncio.create_task(accounts.wait_slot(member["id"], "execution", 1, 1, 60, 2))
        await asyncio.sleep(.03)
        snapshot = queues(client.app.state.runtime)["job"]
        assert snapshot["running"] == 1 and snapshot["waiting"] == 1
        assert snapshot["oldest_wait_seconds"] > 0
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        accounts.release(active)
        assert not accounts.wait_started
    client.portal.call(scenario)


def test_log_view_only_extracts_problemal_fields():
    from graphmine_agent.admin_monitor import redacted_log
    raw = '2026-11-19T12:00:00+00:00 agent: INFO: "GET /api/health?token=private HTTP/1.1" 200 OK\nprivate question words\npassword=hunter-test\n2026-11-19T12:00:01+00:00 agent: Application startup complete.'
    result = redacted_log(raw)
    assert 'GET /api/health 200' in result
    assert 'Application startup complete' in result
    assert all(secret not in result for secret in ('token=', 'hunter-test', 'private question words'))
