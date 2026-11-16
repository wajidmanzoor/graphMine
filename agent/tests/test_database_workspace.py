"""SQL lineage, immutable Cypher snapshots, access checks and enrichment."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

neo4j_graph = pytest.importorskip("neo4j.graph", reason="install agent[test,databases]")
Graph, Node, Path = neo4j_graph.Graph, neo4j_graph.Node, neo4j_graph.Path

from graphmine_agent.analytics import AnalyticsError, _key
from graphmine_agent.api import create_app
from graphmine_agent.database_enrichment import canonical_records
from graphmine_agent.database_queries import (
    CypherRequest,
    GraphCollector,
    execute_query,
)
from graphmine_agent.database_sources import (
    DatabaseSource,
    read_rows,
    sql_connection,
    stable_id,
    validate_cypher,
)
from graphmine_agent.database_sync import mapped_records
from graphmine_agent.datasets import DatasetLibrary

HEADERS = {"Authorization": "Bearer test-secret"}


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "tables.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, risk INTEGER, country TEXT);
            INSERT INTO accounts VALUES (1,'Ada',9,'UK'), (2,'Ben',2,'US'), (3,'Chen',7,'SG');
            CREATE TABLE transfers (id INTEGER PRIMARY KEY, sender INTEGER, receiver INTEGER, amount REAL, reason TEXT);
            INSERT INTO transfers VALUES (11,1,2,10,'invoice'), (12,2,3,20,'subscription');
        """)
    return DatabaseSource(
        id="demo",
        name="Local accounts",
        users=["*"],
        sql_type="sqlite",
        sqlite_path=str(path),
        neo4j_uri="bolt://127.0.0.1:17687",
        neo4j_password_env="TEST_NEO4J_PASSWORD",
        entities=[
            {
                "id": "accounts",
                "table": "accounts",
                "key": ["id"],
                "label": "Account",
                "attributes": ["name", "risk", "country"],
                "graph_attributes": ["name"],
                "display": "name",
            }
        ],
        relationships=[
            {
                "id": "transfers",
                "table": "transfers",
                "key": ["id"],
                "label": "TRANSFER",
                "attributes": ["amount", "reason"],
                "graph_attributes": ["amount"],
                "source_entity": "accounts",
                "target_entity": "accounts",
                "source_columns": ["sender"],
                "target_columns": ["receiver"],
                "weight": "amount",
            }
        ],
    )


def documents(source):
    with sql_connection(source) as db:
        nodes, edges = mapped_records(source, db, "first-import")
    return canonical_records(source, nodes, edges)


def driver_path(source):
    with sql_connection(source) as db:
        nodes, edges = mapped_records(source, db, "first-import")
    g = Graph()
    a, b = [
        Node(g, str(i), i, {"Account", "GraphMineEntity"}, n["properties"])
        for i, n in enumerate(nodes[:2])
    ]
    relationship = g.relationship_type("TRANSFER")(g, "r11", 11, edges[0]["properties"])
    relationship._start_node, relationship._end_node = a, b
    return Path(a, relationship)


@pytest.fixture
def workspace(settings, source, tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps([source.model_dump()]))
    config.chmod(0o600)
    app = create_app(replace(settings, database_sources_file=config))
    g, lineage = documents(source)
    g["vertices"], g["edges"] = g["vertices"][:2], g["edges"][:1]
    calls = []

    def execute(src, body, limit):
        calls.append(body.statement)
        return g, lineage, [], 1, None

    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    with TestClient(app) as client:
        client.headers.update(HEADERS)
        snapshot = client.post(
            "/api/database-sources/demo/queries",
            json={"statement": "MATCH p=()-[]->() RETURN p"},
        )
        assert snapshot.status_code == 201, snapshot.text
        opened = client.post(
            f"/api/database-query-snapshots/{snapshot.json()['dataset']['id']}/chat",
            json={},
        )
        assert opened.status_code == 201, opened.text
        yield SimpleNamespace(
            client=client,
            runtime=app.state.runtime,
            file=opened.json()["file"],
            session=opened.json()["session"],
            snapshot=snapshot.json(),
            calls=calls,
            config=config,
        )


@pytest.mark.parametrize(
    "statement",
    [
        "MATCH (n) DETACH DELETE n",
        "CALL db.labels()",
        "LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row",
        "MATCH (n) RETURN n; CREATE (n)",
        "USE system RETURN 1",
        "MATCH (n) SET n.x=1 RETURN n",
        "CREATE INDEX foo FOR (n:Foo) ON (n.x)",
        "START DATABASE x",
        "STOP DATABASE x",
        "TERMINATE TRANSACTIONS 'transaction-1'",
        "MATCH (n) WITH n CALL db.labels() YIELD label RETURN label",
        "RETURN COUNT { CALL db.labels() YIELD label RETURN label }",
        "MATCH (n) WHERE EXISTS { MATCH (m) SET m.changed=true RETURN m } RETURN n",
        "RETURN 1 UNION ALL CALL db.labels()",
    ],
)
def test_query_editor_rejects_writes_and_procedures(statement):
    with pytest.raises(AnalyticsError, match="read|statement"):
        validate_cypher(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "MATCH (n) WHERE n.name = $name RETURN n LIMIT 100",
        "// SET is a comment\nMATCH (n) WHERE n.name='DELETE; CALL' RETURN n;",
        "RETURN {text: 'CREATE'} AS value",
        "MATCH (n) RETURN n.`set`",
        "MATCH (start:User) RETURN start",
        "MATCH (start:User)-[:FRIEND]-(stop:User) WHERE stop <> start RETURN start, stop",
        "MATCH (n) WITH n AS start RETURN start.start AS stop",
        "MATCH (n) WHERE n.start=$start RETURN {start:n.start, stop:n.stop}",
        "MATCH (count) RETURN count {start:count.start, call:count.call}",
        "RETURN COUNT { MATCH (start:User) RETURN start }",
        "MATCH (n) RETURN n; // trailing comment",
    ],
)
def test_query_editor_accepts_read_queries_with_literals_and_comments(statement):
    validate_cypher(statement)


def test_sql_read_only_parameterized_composite_keys_and_budgets(source):
    with sql_connection(source) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM accounts")
        assert read_rows(db, source, source.entities[0], keys=[["1 OR 1=1"]]) == []
        assert len(read_rows(db, source, source.entities[0], keys=[[1]])) == 1
        limited = source.model_copy(update={"max_rows": 1})
        with pytest.raises(AnalyticsError, match="limit"):
            read_rows(db, limited, limited.entities[0])
    assert stable_id(source, source.entities[0], [1]) != stable_id(
        source, source.entities[0], ["1"]
    )
    assert stable_id(source, source.entities[0], ["a", "b:c"]) != stable_id(
        source, source.entities[0], ["a:b", "c"]
    )


def test_driver_values_preserve_real_graph_identity_and_lineage(source):
    collector = GraphCollector(source, 100_000)
    path = driver_path(source)
    collector.collect(
        {"path": path, "again": path.nodes[0], "scalar": {"id": "not-a-node"}}
    )
    g = collector.graph()
    assert len(g["vertices"]) == 2 and len(g["edges"]) == 1
    assert g["edges"][0]["weight"] == 10
    assert g["vertices"][0]["attributes"] == {
        "name": "Ada",
        "neo4j_labels": ["Account", "GraphMineEntity"],
    }
    assert collector.lineage["vertices"][_key(g["vertices"][0]["id"])] == {
        "mapping": "accounts",
        "keys": [1],
    }
    assert "risk" not in g["vertices"][0]["attributes"]
    with pytest.raises(AnalyticsError, match="limit"):
        GraphCollector(source, 5).collect(path)


def test_query_checks_server_query_type_limits_and_rolls_back(source, monkeypatch):
    class Result(list):
        def keys(self):
            return ["p"]

        def consume(self):
            return SimpleNamespace(query_type="r")

    class Transaction:
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, statement, parameters):
            return (
                Result()
                if statement.startswith("EXPLAIN ")
                else Result([{"p": driver_path(source)}])
            )

        def rollback(self):
            self.rolled_back = True

    tx = Transaction()

    @contextmanager
    def session(_):
        yield SimpleNamespace(begin_transaction=lambda **_: tx)

    monkeypatch.setattr("graphmine_agent.database_queries.neo4j_session", session)
    g, lineage, _rows, count, _table = execute_query(
        source,
        CypherRequest(statement="MATCH p=()-[]->() RETURN p", directed=False),
        100_000,
    )
    assert (
        not g["graph"]["directed"]
        and tx.rolled_back
        and count == 1
        and lineage["edges"]
    )


def test_snapshot_chat_handoff_reuses_exact_saved_graph(workspace):
    w = workspace
    assert len(w.calls) == 1
    file = w.runtime.database.get_file(w.file["id"])
    assert file.provenance["version_id"] == w.snapshot["dataset"]["id"]
    metadata, raw = DatasetLibrary(w.runtime).get(
        w.snapshot["dataset"]["id"], content=True
    )
    actual = json.loads(
        w.runtime.graph_store.execution_path(file.id, file.session_id).read_text()
    )
    assert actual == json.loads(raw) and metadata["source"]["row_count"] == 1
    schema = w.client.get(f"/api/files/{file.id}/source-schema").json()
    assert (
        "sql_dsn_env" not in schema
        and "neo4j_uri" not in schema
        and "table" not in schema["entities"][0]
    )


def test_enrichment_reads_fresh_attributes_creates_new_version_and_preserves_original(
    workspace, source
):
    w = workspace
    before = json.loads(
        w.runtime.graph_store.execution_path(w.file["id"], w.session["id"]).read_text()
    )
    with sqlite3.connect(source.sqlite_path) as db:
        db.execute("UPDATE accounts SET risk=42 WHERE id=1")
    response = w.client.post(
        f"/api/files/{w.file['id']}/enrichments",
        json={"mapping": "accounts", "fields": ["risk", "country"]},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert (
        data["dataset"]["version"] == 2
        and data["kind"] == "graph"
        and data["entity_kind"] == "vertices"
    )
    assert {row["attributes"]["risk"] for row in data["updates"]} == {42, 2}
    assert (
        json.loads(
            w.runtime.graph_store.execution_path(
                w.file["id"], w.session["id"]
            ).read_text()
        )
        == before
    )
    assert (
        w.client.post(
            f"/api/files/{w.file['id']}/enrichments",
            json={"mapping": "accounts", "fields": ["not_exposed"]},
        ).status_code
        == 422
    )


def test_expansion_reads_only_incident_relationships_and_keeps_row_lineage(workspace):
    w = workspace
    response = w.client.post(
        f"/api/files/{w.file['id']}/expansions", json={"mapping": "transfers"}
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["added"] == {"vertices": 1, "edges": 1}
    assert data["file"]["provenance"]["source"]["type"] == "database_expansion"
    assert len(data["file"]["provenance"]["source"]["lineage"]["vertices"]) == 3
    next_response = w.client.post(
        f"/api/files/{data['file']['id']}/enrichments",
        json={"mapping": "accounts", "fields": ["country"]},
    )
    assert (
        next_response.status_code == 201 and len(next_response.json()["updates"]) == 3
    )


def test_source_access_and_mapping_revision_rechecked_on_old_snapshots(
    workspace, source
):
    w = workspace
    source.revision += 1
    w.config.write_text(json.dumps([source.model_dump()]))
    response = w.client.post(
        f"/api/files/{w.file['id']}/enrichments",
        json={"mapping": "accounts", "fields": ["risk"]},
    )
    assert response.status_code == 409
    source.users = ["another-user"]
    w.config.write_text(json.dumps([source.model_dump()]))
    assert w.client.get("/api/database-sources").json() == []
    assert w.client.get(f"/api/files/{w.file['id']}/source-schema").status_code == 404
    assert (
        w.client.post(
            f"/api/database-query-snapshots/{w.snapshot['dataset']['id']}/chat", json={}
        ).status_code
        == 404
    )


def test_result_enrichment_uses_server_selection_and_revision(workspace):
    w = workspace
    g = json.loads(
        w.runtime.graph_store.execution_path(w.file["id"], w.session["id"]).read_text()
    )
    record = {
        "id": "saved",
        "session_id": w.session["id"],
        "revision": 1,
        "status": "completed",
        "steps": {"mine": {"status": "completed"}},
        "input_files": {"main": {"file_id": w.file["id"], "kind": "graph"}},
        "validation": {
            "plan": {
                "steps": [
                    {
                        "id": "mine",
                        "operation": "densest-subgraph",
                        "input": {"input": "main"},
                    }
                ]
            }
        },
    }
    service = w.runtime.analytics
    service._save(record)
    service._write(
        service._directory(record) / "inputs.json",
        {"main": {"kind": "graph", "data": g}},
    )
    service._write(
        service._directory(record) / "step-mine.json",
        {
            "result": {
                "operation": "densest-subgraph",
                "ports": {
                    "vertices": {
                        "type": "vertex_set",
                        "value": [g["vertices"][0]["id"]],
                        "complete": True,
                    }
                },
            }
        },
    )
    body = {
        "mapping": "accounts",
        "fields": ["risk"],
        "selection": {
            "workflow_id": "saved",
            "revision": 1,
            "step": "mine",
            "port": "vertices",
        },
    }
    response = w.client.post(f"/api/files/{w.file['id']}/enrichments", json=body)
    assert response.status_code == 201, response.text
    assert len(response.json()["updates"]) == 1
    enriched = response.json()["file"]
    body["fields"] = ["country"]
    next_response = w.client.post(f"/api/files/{enriched['id']}/enrichments", json=body)
    assert next_response.status_code == 201, next_response.text
    newest = next_response.json()["file"]
    saved_graph = json.loads(
        w.runtime.graph_store.execution_path(newest["id"], w.session["id"]).read_text()
    )
    assert saved_graph["vertices"][0]["attributes"]["risk"] == 9
    assert saved_graph["vertices"][0]["attributes"]["country"] == "UK"
    expanded = w.client.post(
        f"/api/files/{newest['id']}/expansions",
        json={"mapping": "transfers", "selection": body["selection"]},
    )
    assert expanded.status_code == 201, expanded.text
    expanded_graph = json.loads(
        w.runtime.graph_store.execution_path(
            expanded.json()["file"]["id"], w.session["id"]
        ).read_text()
    )
    ada = next(v for v in expanded_graph["vertices"] if v.get("label") == "Ada")
    assert ada["attributes"]["risk"] == 9 and ada["attributes"]["country"] == "UK"
    body["selection"]["revision"] = 2
    assert (
        w.client.post(f"/api/files/{w.file['id']}/enrichments", json=body).status_code
        == 409
    )
    body["selection"]["revision"] = 1
    body["ids"] = [g["vertices"][1]["id"]]
    assert (
        w.client.post(f"/api/files/{w.file['id']}/enrichments", json=body).status_code
        == 422
    )
