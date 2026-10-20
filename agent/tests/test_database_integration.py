"""Opt-in disposable PostgreSQL + Neo4j demo, with real native CPU execution.

Load the demo.env from deploy/database-workspace and set
GRAPHMINE_TEST_DATABASE_INTEGRATION=1. No LLM responses are involved here.
GRAPHMINE_TEST_RUNTIME_ROOT may point to a compatible prebuilt native checkout.
"""

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings

pytestmark = pytest.mark.skipif(
    os.getenv("GRAPHMINE_TEST_DATABASE_INTEGRATION") != "1",
    reason="requires the disposable database demo",
)


@pytest.fixture
def live_client(settings, tmp_path):
    runtime_root = Path(
        os.getenv("GRAPHMINE_TEST_RUNTIME_ROOT", settings.repository_root)
    ).resolve()
    base = Settings.from_env(runtime_root)
    configured = replace(
        base,
        accounts_enabled=False,
        api_token="test-secret",
        llm_enabled=False,
        data_root=tmp_path / "live-agent",
        analytics_python=Path(__import__("sys").executable),
        native_runtime_library=runtime_root
        / "library/build/runtime/libgraphmine_runtime.so",
        graph_gpu_uuid=None,
        llm_gpu_uuid=None,
        analytics_gpu_uuids=(),
        job_timeout_seconds=60,
    )
    with TestClient(create_app(configured)) as client:
        client.headers["Authorization"] = "Bearer test-secret"
        sources = client.get("/api/database-sources").json()
        assert any(s["id"] == "local-transfers" for s in sources), (
            "Use the disposable seeded local-transfers source"
        )
        sync = client.post("/api/database-sources/local-transfers/sync")
        assert sync.status_code == 200, sync.text
        assert sync.json()["nodes"] == 8 and sync.json()["relationships"] == 10
        yield client


def query_chat(
    client,
    *,
    directed=True,
    query="MATCH p=(a:Account)-[:TRANSFER]->(b:Account) RETURN p",
    parameters=None,
):
    response = client.post(
        "/api/database-sources/local-transfers/queries",
        json={"statement": query, "parameters": parameters or {}, "directed": directed},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    opened = client.post(
        f"/api/database-query-snapshots/{data['dataset']['id']}/chat", json={}
    )
    assert opened.status_code == 201, opened.text
    return data, opened.json()


def analyze(client, opened, operation, parameters=None):
    created = client.post(
        f"/api/sessions/{opened['session']['id']}/workflows",
        json={
            "mode": "normal",
            "inputs": {"main": {"kind": "graph", "file_id": opened["file"]["id"]}},
            "plan": {
                "version": 1,
                "device": "cpu",
                "steps": [
                    {
                        "id": "analyze",
                        "operation": operation,
                        "input": {"input": "main"},
                        "parameters": parameters or {},
                    }
                ],
            },
        },
    )
    assert created.status_code == 201, created.text
    wid = created.json()["id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        record = client.get(f"/api/workflows/{wid}").json()
        if record["status"] not in {"queued", "running"}:
            break
        time.sleep(0.05)
    assert record["status"] == "completed", record
    result = client.get(f"/api/workflows/{wid}/result").json()["steps"]["analyze"][
        "result"
    ]
    assert result["backend"]["device"] == "cpu"
    return record, result


def test_real_shortest_path_focus_and_live_table_attributes(live_client):
    client = live_client
    snapshot, opened = query_chat(client)
    by_name = {v["label"]: v["id"] for v in snapshot["graph"]["vertices"]}
    record, result = analyze(
        client, opened, "single-source-shortest-paths", {"source": by_name["Ada"]}
    )
    rows = result["ports"]["distances"]["value"]
    index = next(i for i, r in enumerate(rows) if r["vertex"] == by_name["Chen"])
    assert rows[index]["distance"] == 20
    path = f"/api/workflows/{record['id']}/steps/analyze/ports/distances/view"
    view = client.get(path, params={"index": index}).json()
    assert {v["label"] for v in view["vertices"]} == {"Ada", "Ben", "Chen"}
    assert len(view["edges"]) == 2
    assert all(e["weight"] == 10 for e in view["edges"])
    body = {
        "mapping": "accounts",
        "fields": ["risk_score", "country"],
        "selection": {
            "workflow_id": record["id"],
            "revision": record["revision"],
            "step": "analyze",
            "port": "distances",
            "index": index,
        },
    }
    enrich = client.post(f"/api/files/{opened['file']['id']}/enrichments", json=body)
    assert enrich.status_code == 201, enrich.text
    assert (
        len(enrich.json()["updates"]) == 3 and enrich.json()["dataset"]["version"] == 2
    )
    assert {r["attributes"]["risk_score"] for r in enrich.json()["updates"]} == {
        85,
        73,
        91,
    }
    assert client.get(path, params={"index": index}).json() == view


def test_real_densest_view_expands_from_tables_then_reanalyzes(live_client):
    client = live_client
    _snapshot, opened = query_chat(client, directed=False)
    record, _result = analyze(client, opened, "densest-subgraph")
    path = f"/api/workflows/{record['id']}/steps/analyze/ports/vertices/view"
    view = client.get(path).json()
    assert {v["label"] for v in view["vertices"]} == {"Ada", "Ben", "Chen", "Dia"}
    assert view["edge_count"] == 6 and view["vertex_count"] == 4
    context = client.get(path, params={"context": True}).json()
    assert context["vertex_count"] == 8 and len(context["selected_vertices"]) == 4
    expand = client.post(
        f"/api/files/{opened['file']['id']}/expansions",
        json={
            "mapping": "transfers",
            "selection": {
                "workflow_id": record["id"],
                "revision": record["revision"],
                "step": "analyze",
                "port": "vertices",
            },
        },
    )
    assert expand.status_code == 201, expand.text
    assert expand.json()["added"] == {"vertices": 1, "edges": 1}
    new = {"session": opened["session"], "file": expand.json()["file"]}
    second, _ = analyze(client, new, "densest-subgraph")
    assert (
        second["input_files"]["main"]["file_id"]
        != record["input_files"]["main"]["file_id"]
    )
    assert client.get(path).json() == view


def test_real_parameterized_query_and_scalar_result_have_exact_scope(live_client):
    client = live_client
    snapshot, _opened = query_chat(
        client,
        query="MATCH (a:Account) WHERE a.name=$name RETURN a",
        parameters={"name": "Ada"},
    )
    assert snapshot["vertex_count"] == 1 and snapshot["edge_count"] == 0
    assert snapshot["graph"]["vertices"][0]["label"] == "Ada"
    scalar = client.post(
        "/api/database-sources/local-transfers/queries",
        json={"statement": "MATCH (a:Account) RETURN count(a) AS count"},
    )
    assert scalar.status_code == 201 and scalar.json()["dataset"] is None
    assert scalar.json()["rows"] == [{"count": 8}]
    assert (
        client.post(
            "/api/database-sources/local-transfers/queries",
            json={"statement": "MATCH (a:Account) DELETE a"},
        ).status_code
        == 422
    )
    # Neo4j returns endpoint stubs for RETURN r. They must still link to SQL rows.
    relationship, linked = query_chat(
        client, query="MATCH ()-[r:TRANSFER]->() RETURN r ORDER BY r.amount LIMIT 1"
    )
    assert relationship["vertex_count"] == 2 and relationship["edge_count"] == 1
    assert len(linked["file"]["provenance"]["source"]["lineage"]["vertices"]) == 2
    assert all(v.get("label") for v in relationship["graph"]["vertices"])
    from graphmine_agent.database_sources import configured, sql_connection

    source = configured(client.app.state.runtime.settings)[0]
    with sql_connection(source) as db:
        assert (
            db.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]
            == "on"
        )
        assert (
            db.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
            == "repeatable read"
        )
