"""Phase 3: real authorization, private keys, durable policy and bounded workers."""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from graphmine_agent import admin_settings, semantic_providers
from graphmine_agent.database import Database
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.identity import AccountError, identity_scope
from graphmine_agent.semantic_policy import execution_policy, slot
from test_admin_console import console  # noqa: F401
from test_database_workspace import source, workspace  # noqa: F401
from test_semantic_native import native_engine  # noqa: F401
from test_accounts import PASSWORD, login

ROOT = "/api/admin/semantic"
PREFIX = "GRAPHMINE_SEMANTIC_"


def save(console, **changes):
    client, _, headers, _ = console
    before = client.get(ROOT, headers=headers).json()["values"]
    return client.patch(ROOT + "/settings", headers=headers, json={"values": {PREFIX + k: v for k, v in changes.items()}, "expected": before, "confirm": True})


def provider(console, **fields):
    client, _, headers, _ = console
    response = client.post(ROOT + "/providers", headers=headers,
                           json={"name": "Fixture provider", "base_url": "http://127.0.0.1:12345/v1", **fields})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def model_catalog():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        mode = "ok"
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            if self.mode == "redirect":
                self.send_response(302); self.send_header("Location", "/would-leak-key"); self.end_headers(); return
            self.send_response(401 if self.mode == "auth" else 200)
            self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "fixture-model"}]} if self.mode == "ok" else {"error": "synthetic-private-response"}).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls, Handler
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_defaults_builtin_provider_policy_and_live_cache_gates(console):
    client, accounts, admin, _ = console
    response = client.get(ROOT, headers=admin)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
    data = response.json()
    assert data["providers"][0]["id"] == "graphmine"
    assert data["aliases"][0]["model_id"] == client.app.state.runtime.settings.llm_model
    assert data["values"][PREFIX + "ACCESS"] == "admins"
    assert data["requirements"] == {"thinking": "off", "strict_json": True, "temperature": 0}
    assert data["capabilities"]["live"] == data["engine"]["installed"]
    assert data["capabilities"]["cache"] == data["engine"]["installed"]
    assert data["values"][PREFIX + "MODE"] == "mock"
    for change in ({"MODE": "live"}, {"CACHE_ENABLED": True}):
        result = save(console, **change)
        assert result.status_code == 200, result.text
    assert client.post(ROOT + "/cache/clear", headers=admin, json={"confirm": False}).status_code == 422
    assert client.post(ROOT + "/cache/clear", headers=admin, json={"confirm": True}).json() == {"cleared_answers": 0}


def test_settings_persist_apply_and_warn_without_changing_vllm(console):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    before = client.get(ROOT, headers=admin).json()["values"]
    result = save(console, MAX_CONCURRENT_REQUESTS=2, BATCH_SIZE=3, DEFAULT_CALL_LIMIT=2, MAX_CALLS=5, TIMEOUT_SECONDS=15, CACHE_MAX_AGE_DAYS=7)
    assert result.status_code == 200, result.text
    assert result.json()["concurrency"]["warning"]
    assert runtime.settings.llm_max_num_seqs == 2 and runtime.settings.max_model_calls == 2
    assert runtime.settings.semantic_batch_size == runtime.accounts.settings.semantic_batch_size == 3
    loaded = admin_settings.load(replace(runtime.settings, semantic_batch_size=16), Database(runtime.database.path))
    assert loaded.semantic_batch_size == 3 and loaded.semantic_cache_max_age_days == 7
    stale = client.patch(ROOT + "/settings", headers=admin, json={"values": {PREFIX + "BATCH_SIZE": 4}, "expected": before, "confirm": True})
    assert stale.status_code == 409
    for changes in ({"MAX_CALLS": 1}, {"BATCH_SIZE": 0}, {"MAX_CONCURRENT_REQUESTS": True}, {"ACCOUNTS": ["missing-user"]}):
        assert save(console, **changes).status_code == 422
    with runtime.database._connect() as db:
        row = db.execute('SELECT "after" FROM admin_activity WHERE action=\'settings.updated\' AND target=\'semantic\'').fetchone()
    assert json.loads(row[0])[PREFIX + "BATCH_SIZE"] == 3


def test_account_access_and_disabled_mode_are_enforced_for_execution(console):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    principal = accounts.authenticate(login(client, "member")["Authorization"].removeprefix("Bearer "))
    body = {"model": "mock", "statement": "RETURN llm('mock','{answer STRING}')", "call_limit": 99}
    with identity_scope(principal):
        with pytest.raises(AccountError) as error:
            execution_policy(runtime, body)
        assert error.value.code == "semantic_access"
        assert execution_policy(runtime, {**body, "statement": "RETURN 1"})["call_limit"] == 99
    assert save(console, ACCESS="selected", ACCOUNTS=[principal.user_id], DEFAULT_CALL_LIMIT=2, MAX_CALLS=3).status_code == 200
    with identity_scope(principal):
        assert execution_policy(runtime, body)["call_limit"] == 3
        assert execution_policy(runtime, {**body, "call_limit": None})["call_limit"] == 2
    assert save(console, MODE="disabled").status_code == 200
    with identity_scope(principal):
        with pytest.raises(AnalyticsError, match="disabled"):
            execution_policy(runtime, body)
        assert execution_policy(runtime, {**body, "statement": "RETURN 1"})
    assert save(console, MODE="mock", ACCESS="admins").status_code == 200
    with identity_scope(principal):
        with pytest.raises(AccountError):
            execution_policy(runtime, body)


@pytest.mark.parametrize("body", [
    {"name": "p", "base_url": "https://user:synthetic-secret@host/v1", "api_key": "synthetic-secret"},
    {"name": "p", "base_url": "https://host/v1?key=synthetic-secret", "api_key": "synthetic-secret"},
    {"name": "p", "base_url": "file:///tmp/secret", "api_key": "synthetic-secret"},
    {"name": "p", "base_url": "https://host/v1", "api_key": {"nested": "synthetic-secret"}},
    {"name": "p", "base_url": "https://host/v1", "api_key": "synthetic-secret\nInjected: yes"},
    ["synthetic-secret"],
])
def test_invalid_provider_requests_never_echo_credentials(console, body):
    client, _, admin, _ = console
    response = client.post(ROOT + "/providers", headers=admin, json=body)
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text


def test_keys_are_private_rotatable_and_absent_from_metadata_audit_and_tests(console, model_catalog):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    url, calls, handler = model_catalog
    saved = provider(console, base_url=url, api_key="synthetic-key-one")
    assert saved["key_configured"] and "api_key" not in saved and "secret_ref" not in saved
    alias = client.put(ROOT + "/aliases", headers=admin, json={"alias": "fixture", "provider_id": saved["id"], "model_id": "fixture-model"}).json()
    tested = client.post(ROOT + "/providers/" + saved["id"] + "/test", headers=admin)
    assert tested.status_code == 200 and tested.json()["connected"]
    assert tested.json()["models"] == [{"alias": "fixture", "available": True}]
    assert calls[-1] == ("/v1/models", "Bearer synthetic-key-one")
    assert tested.json()["live_execution_verified"] is False
    directory = runtime.settings.data_root / "semantic-credentials"
    assert directory.stat().st_mode & 0o777 == 0o700
    files = list(directory.iterdir())
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    assert files[0].read_text() == "synthetic-key-one"
    updated = client.put(ROOT + "/providers/" + saved["id"], headers=admin,
        json={"name": "Renamed", "base_url": url, "expected_revision": saved["revision"], "api_key": "synthetic-key-two"})
    assert updated.status_code == 200, updated.text
    assert not files[0].exists() and len(list(directory.iterdir())) == 1
    client.post(ROOT + "/providers/" + saved["id"] + "/test", headers=admin)
    assert calls[-1][1] == "Bearer synthetic-key-two"
    restored = SimpleNamespace(settings=runtime.settings, database=Database(runtime.database.path))
    assert semantic_providers.catalog(restored)["providers"][1]["key_configured"]
    for path in (ROOT, "/api/admin/activity", "/api/admin/activity/export"):
        text = client.get(path, headers=admin).text
        assert "synthetic-key-" not in text and "secret_ref" not in text
    with runtime.database._connect() as db:
        text = " ".join(str(tuple(row)) for row in db.execute("SELECT * FROM semantic_providers"))
        text += " ".join(str(tuple(row)) for row in db.execute("SELECT * FROM admin_activity"))
    assert "synthetic-key-" not in text
    # A stale editor cannot rotate credentials or move them to a different host.
    rejected = client.put(ROOT + "/providers/" + saved["id"], headers=admin, json={"name": "old", "base_url": url, "expected_revision": 1, "api_key": "never-saved"})
    assert rejected.status_code == 409 and len(list(directory.iterdir())) == 1
    moved = client.put(ROOT + "/providers/" + saved["id"], headers=admin, json={"name": "move", "base_url": url + "/other", "expected_revision": 2})
    assert moved.status_code == 422
    assert client.request("DELETE", ROOT + "/providers/" + saved["id"], headers=admin, json={"confirm": True, "expected_revision": 2}).status_code == 409
    assert client.request("DELETE", ROOT + "/aliases/fixture", headers=admin, json={"confirm": True, "expected_revision": alias["revision"]}).status_code == 200
    assert client.request("DELETE", ROOT + "/providers/" + saved["id"], headers=admin, json={"confirm": True, "expected_revision": 2}).status_code == 200
    assert not list(directory.iterdir())


@pytest.mark.parametrize("mode", ["auth", "redirect", "invalid"])
def test_connection_failures_are_sanitized_and_redirects_are_not_followed(console, model_catalog, mode):
    client, _, admin, _ = console
    url, calls, handler = model_catalog
    saved = provider(console, base_url=url, api_key="synthetic-key")
    handler.mode = mode
    response = client.post(ROOT + "/providers/" + saved["id"] + "/test", headers=admin)
    assert response.status_code == 200 and not response.json()["connected"]
    assert "synthetic-" not in response.text
    assert len(calls) == 1 and calls[0][0] == "/v1/models"


def test_alias_management_cannot_enable_live_calls_or_edit_builtin_models(console):
    client, accounts, admin, _ = console
    saved = provider(console)
    response = client.put(ROOT + "/aliases", headers=admin, json={"alias": "secondary", "provider_id": saved["id"], "model_id": "another-base"})
    assert response.status_code == 200
    with identity_scope(accounts.authenticate(admin["Authorization"].removeprefix("Bearer "))):
        with pytest.raises(AnalyticsError) as error:
            execution_policy(client.app.state.runtime, {"model": "secondary", "statement": "RETURN llm('secondary','{answer STRING}')"})
        assert error.value.code == "semantic_live_disabled"
    assert client.put(ROOT + "/aliases", headers=admin, json={"alias": "qwen", "provider_id": saved["id"], "model_id": "wrong-model"}).status_code == 409
    assert client.put(ROOT + "/providers/graphmine", headers=admin, json={"name": "wrong", "base_url": "https://example.org/v1"}).status_code == 409


def test_simultaneous_provider_catalog_checks_keep_credentials_independent(console):
    client, accounts, admin, _ = console
    # Exercise credential isolation with two admitted catalog checks.
    client.app.state.runtime.upload_slots = asyncio.Semaphore(2)
    # Each account admits only one mutation at once; use two authorized admins.
    accounts.create_user("other-admin", PASSWORD, admin=True)
    other_admin = login(client, "other-admin")
    overlap, calls = threading.Barrier(2), []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            overlap.wait(timeout=5)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        providers = [provider(console, name=name, base_url=f"http://127.0.0.1:{server.server_port}/{name}",
                              api_key=f"synthetic-{name}") for name in ("alpha", "beta")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.post, ROOT + "/providers/" + item["id"] + "/test", headers=headers)
                       for item, headers in zip(providers, (admin, other_admin))]
            responses = [future.result(timeout=10) for future in futures]
        assert all(response.status_code == 200 and response.json()["connected"] for response in responses), [response.json() for response in responses]
        assert set(calls) == {("/alpha/models", "Bearer synthetic-alpha"), ("/beta/models", "Bearer synthetic-beta")}
        assert all("synthetic-" not in response.text for response in responses)
        assert "synthetic-" not in client.get(ROOT, headers=admin).text
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_admin_mock_uses_the_real_engine_and_current_limits(console, native_engine):
    client, _, admin, _ = console
    assert save(console, BATCH_SIZE=2, DEFAULT_CALL_LIMIT=2, MAX_CALLS=3, TIMEOUT_SECONDS=10).status_code == 200
    response = client.post(ROOT + "/test-mock", headers=admin)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["passed"] and value["simulated"] and value["http_requests"] == 0
    assert value["settings"]["llm_batch_size"] == "2"
    assert value["settings"]["admin_policy"]["timeout_seconds"] == 10
    assert value["usage"]["calls"] == 1


def test_slots_bound_concurrent_jobs_and_release_after_failure(workspace):
    runtime = workspace.runtime
    body = {"statement": "RETURN 1", "model": "qwen", "call_limit": 1}
    active, release, second = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def first():
        try:
            with slot(runtime, body):
                active.set(); assert release.wait(5)
                raise RuntimeError("expected fixture failure")
        except RuntimeError:
            pass
        except Exception as error:
            errors.append(error)
    def later():
        try:
            with slot(runtime, body):
                second.set()
        except Exception as error:
            errors.append(error)
    one, two = threading.Thread(target=first), threading.Thread(target=later)
    one.start(); assert active.wait(3)
    two.start()
    try:
        assert not second.wait(0.25)
    finally:
        release.set(); one.join(5); two.join(5)
    assert second.is_set() and not errors and not one.is_alive() and not two.is_alive()


def test_lowered_limit_blocks_another_process_until_existing_workers_finish(workspace, tmp_path):
    runtime = workspace.runtime
    body = {"statement": "RETURN 1", "model": "qwen", "call_limit": 1}
    def capacity(value):
        admin_settings.save(runtime, {PREFIX + "MAX_CONCURRENT_REQUESTS": value}, keys=admin_settings.SEMANTIC_KEYS, target="semantic")
    capacity(2)
    ready, admitted = tmp_path / "waiting", tmp_path / "admitted"
    script = f"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from graphmine_agent.config import Settings
from graphmine_agent.database import Database
from graphmine_agent.semantic_policy import slot
runtime = SimpleNamespace(settings=replace(Settings.from_env(), data_root=Path({str(runtime.settings.data_root)!r}), accounts_enabled=False), database=Database(Path({str(runtime.database.path)!r})))
Path({str(ready)!r}).touch()
with slot(runtime, {body!r}):
    Path({str(admitted)!r}).touch()
"""
    process = None
    try:
        with slot(runtime, body):
            with slot(runtime, body):
                process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert ready.exists()
                capacity(1)
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.3)
            assert not admitted.exists()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr.decode()
        assert admitted.exists()
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def test_cookie_mutations_need_csrf_verification(console):
    client, _, admin, _ = console
    from test_accounts import PASSWORD
    response = client.post("/api/auth/login", headers={"X-GraphMine-Request": "1"},
                           json={"username": "owner", "password": PASSWORD})
    assert response.status_code == 200
    response = client.post(ROOT + "/providers", json={"name": "p", "base_url": "https://example.org/v1"})
    assert response.status_code == 403

def test_legacy_builtin_url_credentials_are_hidden_and_never_tested(console, monkeypatch):
    client, _, admin, _ = console
    runtime = client.app.state.runtime
    runtime.settings = replace(runtime.settings, llm_base_url="https://user:synthetic-hidden@localhost/v1?token=synthetic-hidden")
    def forbidden(*args, **kwargs):
        pytest.fail("An invalid server URL must not open an HTTP client")
    monkeypatch.setattr(semantic_providers.httpx, "Client", forbidden)
    response = client.get(ROOT, headers=admin)
    assert "synthetic-hidden" not in response.text
    assert response.json()["providers"][0]["configuration_valid"] is False
    response = client.post(ROOT + "/providers/graphmine/test", headers=admin)
    assert not response.json()["connected"] and "synthetic-hidden" not in response.text


def test_queued_work_rechecks_access_and_run_uses_current_limits(console, source, native_engine):
    from graphmine_agent.query_previews import QueryPreviews
    from test_database_jobs import wait_job
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    config = runtime.settings.data_root / "semantic-test-sources.json"
    config.write_text(json.dumps([source.model_dump()])); config.chmod(0o600)
    admin_settings.apply_live(runtime, replace(runtime.settings, database_sources_file=config))
    member = login(client, "member")
    principal = accounts.authenticate(member["Authorization"].removeprefix("Bearer "))
    graph = {"graph": {"id": "owned-base", "directed": True, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [{"id": 1, "attributes": {"text": "alpha"}}], "edges": []}
    with identity_scope(principal):
        base = QueryPreviews(runtime).store(graph, name="base", kind="graph",
            source={"type": "database_query", "database_source": {"id": source.id}, "lineage": {}}, complete=True)
        before = QueryPreviews(runtime).get(base["id"], content=True)
    body = {"base_version_id": base["id"], "model": "mock", "call_limit": 99,
            "statement": "MATCH(n) RETURN n,llm('mock','Echo {{n.text}} {answer STRING}') AS answer"}
    assert client.post("/api/semantic-queries", headers=member, json=body).status_code == 403
    assert save(console, ACCESS="selected", ACCOUNTS=[principal.user_id], BATCH_SIZE=2, DEFAULT_CALL_LIMIT=2, MAX_CALLS=3).status_code == 200
    client.portal.call(runtime.database_jobs.stop)
    queued = client.post("/api/semantic-queries", headers=member, json=body)
    assert queued.status_code == 202, queued.text
    assert save(console, ACCESS="admins").status_code == 200
    client.portal.call(runtime.database_jobs.start)
    client.headers.update(member)
    failed = wait_job(client, queued.json()["job"]["id"], "failed")
    assert failed["error"]["code"] == "semantic_access"
    assert save(console, ACCESS="selected").status_code == 200
    job = client.post("/api/semantic-queries", headers=member, json=body).json()["job"]
    wait_job(client, job["id"])
    result = client.get("/api/database-jobs/" + job["id"] + "/result", headers=member).json()
    provenance = result["dataset"]["source"]
    assert provenance["requested_call_limit"] == 99
    assert provenance["settings"]["llm_max_calls"] == "3" and provenance["settings"]["llm_batch_size"] == "2"
    with identity_scope(principal):
        assert QueryPreviews(runtime).get(base["id"], content=True) == before
        output_before = QueryPreviews(runtime).get(result["dataset"]["id"], content=True)
    assert save(console, CACHE_MAX_AGE_DAYS=1, BATCH_SIZE=8).status_code == 200
    assert client.post(ROOT + "/cache/clear", headers=admin, json={"confirm": True}).status_code == 200
    with identity_scope(principal):
        assert QueryPreviews(runtime).get(result["dataset"]["id"], content=True) == output_before
