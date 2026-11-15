"""Complete scalar tables retain types, provenance, ownership and reusable rows."""

import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from neo4j import Record

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.backup import online_snapshot, restore_snapshot
from graphmine_agent.database import Database, RecordNotFound
from graphmine_agent.database_queries import CypherRequest, execute_query
from graphmine_agent.datasets import DatasetLibrary
from graphmine_agent.identity import Principal, identity_scope
from graphmine_agent.query_previews import QueryPreviews
from graphmine_agent.table_artifacts import TableArtifacts, make_table
from test_database_query_projection import read_transaction
from test_database_workspace import source, workspace  # noqa: F401


def records(count=125):
    return [Record({"source": 9007199254740993 + index, "target": f"{index:03d}", "amount": index + 0.5,
                    "note": '=1+1' if index == 0 else 'line one\nline "two"', "optional": None,
                    "active": True, "details": {"index": index}}) for index in range(count)]


def query_table(workspace, monkeypatch, rows=None, columns=None):
    read_transaction(monkeypatch, records() if rows is None else rows, columns=columns)
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute_query)
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "RETURN $source AS source, $target AS target", "parameters": {"source": 9007199254740993, "target": "001"}})
    assert response.status_code == 201, response.text
    return response.json()


def test_all_rows_are_stored_and_paged_with_exact_types(workspace, monkeypatch):
    result = query_table(workspace, monkeypatch)
    assert result["dataset"] is None and result["row_count"] == 125
    assert len(result["rows"]) == 50 and result["rows_truncated"]
    table = result["table"]
    assert table["kind"] == "table" and table["temporary"]
    assert table["table"]["row_count"] == 125
    assert table["source"]["parameters"]["source"] == 9007199254740993
    path = f"/api/database-query-snapshots/{table['id']}/table"
    page = workspace.client.get(path, params={"offset": 100, "limit": 50}).json()
    assert len(page["rows"]) == 25 and not page["has_more"]
    assert page["rows"][-1]["source"] == 9007199254741117
    assert page["rows"][0]["target"] == "100"
    assert page["rows"][0]["optional"] is None and page["rows"][0]["active"] is True
    assert page["rows"][0]["details"] == {"index": 100}
    assert page["complete"] and page["sha256"] == table["sha256"]
    assert workspace.client.get(path, params={"limit": 501}).status_code == 422
    assert workspace.client.get(path, params={"sort": "amount; DROP TABLE sessions"}).status_code == 422


def test_sorting_covers_full_result_and_keeps_nulls_last_and_ties_stable(workspace, monkeypatch):
    rows = [Record({"key": "null", "value": None}), Record({"key": "small", "value": 2}),
            Record({"key": "first", "value": 10}), Record({"key": "second", "value": 10})]
    result = query_table(workspace, monkeypatch, rows)
    service = TableArtifacts(workspace.runtime)
    assert [r["key"] for r in service.page(result["table"]["id"], sort="value")["rows"]] == ["small", "first", "second", "null"]
    assert [r["key"] for r in service.page(result["table"]["id"], sort="value", direction="desc")["rows"]] == ["first", "second", "small", "null"]


def test_csv_and_json_export_all_rows_without_rerunning_query(workspace, monkeypatch):
    result = query_table(workspace, monkeypatch)
    path = f"/api/database-query-snapshots/{result['table']['id']}/table"
    def rerun(*_):
        raise AssertionError("Exports must only read the stored table")
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", rerun)
    response = workspace.client.get(path + "/csv", params={"sort": "amount", "direction": "desc"})
    assert response.status_code == 200
    assert response.content.count(b"\xef\xbb\xbf") == 1
    assert "attachment" in response.headers["Content-Disposition"]
    exported = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(exported) == 125
    assert exported[0]["source"] == "9007199254741117"
    assert exported[-1]["note"] == "'=1+1"
    assert exported[-1]["optional"] == "null" and exported[-1]["active"] == "true"
    assert exported[0]["note"] == 'line one\nline "two"'
    exact = workspace.client.get(path + "/json").json()
    assert exact["rows"][0]["source"] == 9007199254740993
    assert exact["rows"][0]["target"] == "000" and exact["rows"][0]["note"] == "=1+1"
    assert exact["rows"][0]["optional"] is None and exact["rows"][0]["active"] is True


def test_empty_table_preserves_columns_for_export(workspace, monkeypatch):
    result = query_table(workspace, monkeypatch, [], columns=["source", "target"])
    assert result["table"]["table"]["row_count"] == 0
    assert result["message"].startswith("No rows matched.")
    response = workspace.client.get(f"/api/database-query-snapshots/{result['table']['id']}/table/csv")
    assert response.content.decode("utf-8-sig") == "source,target\r\n"


def test_saved_table_import_keeps_types_and_entire_query_provenance(workspace, monkeypatch):
    result = query_table(workspace, monkeypatch)
    snapshot = result["table"]
    response = workspace.client.post(f"/api/database-query-snapshots/{snapshot['id']}/chat", json={})
    assert response.status_code == 201, response.text
    value = response.json(); assert value["kind"] == "table"
    metadata, raw = DatasetLibrary(workspace.runtime).get(snapshot["id"], content=True)
    assert not metadata.get("temporary") and metadata["sha256"] == snapshot["sha256"]
    record = workspace.runtime.database.get_file(value["file"]["id"])
    assert record.role.value == "attachment" and Path(record.source_path).read_bytes() == raw
    assert record.provenance["source"] == snapshot["source"]
    schema = workspace.client.get(f"/api/sessions/{value['session']['id']}/tables/{record.id}/schema").json()
    assert schema["row_count"] == 125 and schema["columns"][0]["type"] == "integer"
    assert schema["sample"][0]["source"] == 9007199254740993


def test_query_table_projection_receives_full_rows_and_retains_source(workspace, monkeypatch):
    result = query_table(workspace, monkeypatch)
    response = workspace.client.post(f"/api/sessions/{workspace.session['id']}/datasets/{result['table']['id']}/import")
    assert response.status_code == 201, response.text
    file = response.json()["file"]
    called = []
    async def native(runtime, value, input_bytes, *, device):
        called.append(value)
        rows = value["tables"]["query"]["data"]["rows"]
        assert len(rows) == 125 and rows[0]["source"] == "9007199254740993"
        assert rows[0]["target"] == "000" and rows[0]["optional"] == ""
        assert rows[0]["details"] == '{"index":0}'
        return {"graph": {"graph": {"id": "projected", "directed": True, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [{"id": 9007199254740993}, {"id": "000"}],
                          "edges": [{"id": "e", "source": 9007199254740993, "target": "000", "weight": 0.5}]},
                "provenance": {"retained_rows": 125, "edge_count": 1}, "complete": True, "allocation": {"device": device}}
    monkeypatch.setattr("graphmine_agent.analytics_projection.native_request", native)
    body = {"tables": {"query": file["id"]}, "projection": {"version": 1, "edge_table": "query", "source": {"field": "query.source", "type": "integer"}, "target": {"field": "query.target", "type": "string"}}}
    projected = workspace.client.post(f"/api/sessions/{workspace.session['id']}/projections", json=body)
    assert projected.status_code == 201, projected.text
    provenance = projected.json()["file"]["provenance"]["tables"]["query"]
    assert provenance["reader"] == "query_table_json"
    assert provenance["source"]["version_id"] == result["table"]["id"]
    assert provenance["source"]["source"]["query"] == result["table"]["source"]["query"]
    other = workspace.client.post("/api/sessions", json={}).json()["id"]
    assert workspace.client.post(f"/api/sessions/{other}/projections", json=body).status_code == 422
    assert workspace.client.post(f"/api/sessions/{workspace.session['id']}/projections", json={**body, "device": "gpu"}).status_code == 422
    assert len(called) == 1


def test_private_table_paging_and_exports_cannot_read_another_owner(workspace):
    preview = QueryPreviews(workspace.runtime)
    accounts = SimpleNamespace(upload_remaining=lambda _: 10**9)
    with identity_scope(Principal("alice", "alice", accounts)):
        snapshot = preview.store(make_table(["value"], [{"value": "private"}]), name="Private", kind="table", source={}, complete=True)
    with identity_scope(Principal("bob", "bob", accounts)):
        for read in (TableArtifacts(workspace.runtime).load, TableArtifacts(workspace.runtime).page, preview.promote):
            with pytest.raises(RecordNotFound):
                read(snapshot["id"])
    with identity_scope(Principal("alice", "alice", accounts)):
        assert TableArtifacts(workspace.runtime).page(snapshot["id"])["rows"] == [{"value": "private"}]


def test_expired_or_corrupt_tables_are_not_exported(workspace, monkeypatch):
    snapshot = query_table(workspace, monkeypatch)["table"]
    # A cached page must not hide corruption introduced after indexing.
    assert TableArtifacts(workspace.runtime).page(snapshot["id"])["row_count"] == 125
    with workspace.runtime.database._connect() as db:
        db.execute("UPDATE query_preview_blobs SET content=? WHERE sha256=?", (b"corrupt", snapshot["sha256"]))
    path = f"/api/database-query-snapshots/{snapshot['id']}/table"
    assert workspace.client.get(path).status_code == 409
    assert workspace.client.get(path + "/csv").status_code == 409
    with workspace.runtime.database._connect() as db:
        db.execute("UPDATE query_previews SET expires_at=0 WHERE id=?", (snapshot["id"],))
    assert workspace.client.get(path).status_code == 410


def test_warm_table_pages_do_not_read_content_and_promotion_delete_remain_safe(workspace, monkeypatch):
    from graphmine_agent.result_index import table_index_path

    snapshot = query_table(workspace, monkeypatch)["table"]
    service = TableArtifacts(workspace.runtime)
    assert service.page(snapshot["id"], offset=120)["rows"][-1]["source"] == 9007199254741117
    def forbidden(*_, **__):
        raise AssertionError("Warm pages must not load the source table")
    with monkeypatch.context() as patch:
        patch.setattr(service, "load", forbidden)
        assert service.page(snapshot["id"], sort="amount", direction="desc", limit=2)["rows"][0]["amount"] == 124.5
    QueryPreviews(workspace.runtime).promote(snapshot["id"])
    assert service.page(snapshot["id"], offset=124)["rows"][0]["amount"] == 124.5
    cache = table_index_path(workspace.runtime.database, snapshot["id"])
    assert cache.is_file()
    DatasetLibrary(workspace.runtime).delete(snapshot["id"])
    assert not cache.exists()
    with pytest.raises(RecordNotFound):
        service.page(snapshot["id"])


def test_preview_discard_expiry_and_changed_claimed_hash_invalidate_indexes(workspace, monkeypatch):
    from graphmine_agent.query_previews import expire_previews
    from graphmine_agent.result_index import table_index_path

    for action in ("discard", "expire", "hash"):
        snapshot = query_table(workspace, monkeypatch)["table"]
        TableArtifacts(workspace.runtime).page(snapshot["id"])
        path = table_index_path(workspace.runtime.database, snapshot["id"])
        assert path.exists()
        if action == "discard":
            QueryPreviews(workspace.runtime).discard(snapshot["id"])
            assert not path.exists()
        elif action == "expire":
            expire_previews(workspace.runtime.database, now=10**12)
            assert not path.exists()
        else:
            with workspace.runtime.database._connect() as db:
                db.execute("UPDATE query_previews SET metadata=json_set(metadata,'$.sha256','wrong') WHERE id=?", (snapshot["id"],))
            with pytest.raises(AnalyticsError, match="integrity"):
                TableArtifacts(workspace.runtime).page(snapshot["id"])


def test_query_table_backup_restores_full_content(workspace, monkeypatch, tmp_path):
    snapshot = query_table(workspace, monkeypatch)["table"]
    online_snapshot(workspace.runtime.settings.data_root, tmp_path / "backup")
    restored = restore_snapshot(tmp_path / "backup", tmp_path / "restore")
    runtime = SimpleNamespace(database=Database(Path(restored["data_root"]) / "agent.sqlite3"))
    assert TableArtifacts(runtime).page(snapshot["id"], offset=120)["rows"][-1]["source"] == 9007199254741117


def test_table_collection_still_enforces_query_limits(source, monkeypatch):
    read_transaction(monkeypatch, records(3))
    with pytest.raises(AnalyticsError, match="row limit"):
        execute_query(source.model_copy(update={"max_rows": 2}), CypherRequest(statement="RETURN 1"), 100_000)
    with pytest.raises(AnalyticsError, match="byte limit"):
        execute_query(source, CypherRequest(statement="RETURN 1"), 100)
