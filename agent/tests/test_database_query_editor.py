"""Direct Cypher survives removal of saved queries and guided generation."""

import pytest
from neo4j import Record

from graphmine_agent.analytics import AnalyticsError, _key
from graphmine_agent.database_queries import CypherRequest, execute_query
from test_database_query_projection import read_transaction
from test_database_workspace import driver_path, source, workspace  # noqa: F401


@pytest.mark.parametrize("method,path", [
    ("get", "/api/query-library"), ("post", "/api/query-library"),
    ("get", "/api/query-library/old-query"), ("put", "/api/query-library/old-query"),
    ("delete", "/api/query-library/old-query"),
    ("get", "/api/database-sources/demo/graph-builder"),
    ("post", "/api/database-sources/demo/graph-builder"),
])
def test_removed_features_have_no_routes(workspace, method, path):
    before = len(workspace.calls)
    # Unregistered writes reach the static mount, which rejects them with 405.
    assert getattr(workspace.client, method)(path).status_code == (404 if method == "get" else 405)
    routes = workspace.client.app.openapi()["paths"]
    assert "/api/query-library" not in routes
    assert "/api/query-library/{identifier}" not in routes
    assert "/api/database-sources/{source_id}/graph-builder" not in routes
    assert len(workspace.calls) == before


def test_direct_query_and_errors_need_no_library_storage(workspace, monkeypatch):
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "MATCH (n) RETURN n"})
    assert response.status_code == 201, response.text
    assert response.json()["dataset"]["temporary"]
    assert "history_id" not in response.json() and "history_warning" not in response.json()
    def failed(*_):
        raise AnalyticsError("Bad query", "cypher_syntax", details={"line": 2, "column": 4, "offset": 17})
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", failed)
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "MATCH (n) RETURN typo(n)"})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"line": 2, "column": 4, "offset": 17}
    with workspace.runtime.database._connect() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='query_library'").fetchone() is None
    assert workspace.client.get("/api/workspace/recent/queries").status_code == 422


def test_empty_query_keeps_its_validation_error(workspace, monkeypatch):
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute_query)
    response = workspace.client.post("/api/database-sources/demo/queries", json={"statement": "  \n "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "cypher_read_only"


def test_nonfinite_query_parameters_are_rejected(source):
    query = CypherRequest(statement="RETURN $value", parameters={"value": float("nan")})
    with pytest.raises(AnalyticsError, match="finite JSON"):
        execute_query(source, query, 100_000)


def test_neo4j_syntax_error_exposes_editor_position(source, monkeypatch):
    error = RuntimeError()
    error.code = "Neo.ClientError.Statement.SyntaxError"
    error.message = 'Invalid input (line 2, column 4 (offset: 17))'
    read_transaction(monkeypatch, [], error=error)
    with pytest.raises(AnalyticsError) as raised:
        execute_query(source, CypherRequest(statement="MATCH (n) RETURN n"), 100_000)
    assert raised.value.details == {"line": 2, "column": 4, "offset": 17}


def test_custom_weight_keeps_original_relationship_identity_and_lineage(source, monkeypatch):
    path = driver_path(source)
    path.relationships[0]._properties["amount"] = 25
    read_transaction(monkeypatch, [Record({"p": path})])
    graph, lineage, _, _, _ = execute_query(source, CypherRequest(statement="MATCH p=()-[]->() RETURN p", weight_property="amount"), 100_000)
    edge = graph["edges"][0]
    assert edge["weight"] == 25
    assert lineage["edges"][_key(edge["id"])]["mapping"] == "transfers"


@pytest.mark.parametrize("value", [None, "25", True, float("inf"), float("nan")])
def test_custom_weights_require_every_relationship_to_be_numeric(source, monkeypatch, value):
    path = driver_path(source)
    path.relationships[0]._properties["amount"] = value
    read_transaction(monkeypatch, [Record({"p": path})])
    with pytest.raises(AnalyticsError, match="finite numeric"):
        execute_query(source, CypherRequest(statement="MATCH p=()-[]->() RETURN p", weight_property="amount"), 100_000)


def test_custom_weights_cannot_conflict_with_row_projection(source):
    with pytest.raises(AnalyticsError, match="weight column"):
        execute_query(source, CypherRequest(statement="RETURN 1", weight_property="amount", projection="rows"), 100_000)
