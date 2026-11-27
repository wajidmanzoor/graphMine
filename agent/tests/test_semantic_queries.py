"""Snapshot ownership, queue lifecycle and publication through the existing API."""

from importlib import metadata
import json
from threading import Event
from types import SimpleNamespace

import pytest
from graphmine_agent.database import RecordNotFound
from graphmine_agent.database_job_context import checkpoint
from graphmine_agent.database_jobs import DatabaseJobs, MAX_OWNER_PENDING
from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.errors import AnalyticsError
from graphmine_agent.identity import Principal, identity_scope
from graphmine_agent.query_previews import QueryPreviews, expire_previews
from graphmine_agent.query_results import is_database_query
from graphmine_agent.semantic_queries import SemanticRequest
from test_database_jobs import wait_job
from test_database_workspace import source, workspace  # noqa: F401
from test_semantic_native import native_engine  # noqa: F401


@pytest.fixture(autouse=True)
def installed_distribution(monkeypatch):
    # Admission needs only metadata, never a native import. Real execution tests
    # separately require native_engine, preserving failure on an incompatible pin.
    original = metadata.version
    monkeypatch.setattr("graphmine_agent.semantic_queries.package_metadata", SimpleNamespace(
        version=lambda name: "0.1.0+62e124217e2c" if name == "graphmine-tento" else original(name),
        PackageNotFoundError=metadata.PackageNotFoundError))


def submit(workspace, key="semantic-first", **fields):
    body = {"base_version_id": workspace.snapshot["dataset"]["id"], "statement": "MATCH(n:Vertex) RETURN n", **fields}
    response = workspace.client.post("/api/semantic-queries", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    return response.json()["job"]


def hold_worker(monkeypatch):
    from graphmine_agent import semantic_queries
    original = semantic_queries.run_worker
    started, release = Event(), Event()
    def run(*args, **kwargs):
        started.set()
        while not release.wait(0.01):
            checkpoint("asking_model", usage={"calls": 3})
        return original(*args, **kwargs)
    monkeypatch.setattr(semantic_queries, "run_worker", run)
    return started, release


def test_refinement_preserves_parent_lineage_and_can_be_saved_or_opened_in_chat(workspace, native_engine):
    previews = QueryPreviews(workspace.runtime)
    base, before = previews.get(workspace.snapshot["dataset"]["id"], content=True)
    calls = len(workspace.calls)
    job = submit(workspace, statement="MATCH(n:Vertex) WHERE has_label(n,'Account') RETURN n LIMIT 1")
    wait_job(workspace.client, job["id"])
    result = workspace.client.get(f"/api/database-jobs/{job['id']}/result")
    assert result.status_code == 200, result.text
    output = result.json()
    snapshot = output["dataset"]
    assert snapshot["id"] != base["id"] and snapshot["sha256"] != base["sha256"]
    assert output["vertex_count"] == 1 and len(workspace.calls) == calls
    provenance = snapshot["source"]
    assert provenance["type"] == "semantic_query" and is_database_query(provenance)
    assert provenance["parent"]["version_id"] == base["id"] and provenance["base_sha256"] == base["sha256"]
    assert len(provenance["lineage"]["vertices"]) == 1 and not provenance["lineage"]["edges"]
    assert provenance["database_source"] == base["source"]["database_source"]
    assert provenance["model_dependent_input"] is False and provenance["simulation"] is False
    assert previews.get(base["id"], content=True)[1] == before
    assert workspace.client.post(f"/api/database-query-snapshots/{snapshot['id']}/save").status_code == 200
    opened = workspace.client.post(f"/api/database-query-snapshots/{snapshot['id']}/chat", json={})
    assert opened.status_code == 201, opened.text
    attached = workspace.runtime.database.get_file(opened.json()["file"]["id"])
    assert attached.provenance["source"]["parent"]["version_id"] == base["id"]
    # A derived snapshot remains a valid base without going back to Neo4j.
    follow = submit(workspace, "second-refinement", base_version_id=snapshot["id"], statement="MATCH(n) RETURN count(n) AS total")
    wait_job(workspace.client, follow["id"])
    assert workspace.client.get(f"/api/database-jobs/{follow['id']}/result").json()["rows"] == [{"total": 1}]
    assert len(workspace.calls) == calls


def test_explicit_mock_has_honest_usage_and_complete_scalar_artifact(workspace, native_engine):
    job = submit(workspace, model="mock", statement="UNWIND range(1,75) AS x RETURN x, llm('mock','Echo {{x}} {answer STRING}') AS answer")
    wait_job(workspace.client, job["id"])
    result = workspace.client.get(f"/api/database-jobs/{job['id']}/result").json()
    assert result["table"]["table"]["row_count"] == result["row_count"] == 75
    assert len(result["rows"]) == 50 and result["rows_truncated"]
    provenance = result["table"]["source"]
    assert provenance["simulation"] is True
    assert provenance["settings"]["provider"] == "mock"
    assert provenance["settings"]["http_requests"] == 0 and provenance["settings"]["answers_retained"] == 0
    assert provenance["settings"]["call_limit_scope"] == "per_expression"
    assert provenance["usage"]["calls"] > 0 and result["usage"] == provenance["usage"]
    raw = QueryPreviews(workspace.runtime).get(result["table"]["id"], content=True)[1]
    assert len(json.loads(raw)["rows"]) == 75


def test_schema_and_admission_reject_live_cache_writes_and_missing_support(workspace, monkeypatch):
    identifier = workspace.snapshot["dataset"]["id"]
    response = workspace.client.get(f"/api/database-query-snapshots/{identifier}/semantic-schema")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["schema"]["vertex_table"] == "Vertex"
    assert value["capabilities"]["live_queries"] is False
    for fields, code in [
        ({"statement": "RETURN llm('qwen','{answer STRING}')"}, "semantic_controls_unsupported"),
        ({"reuse_answers": True}, "semantic_cache_unsupported"),
        ({"statement": "MATCH(n) SET n.x=1 RETURN n"}, "semantic_read_only"),
        ({"projection": "rows", "weight_property": "amount"}, "query_projection"),
        ({"parameters": {"text": "x" * (256 * 1024)}}, "resource_limit"),
    ]:
        response = workspace.client.post("/api/semantic-queries", json={"base_version_id": identifier, "statement": "RETURN 1", **fields})
        assert response.json()["error"]["code"] == code, response.text
    def missing(_):
        raise metadata.PackageNotFoundError("graphmine-tento")
    monkeypatch.setattr("graphmine_agent.semantic_queries.package_metadata.version", missing)
    response = workspace.client.post("/api/semantic-queries", json={"base_version_id": identifier, "statement": "RETURN 1"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "semantic_unavailable"
    assert workspace.client.get("/api/database-jobs?kind=semantic").json()["items"] == []
    # Ordinary database queries still work without the optional engine.
    assert workspace.client.post("/api/database-sources/demo/queries", json={"statement": "RETURN 1"}).status_code == 201


def test_preview_is_leased_through_queue_expiry_and_released_after_cancel(workspace):
    client, runtime = workspace.client, workspace.runtime
    client.portal.call(runtime.database_jobs.stop)
    base, raw = QueryPreviews(runtime).get(workspace.snapshot["dataset"]["id"], content=True)
    preview = QueryPreviews(runtime).store(json.loads(raw), name="temporary base", kind="graph", source=base["source"], complete=True)
    job = submit(workspace, base_version_id=preview["id"])
    with runtime.database._connect() as db:
        db.execute("UPDATE query_previews SET expires_at=0 WHERE id=?", (preview["id"],))
    assert expire_previews(runtime.database) == 0
    assert QueryPreviews(runtime).get(preview["id"])["id"] == preview["id"]
    assert client.delete(f"/api/database-query-snapshots/{preview['id']}").status_code == 409
    assert client.delete(f"/api/database-jobs/{job['id']}").json()["status"] == "cancelled"
    assert expire_previews(runtime.database) == 1
    with pytest.raises(RecordNotFound):
        QueryPreviews(runtime).get(preview["id"])


def test_promoting_a_leased_preview_keeps_the_lease_on_the_saved_version(workspace):
    client, runtime = workspace.client, workspace.runtime
    client.portal.call(runtime.database_jobs.stop)
    base, raw = QueryPreviews(runtime).get(workspace.snapshot["dataset"]["id"], content=True)
    preview = QueryPreviews(runtime).store(json.loads(raw), name="temporary base", kind="graph", source=base["source"], complete=True)
    job = submit(workspace, base_version_id=preview["id"])
    assert client.post(f"/api/database-query-snapshots/{preview['id']}/save").status_code == 200
    with pytest.raises(AnalyticsError) as error:
        DatasetLibrary(runtime).delete(preview["id"])
    assert error.value.code == "snapshot_in_use"
    client.delete(f"/api/database-jobs/{job['id']}")
    DatasetLibrary(runtime).delete(preview["id"])


def test_running_cancel_and_explicit_retry_preserve_idempotency(workspace, monkeypatch, native_engine):
    started, release = hold_worker(monkeypatch)
    try:
        job = submit(workspace)
        assert started.wait(3)
        assert submit(workspace)["id"] == job["id"]
        conflict = workspace.client.post("/api/semantic-queries", json={"base_version_id": workspace.snapshot["dataset"]["id"], "statement": "RETURN 2"}, headers={"Idempotency-Key": "semantic-first"})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
        workspace.client.delete(f"/api/database-jobs/{job['id']}")
        wait_job(workspace.client, job["id"], "cancelled")
        with workspace.runtime.database._connect() as db:
            assert db.execute("SELECT count(*) FROM query_previews").fetchone()[0] == 0
    finally:
        release.set()
    retry = workspace.client.post(f"/api/database-jobs/{job['id']}/retry", headers={"Idempotency-Key": "retry"})
    assert retry.status_code == 202, retry.text
    retried = retry.json()["job"]
    wait_job(workspace.client, retried["id"])
    assert retried["id"] != job["id"]
    assert workspace.client.post(f"/api/database-jobs/{job['id']}/retry", headers={"Idempotency-Key": "retry"}).json()["job"]["id"] == retried["id"]


def test_queue_budget_and_restart_do_not_replay_running_semantics(workspace):
    client, service = workspace.client, workspace.runtime.database_jobs
    client.portal.call(service.stop)
    jobs = [submit(workspace, str(i)) for i in range(MAX_OWNER_PENDING)]
    response = client.post("/api/semantic-queries", json={"base_version_id": workspace.snapshot["dataset"]["id"], "statement": "RETURN 1"})
    assert response.status_code == 429 and response.json()["error"]["code"] == "database_queue_full"
    active = service._claim()
    restored = DatabaseJobs(workspace.runtime)
    restored.recover()
    assert restored.get(active["id"])["status"] == "interrupted"
    assert len(restored.list(kind="semantic")["items"]) == MAX_OWNER_PENDING - 1
    for job in jobs:
        if job["id"] != active["id"]:
            restored.cancel(job["id"])
    DatasetLibrary(workspace.runtime).delete(workspace.snapshot["dataset"]["id"])


def test_snapshot_execution_ignores_mapping_refresh_but_checks_input_integrity(workspace, native_engine):
    client, runtime = workspace.client, workspace.runtime
    client.portal.call(runtime.database_jobs.stop)
    job = submit(workspace)
    sources = json.loads(workspace.config.read_text())
    sources[0]["name"] = "Renamed after snapshot"
    workspace.config.write_text(json.dumps(sources))
    client.portal.call(runtime.database_jobs.start)
    wait_job(client, job["id"])
    client.portal.call(runtime.database_jobs.stop)
    bad = submit(workspace, "tampered")
    with runtime.database._connect() as db:
        db.execute("UPDATE dataset_versions SET content=? WHERE id=?", (b"{}", workspace.snapshot["dataset"]["id"]))
    client.portal.call(runtime.database_jobs.start)
    failed = wait_job(client, bad["id"], "failed")
    assert failed["error"]["code"] == "data_integrity"


def test_snapshot_schema_and_all_job_actions_are_owner_scoped(workspace):
    workspace.client.portal.call(workspace.runtime.database_jobs.stop)
    previews = QueryPreviews(workspace.runtime)
    base, raw = previews.get(workspace.snapshot["dataset"]["id"], content=True)
    accounts = SimpleNamespace(upload_remaining=lambda _: 100_000_000)
    service = DatabaseJobs(workspace.runtime)
    with identity_scope(Principal("alice", "alice", accounts)):
        own = previews.store(json.loads(raw), name="alice", kind="graph", source=base["source"], complete=True)
        job = service.enqueue("semantic", "demo", SemanticRequest(base_version_id=own["id"], statement="RETURN 1"))
    with identity_scope(Principal("bob", "bob", accounts)):
        from graphmine_agent.semantic_queries import snapshot_schema
        with pytest.raises(RecordNotFound):
            snapshot_schema(workspace.runtime, own["id"])
        with pytest.raises(RecordNotFound):
            service.enqueue("semantic", "demo", SemanticRequest(base_version_id=own["id"], statement="RETURN 1"))
        for action in (service.get, service.result, service.cancel, service.retry):
            with pytest.raises(RecordNotFound):
                action(job["id"])
        assert service.list(kind="semantic")["items"] == []
    with identity_scope(Principal("alice", "alice", accounts)):
        service.cancel(job["id"])
