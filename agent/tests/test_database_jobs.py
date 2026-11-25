"""Durable database work survives request loss without replaying writes."""

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.api import create_app
from graphmine_agent.backup import online_snapshot, restore_snapshot
from graphmine_agent.database import RecordNotFound
from graphmine_agent.database_job_context import checkpoint, current_database_job
from graphmine_agent.database_jobs import DatabaseJobs, JobControl, MAX_OWNER_PENDING, WorkStopped
from graphmine_agent.database_queries import CypherRequest
from graphmine_agent.database_sync import sync_source
from graphmine_agent.identity import AccountError, Principal, current_principal, identity_scope
from test_accounts import PASSWORD, account_settings, login  # noqa: F401
from test_database_workspace import documents, source, workspace  # noqa: F401

ASYNC = {"Prefer": "respond-async"}
QUERY = {"statement": "MATCH p=()-[]->() RETURN p"}


def wait_job(client, identifier, expected="completed"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/database-jobs/{identifier}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] == expected:
            return value
        time.sleep(0.02)
    pytest.fail(f"Expected {expected}: {value}")


def submit(workspace, key="first", **body):
    response = workspace.client.post("/api/database-sources/demo/queries", json={**QUERY, **body}, headers={**ASYNC, "Idempotency-Key": key})
    assert response.status_code == 202, response.text
    assert response.headers["Location"].endswith(response.json()["job"]["id"])
    return response.json()["job"]


def hold_query(workspace, monkeypatch):
    from graphmine_agent import database_queries

    original = database_queries.execute_query
    started, release = Event(), Event()
    def execute(*args):
        started.set()
        while not release.wait(0.01):
            checkpoint("reading", 12)
        return original(*args)
    monkeypatch.setattr(database_queries, "execute_query", execute)
    return started, release


def test_background_queries_use_their_runtime_pool_scope(workspace, monkeypatch):
    from graphmine_agent import database_queries
    from graphmine_agent.database_pools import current_database_pools
    original = database_queries.execute_query
    observed = []
    def execute(*args):
        observed.append(current_database_pools.get())
        return original(*args)
    monkeypatch.setattr(database_queries, "execute_query", execute)
    first = submit(workspace)
    wait_job(workspace.client, first["id"])
    second = submit(workspace, key="second")
    wait_job(workspace.client, second["id"])
    assert observed == [workspace.runtime.database_pools] * 2
    assert current_database_pools.get() is None


def test_async_admission_returns_before_query_and_duplicate_request_runs_once(workspace, monkeypatch):
    started, release = hold_query(workspace, monkeypatch)
    initial = len(workspace.calls)
    try:
        job = submit(workspace)
        assert started.wait(3)
        assert job["status"] == "queued" and "owner_id" not in job
        assert submit(workspace)["id"] == job["id"]
        conflict = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "RETURN 2"}, headers={**ASYNC, "Idempotency-Key": "first"})
        assert conflict.status_code == 409
        value = wait_job(workspace.client, job["id"], "running")
        assert value["progress"]["stage"] in {"connecting", "reading"}
        assert len(workspace.calls) == initial
    finally:
        release.set()
    wait_job(workspace.client, job["id"])
    assert len(workspace.calls) == initial + 1
    # Finished work is delivered from memory, without a persistent history row.
    result = workspace.runtime.database_jobs.result(job["id"])
    with pytest.raises(RecordNotFound):
        DatabaseJobs(workspace.runtime).result(job["id"])
    assert submit(workspace)["id"] == job["id"]
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM database_jobs").fetchone()[0] == 0
    assert workspace.client.get("/api/database-jobs").json()["items"] == []
    assert result["dataset"]["temporary"] and result["vertex_count"] == 2
    assert len(result["graph"]["vertices"]) == 2
    assert result["dataset"]["source"]["query"] == QUERY["statement"]
    assert len(workspace.calls) == initial + 1


def test_running_and_queued_cancellation_do_not_publish_snapshots(workspace, monkeypatch):
    started, release = hold_query(workspace, monkeypatch)
    initial = len(workspace.calls)
    try:
        active = submit(workspace)
        assert started.wait(3)
        queued = submit(workspace, "second")
        cancelled = workspace.client.delete(f"/api/database-jobs/{queued['id']}").json()
        assert cancelled["status"] == "cancelled"
        response = workspace.client.delete(f"/api/database-jobs/{active['id']}")
        assert response.status_code == 200 and response.json()["status"] == "cancelling"
        assert workspace.client.delete(f"/api/database-jobs/{active['id']}").status_code == 200
        wait_job(workspace.client, active["id"], "cancelled")
        assert workspace.client.get(f"/api/database-jobs/{active['id']}/result").status_code == 409
        assert len(workspace.calls) == initial
        with workspace.runtime.database._connect() as db:
            assert db.execute("SELECT count(*) FROM query_previews").fetchone()[0] == 0
    finally:
        release.set()


def test_cancelled_query_retry_is_explicit_and_idempotent(workspace, monkeypatch):
    started, release = hold_query(workspace, monkeypatch)
    try:
        job = submit(workspace)
        assert started.wait(3)
        workspace.client.delete(f"/api/database-jobs/{job['id']}")
        wait_job(workspace.client, job["id"], "cancelled")
    finally:
        release.set()
    response = workspace.client.post(f"/api/database-jobs/{job['id']}/retry", headers={"Idempotency-Key": "retry-one"})
    assert response.status_code == 202, response.text
    retried = response.json()["job"]
    assert retried["id"] != job["id"]
    duplicate = workspace.client.post(f"/api/database-jobs/{job['id']}/retry", headers={"Idempotency-Key": "retry-one"})
    assert duplicate.json()["job"]["id"] == retried["id"]
    wait_job(workspace.client, retried["id"])


def test_owner_scope_covers_all_job_and_result_actions(workspace):
    service = DatabaseJobs(workspace.runtime)
    accounts = SimpleNamespace(upload_remaining=lambda _: 100_000_000)
    with identity_scope(Principal("alice", "alice", accounts)):
        job = service.enqueue("query", "demo", CypherRequest(**QUERY), request_key="shared-key")
    with identity_scope(Principal("bob", "bob", accounts)):
        assert not service.list()["items"]
        for problem in (service.get, service.result, service.cancel, service.retry):
            with pytest.raises(RecordNotFound):
                problem(job["id"])
        other = service.enqueue("query", "demo", CypherRequest(**QUERY), request_key="shared-key")
        service.cancel(other["id"])
    with identity_scope(Principal("alice", "alice", accounts)):
        service.cancel(job["id"])
    assert other["id"] != job["id"]
    with pytest.raises(RecordNotFound):
        service.get(job["id"])


def test_storage_and_queue_admission_are_bounded_without_losing_existing_jobs(workspace, monkeypatch):
    service = DatabaseJobs(workspace.runtime)
    accounts = SimpleNamespace(upload_remaining=lambda _: 1)
    with identity_scope(Principal("alice", "alice", accounts)):
        with pytest.raises(AccountError, match="storage"):
            service.enqueue("query", "demo", CypherRequest(**QUERY))
    started, release = hold_query(workspace, monkeypatch)
    try:
        jobs = [submit(workspace, str(i)) for i in range(MAX_OWNER_PENDING)]
        assert started.wait(3)
        response = workspace.client.post("/api/database-sources/demo/queries", json=QUERY, headers=ASYNC)
        assert response.status_code == 429 and response.json()["error"]["code"] == "database_queue_full"
        assert len(service.list()["items"]) == MAX_OWNER_PENDING
        for job in jobs:
            service.cancel(job["id"])
    finally:
        release.set()


def test_recovery_retains_queued_work_and_marks_active_sync_interrupted(workspace):
    # Use an isolated database with no worker so restart timing is deterministic.
    from graphmine_agent.database import Database

    database = Database(workspace.runtime.settings.data_root / "restart.sqlite3")
    runtime = SimpleNamespace(settings=workspace.runtime.settings, database=database)
    original = DatabaseJobs(runtime)
    sync = original.enqueue("sync", "demo")
    assert original._claim()["id"] == sync["id"]
    query = original.enqueue("query", "demo", CypherRequest(**QUERY))
    restored = DatabaseJobs(SimpleNamespace(settings=runtime.settings, database=Database(database.path)))
    restored.recover()
    assert restored.get(query["id"])["status"] == "queued"
    interrupted = restored.get(sync["id"])
    assert interrupted["status"] == "interrupted"
    assert "may already have been committed" in interrupted["error"]["message"]
    assert restored._claim()["id"] == query["id"]


def test_changed_source_is_not_replayed(workspace):
    from graphmine_agent.database import Database

    runtime = SimpleNamespace(settings=workspace.runtime.settings, database=Database(workspace.runtime.settings.data_root / "changed.sqlite3"))
    service = DatabaseJobs(runtime)
    job = service.enqueue("query", "demo", CypherRequest(**QUERY))
    service.cancel(job["id"])
    path = workspace.runtime.settings.database_sources_file
    sources = json.loads(path.read_text()); sources[0]["revision"] += 1; path.write_text(json.dumps(sources))
    with pytest.raises(AnalyticsError, match="changed"):
        service.retry(job["id"])


def test_expired_and_corrupt_results_are_not_served(workspace):
    job = submit(workspace)
    wait_job(workspace.client, job["id"])
    with workspace.runtime.database._connect() as db:
        db.execute("UPDATE query_preview_blobs SET content=?", (b"{}",))
    assert workspace.client.get(f"/api/database-jobs/{job['id']}/result").status_code == 409
    with workspace.runtime.database._connect() as db:
        db.execute("UPDATE query_previews SET expires_at=0")
    assert workspace.client.get(f"/api/database-jobs/{job['id']}/result").status_code == 410


def test_sync_cancellation_rolls_back_before_commit(source, monkeypatch):
    actions = []
    class Result(list):
        def consume(self): return None
        def single(self): return self[0] if self else None
    class Transaction:
        def run(self, statement, **kwargs):
            actions.append(statement)
            return Result() if 'RETURN elementId(' in statement else Result([{'changed': len(kwargs.get('rows', []))}])
        def commit(self):
            actions.append("commit")
        def __enter__(self):
            return self
        def __exit__(self, kind, value, traceback):
            actions.append("rollback" if kind else "close")
    class Control:
        def checkpoint(self, stage, *_):
            if stage == "writing" and any("UNWIND" in action for action in actions):
                raise WorkStopped()
        def seal(self, stage):
            self.checkpoint("writing")
    @contextmanager
    def session(*_, **__):
        tx = Transaction()
        yield SimpleNamespace(run=tx.run, begin_transaction=lambda **_: tx)
    monkeypatch.setattr("graphmine_agent.database_sync.neo4j_session", session)
    token = current_database_job.set(Control())
    try:
        with pytest.raises(WorkStopped):
            sync_source(source)
    finally:
        current_database_job.reset(token)
    assert "rollback" in actions and "commit" not in actions


def test_commit_boundary_rejects_late_cancellation_and_never_replays_sync(workspace, monkeypatch):
    from graphmine_agent.database_job_context import begin_commit

    committing, release = Event(), Event()
    calls = []
    def synchronize(source, limit):
        checkpoint("writing", 3, 3)
        begin_commit(); committing.set()
        assert release.wait(5)
        calls.append(source.id)
        return {"source_id": source.id, "nodes": 3, "relationships": 2}
    monkeypatch.setattr("graphmine_agent.database_sync.sync_source", synchronize)
    response = workspace.client.post("/api/database-sources/demo/sync", headers=ASYNC)
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    try:
        assert committing.wait(3)
        cancelled = workspace.client.delete(f"/api/database-jobs/{job['id']}")
        assert cancelled.status_code == 409 and cancelled.json()["error"]["code"] == "database_committing"
    finally:
        release.set()
    wait_job(workspace.client, job["id"])
    assert workspace.client.get(f"/api/database-jobs/{job['id']}/result").json()["nodes"] == 3
    assert workspace.client.post(f"/api/database-jobs/{job['id']}/retry").status_code == 409
    assert calls == ["demo"]


def test_uncertain_sync_commit_is_interrupted_and_errors_are_redacted(workspace, monkeypatch):
    from graphmine_agent.database_job_context import begin_commit

    def synchronize(*_):
        begin_commit()
        raise OSError("secret database password")
    monkeypatch.setattr("graphmine_agent.database_sync.sync_source", synchronize)
    response = workspace.client.post("/api/database-sources/demo/sync", headers=ASYNC)
    job = wait_job(workspace.client, response.json()["job"]["id"], "interrupted")
    assert job["error"]["code"] == "database_commit_unknown"
    assert "secret" not in json.dumps(job)


def test_lost_or_disabled_owner_cannot_execute_private_work(workspace):
    service = DatabaseJobs(workspace.runtime)
    with pytest.raises(AccountError):
        service._principal("missing-owner")
    service.runtime = SimpleNamespace(settings=replace(workspace.runtime.settings, accounts_enabled=True))
    with pytest.raises(AccountError):
        service._principal("")


def test_failure_details_survive_job_polling_for_inline_query_errors(workspace, monkeypatch):
    def execute(*_):
        raise AnalyticsError("Invalid syntax", "cypher_syntax", details={"line": 2, "column": 3, "offset": 9})
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    job = submit(workspace)
    failed = wait_job(workspace.client, job["id"], "failed")
    assert failed["error"]["details"]["offset"] == 9
    assert workspace.client.get("/api/database-jobs?limit=1").json()["items"] == []
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM database_jobs").fetchone()[0] == 0


def test_account_queue_resumes_with_fresh_owner_identity_and_rejects_disabled_owner(account_settings, source, tmp_path, monkeypatch):
    config = tmp_path / "account-sources.json"
    config.write_text(json.dumps([source.model_dump()])); config.chmod(0o600)
    settings = replace(account_settings, database_sources_file=config)
    graph, lineage = documents(source)
    executions = []
    def execute(*_):
        executions.append(current_principal.get().user_id)
        return graph, lineage, [], 1, None
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        alice = runtime.accounts.create_user("alice", PASSWORD)
        runtime.accounts.create_user("bob", PASSWORD)
        client.headers.update(login(client))
        client.portal.call(runtime.database_jobs.stop)
        response = client.post("/api/database-sources/demo/queries", json=QUERY, headers=ASYNC)
        assert response.status_code == 202, response.text
        identifier = response.json()["job"]["id"]
        pending_usage = runtime.accounts.storage_usage(alice["id"])["database_jobs"]
        assert pending_usage > 500_000 and not executions
        runtime.accounts.logout(runtime.accounts.authenticate(client.headers["Authorization"].removeprefix("Bearer ")))
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        client.headers.update(login(client))
        wait_job(client, identifier)
        result = client.get(f"/api/database-jobs/{identifier}/result")
        assert result.status_code == 200 and result.json()["vertex_count"] == 3
        assert executions == [alice["id"]]
        assert runtime.accounts.storage_usage(alice["id"])["database_jobs"] == 0
        client.headers.update(login(client, "bob"))
        assert client.get(f"/api/database-jobs/{identifier}").status_code == 404
        assert client.get(f"/api/database-jobs/{identifier}/result").status_code == 404
        assert client.get("/api/database-jobs").json()["items"] == []
        client.headers.update(login(client))
        client.portal.call(runtime.database_jobs.stop)
        blocked = client.post("/api/database-sources/demo/queries", json=QUERY, headers=ASYNC).json()["job"]["id"]
        with runtime.database._connect() as db:
            db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (alice["id"],))
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with identity_scope(Principal(alice["id"], "alice", runtime.accounts)):
                value = runtime.database_jobs.get(blocked)
            if value["status"] == "failed":
                break
            time.sleep(0.02)
        assert value["error"]["code"] == "account_unavailable"
        assert executions == [alice["id"]]


def test_online_backup_preserves_snapshot_without_finished_job_history(workspace, tmp_path):
    from graphmine_agent.database import Database

    job = submit(workspace)
    wait_job(workspace.client, job["id"])
    before = workspace.runtime.database_jobs.result(job["id"])
    workspace.client.portal.call(workspace.runtime.database_jobs.stop)
    pending = workspace.runtime.database_jobs.enqueue("sync", "demo")
    backup = tmp_path / "job-backup"
    online_snapshot(workspace.runtime.settings.data_root, backup)
    restored = tmp_path / "job-restored"
    report = restore_snapshot(backup, restored)
    data_root = Path(report["data_root"])
    runtime = SimpleNamespace(settings=replace(workspace.runtime.settings, data_root=data_root), database=Database(data_root / "agent.sqlite3"))
    service = DatabaseJobs(runtime)
    from graphmine_agent.query_previews import QueryPreviews
    assert QueryPreviews(runtime).get(before["dataset"]["id"])["sha256"] == before["dataset"]["sha256"]
    service.recover()
    for identifier in (job["id"], pending["id"]):
        with pytest.raises(RecordNotFound):
            service.get(identifier)
    assert report["cancelled_database_job_ids"] == [pending["id"]]


def test_separate_api_origin_accepts_async_headers_and_results_are_not_cached(settings, workspace):
    with TestClient(create_app(replace(settings, data_root=settings.data_root / "cors", allowed_origins=("https://workspace.example",)))) as client:
        response = client.options("/api/database-sources/demo/queries", headers={"Origin": "https://workspace.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,prefer,idempotency-key"})
        assert response.status_code == 200
    job = submit(workspace)
    wait_job(workspace.client, job["id"])
    for suffix in ("", "/result"):
        assert "no-store" in workspace.client.get(f"/api/database-jobs/{job['id']}{suffix}").headers["Cache-Control"]
    assert "no-store" in workspace.client.get("/api/database-jobs").headers["Cache-Control"]


def test_terminal_storage_failure_is_reconciled_without_reexecution(workspace, monkeypatch):
    service = workspace.runtime.database_jobs
    original, failures = service._save, []
    def save(db, job):
        if job["status"] in {"completed", "failed"} and len(failures) < 2:
            failures.append(job["status"])
            raise sqlite3.OperationalError("Simulated unavailable metadata store")
        original(db, job)
    monkeypatch.setattr(service, "_save", save)
    initial = len(workspace.calls)
    job = submit(workspace)
    interrupted = wait_job(workspace.client, job["id"], "interrupted")
    assert interrupted["error"]["code"] == "database_state_unknown"
    assert len(workspace.calls) == initial + 1
    assert failures == ["completed", "failed"]


def test_large_graph_row_sample_is_disclosed_without_truncating_snapshot(workspace, monkeypatch):
    from graphmine_agent import database_queries

    original = database_queries.execute_query
    def execute(*args):
        graph, lineage, _, count, table = original(*args)
        return graph, lineage, [{"note": "x" * 300_000}], count, table
    monkeypatch.setattr(database_queries, "execute_query", execute)
    job = submit(workspace)
    wait_job(workspace.client, job["id"])
    result = workspace.client.get(f"/api/database-jobs/{job['id']}/result").json()
    assert result["rows"] == [] and result["rows_truncated"]
    assert "limited by bytes" in result["row_sample_warning"]
    assert result["dataset"]["source_complete"] and result["vertex_count"] == 2


def test_async_table_result_reloads_exact_typed_snapshot(workspace, monkeypatch):
    from graphmine_agent import database_queries
    from graphmine_agent.table_artifacts import make_table

    original = database_queries.execute_query
    def execute(*args):
        graph, _, _, _, _ = original(*args)
        graph = {**graph, "vertices": [], "edges": []}
        table = make_table(["id", "key"], [{"id": 9007199254740993, "key": "001"}])
        return graph, {"vertices": {}, "edges": {}}, table["rows"], 1, table
    monkeypatch.setattr(database_queries, "execute_query", execute)
    job = submit(workspace)
    wait_job(workspace.client, job["id"])
    result = workspace.client.get(f"/api/database-jobs/{job['id']}/result").json()
    assert result["table"]["kind"] == "table" and result["dataset"] is None
    assert result["rows"] == [{"id": 9007199254740993, "key": "001"}]
    assert not result["rows_truncated"]


def test_finished_delivery_expires_without_removing_the_snapshot(workspace, monkeypatch):
    from graphmine_agent import database_jobs
    from graphmine_agent.query_previews import QueryPreviews
    job = submit(workspace)
    wait_job(workspace.client, job["id"])
    service = workspace.runtime.database_jobs
    metadata = service.result(job["id"])["dataset"]
    deadline = service._finished[job["id"]][0]
    service.cancel(job["id"])
    assert service._finished[job["id"]][0] == deadline
    expired = time.monotonic() + database_jobs.RESULT_TTL_SECONDS + 1
    monkeypatch.setattr(database_jobs, "time", SimpleNamespace(monotonic=lambda: expired))
    assert workspace.client.get(f"/api/database-jobs/{job['id']}").status_code == 404
    assert workspace.client.get(f"/api/database-jobs/{job['id']}/result").status_code == 404
    assert not service._finished
    assert QueryPreviews(workspace.runtime).get(metadata["id"])["sha256"] == metadata["sha256"]


@pytest.mark.parametrize("budget", ["count", "bytes"])
def test_temporary_delivery_memory_is_bounded(workspace, monkeypatch, budget):
    from graphmine_agent import database_jobs
    from graphmine_agent.database import Database
    runtime = SimpleNamespace(settings=workspace.runtime.settings, database=Database(workspace.runtime.settings.data_root / "delivery.sqlite3"))
    service = DatabaseJobs(runtime)
    first = service.enqueue("query", "demo", CypherRequest(**QUERY))
    service.cancel(first["id"])
    if budget == "count":
        monkeypatch.setattr(database_jobs, "MAX_RESULTS", 1)
    else:
        monkeypatch.setattr(database_jobs, "MAX_RESULT_BYTES", service._finished[first["id"]][3] + 100)
    second = service.enqueue("query", "demo", CypherRequest(**QUERY))
    service.cancel(second["id"])
    with pytest.raises(RecordNotFound):
        service.get(first["id"])
    assert service.get(second["id"])["status"] == "cancelled"
    with runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM database_jobs").fetchone()[0] == 0


def test_startup_removes_legacy_history_but_keeps_queued_work(workspace):
    from graphmine_agent.database import Database
    runtime = SimpleNamespace(settings=workspace.runtime.settings, database=Database(workspace.runtime.settings.data_root / "legacy.sqlite3"))
    service = DatabaseJobs(runtime)
    old = []
    for status in ("completed", "failed", "cancelled", "interrupted"):
        job = service.enqueue("query", "demo", CypherRequest(**QUERY))
        old.append(job["id"])
        with runtime.database._connect() as db:
            value = json.loads(db.execute("SELECT document FROM database_jobs WHERE id=?", (job["id"],)).fetchone()[0])
            value["status"] = status
            db.execute("UPDATE database_jobs SET status=?,document=? WHERE id=?", (status, json.dumps(value), job["id"]))
    queued = service.enqueue("query", "demo", CypherRequest(**QUERY))
    service.recover()
    assert [job["id"] for job in service.list()["items"]] == [queued["id"]]
    for identifier in old:
        with pytest.raises(RecordNotFound):
            service.get(identifier)
    with runtime.database._connect() as db:
        assert db.execute("SELECT count(*) FROM database_jobs").fetchone()[0] == 1
