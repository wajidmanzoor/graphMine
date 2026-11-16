"""Full query results survive storage/chat while large visual previews are skipped."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from neo4j import Record

from graphmine_agent.analytics import InputReference, AnalyticsError
from graphmine_agent.database_queries import CypherRequest, OpenChat, execute_query, open_chat, run_query
from graphmine_agent.graph_store import UploadError
from graphmine_agent.identity import AccountError, Principal, identity_scope
from graphmine_agent.models import FileRole
from graphmine_agent.query_previews import QueryPreviews
from graphmine_agent.query_results import graph_preview
from test_database_query_projection import read_transaction
from test_database_workspace import driver_path, source, workspace  # noqa: F401
from test_database_jobs import submit, wait_job


def chain(count):
    return {
        "graph": {"id": "chain", "directed": True, "allows_self_loops": False, "allows_parallel_edges": False},
        "vertices": [{"id": i, "label": f"Node {i}"} for i in range(count)],
        "edges": [{"id": i, "source": i, "target": i + 1} for i in range(count - 1)],
    }


def test_cypher_reads_past_source_row_and_byte_limits_without_a_timeout(source, monkeypatch):
    records = [Record({"p": driver_path(source)})] * 100_001
    transaction = read_transaction(monkeypatch, records)
    graph, _lineage, _sample, count, table = execute_query(source.model_copy(update={"max_bytes": 1024}), CypherRequest(statement="MATCH p=()-[]->() UNWIND range(0,100000) AS value RETURN p"))
    assert transaction.options == {"timeout": 0}
    assert transaction.rolled_back
    assert count == 100_001 and table is None
    assert len(graph["vertices"]) == 2 and len(graph["edges"]) == 1


@pytest.mark.parametrize("projection", ["elements", "rows"])
def test_graph_elements_and_derived_edges_ignore_source_caps(source, monkeypatch, projection):
    path = driver_path(source)
    record = Record({"p": path}) if projection == "elements" else Record({"source": path.nodes[0], "target": path.nodes[1]})
    read_transaction(monkeypatch, [record] * 501)
    graph, _lineage, _sample, count, _table = execute_query(
        source.model_copy(update={"max_rows": 1, "max_bytes": 1}),
        CypherRequest(statement="MATCH p=()-[]->() RETURN p", projection=projection),
    )
    assert count == 501 and len(graph["vertices"]) == 2
    assert len(graph["edges"]) == (1 if projection == "elements" else 501)


@pytest.mark.parametrize("count,skipped", [(500, False), (501, True)])
def test_preview_threshold_does_not_truncate_the_stored_graph(count, skipped):
    graph = chain(count)
    preview = graph_preview(graph)
    assert preview["preview_skipped"] is skipped
    assert preview["vertex_count"] == len(graph["vertices"]) == count
    assert len(preview["vertices"]) == (0 if skipped else count)
    assert len(preview["edges"]) == (0 if skipped else count - 1)


def test_full_graph_survives_query_storage_promotion_chat_and_analysis(workspace, monkeypatch, tmp_path):
    runtime = workspace.runtime
    small_limits = replace(runtime.settings, analytics_max_input_bytes=256, account_upload_bytes=256,
                           max_upload_bytes=256, max_result_bytes=256)
    for component in (runtime, runtime.graph_store, runtime.analytics):
        monkeypatch.setattr(component, "settings", small_limits)
    graph = chain(501)
    calls = []

    def execute(source, body, limit):
        calls.append(limit)
        return graph, {"vertices": {}, "edges": {}}, [], 501, None

    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", execute)
    accounts = SimpleNamespace(upload_remaining=lambda _: 100_000_000)
    with identity_scope(Principal("large-query-user", "large-query-user", accounts)):
        result = run_query(runtime, "demo", CypherRequest(statement="MATCH (n) RETURN n"))
        assert result["graph"]["preview_skipped"]
        assert result["vertex_count"] == 501 and result["edge_count"] == 500
        version = result["dataset"]["id"]
        opened = open_chat(runtime, version, OpenChat())
        file = opened["file"]
        reference = InputReference(file_id=file.id)
        inputs = runtime.analytics._inputs(opened["session"]["id"], {"main": reference})
        assert inputs["main"]["data"] == graph
        _, raw = QueryPreviews(runtime).get(version, content=True)
        assert json.loads(raw) == graph
        runtime.analytics._write(tmp_path / "inputs.json", inputs, input_snapshot=True)
        assert json.loads((tmp_path / "inputs.json").read_text()) == inputs
        with pytest.raises(AnalyticsError, match="artifact exceeds"):
            runtime.analytics._write(tmp_path / "result.json", inputs)
        with pytest.raises((UploadError, AccountError)):
            runtime.graph_store.ingest(session_id=opened["session"]["id"], role=FileRole.graph,
                                       filename="upload.json", content=json.dumps(graph).encode())
        # Previewing a large conversation graph does not load its full JSON.
        monkeypatch.setattr(runtime.graph_store, "_read_json", lambda *_: pytest.fail("read large preview"))
        preview = runtime.graph_store.graph_preview(file.id)
        assert preview["preview_skipped"] and preview["vertices"] == []
        assert preview["vertex_count"] == 501
    assert calls == [None]


def test_large_graph_snapshots_still_respect_account_storage(workspace):
    accounts = SimpleNamespace(upload_remaining=lambda _: 0)
    with identity_scope(Principal("full-account", "full-account", accounts)):
        with pytest.raises(AccountError, match="storage allowance"):
            QueryPreviews(workspace.runtime).store(chain(501), name="Large", kind="graph",
                                                   source={"type": "database_query"}, complete=True)


@pytest.mark.asyncio
async def test_worker_accepts_the_complete_validated_graph_request(workspace, monkeypatch, tmp_path):
    script = tmp_path / "inspect-worker-input"
    script.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\n"
        "raw=sys.stdin.buffer.read()\nrequest=json.loads(raw)\n"
        "assert len(raw)<=int(os.environ['GRAPHMINE_WORKER_INPUT_BYTES'])\n"
        "print(json.dumps({'event':'complete','result':{'vertices':len(request['inputs']['main']['data']['vertices'])}}))\n"
    )
    script.chmod(0o700)
    service = workspace.runtime.analytics
    monkeypatch.setattr(service, "settings", replace(service.settings, analytics_python=script,
                                                     analytics_max_input_bytes=256, max_result_bytes=256))
    result = await service._call({"command": "validate", "plan": {"device": "cpu"},
                                  "inputs": {"main": {"kind": "graph", "data": chain(501)}}})
    assert result == {"vertices": 501}


def test_background_query_result_skips_large_preview_but_keeps_all_nodes(workspace, monkeypatch):
    graph = chain(501)
    monkeypatch.setattr("graphmine_agent.database_queries.execute_query", lambda *_: (graph, {}, [], 501, None))
    job = submit(workspace, key="large-graph")
    wait_job(workspace.client, job["id"])
    response = workspace.client.get(f"/api/database-jobs/{job['id']}/result")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["graph"]["preview_skipped"] and result["graph"]["vertices"] == []
    assert (result["vertex_count"], result["edge_count"]) == (501, 500)
    _, raw = QueryPreviews(workspace.runtime).get(result["dataset"]["id"], content=True)
    assert json.loads(raw) == graph
