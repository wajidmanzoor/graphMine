"""Query rows become derived graph edges without writing to the source."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from neo4j import Record

from graphmine_agent.analytics import AnalyticsError, _key
from graphmine_agent.database_queries import CypherRequest, execute_query
from test_database_workspace import driver_path, source, workspace  # noqa: F401


def read_transaction(monkeypatch, records, columns=None, error=None):
    class Result(list):
        def keys(self):
            return columns if columns is not None else list(records[0].keys()) if records else []

        def consume(self):
            return SimpleNamespace(query_type="r")

    class Transaction:
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def run(self, statement, parameters):
            if error:
                raise error
            return Result() if statement.startswith("EXPLAIN ") else Result(records)

        def rollback(self):
            self.rolled_back = True

    transaction = Transaction()

    @contextmanager
    def session(_):
        yield SimpleNamespace(begin_transaction=lambda **_: transaction)

    monkeypatch.setattr("graphmine_agent.database_queries.neo4j_session", session)
    return transaction


def request(**options):
    return CypherRequest(
        statement="MATCH (a)-[]->(b) RETURN a AS source, b AS target, 2 AS weight",
        **{"projection": "rows", "directed": False, **options},
    )


def test_rows_create_weighted_edges_and_keep_endpoint_lineage(source, monkeypatch):
    a, b = driver_path(source).nodes
    records = [
        Record({"source": a, "target": b, "weight": i + 1, "type": "SHARED", "common": ["a", "b"]})
        for i in range(60)
    ]
    tx = read_transaction(monkeypatch, records)
    graph, lineage, sample, count, table = execute_query(source, request(), 100_000)
    assert table is None
    assert tx.rolled_back and count == 60 and len(sample) == 50
    assert not graph["graph"]["directed"]
    assert len(graph["vertices"]) == 2 and len(graph["edges"]) == 60
    assert len({edge["id"] for edge in graph["edges"]}) == 60
    assert [edge["weight"] for edge in graph["edges"]] == list(range(1, 61))
    assert graph["edges"][0]["type"] == "SHARED"
    assert graph["edges"][0]["attributes"]["common"] == ["a", "b"]
    assert lineage["edges"] == {}
    assert all(_key(node["id"]) in lineage["vertices"] for node in graph["vertices"])
    assert sample[0]["weight"] == 1 and "node" in sample[0]["source"]


def test_default_projection_does_not_infer_relationships(source, monkeypatch):
    a, b = driver_path(source).nodes
    read_transaction(monkeypatch, [Record({"source": a, "target": b, "weight": 2})])
    graph, _, _, _, _ = execute_query(source, request(projection="elements"), 100_000)
    assert len(graph["vertices"]) == 2 and graph["edges"] == []


@pytest.mark.parametrize("endpoint", [None, 33, "33", {"id": 33}])
def test_projected_endpoints_must_be_real_nodes(source, monkeypatch, endpoint):
    a, _ = driver_path(source).nodes
    read_transaction(monkeypatch, [Record({"source": a, "target": endpoint})])
    with pytest.raises(AnalyticsError, match="must be nodes"):
        execute_query(source, request(), 100_000)


@pytest.mark.parametrize("weight", [None, True, "2", float("nan"), float("inf")])
def test_projected_weights_must_be_finite_numbers(source, monkeypatch, weight):
    a, b = driver_path(source).nodes
    read_transaction(monkeypatch, [Record({"source": a, "target": b, "weight": weight})])
    with pytest.raises(AnalyticsError, match="weight must be a finite number"):
        execute_query(source, request(), 100_000)


@pytest.mark.parametrize("edge_type", [None, "", "  ", 1])
def test_projected_types_must_be_nonempty_text(source, monkeypatch, edge_type):
    a, b = driver_path(source).nodes
    read_transaction(monkeypatch, [Record({"source": a, "target": b, "type": edge_type})])
    with pytest.raises(AnalyticsError, match="type must be a nonempty string"):
        execute_query(source, request(), 100_000)


def test_projection_validates_columns_even_for_empty_results(source, monkeypatch):
    read_transaction(monkeypatch, [], columns=["movieId", "rating"])
    with pytest.raises(AnalyticsError, match="requires RETURN"):
        execute_query(source, request(), 100_000)
    tx = read_transaction(monkeypatch, [], columns=["source", "target"])
    graph, lineage, sample, count, _table = execute_query(source, request(), 100_000)
    assert count == 0 and graph["vertices"] == [] and sample == [] and tx.rolled_back


def test_projected_edges_use_the_graph_resource_budget(source, monkeypatch):
    a, b = driver_path(source).nodes
    read_transaction(monkeypatch, [Record({"source": a, "target": b})])
    with pytest.raises(AnalyticsError, match="graph exceeds"):
        execute_query(source.model_copy(update={"max_rows": 2}), request(), 100_000)
    with pytest.raises(AnalyticsError, match="limit"):
        execute_query(source, request(), 50)


def test_projection_still_rejects_source_writes(source):
    with pytest.raises(AnalyticsError, match="Write clauses"):
        execute_query(
            source,
            CypherRequest(statement="MATCH (a), (b) MERGE (a)-[:SHARED]->(b) RETURN a, b", projection="rows"),
            100_000,
        )


def test_projected_graph_snapshot_opens_in_chat_and_enriches_nodes(workspace, source, monkeypatch):
    a, b = driver_path(source).nodes
    read_transaction(monkeypatch, [Record({"source": a, "target": b, "weight": 3})])
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute_query)
    client = workspace.client
    response = client.post("/api/database-sources/demo/queries", json=request().model_dump())
    assert response.status_code == 201, response.text
    data = response.json()
    assert (data["row_count"], data["vertex_count"], data["edge_count"]) == (1, 2, 1)
    assert data["dataset"]["source"]["projection"] == "rows"
    opened = client.post(f"/api/database-query-snapshots/{data['dataset']['id']}/chat", json={})
    assert opened.status_code == 201, opened.text
    file = opened.json()["file"]
    saved = json.loads(workspace.runtime.graph_store.execution_path(file["id"], file["session_id"]).read_text())
    assert saved["edges"][0]["weight"] == 3 and saved["graph"]["directed"] is False
    enriched = client.post(f"/api/files/{file['id']}/enrichments", json={
        "mapping": "accounts", "fields": ["risk"], "kind": "vertices",
    })
    assert enriched.status_code == 201, enriched.text
    assert len(enriched.json()["updates"]) == 2
    edge_lookup = client.post(f"/api/files/{file['id']}/enrichments", json={
        "mapping": "transfers", "fields": ["amount"], "kind": "edges",
    })
    assert edge_lookup.status_code == 409


def test_scalar_results_are_not_reported_as_no_rows(workspace, monkeypatch):
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute_query)
    read_transaction(monkeypatch, [Record({"movieId": 1, "rating": 5.0})])
    response = workspace.client.post("/api/database-sources/demo/queries", json={
        "statement": "RETURN 1 AS movieId, 5.0 AS rating",
    })
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["row_count"] == 1 and result["dataset"] is None
    assert result["table"]["kind"] == "table"
    assert "1 rows saved in a temporary table" in result["message"]
    read_transaction(monkeypatch, [])
    result = workspace.client.post("/api/database-sources/demo/queries", json={
        "statement": "MATCH (n) WHERE false RETURN n",
    }).json()
    assert result["row_count"] == 0 and result["message"].startswith("No rows matched.")


def test_missing_parameters_have_actionable_feedback(source, monkeypatch):
    error = RuntimeError("Expected parameters")
    error.code = "Neo.ClientError.Statement.ParameterMissing"
    read_transaction(monkeypatch, [], error=error)
    with pytest.raises(AnalyticsError, match="Expand Parameters"):
        execute_query(source, request(), 100_000)
