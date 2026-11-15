"""Existing benchmark graph properties resolve to exact, scoped SQL keys."""

import pytest
import sqlite3
from neo4j.graph import Graph, Node

from graphmine_agent.analytics import AnalyticsError, _key
from graphmine_agent.benchmark_mappings import catalog_source
from graphmine_agent.database_queries import GraphCollector
from graphmine_agent.database_sources import source_keys, sql_connection
from graphmine_agent.database_sync import mapped_records
from graphmine_agent.database_enrichment import canonical_records
from test_database_workspace import source, workspace  # noqa: F401


def dataset(identifier="yelp"):
    return {
        "id": identifier, "name": "Imported benchmark", "status": "ready",
        "graph_label": "GM_Test", "schema_name": identifier.replace("-", "_"),
        "tables": [{"name": "accounts", "kind": "nodes", "key": "id",
                    "labels": ["Account", "GM_Test"],
                    "columns": [{"name": name, "type": dtype} for name, dtype in [
                        ("id", "bigint"), ("name", "text"), ("risk", "bigint"), ("country", "text")
                    ]]}],
    }


@pytest.mark.parametrize("identifier", ["yelp", "movielens-32m", "movielens-genome", "ontime", "stackoverflow", "ldbc-snb"])
def test_catalog_node_lineage_uses_source_key_and_dataset_namespace(source, identifier):
    mapped = catalog_source(source, dataset(identifier))
    collector = GraphCollector(mapped, 100_000)
    value = Node(Graph(), "native-element-123", 123, {"Account", "GM_Test"}, {"id": 1, "name": "Ada"})
    identity = collector.node(value)
    assert identity != "neo4j:native-element-123"
    assert collector.lineage["vertices"][_key(identity)] == {
        "mapping": identifier.replace("-", "_") + "_accounts", "keys": [1],
    }
    # Merely sharing a label/property with a different graph grants no lineage.
    other = Node(Graph(), "foreign", 124, {"Account"}, {"id": 1, "gm_source": source.id, "gm_mapping": "accounts"})
    other_id = collector.node(other)
    assert _key(other_id) not in collector.lineage["vertices"]
    with pytest.raises(AnalyticsError, match="SQL type"):
        collector.node(Node(Graph(), "invalid", 125, {"Account", "GM_Test"}, {"id": 1.5}))


def test_catalog_snapshot_can_fetch_current_sql_attributes(workspace, monkeypatch):
    imported = dataset()
    monkeypatch.setattr("graphmine_agent.database_datasets.datasets", lambda *_: [imported])

    def execute(source, body, limit):
        collector = GraphCollector(source, limit)
        collector.node(Node(Graph(), "n1", 1, {"Account", "GM_Test"}, {"id": 1, "name": "Ada"}))
        return collector.graph(), collector.lineage, [], 1, None

    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    client = workspace.client
    snapshot = client.post("/api/database-sources/demo/queries", json={
        "statement": "MATCH (n:GM_Test) RETURN n LIMIT 1", "dataset_id": "yelp",
    })
    assert snapshot.status_code == 201, snapshot.text
    opened = client.post(f"/api/database-query-snapshots/{snapshot.json()['dataset']['id']}/chat", json={})
    assert opened.status_code == 201, opened.text
    file_id = opened.json()["file"]["id"]
    schema = client.get(f"/api/files/{file_id}/source-schema")
    assert schema.status_code == 200, schema.text
    assert schema.json()["entities"][0]["id"] == "yelp_accounts"
    result = client.post(f"/api/files/{file_id}/enrichments", json={
        "mapping": "yelp_accounts", "kind": "vertices", "fields": ["risk", "country"],
    })
    assert result.status_code == 201, result.text
    assert result.json()["updates"][0]["attributes"] == {"risk": 9, "country": "UK"}


def test_ldbc_relationship_uses_endpoint_keys_and_preserves_parallel_work_years(source):
    imported = {"id": "ldbc-snb", "graph_label": "GM_LDBC", "tables": []}
    for name in ("Person", "Organisation"):
        imported["tables"].append({
            "name": name, "kind": "nodes", "key": "id", "labels": [name, "GM_LDBC"],
            "columns": [{"name": "id", "type": "bigint"}, {"name": "name", "type": "text"}],
        })
    imported["tables"].append({
        "name": "Person_workAt_Company", "kind": "relationships", "relationship_type": "WORK_AT",
        "columns": [{"name": name, "type": "bigint"} for name in ["PersonId", "CompanyId", "workFrom"]],
    })
    mapped = catalog_source(source, imported)
    collector = GraphCollector(mapped, 100_000)
    g = Graph()
    person = Node(g, "p", 1, {"Person", "GM_LDBC"}, {"id": 9007199254740993})
    company = Node(g, "c", 2, {"Organisation", "Company", "GM_LDBC"}, {"id": 42})
    for year in (2010, 2015):
        edge = g.relationship_type("WORK_AT")(g, str(year), year, {"workFrom": year})
        edge._start_node, edge._end_node = person, company
        collector.relationship(edge)
    assert len(collector.graph()["edges"]) == 2
    assert sorted(link["keys"] for link in collector.lineage["edges"].values()) == [
        [9007199254740993, 42, 2010], [9007199254740993, 42, 2015],
    ]


def test_catalog_mapping_change_changes_snapshot_fingerprint(workspace):
    original = dataset()
    # Changing a key or schema must change the fingerprint used by snapshots.
    from graphmine_agent.database_sources import get_source
    base = get_source(workspace.runtime.settings, "demo")
    before = catalog_source(base, original)
    changed = {**original, "schema_name": "replacement"}
    assert before.fingerprint() != catalog_source(base, changed).fingerprint()


def test_expansion_matches_text_foreign_keys_to_integer_node_ids(source):
    with sqlite3.connect(source.sqlite_path) as db:
        db.executescript("""
            CREATE TABLE directors(name TEXT PRIMARY KEY);
            CREATE TABLE movies(item_id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE directed(src TEXT, dst TEXT);
            INSERT INTO directors VALUES ('Director');
            INSERT INTO movies VALUES (42,'Film');
            INSERT INTO directed VALUES ('Director','42');
        """)
    imported = {"id": "movielens-genome", "graph_label": "GM_Genome", "tables": [
        {"name": "directors", "kind": "nodes", "key": "name", "labels": ["Director", "GM_Genome"],
         "columns": [{"name": "name", "type": "text"}]},
        {"name": "movies", "kind": "nodes", "key": "item_id", "labels": ["Movie", "GM_Genome"],
         "columns": [{"name": "item_id", "type": "bigint"}, {"name": "title", "type": "text"}]},
        {"name": "directed", "kind": "relationships", "relationship_type": "DIRECTED",
         "columns": [{"name": "src", "type": "text"}, {"name": "dst", "type": "text"}]},
    ]}
    mapped = catalog_source(source, imported)
    relation = mapped.relationships[0]
    assert source_keys(mapped, relation, [42], ["dst"]) == ["42"]
    with sql_connection(mapped) as db:
        nodes, edges = mapped_records(mapped, db, "expansion", relationship=relation, selected=[
            {"mapping": relation.target_entity, "keys": [42]},
        ])
    expanded, _ = canonical_records(mapped, nodes, edges)
    collector, g = GraphCollector(mapped, 100_000), Graph()
    director = Node(g, "d", 1, {"Director", "GM_Genome"}, {"name": "Director"})
    movie = Node(g, "m", 2, {"Movie", "GM_Genome"}, {"item_id": 42, "title": "Film"})
    edge = g.relationship_type("DIRECTED")(g, "r", 3, {"src": "Director", "dst": "42"})
    edge._start_node, edge._end_node = director, movie
    collector.relationship(edge)
    assert {v["id"] for v in expanded["vertices"]} == {v["id"] for v in collector.graph()["vertices"]}
    assert [(e["id"], e["source"], e["target"]) for e in expanded["edges"]] == [
        (e["id"], e["source"], e["target"]) for e in collector.graph()["edges"]
    ]
