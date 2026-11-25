"""Result context uses execution snapshots and distinguishes display bounds."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from graphmine_agent.analytics import AnalyticsError, AnalyticsService, InputReference
from graphmine_agent.analytics_exports import report_bundle
from graphmine_agent.models import FileRole
from graphmine_agent.result_views import result_view
from test_datasets import library  # noqa: F401


def test_input_identity_and_scope_are_captured_before_file_deletion(database, graph_store, session, triangle_graph):
    provenance = {"dataset_id": "dataset-a", "version_id": "version-a", "version": 2, "source_complete": False,
                  "source": {"type": "database_query", "query": "MATCH (n) RETURN n LIMIT $limit", "parameters": {"limit": 9007199254740993}, "scope": "exact returned graph elements"}}
    file = graph_store.ingest(session_id=session.id, role=FileRole.graph, filename="Accounts-v2.json", content=triangle_graph, provenance=provenance)
    service = SimpleNamespace(database=database)
    snapshot = AnalyticsService._input_provenance(service, {"main": InputReference(file_id=file.id)})["main"]
    assert snapshot["file_snapshot"] == {"name": file.original_name, "kind": "graph", "created_at": file.created_at.isoformat(), "size_bytes": file.size_bytes,
                                        "graph": {"directed": False, "vertex_count": 3, "edge_count": 3}}
    assert snapshot["file_id"] == file.id and snapshot["sha256"] == file.sha256
    assert snapshot["source"] == provenance["source"] and snapshot["source_complete"] is False
    database.delete_file(file.id)
    assert json.loads(json.dumps(snapshot))["source"]["parameters"]["limit"] == 9007199254740993
    assert "source_path" not in snapshot and "canonical_path" not in snapshot


def test_recorded_file_identity_cannot_be_replaced_by_nested_provenance(database, graph_store, session, triangle_graph):
    file = graph_store.ingest(session_id=session.id, role=FileRole.graph, filename="graph.json", content=triangle_graph,
                              provenance={"file_id": "different", "sha256": "not-this-file", "file_snapshot": {"name": "stale name"}})
    snapshot = AnalyticsService._input_provenance(SimpleNamespace(database=database), {"main": InputReference(file_id=file.id)})["main"]
    assert snapshot["file_id"] == file.id and snapshot["sha256"] == file.sha256
    assert snapshot["file_snapshot"]["name"] == "graph.json"


def test_non_graph_input_retains_its_kind_without_inventing_graph_counts(database, graph_store, session):
    file = graph_store.ingest(session_id=session.id, role=FileRole.attachment, filename="features.json", content=b'{"vectors":[[1,2]]}')
    snapshot = AnalyticsService._input_provenance(SimpleNamespace(database=database), {"features": InputReference(file_id=file.id, kind="feature_vectors")})["features"]
    assert snapshot["file_snapshot"]["kind"] == "feature_vectors" and snapshot["file_snapshot"]["graph"] == {}
    assert "source_complete" not in snapshot


@pytest.mark.parametrize("complete", [False, True])
def test_preview_bounds_do_not_change_completeness_or_quality(complete):
    graph = {"graph": {"directed": False}, "vertices": [{"id": i} for i in range(5)], "edges": [{"id": i, "source": i, "target": i+1} for i in range(4)]}
    output = {"problem": "k-core", "quality": "exact", "complete": complete,
              "ports": {"vertices": {"type": "vertex_set", "complete": complete, "value": [0, 1, 2, 3, 4]}}}
    record = {"id": "analysis", "revision": 4, "input_files": {"main": {"file_id": "deleted-source"}},
              "validation": {"plan": {"steps": [{"id": "core", "input": {"input": "main"}}]}}}
    service = SimpleNamespace(get=lambda _: record, _saved=lambda *_, **__: {"result": output}, _directory=lambda _: Path("/unused"),
                              _read_result=lambda _: {"main": {"kind": "graph", "data": graph}})
    before = deepcopy(output)
    view = result_view(service, "analysis", "core", "vertices", vertex_limit=2, edge_limit=1)
    assert view["limits"] == {"vertices": 2, "edges": 1}
    assert view["input_graph"] == {"vertex_count": 5, "edge_count": 4, "directed": False}
    assert view["vertices_truncated"] and view["edges_truncated"]
    assert view["vertex_count"] == 5 and view["edge_count"] == 4
    assert view["complete"] is complete and output == before


@pytest.mark.parametrize("suffix,method", [
    ("/result", "GET"), ("/result?summary=true", "GET"), ("/steps/core/result", "GET"),
    ("/steps/core/ports/groups", "GET"), ("/steps/core/ports/groups/view", "GET"),
    ("/steps/core/ports/groups/groups/0/graph", "GET"), ("/steps/core/ports/groups/memberships", "POST"),
    ("/steps/core/ports/groups/csv", "GET"), ("/report", "GET"),
])
def test_result_routes_pin_revision_after_owner_check(library, suffix, method):
    client, runtime, alice, bob, sessions, file = library
    record = {"id": "pinned", "session_id": sessions[0], "revision": 2, "status": "completed", "steps": {"core": {"status": "completed"}},
              "input_files": {"main": {"file_id": file["id"], "kind": "graph"}},
              "validation": {"workflow_hash": "a" * 64, "plan": {"steps": [{"id": "core", "problem": "maximal-cliques", "input": {"input": "main"}}]}}}
    output = {"result": {"problem": "maximal-cliques", "quality": "exact", "complete": True,
                        "ports": {"groups": {"type": "vertex_groups", "value": [{"vertices": [0, 1, 2]}], "complete": True}}}}
    graph = {"graph": {"directed": False}, "vertices": [{"id": i} for i in range(3)], "edges": []}
    runtime.analytics._save(record)
    directory = runtime.analytics._directory(record)
    runtime.analytics._write(directory / "inputs.json", {"main": {"kind": "graph", "data": graph}})
    runtime.analytics._write(directory / "result.json", {"steps": {"core": output}})
    runtime.analytics._write(directory / "step-core.json", output)
    path = "/api/workflows/pinned" + suffix
    options = {"json": {"vertices": [0]}} if method == "POST" else {}
    separator = "&" if "?" in path else "?"
    stale = client.request(method, path + separator + "expected_revision=1", headers=alice, **options)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    assert client.request(method, path + separator + "expected_revision=1", headers=bob, **options).status_code == 404
    valid = client.request(method, path + separator + "expected_revision=2", headers=alice, **options)
    assert valid.status_code == 200, valid.text
    assert client.request(method, path + separator + "expected_revision=0", headers=alice, **options).status_code == 422


@pytest.mark.parametrize("kind", ["view", "group", "report"])
def test_revision_change_between_metadata_and_artifact_read_fails_closed(kind):
    service = object.__new__(AnalyticsService)
    records = iter([{"id": "w", "revision": 1}, {"id": "w", "revision": 2}])
    service.get = lambda _: next(records)
    with pytest.raises(AnalyticsError, match="revision changed") as error:
        if kind == "view":
            result_view(service, "w", "core", "groups", expected_revision=1)
        elif kind == "report":
            report_bundle(service, "w", expected_revision=1)
        else:
            service.group_graph("w", "core", "groups", 0, expected_revision=1)
    assert error.value.code == "revision_conflict"

