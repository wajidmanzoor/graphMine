"""Backend isolation preserves records, bytes and ordinary uploaded inputs."""

import json
from pathlib import Path
import sqlite3

import pytest

from graphmine_agent.api import build_runtime
from graphmine_agent.database import Database, RecordNotFound
from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.models import ConversationEvent, FileRole, SessionRecord, StoredFile
from graphmine_agent.neo4j_backend import IU_URI, set_active_backend
from graphmine_agent.neo4j_records import migrate_connections, migrate_workflows, worker_backend
from graphmine_agent.query_previews import QueryPreviews
from graphmine_agent.table_artifacts import TableArtifacts, make_table
from test_database_workspace import workspace, source  # noqa: F401


def workflow(runtime, file, session):
    record = {"id": "backend-workflow", "session_id": session, "revision": 1, "status": "completed",
        "mode": "manual", "created_at": "2026-01-01T00:00:00+00:00", "input_provenance": {"graph": {**file["provenance"], "file_id": file["id"]}},
        "input_files": {"graph": {"kind": "graph", "file_id": file["id"]}}, "validation": {"plan": {"steps": []}}, "steps": {}}
    runtime.analytics._save(record)
    path = runtime.analytics._directory(record) / "result.json"
    runtime.analytics._write(path, {"result": {"ports": {}}, "complete": True})
    return record, path


def test_switch_hides_and_restores_sources_datasets_files_workflows_and_warm_table_index(workspace, triangle_graph):
    w, runtime = workspace, workspace.runtime
    values = json.loads(w.config.read_text())
    values.append({"id": "iu", "name": "IU", "users": ["*"], "neo4j_uri": IU_URI, "auth_disabled": True})
    w.config.write_text(json.dumps(values))
    library = DatasetLibrary(runtime)
    upload = library.store(json.loads(triangle_graph), name="Ordinary upload", kind="graph", source={"type": "upload"}, complete=True)
    table = QueryPreviews(runtime).store(make_table(["name"], [{"name": "local-only"}]), name="Local table", kind="table",
                                         source={"type": "database_query", "backend_id": "local"}, complete=True)
    assert TableArtifacts(runtime).page(table["id"])["rows"] == [{"name": "local-only"}]
    record, path = workflow(runtime, w.file, w.session["id"])
    raw_result = path.read_bytes()
    snapshot = w.snapshot["dataset"]["id"]
    assert {row["id"] for row in w.client.get("/api/database-sources").json()} == {"demo"}
    set_active_backend(runtime.settings, "iu-remote")
    assert {row["id"] for row in w.client.get("/api/database-sources").json()} == {"iu"}
    assert [row["id"] for row in library.list()] == [upload["id"]]
    assert library.page(search="local")["items"] == []
    assert runtime.database.list_files(w.session["id"]) == []
    assert runtime.analytics.list(w.session["id"], summary=True) == []
    assert runtime.analytics.list(w.session["id"]) == []
    assert w.client.get("/api/workspace/recent/analyses").json()["items"] == []
    for operation in (lambda: library.get(snapshot), lambda: runtime.database.get_file(w.file["id"]),
                      lambda: runtime.analytics.get(record["id"]), lambda: runtime.analytics.result(record["id"]),
                      lambda: TableArtifacts(runtime).page(table["id"]), lambda: QueryPreviews(runtime).promote(table["id"]),
                      lambda: QueryPreviews(runtime).discard(table["id"])):
        with pytest.raises(RecordNotFound):
            operation()
    for route in ("/api/database-sources/demo", "/api/database-sources/demo/settings",
                  f"/api/database-query-snapshots/{table['id']}/table", f"/api/workflows/{record['id']}"):
        response = w.client.get(route)
        assert response.status_code == 404, (route, response.text)
        assert "local-only" not in response.text
    set_active_backend(runtime.settings, "local")
    assert {row["id"] for row in library.list()} == {upload["id"], snapshot}
    assert runtime.database.get_file(w.file["id"]).backend_id == "local"
    assert runtime.analytics.result(record["id"])["backend_id"] == "local"
    assert path.read_bytes() == raw_result
    assert w.client.get("/api/workspace/recent/analyses").json()["items"][0]["id"] == record["id"]
    assert TableArtifacts(runtime).page(table["id"])["rows"] == [{"name": "local-only"}]


def test_remote_snapshots_are_tagged_and_ordinary_uploads_remain_visible(workspace, triangle_graph):
    runtime = workspace.runtime
    set_active_backend(runtime.settings, "iu-remote")
    library = DatasetLibrary(runtime)
    remote = library.store(json.loads(triangle_graph), name="Remote", kind="graph",
                           source={"type": "database_query", "backend_id": "iu-remote"}, complete=True)
    upload = library.store(json.loads(triangle_graph), name="Upload", kind="graph", source={"type": "upload"}, complete=True)
    assert remote["backend_id"] == "iu-remote" and upload.get("backend_id") is None
    with pytest.raises(RecordNotFound):
        library.store(json.loads(triangle_graph), name="Wrong backend", kind="graph",
                      source={"type": "database_query", "backend_id": "local"}, complete=True)
    set_active_backend(runtime.settings, "local")
    with pytest.raises(RecordNotFound):
        library.get(remote["id"])
    assert library.get(upload["id"])["id"] == upload["id"]


def test_events_and_already_admitted_analytics_keep_their_backend(workspace):
    w = workspace
    record, _ = workflow(w.runtime, w.file, w.session["id"])
    w.runtime.database.add_event(ConversationEvent(session_id=w.session["id"], type="workflow.answer",
                                                  payload={"workflow_id": record["id"], "answer": "local evidence"}))
    assert w.runtime.database.events(w.session["id"])[-1].payload["backend_id"] == "local"
    set_active_backend(w.runtime.settings, "iu-remote")
    assert not any(row.type == "workflow.answer" for row in w.runtime.database.events(w.session["id"]))
    with worker_backend("local"):
        assert w.runtime.database.get_file(w.file["id"]).backend_id == "local"
        assert w.runtime.analytics.get(record["id"])["backend_id"] == "local"
    with pytest.raises(RecordNotFound):
        w.runtime.database.get_file(w.file["id"])


def test_migration_tags_legacy_metadata_without_rewriting_graph_or_result_bytes(settings, triangle_graph):
    runtime = build_runtime(settings)
    session = runtime.database.create_session(SessionRecord(domain_id="general"))
    file = runtime.database.add_file(StoredFile(session_id=session.id, role=FileRole.graph, original_name="query.json",
        source_path="/retained/data.json", sha256="a" * 64, size_bytes=len(triangle_graph),
        provenance={"source": {"type": "database_query", "database_source": {"id": "old-local"}}}))
    version = DatasetLibrary(runtime).store(json.loads(triangle_graph), name="Legacy", kind="graph", source=file.provenance["source"], complete=True)
    record, path = workflow(runtime, file.model_dump(), session.id)
    raw = path.read_bytes()
    with runtime.database._connect() as db:
        db.execute("UPDATE files SET payload=json_remove(payload,'$.backend_id')")
        db.execute("UPDATE dataset_versions SET metadata=json_remove(metadata,'$.backend_id')")
        db.execute("CREATE TABLE query_library (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
        db.execute("INSERT INTO query_library VALUES ('retained-query',?)", (json.dumps({"statement": "RETURN 1"}),))
        db.execute("PRAGMA user_version=12")
    with sqlite3.connect(runtime.analytics.path) as db:
        db.execute("UPDATE workflows SET document=json_remove(document,'$.backend_id')")
        db.execute("DELETE FROM neo4j_result_backends")
    reopened = Database(settings.database_path)
    assert reopened.get_file(file.id).backend_id == "local"
    migrate_workflows(runtime.analytics)
    with reopened._connect() as db:
        row = db.execute("SELECT metadata,content FROM dataset_versions WHERE id=?", (version["id"],)).fetchone()
        assert json.loads(row[0])["backend_id"] == "local"
        assert json.loads(row[1]) == json.loads(triangle_graph)
        saved = db.execute("SELECT document,backend_id FROM query_library").fetchone()
        assert json.loads(saved[0]) == {"statement": "RETURN 1", "backend_id": "local"} and saved[1] == "local"
    assert runtime.analytics.get(record["id"])["backend_id"] == "local" and path.read_bytes() == raw
    with sqlite3.connect(runtime.analytics.path) as db:
        assert db.execute("SELECT backend_id FROM neo4j_result_backends").fetchone()[0] == "local"
    # A repeated migration is harmless and never relabels old work to the default IU backend.
    set_active_backend(settings, "iu-remote")
    migrate_workflows(runtime.analytics)
    assert DatasetLibrary(runtime).list() == []
    assert path.read_bytes() == raw


def test_legacy_connection_file_migration_preserves_its_other_fields(settings):
    path = settings.data_root / "database-connections" / "owner" / "source.json"
    path.parent.mkdir(parents=True)
    value = {"source": {"id": "old-local"}, "sql": {"unchanged": True}, "neo4j_password": "generated-test-value"}
    path.write_text(json.dumps(value)); path.chmod(0o600)
    migrate_connections(settings)
    assert json.loads(path.read_text()) == {**value, "source": {"id": "old-local", "backend_id": "local"}}
    assert path.stat().st_mode & 0o777 == 0o600


def test_history_bundle_hides_inactive_evidence_and_restores_it(workspace):
    w = workspace
    record, path = workflow(w.runtime, w.file, w.session["id"])
    raw = path.read_bytes()
    routes = [f"/api/sessions/{w.session['id']}/history", f"/api/sessions/{w.session['id']}/history/archive"]
    for route in routes:
        assert w.client.get(route).status_code == 200
    set_active_backend(w.runtime.settings, "iu-remote")
    for route in routes:
        response = w.client.get(route)
        assert response.status_code == 404, response.text
    page = w.client.get(f"/api/sessions/{w.session['id']}/events?paged=true").json()
    assert page["active_backend"] == "iu-remote"
    set_active_backend(w.runtime.settings, "local")
    for route in routes:
        assert w.client.get(route).status_code == 200
    assert path.read_bytes() == raw


def test_mixed_provenance_is_never_treated_as_an_upload(settings):
    from graphmine_agent.neo4j_records import derived_backend, tagged, visible
    value = {"input_provenance": {"a": {"backend_id": "local"}, "b": {"backend_id": "iu-remote"}}}
    assert not visible(value, settings)
    with pytest.raises(RecordNotFound):
        tagged(value)
    assert derived_backend({"file_id": {"untrusted": True}}, {}) is None
    from graphmine_agent.neo4j_records import backend_id
    assert backend_id({"tables": {"main": {"source": {"type": "database_query", "backend_id": "local"}}}}) == "local"
