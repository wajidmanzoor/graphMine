"""Capacity, cleanup, backups and the optional performance adapter acceptance."""

import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from graphmine_agent import admin_data, admin_settings
from graphmine_agent.identity import identity_scope
from graphmine_agent.models import ExecutionPlan, JobRecord, JobStatus, ResultRecord, SessionRecord
from graphmine_agent.neo4j_backend import set_active_backend
from test_accounts import PASSWORD, login
from test_admin_console import console
from test_admin_work import make_workflow


def upload(console, triangle_graph):
    client, accounts, admin, _ = console
    member = login(client, "member")
    sid = client.post("/api/sessions", headers=member, json={"domain_id": "general"}).json()["id"]
    response = client.post(f"/api/sessions/{sid}/files", headers=member, files={"file": ("private-graph.json", triangle_graph, "application/json")})
    assert response.status_code == 201, response.text
    return response.json()["id"], sid, member


def cleanup_body(preview):
    return {key: preview[key] for key in ("kind", "days", "preview_token")} | {"identifiers": [row["id"] for row in preview["items"]], "confirm": True}


def test_unlimited_upload_setting_persists_and_allows_authenticated_uploads(console, triangle_graph):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    changed = {"GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES": None, "GRAPHMINE_ACCOUNT_JOB_SECONDS": 21600}
    response = client.patch("/api/admin/capacity", headers=admin, json={"values": changed, "confirm": True})
    assert response.status_code == 200, response.text
    loaded = admin_settings.load(runtime.settings, runtime.database)
    assert loaded.max_upload_bytes is loaded.account_upload_bytes is loaded.analytics_max_input_bytes is None
    assert loaded.account_job_seconds == 21600
    file_id, _, _ = upload(console, triangle_graph)
    assert runtime.database.get_file(file_id).size_bytes == len(triangle_graph)


def test_capacity_ranges_conflicts_live_consumers_and_restart(console):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    data = client.get("/api/admin/capacity", headers=admin).json()
    assert len(data["rows"]) == 14
    for row in data["rows"]:
        for invalid in (row["minimum"] - 1, row["maximum"] + 1, True, 1.5):
            response = client.patch("/api/admin/capacity", headers=admin, json={"values": {row["key"]: invalid}, "confirm": True})
            assert response.status_code == 422, (row["key"], invalid, response.text)
    assert client.patch("/api/admin/capacity", headers=admin, json={"values": {"GRAPHMINE_MAX_MODEL_CALLS": 3}, "confirm": True}).status_code == 422
    changed = {"GRAPHMINE_MAX_MODEL_CALLS": 3, "GRAPHMINE_LLM_MAX_NUM_SEQS": 4, "MODEL_QUEUE_SECONDS": 30,
               "GRAPHMINE_ACCOUNT_RUNNING_JOBS": 3, "GRAPHMINE_ACCOUNT_USER_RUNNING_JOBS": 2, "GRAPHMINE_ANALYTICS_CPU_WORKERS": 3,
               "GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES": 128 * 2**20, "GRAPHMINE_BACKUP_KEEP": 18}
    assert client.patch("/api/admin/capacity", headers=admin, json={"values": changed, "confirm": False}).status_code == 422
    response = client.patch("/api/admin/capacity", headers=admin, json={"values": changed, "expected": data["values"], "confirm": True})
    assert response.status_code == 200, response.text
    assert response.json()["restart_required"] == ["GRAPHMINE_LLM_MAX_NUM_SEQS"]
    assert runtime.settings.llm_max_num_seqs == 2
    assert runtime.accounts.settings.model_queue_seconds == 30
    assert runtime.analytics.scheduler.settings.analytics_cpu_workers == 3
    assert runtime.graph_store.settings.max_upload_bytes == 128 * 2**20
    assert runtime.accounts.settings.account_upload_bytes == 128 * 2**20
    assert runtime.settings.backup_keep == 18
    loaded = admin_settings.load(replace(runtime.settings, llm_max_num_seqs=2), runtime.database)
    assert loaded.llm_max_num_seqs == 4 and loaded.max_model_calls == 3
    assert client.patch("/api/admin/capacity", headers=admin, json={"values": {"MODEL_QUEUE_SECONDS": 60}, "expected": data["values"], "confirm": True}).status_code == 409
    with accounts.database._connect() as db:
        row = db.execute('SELECT actor,"before","after" FROM admin_activity WHERE action=\'settings.updated\'').fetchone()
        assert row[0] == "owner" and json.loads(row[1])["MODEL_QUEUE_SECONDS"] == data["values"]["MODEL_QUEUE_SECONDS"]
        assert json.loads(row[2])["MODEL_QUEUE_SECONDS"] == 30
    # Actual admission uses the new per-user limit, not only the response value.
    _, principal = accounts.login("member", PASSWORD, "local")
    with identity_scope(principal):
        leases = [accounts.admit_jobs(principal.user_id) for _ in range(2)]
        assert len(leases) == 2
        for lease in leases:
            accounts.abort_admission(lease)


def test_cleanup_rechecks_references_and_download_is_logged(console, triangle_graph):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    file_id, sid, member = upload(console, triangle_graph)
    data = client.get("/api/admin/data", headers=admin)
    assert data.status_code == 200, data.text
    assert data.json()["files"][0]["deletable"]
    assert data.json()["total_bytes"] == sum(row["bytes"] for row in data.json()["categories"])
    downloaded = client.get(f"/api/admin/data/files/{file_id}/download", headers=admin)
    assert downloaded.status_code == 200 and downloaded.content == triangle_graph
    preview = client.get("/api/admin/data/cleanup-preview?kind=unused", headers=admin).json()
    _, principal = accounts.login("member", PASSWORD, "local")
    record = make_workflow(runtime, principal)
    record["input_files"] = {"graph": {"file_id": file_id}}
    runtime.analytics._save(record)
    assert client.post("/api/admin/data/cleanup", headers=admin, json=cleanup_body(preview)).status_code == 409
    assert client.get("/api/admin/data", headers=admin).json()["files"][0]["analyses"] == 1
    record["input_files"] = {}
    runtime.analytics._save(record)
    preview = client.get("/api/admin/data/cleanup-preview?kind=unused", headers=admin).json()
    body = cleanup_body(preview)
    assert client.post("/api/admin/data/cleanup", headers=admin, json={**body, "confirm": False}).status_code == 422
    response = client.post("/api/admin/data/cleanup", headers=admin, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["removed"] == 1 and response.json()["cleanup"]["pending"] == 0
    assert client.get(f"/api/sessions/{sid}/files", headers=member).json() == []
    with accounts.database._connect() as db:
        assert db.execute("SELECT actor FROM admin_activity WHERE action='file.downloaded'").fetchone()[0] == "owner"
        row = db.execute('SELECT "before","after" FROM admin_activity WHERE action=\'storage.cleaned\'').fetchone()
        assert json.loads(row[0])["items"][0]["id"] == file_id and json.loads(row[1])["removed"] == [file_id]


def test_cleanup_blocks_busy_owner_and_external_source(console, triangle_graph, tmp_path):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    file_id, _, _ = upload(console, triangle_graph)
    _, principal = accounts.login("member", PASSWORD, "local")
    with identity_scope(principal):
        lease = accounts.admit_jobs(principal.user_id)
    assert client.get("/api/admin/data/cleanup-preview?kind=unused", headers=admin).json()["count"] == 0
    accounts.abort_admission(lease)
    outside = tmp_path / "external-source.json"
    outside.write_bytes(triangle_graph)
    with accounts.database._connect() as db:
        record = json.loads(db.execute("SELECT payload FROM files WHERE id=?", (file_id,)).fetchone()[0])
        record["source_path"] = str(outside)
        db.execute("UPDATE files SET payload=? WHERE id=?", (json.dumps(record), file_id))
    response = client.get("/api/admin/data", headers=admin)
    assert response.status_code == 200 and not response.json()["files"][0]["managed"]
    assert client.get(f"/api/admin/data/files/{file_id}/download", headers=admin).status_code == 409
    assert client.get("/api/admin/data/cleanup-preview?kind=unused", headers=admin).json()["count"] == 0
    assert outside.read_bytes() == triangle_graph


def test_storage_inventory_download_and_cleanup_hide_inactive_files(console, triangle_graph):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    set_active_backend(runtime.settings, "local")
    file_id, _, _ = upload(console, triangle_graph)
    with accounts.database._connect() as db:
        db.execute("UPDATE files SET payload=json_set(payload,'$.backend_id','local') WHERE id=?", (file_id,))
        original = db.execute("SELECT payload FROM files WHERE id=?", (file_id,)).fetchone()[0]
    preview = client.get("/api/admin/data/cleanup-preview?kind=unused", headers=admin).json()
    assert preview["count"] == 1
    set_active_backend(runtime.settings, "iu-remote")
    inventory = client.get("/api/admin/data", headers=admin).json()
    assert inventory["files"] == [] and inventory["unused_count"] == 0 and inventory["unused_bytes"] == 0
    assert client.get(f"/api/admin/data/files/{file_id}/download", headers=admin).status_code == 404
    assert client.get("/api/admin/data/cleanup-preview?kind=unused", headers=admin).json()["count"] == 0
    assert client.post("/api/admin/data/cleanup", headers=admin, json=cleanup_body(preview)).status_code == 404
    with accounts.database._connect() as db:
        assert db.execute("SELECT payload FROM files WHERE id=?", (file_id,)).fetchone()[0] == original
    set_active_backend(runtime.settings, "local")
    assert client.get(f"/api/admin/data/files/{file_id}/download", headers=admin).content == triangle_graph
    assert client.get("/api/admin/data", headers=admin).json()["files"][0]["id"] == file_id


def test_hidden_results_stay_retained_and_protect_shared_uploads(console, triangle_graph):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    set_active_backend(runtime.settings, "local")
    file_id, sid, _ = upload(console, triangle_graph)
    _, principal = accounts.login("member", PASSWORD, "local")
    old = accounts.clock() - 200 * 86400
    created = datetime.fromtimestamp(old, timezone.utc)
    work = make_workflow(runtime, principal, "hidden-analysis")
    work["input_provenance"]["graph"]["backend_id"] = "local"
    work.update(status="completed", finished_at=created.isoformat(), backend_id="local", input_files={"graph": {"file_id": file_id}})
    runtime.analytics._save(work)
    path = runtime.analytics._directory(work) / "result.json"
    path.write_bytes(b'{"private":"retained result"}')
    with identity_scope(principal):
        plan = ExecutionPlan(session_id=sid, graph_id=file_id, topic_id="core", problem_id="k-core", parameters={"k": 2})
        job = runtime.database.save_job(JobRecord(session_id=sid, plan=plan, status=JobStatus.completed, backend_id="local"))
        result = runtime.database.save_result(ResultRecord(job_id=job.id, session_id=sid, problem_id="k-core", payload={"private": "values"}, summary={}, created_at=created, backend_id="local"))
    with accounts.database._connect() as db:
        db.execute("UPDATE admin_metadata SET value=? WHERE key='resource_access_since'", (str(old),))
        original = db.execute("SELECT payload FROM results WHERE id=?", (result.id,)).fetchone()[0]
    preview = client.get("/api/admin/data/cleanup-preview?kind=results&days=180", headers=admin).json()
    assert {row["id"] for row in preview["items"]} == {work["id"], result.id}
    set_active_backend(runtime.settings, "iu-remote")
    inventory = client.get("/api/admin/data", headers=admin).json()
    assert inventory["files"][0]["id"] == file_id
    assert inventory["files"][0]["used_by"] == ["Retained reference"]
    assert not inventory["files"][0]["deletable"]
    for kind in ("unused", "results"):
        assert client.get(f"/api/admin/data/cleanup-preview?kind={kind}&days=180", headers=admin).json()["count"] == 0
    assert client.post("/api/admin/data/cleanup", headers=admin, json=cleanup_body(preview)).status_code == 404
    assert path.read_bytes() == b'{"private":"retained result"}'
    for kind, identifier in (("workflow", work["id"]), ("job", job.id)):
        assert client.get(f"/api/admin/jobs/{kind}/{identifier}", headers=admin).status_code == 404
    assert client.get("/api/admin/jobs?view=finished", headers=admin).json()["calculations"] == []
    with accounts.database._connect() as db:
        assert db.execute("SELECT payload FROM results WHERE id=?", (result.id,)).fetchone()[0] == original
    set_active_backend(runtime.settings, "local")
    assert client.get("/api/admin/data/cleanup-preview?kind=results&days=180", headers=admin).json()["count"] == 2
    assert client.get(f"/api/admin/jobs/workflow/{work['id']}", headers=admin).status_code == 200


def test_result_retention_respects_unknown_recent_and_saved_references(console):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    _, principal = accounts.login("member", PASSWORD, "local")
    old = accounts.clock() - 200 * 86400
    for identifier in ("old-result", "recent-result", "protected-result"):
        record = make_workflow(runtime, principal, identifier)
        record.update(status="completed", finished_at=datetime.fromtimestamp(old, timezone.utc).isoformat())
        runtime.analytics._save(record)
        directory = runtime.analytics._directory(record)
        (directory / "result.json").write_text('{"private": "result values"}')
        (directory / "result.rows.sqlite3").write_bytes(b"derived-index")
    # Unrecorded historical opens cannot be inferred to be old.
    assert client.get("/api/admin/data/cleanup-preview?kind=results&days=90", headers=admin).json()["count"] == 0
    with accounts.database._connect() as db:
        db.execute("UPDATE admin_metadata SET value=? WHERE key='resource_access_since'", (str(old),))
        db.execute("INSERT INTO session_exploration VALUES (?,?,?,?)", (record["session_id"], 1, json.dumps({"workflow_id": "protected-result"}), datetime.now(timezone.utc).isoformat()))
    with identity_scope(principal):
        runtime.analytics.result("recent-result")
    preview = client.get("/api/admin/data/cleanup-preview?kind=results&days=90", headers=admin).json()
    assert [row["id"] for row in preview["items"]] == ["old-result"]
    # Opening a result after the preview invalidates that preview.
    with identity_scope(principal):
        runtime.analytics.result("old-result")
    assert client.post("/api/admin/data/cleanup", headers=admin, json=cleanup_body(preview)).status_code == 409
    with accounts.database._connect() as db:
        db.execute("UPDATE admin_resource_access SET opened_at=? WHERE id='old-result'", (old,))
    preview = client.get("/api/admin/data/cleanup-preview?kind=results&days=90", headers=admin).json()
    response = client.post("/api/admin/data/cleanup", headers=admin, json=cleanup_body(preview))
    assert response.status_code == 200, response.text
    assert not list((runtime.analytics.root / "old-result").rglob("result*"))
    assert list((runtime.analytics.root / "old-result").rglob("inputs.json"))
    with identity_scope(principal):
        assert runtime.analytics.get("old-result")["error"]["code"] == "results_removed"


def test_backup_create_verify_staged_restore_and_tampering(console, triangle_graph):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    upload(console, triangle_graph)
    response = client.post("/api/admin/data/backups", headers=admin)
    assert response.status_code == 200, response.text
    name = response.json()["name"]
    backups = client.get("/api/admin/data", headers=admin).json()["backups"]
    assert backups["items"][0]["verified"] and backups["keep"] == 14 and not backups["scheduled"]
    prefix = f"/api/admin/data/backups/{name}"
    assert client.post(prefix + "/verify", headers=admin).status_code == 200
    assert client.post(prefix + "/restore", headers=admin, json={"confirm": True, "confirm_name": "wrong"}).status_code == 422
    restored = client.post(prefix + "/restore", headers=admin, json={"confirm": True, "confirm_name": name})
    assert restored.status_code == 200, restored.text
    assert restored.json()["services_started"] is False
    assert Path(restored.json()["data_root"]).is_dir() and Path(restored.json()["data_root"]) != runtime.settings.data_root
    snapshot = admin_data.snapshot_path(runtime, name)
    (snapshot / "data" / "agent.sqlite3").write_bytes(b"corrupt")
    assert client.post(prefix + "/verify", headers=admin).status_code == 409
    assert not client.get("/api/admin/data", headers=admin).json()["backups"]["items"][0]["verified"]
    with accounts.database._connect() as db:
        actions = {row[0] for row in db.execute("SELECT action FROM admin_activity")}
        assert {"backup.create_completed", "backup.verify_completed", "backup.restore_completed", "backup.verify_failed"} <= actions


def test_old_legacy_results_are_removed_without_losing_the_plan(console, triangle_graph):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    file_id, sid, member = upload(console, triangle_graph)
    _, principal = accounts.login("member", PASSWORD, "local")
    old = accounts.clock() - 200 * 86400
    with identity_scope(principal):
        plan = ExecutionPlan(session_id=sid, graph_id=file_id, topic_id="core", problem_id="k-core", parameters={"k": 2})
        job = runtime.database.save_job(JobRecord(session_id=sid, plan=plan, status=JobStatus.completed))
        result = runtime.database.save_result(ResultRecord(job_id=job.id, session_id=sid, problem_id="k-core", payload={"private": "values"}, summary={}, created_at=datetime.fromtimestamp(old, timezone.utc)))
    with accounts.database._connect() as db:
        db.execute("UPDATE admin_metadata SET value=? WHERE key='resource_access_since'", (str(old),))
    preview = client.get("/api/admin/data/cleanup-preview?kind=results&days=180", headers=admin).json()
    assert preview["count"] == 1 and preview["items"][0]["kind"] == "result"
    response = client.post("/api/admin/data/cleanup", headers=admin, json=cleanup_body(preview))
    assert response.status_code == 200, response.text
    assert client.get(f"/api/results/{result.id}", headers=member).status_code == 404
    with identity_scope(principal):
        saved = runtime.database.get_job(job.id)
        assert saved.plan == plan and saved.error["code"] == "results_removed"
    assert not (runtime.database.history.session_path(sid) / "results" / result.id / "result.json").exists()


def test_capacity_effective_model_limit_comes_from_running_process(console, monkeypatch):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    async def loaded():
        return {"max_requests": 2}
    monkeypatch.setattr(client.app.state.admin_monitor, "loaded", loaded)
    # An agent can restart and load the desired limit before vLLM restarts.
    admin_settings.apply_live(runtime, replace(runtime.settings, llm_max_num_seqs=8))
    data = client.get("/api/admin/capacity", headers=admin).json()
    assert data["values"]["GRAPHMINE_LLM_MAX_NUM_SEQS"] == 8
    assert data["effective"]["GRAPHMINE_LLM_MAX_NUM_SEQS"] == 2


def make_run(directory, identifier, p50=1000):
    run = directory / identifier
    run.mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({"label": identifier, "test": "load", "prepared_at": "2026-11-19T01:00:00Z", "finished_at": "2026-11-19T01:20:00Z", "requested_users": 10,
                                               "query": "PRIVATE QUERY", "capacity": {"GRAPHMINE_MAX_MODEL_CALLS": 2, "PRIVATE": "SECRET"}}))
    (run / "summary.json").write_text(json.dumps({"headline": {"answer_p50_ms": p50, "answer_p95_ms": p50 * 2, "question_error_percent": 0},
                                                "flags": [{"message": "calculation slots are the bottleneck", "private": "PRIVATE"}], "config": {"private": "PRIVATE"}}))
    (run / "report.html").write_text("<!doctype html><title>Test report</title><h1>Measured report</h1>")
    return run


def test_performance_optional_suite_metadata_reports_and_paths(console, tmp_path):
    client, accounts, admin, _ = console
    service = client.app.state.admin_performance
    configured = replace(service.runtime.settings, repository_root=tmp_path / "repo")
    admin_settings.apply_live(service.runtime, configured)
    assert client.get("/api/admin/performance", headers=admin).json()["installed"] is False
    make_run(service.directory, "test-before")
    make_run(service.directory, "test-after", 500)
    (service.directory / "linked").symlink_to(service.directory / "test-before", target_is_directory=True)
    response = client.get("/api/admin/performance", headers=admin)
    assert len(response.json()["runs"]) == 2 and "PRIVATE" not in response.text and "SECRET" not in response.text
    assert response.json()["allowed_tests"] == ["benchmark", "load"]
    report = client.get("/api/admin/performance/runs/test-before/report", headers=admin)
    assert report.status_code == 200 and "Measured report" in report.text
    csp = report.headers["content-security-policy"]
    assert "sandbox allow-scripts;" in csp and "allow-same-origin" not in csp and "connect-src 'none'" in csp
    assert client.get("/api/admin/performance/runs/linked/report", headers=admin).status_code == 404
    result = client.post("/api/admin/performance/start", headers=admin, json={"test": "load", "label": "try", "lab_window": "agreed fixture slot", "confirm": True})
    assert result.status_code == 409


def test_performance_background_runner_allowlist_and_private_environment(console, tmp_path, monkeypatch):
    client, accounts, admin, _ = console
    service = client.app.state.admin_performance
    root = tmp_path / "perf-repo"
    (root / "perf").mkdir(parents=True)
    # This fixture executes no model/GPU work. It validates the adapter contract.
    (root / "perf" / "run.py").write_text("""import json, os, pathlib, sys
args = sys.argv[1:]
config = pathlib.Path(args[args.index('--app-env')+1])
assert config.stat().st_mode & 0o777 == 0o600
env = json.loads(config.read_text())
assert env['GRAPHMINE_MAX_MODEL_CALLS'] == '2'
assert args[0] == 'load' and '--confirm-shared-gpu' not in args
pathlib.Path('invoked.json').write_text(json.dumps({'args': args, 'config': str(config)}))
""")
    admin_settings.apply_live(service.runtime, replace(service.runtime.settings, repository_root=root))
    async def unit(_):
        return {"unit": "graphmine-vllm.service", "active": "active", "pid": 1234}
    monkeypatch.setattr(client.app.state.admin_monitor, "unit", unit)
    body = {"test": "stress", "label": "fixture", "lab_window": "agreed fixture slot", "confirm": True}
    assert client.post("/api/admin/performance/start", headers=admin, json=body).status_code == 403
    assert client.post("/api/admin/performance/start", headers=admin, json={**body, "test": "load", "label": "bad;label"}).status_code == 422
    response = client.post("/api/admin/performance/start", headers=admin, json={**body, "test": "load"})
    assert response.status_code == 202, response.text
    async def finished():
        await asyncio.wait_for(service.task, 5)
    client.portal.call(finished)
    invoked = json.loads((root / "invoked.json").read_text())
    assert not Path(invoked["config"]).exists()
    job = client.get("/api/admin/performance", headers=admin).json()["jobs"][0]
    assert job["status"] == "completed" and job["exit_code"] == 0
    with accounts.database._connect() as db:
        assert db.execute("SELECT actor FROM admin_activity WHERE action='performance.completed'").fetchone()[0] == "owner"
