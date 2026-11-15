"""Guided queries retain dataset scope, parameter safety and edge lineage."""

import pytest
from neo4j import Record

from graphmine_agent.analytics import AnalyticsError, _key
from graphmine_agent.database_queries import CypherRequest, execute_query
from graphmine_agent.graph_builder import GraphBuild, compile_query
from test_database_query_projection import read_transaction
from test_database_workspace import driver_path, source, workspace  # noqa: F401


def test_builder_schema_exposes_graph_properties_and_requires_access(workspace):
    client = workspace.client
    path = "/api/database-sources/demo/graph-builder"
    response = client.get(path)
    assert response.status_code == 200, response.text
    schema = response.json()
    assert [p["name"] for p in schema["entities"][0]["properties"]] == ["name"]
    assert [p["name"] for p in schema["relationships"][0]["properties"]] == ["amount"]
    assert schema["relationships"][0]["source_entity"] == "accounts"
    assert client.get(path, params={"dataset_id": "unrelated-dataset"}).status_code == 404
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/database-sources/private/graph-builder").status_code == 404


def test_builder_parameterizes_filters_and_does_not_execute_query(workspace):
    before = len(workspace.calls)
    injected = "Ada' OR true DELETE a //"
    response = workspace.client.post("/api/database-sources/demo/graph-builder", json={
        "source_entity": "accounts", "relationship": "transfers", "target_entity": "accounts",
        "weight_property": "amount", "directed": False, "limit": 50,
        "filters": [{"property": "name", "value": injected},
                    {"scope": "relationship", "property": "amount", "operator": "gte", "value": 10}],
    })
    assert response.status_code == 200, response.text
    query = response.json()
    assert injected not in query["statement"]
    assert query["parameters"]["filter_0"] == injected
    assert query["parameters"]["filter_1"] == 10
    assert query["parameters"]["source_id"] == "demo"
    assert all(f"{alias}.gm_mapping" in query["statement"] for alias in ("a", "b", "r"))
    assert query["statement"].endswith("RETURN p\nLIMIT $row_limit")
    assert query["weight_property"] == "amount" and not query["directed"]
    assert len(workspace.calls) == before


@pytest.mark.parametrize("fields", [
    {"source_entity": "not-a-mapping"},
    {"filters": [{"property": "risk", "value": 1}]},  # SQL-only field
    {"filters": [{"property": "name", "value": {"nested": "map"}}]},
    {"filters": [{"property": "name", "operator": "contains", "value": 1}]},
    {"filters": [{"scope": "target", "property": "name", "value": "Ada"}]},
    {"weight_property": "amount"},  # no relationship
    {"relationship": "transfers", "target_entity": "accounts", "weight_property": "reason"},
])
def test_builder_rejects_invalid_choices(workspace, fields):
    response = workspace.client.post("/api/database-sources/demo/graph-builder", json={"source_entity": "accounts", **fields})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "graph_builder"


def catalog_schema():
    return {"source_id": "catalog", "graph_label": "GM_Sample", "max_rows": 100,
            "entities": [{"id": "users", "label": "User", "properties": [{"name": "odd`property"}]},
                         {"id": "movies", "label": "Movie", "properties": []}],
            "relationships": [{"id": "ratings", "label": "RATED", "source_entity": "users", "target_entity": "movies", "properties": []}]}


def test_catalog_builder_scopes_both_endpoints_and_quotes_properties():
    query = compile_query(catalog_schema(), GraphBuild(dataset_id="sample", source_entity="movies", relationship="ratings", target_entity="users", match_direction="incoming", limit=50,
        filters=[{"scope": "target", "property": "odd`property", "operator": "not_null"}]))
    assert "(a:`GM_Sample`:`Movie`)<-[r:`RATED`]-(b:`GM_Sample`:`User`)" in query["statement"]
    assert "b.`odd``property` IS NOT NULL" in query["statement"]
    assert query["parameters"] == {"row_limit": 50}
    with pytest.raises(AnalyticsError, match="direction"):
        compile_query(catalog_schema(), GraphBuild(source_entity="movies", relationship="ratings", target_entity="users", limit=50))
    with pytest.raises(AnalyticsError, match="row limit"):
        compile_query(catalog_schema(), GraphBuild(source_entity="users", limit=101))


def test_either_direction_returns_each_relationship_once():
    query = compile_query(catalog_schema(), GraphBuild(source_entity="users", relationship="ratings", target_entity="movies", match_direction="either", limit=50))
    assert "RETURN DISTINCT r" in query["statement"]


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
