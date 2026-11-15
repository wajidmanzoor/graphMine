"""Saved query ownership, bounded history, revisions, quota and error locations."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from graphmine_agent.analytics import AnalyticsError, _json
from graphmine_agent.api import create_app
from graphmine_agent.backup import online_snapshot, restore_snapshot
from graphmine_agent.database import Database, RecordNotFound
from graphmine_agent.database_queries import CypherRequest, execute_query
from graphmine_agent.identity import AccountError, Principal, identity_scope
from graphmine_agent.query_library import MAX_HISTORY, QueryLibrary, SaveQuery
from test_accounts import PASSWORD, account_settings
from test_database_query_projection import read_transaction
from test_database_workspace import source, workspace  # noqa: F401


def body(**options):
    return SaveQuery(source_id="demo", name="Account links", query=CypherRequest(statement="MATCH (n) RETURN n LIMIT $limit", parameters={"limit": 10}, dataset_id="default"), **options)


def test_saved_queries_update_with_revision_and_delete_without_execution(workspace):
    client = workspace.client
    before = len(workspace.calls)
    created = client.post("/api/query-library", json=body().model_dump())
    assert created.status_code == 201, created.text
    item = created.json(); path = "/api/query-library/" + item["id"]
    listing = client.get("/api/query-library", params={"source_id": "demo", "dataset_id": "default"}).json()
    assert listing["items"][0]["id"] == item["id"]
    assert "query" not in listing["items"][0]  # paging is metadata-only
    assert client.get(path).json()["query"]["parameters"] == {"limit": 10}
    updated = body(expected_revision=1).model_dump()
    updated["name"] = "Renamed"
    assert client.put(path, json=updated).json()["revision"] == 2
    assert client.put(path, json=updated).status_code == 409
    assert client.delete(path + "?revision=1").status_code == 409
    assert client.delete(path + "?revision=2").status_code == 204
    assert client.get(path).status_code == 404
    assert len(workspace.calls) == before


def test_saved_queries_and_history_never_cross_owners(workspace):
    library = QueryLibrary(workspace.runtime)
    accounts = SimpleNamespace(upload_remaining=lambda _: 10**9)
    with identity_scope(Principal("alice", "alice", accounts)):
        saved = library.save(body())
        history, warning = library.record("demo", body().query)
        assert warning is None
    with identity_scope(Principal("bob", "bob", accounts)):
        assert library.list()["items"] == []
        assert library.list(kind="history")["items"] == []
        for identifier in (saved["id"], history):
            with pytest.raises(RecordNotFound):
                library.get(identifier)
            with pytest.raises(RecordNotFound):
                library.delete(identifier, 1)
        with pytest.raises(RecordNotFound):
            library.save(body(expected_revision=1), saved["id"])


def test_history_is_bounded_and_paged_and_does_not_retain_result_payloads(workspace):
    library = QueryLibrary(workspace.runtime)
    first = None
    for index in range(MAX_HISTORY + 3):
        query = body().query.model_copy(update={"parameters": {"limit": index}})
        identifier, warning = library.record("demo", query, result={"row_count": index, "rows": ["bulk result"]})
        assert warning is None
        first = first or identifier
    with pytest.raises(RecordNotFound):
        library.get(first)
    page = library.list(kind="history", limit=70)
    second = library.list(kind="history", offset=70, limit=70)
    third = library.list(kind="history", offset=140, limit=70)
    assert page["has_more"] and second["has_more"] and not third["has_more"]
    ids = [entry["id"] for part in (page, second, third) for entry in part["items"]]
    assert len(set(ids)) == MAX_HISTORY
    assert "rows" not in library.get(ids[0])


def test_query_execution_records_success_and_failure(workspace, monkeypatch):
    library = QueryLibrary(workspace.runtime)
    first = library.list(kind="history")["items"][0]
    assert library.get(first["id"])["snapshot_id"] == workspace.snapshot["dataset"]["id"]
    def failed(*_):
        raise AnalyticsError("Bad query", "cypher_syntax", details={"line": 2, "column": 4, "offset": 17})
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", failed)
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "MATCH (n)\nRETURN typo(n)"})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"line": 2, "column": 4, "offset": 17}
    failed_entry = library.get(library.list(kind="history")["items"][0]["id"])
    assert failed_entry["status"] == "failed" and failed_entry["error"]["code"] == "cypher_syntax"


def test_history_failure_does_not_lose_successful_preview(workspace, monkeypatch):
    def full(*_, **__):
        raise AccountError("Storage full", "storage_limit")
    monkeypatch.setattr(QueryLibrary, "_put", full)
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "MATCH (n) RETURN n"})
    assert response.status_code == 201, response.text
    assert response.json()["dataset"]["temporary"]
    assert "Storage full" in response.json()["history_warning"]


def test_empty_query_error_is_not_hidden_by_history(workspace, monkeypatch):
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute_query)
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "  \n "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "cypher_read_only"
    entry = QueryLibrary(workspace.runtime).list(kind="history")["items"][0]
    assert entry["name"] == "Empty query" and entry["status"] == "failed"


def test_nonfinite_parameters_are_rejected_when_saved_or_executed(workspace, source):
    invalid = body(); invalid.query.parameters = {"value": float("nan")}
    with pytest.raises(AnalyticsError, match="finite JSON"):
        QueryLibrary(workspace.runtime).save(invalid)
    with pytest.raises(AnalyticsError, match="finite JSON"):
        execute_query(source, invalid.query, 100_000)


def test_query_storage_is_counted_and_update_credits_previous_document(account_settings, source, monkeypatch):
    monkeypatch.setattr("graphmine_agent.query_library.get_source", lambda *_: source)
    with TestClient(create_app(account_settings)) as client:
        runtime = client.app.state.runtime
        user = runtime.accounts.create_user("alice", PASSWORD)
        with identity_scope(Principal(user["id"], "alice", runtime.accounts)):
            library = QueryLibrary(runtime)
            item = library.save(body())
            usage = runtime.accounts.storage_usage(user["id"])
            assert usage["used"] == usage["queries"] == len(_json(item).encode())
            monkeypatch.setattr(runtime.accounts, "upload_remaining", lambda _: 0)
            with pytest.raises(AccountError):
                library.save(body())
            updated = library.save(body(expected_revision=1), item["id"])
            assert updated["revision"] == 2
            identifier, warning = library.record("demo", body().query)
            assert identifier is None and "allowance" in warning


def test_neo4j_syntax_error_exposes_editor_position(source, monkeypatch):
    error = RuntimeError()
    error.code = "Neo.ClientError.Statement.SyntaxError"
    error.message = 'Invalid input (line 2, column 4 (offset: 17))'
    read_transaction(monkeypatch, [], error=error)
    with pytest.raises(AnalyticsError) as raised:
        execute_query(source, body().query, 100_000)
    assert raised.value.details == {"line": 2, "column": 4, "offset": 17}


def test_online_backup_restores_saved_queries_and_history(workspace, tmp_path):
    library = QueryLibrary(workspace.runtime)
    saved = library.save(body())
    history = library.list(kind="history")["items"][0]["id"]
    backup = tmp_path / "backup"
    online_snapshot(workspace.runtime.settings.data_root, backup)
    restored = restore_snapshot(backup, tmp_path / "restored")
    recovered = QueryLibrary(SimpleNamespace(database=Database(Path(restored["data_root"]) / "agent.sqlite3")))
    assert recovered.get(saved["id"]) == saved
    assert recovered.get(history) == library.get(history)
