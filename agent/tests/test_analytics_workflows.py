"""Real library API tests plus isolated process-lifecycle fault injection."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import stat
import sys
import textwrap
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import graphmine_agent
import pytest
from fastapi.testclient import TestClient
from graphmine_agent.analytics import AnalyticsError, AnalyticsService
from graphmine_agent.api import create_app
from graphmine_agent.jobs import EventBus

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.fixture(scope="session", autouse=True)
def analytics_application_evidence(request):
    package = Path(graphmine_agent.__file__).parent
    repository = Path(__file__).resolve().parents[2]

    def snapshot():
        paths = list(package.rglob("*.py")) + [
            Path(__file__),
            Path(__file__).with_name("conftest.py"),
        ]
        paths += [Path(path) for path in {item.path for item in request.session.items}]
        paths += [repository / "catalog/native_execution_evidence.json"]
        native = os.environ.get("GRAPHMINE_NATIVE_LIBRARY")
        if native:
            paths.append(Path(native))
        return {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        }

    before = snapshot()
    yield
    unchanged = before == snapshot()
    xml = getattr(request.config.option, "xmlpath", None)
    if xml:
        metadata = {
            "scope": "Actual library API workflows, synthetic process/ledger fault injection and authored planning decisions; no browser or LLM accuracy coverage",
            "python": sys.version,
            "gpu_test_devices": os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS"),
            "source_files": before,
            "sources_unchanged_during_run": unchanged,
            "collected_test_count": len(request.session.items),
            "test_modules": sorted({str(item.path) for item in request.session.items}),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("fastapi", "pydantic", "httpx", "pytest", "pytest-asyncio")
            },
        }
        Path(str(xml) + ".metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
    assert unchanged, "Application sources changed during verification"


def plan():
    return {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "core",
                "operation": "k-core",
                "input": {"input": "main"},
                "parameters": {"requested_k": 2},
            },
            {
                "id": "sub",
                "operation": "induced-subgraph",
                "parameters": {"mode": "induced"},
                "input": {"input": "main"},
                "bindings": {"vertices_or_seeds": {"step": "core", "port": "vertices"}},
            },
            {
                "id": "rank",
                "operation": "pagerank",
                "input": {"step": "sub", "port": "graph"},
            },
        ],
    }


def upload(client, graph):
    response = client.post("/api/sessions", headers=AUTH, json={"domain_id": "general"})
    assert response.status_code == 201, response.text
    session = response.json()["id"]
    response = client.post(
        f"/api/sessions/{session}/files",
        headers=AUTH,
        files={"file": ("triangle.json", graph, "application/json")},
        data={"role": "graph", "directed": "false"},
    )
    assert response.status_code == 201, response.text
    return session, response.json()["id"]


def body(file_id, mode="interactive"):
    return {
        "mode": mode,
        "plan": plan(),
        "inputs": {"main": {"file_id": file_id, "kind": "graph"}},
    }


def approve(client, record):
    response = client.post(
        f"/api/workflows/{record['id']}/run",
        headers=AUTH,
        json={
            "workflow_hash": record["validation"]["workflow_hash"],
            "expected_revision": record["revision"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait(client, workflow_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        record = client.get(f"/api/workflows/{workflow_id}", headers=AUTH).json()
        if record["status"] not in {"queued", "running"}:
            return record
        time.sleep(0.025)
    pytest.fail("Workflow did not finish within the test deadline")


@pytest.mark.parametrize("mode", ["normal", "interactive", "expert"])
def test_live_modes_dependent_results_and_pagination(settings, triangle_graph, mode):
    # Requires current committed-source CPU evidence and the analytics venv.
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph, mode)
        )
        assert response.status_code == 201, response.text
        record = response.json()
        if mode != "normal":
            assert record["status"] == (
                "awaiting_review" if mode == "interactive" else "ready"
            )
            assert record["approved_hash"] is None
            assert (
                client.get(
                    f"/api/workflows/{record['id']}/result", headers=AUTH
                ).status_code
                == 409
            )
            approve(client, record)
        final = wait(client, record["id"])
        assert final["status"] == "completed", final
        assert final["complete"]
        result = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()
        assert all(
            row["result"]["backend"]["device"] == "cpu"
            for row in result["steps"].values()
        )
        assert result["steps"]["core"]["result"]["result"]["selected_vertices"] == [
            0,
            1,
            2,
        ]
        rows = result["steps"]["rank"]["result"]["result"]["vertices"]
        assert [row["score"] for row in rows] == pytest.approx([1 / 3] * 3)
        page = client.get(
            f"/api/workflows/{record['id']}/steps/rank/ports/scores?offset=1&limit=1",
            headers=AUTH,
        ).json()
        assert page["total_items"] == 3 and page["complete"] and page["has_more"]
        assert page["items"] == [rows[1]]
        assert (
            client.get(
                f"/api/workflows/{record['id']}/steps/rank/ports/scores?limit=1001",
                headers=AUTH,
            ).status_code
            == 422
        )
        assert (
            client.get(f"/api/sessions/{session}/workflows", headers=AUTH).json()[0][
                "id"
            ]
            == record["id"]
        )


def test_live_graph_collection_patterns_and_derived_graph(settings, triangle_graph):
    first = json.loads(triangle_graph)
    second = json.loads(triangle_graph)
    second["graph"]["id"] = "path"
    second["edges"].pop()
    data = {"dataset_id": "two-transactions", "graphs": [first, second]}
    with TestClient(create_app(settings)) as client:
        session, _ = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={
                "file": (
                    "transactions.json",
                    json.dumps(data).encode(),
                    "application/json",
                )
            },
            data={"role": "attachment"},
        )
        assert response.status_code == 201, response.text
        request = {
            "mode": "normal",
            "inputs": {
                "database": {
                    "file_id": response.json()["id"],
                    "kind": "graph_collection",
                }
            },
            "plan": {
                "version": 1,
                "device": "cpu",
                "steps": [
                    {
                        "id": "mine",
                        "operation": "frequent-subgraphs",
                        "input": {"input": "database"},
                        "parameters": {
                            "minimum_support_fraction": 1,
                            "minimum_edges": 2,
                            "maximum_edges": 2,
                            "minimum_vertices": 3,
                            "maximum_vertices": 3,
                            "include_supporting_graph_ids": True,
                        },
                    },
                    {
                        "id": "degree",
                        "operation": "degree-centrality",
                        "input": {
                            "step": "mine",
                            "port": "patterns",
                            "select": {"kind": "pattern_graph", "index": 0},
                        },
                    },
                ],
            },
        }
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = wait(client, response.json()["id"])
        assert record["status"] == "completed", record
        result = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()
        mining = result["steps"]["mine"]["result"]
        assert mining["input_kind"] == "graph_collection"
        assert (
            mining["ports"]["patterns"]["input_fingerprint"]
            == mining["input_fingerprint"]
        )
        patterns = mining["result"]["patterns"]
        assert len(patterns) == 1
        assert patterns[0]["supporting_graph_ids"] == ["path", "triangle"]
        assert (
            patterns[0]["support_graph_count"] == 2
            and patterns[0]["support_fraction"] == 1
        )
        degrees = result["steps"]["degree"]["result"]
        assert sorted(row["score"] for row in degrees["ports"]["scores"]["value"]) == [
            0.5,
            0.5,
            1,
        ]
        assert degrees["graph_fingerprint"] != mining["input_fingerprint"]
        page = client.get(
            f"/api/workflows/{record['id']}/steps/mine/ports/patterns?offset=0&limit=1",
            headers=AUTH,
        ).json()
        assert page["items"] == patterns and page["complete"] and not page["has_more"]


def test_live_graph_pair_fraction_witness_and_common_graph(settings, triangle_graph):
    a = json.loads(triangle_graph)
    a["edges"].pop()
    for row in a["vertices"]:
        row["label"] = "A"
    for row in a["edges"]:
        row["type"] = "x"
    b = json.loads(json.dumps(a))
    b["graph"]["id"] = "target"
    b["vertices"].append({"id": "inserted", "label": "A"})
    b["edges"].append({"id": "new", "source": 2, "target": "inserted"})
    for edge, category in zip(b["edges"], ["y", "x", "y"], strict=True):
        edge["type"] = category
    with TestClient(create_app(settings)) as client:
        session, first = upload(client, json.dumps(a).encode())
        response = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("target.json", json.dumps(b).encode(), "application/json")},
            data={"role": "graph"},
        )
        assert response.status_code == 201, response.text
        request = {
            "mode": "normal",
            "inputs": {
                "a": {"file_id": first},
                "b": {"file_id": response.json()["id"]},
            },
            "plan": {
                "version": 1,
                "device": "cpu",
                "steps": [
                    {
                        "id": "edits",
                        "operation": "graph-edit-distance",
                        "input": {"input": "a"},
                        "bindings": {"other_graph": {"input": "b"}},
                        "parameters": {
                            "edit_costs": {
                                "edge_substitution": 1e-200,
                                "edge_insertion": 0,
                            }
                        },
                    },
                    {
                        "id": "common",
                        "operation": "maximum-common-subgraph",
                        "input": {"input": "a"},
                        "bindings": {"other_graph": {"input": "b"}},
                    },
                    {
                        "id": "degree",
                        "operation": "degree-centrality",
                        "input": {"step": "common", "port": "graph"},
                    },
                ],
            },
        }
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = wait(client, response.json()["id"])
        assert record["status"] == "completed", record
        results = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()["steps"]
        distance = results["edits"]["result"]["ports"]["distance"]
        assert distance["type"] == "rational_scalar"
        assert distance["value"] == {
            "display": 1,
            "display_is_exact": False,
            "numerator": str(10**200 + 1),
            "denominator": str(10**200),
        }
        path = results["edits"]["result"]["result"]["edit_path"]
        assert any(row["operation"] == "vertex_insertion" for row in path)
        page = client.get(
            f"/api/workflows/{record['id']}/steps/edits/ports/edits?offset=0&limit=1",
            headers=AUTH,
        ).json()
        assert page["items"] == path[:1] and page["has_more"]
        common = results["common"]["result"]["result"]["task_result"]
        assert common["vertex_count"] == 2
        degrees = results["degree"]["result"]["ports"]["scores"]["value"]
        assert [row["score"] for row in degrees] == [common["edge_count"]] * 2
        request["plan"]["steps"] = [
            request["plan"]["steps"][0],
            {
                "id": "unsafe_rounding",
                "operation": "k-cliques",
                "input": {"input": "a"},
                "bindings": {"k": {"step": "edits", "port": "distance"}},
            },
        ]
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 422, response.text


def test_live_review_revision_and_cache_recovery(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph)
        )
        assert response.status_code == 201, response.text
        first = response.json()
        approve(client, first)
        assert wait(client, first["id"])["status"] == "completed"
        revision = {**body(graph), "expected_revision": 1}
        # Identical content is still a new review revision.
        response = client.post(
            f"/api/workflows/{first['id']}/revise", headers=AUTH, json=revision
        )
        assert response.status_code == 200, response.text
        second = response.json()
        assert second["revision"] == 2 and second["approved_hash"] is None
        assert "approved_at" not in second and "finished_at" not in second
        old = client.post(
            f"/api/workflows/{first['id']}/run",
            headers=AUTH,
            json={
                "workflow_hash": first["validation"]["workflow_hash"],
                "expected_revision": 1,
            },
        )
        assert old.status_code == 409
        assert (
            client.post(
                f"/api/workflows/{first['id']}/revise", headers=AUTH, json=revision
            ).status_code
            == 409
        )
        approve(client, second)
        assert all(
            step["reused"] for step in wait(client, first["id"])["steps"].values()
        )
        revision["expected_revision"] = 2
        revision["plan"]["steps"][0]["parameters"]["requested_k"] = 3
        third = client.post(
            f"/api/workflows/{first['id']}/revise", headers=AUTH, json=revision
        ).json()
        approve(client, third)
        final = wait(client, first["id"])
        assert final["status"] == "completed", final
        assert not any(step["reused"] for step in final["steps"].values())
        result = client.get(f"/api/workflows/{first['id']}/result", headers=AUTH).json()
        assert result["steps"]["rank"]["result"]["result"]["vertices"] == []


def test_live_capabilities_authorization_and_input_scope(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/analytics/capabilities").status_code == 401
        caps = client.get("/api/analytics/capabilities", headers=AUTH).json()
        assert caps["operations"] and all(
            card["execution"]["cpu"] for card in caps["operations"]
        ), caps.get("reports")
        session, graph = upload(client, triangle_graph)
        other, _ = upload(client, triangle_graph)
        assert client.post(
            f"/api/sessions/{other}/workflows", headers=AUTH, json=body(graph)
        ).status_code in (400, 422)
        invalid = body(graph)
        invalid["resume"] = {"fake": "result"}
        assert (
            client.post(
                f"/api/sessions/{session}/workflows", headers=AUTH, json=invalid
            ).status_code
            == 422
        )
        invalid = body(graph)
        invalid["plan"]["steps"][1]["bindings"]["vertices_or_seeds"]["port"] = (
            "invented"
        )
        assert (
            client.post(
                f"/api/sessions/{session}/workflows", headers=AUTH, json=invalid
            ).status_code
            == 422
        )


@pytest.mark.parametrize("mode", ["normal", "interactive", "expert"])
def test_live_record_query_to_filtered_graph_to_count(settings, triangle_graph, mode):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        request = body(graph, mode)
        request["plan"]["steps"] = [
            {
                "id": "lookup",
                "operation": "edge-filter",
                "input": {"input": "main"},
                "parameters": {
                    "edge_filters": [{"field": "id", "op": "in", "value": ["01", "12"]}]
                },
            },
            {
                "id": "sub",
                "operation": "query-subgraph",
                "input": {"input": "main"},
                "parameters": {"mode": "edges"},
                "bindings": {"edge_ids": {"step": "lookup", "port": "edges"}},
            },
            {
                "id": "count",
                "operation": "triangle-counting",
                "input": {"step": "sub", "port": "graph"},
            },
        ]
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = response.json()
        if mode != "normal":
            assert not record["steps"]
            approve(client, record)
        final = wait(client, record["id"])
        assert final["status"] == "completed", final
        result = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()
        assert result["steps"]["lookup"]["result"]["ports"]["edges"]["value"] == [
            "01",
            "12",
        ]
        assert result["steps"]["count"]["result"]["ports"]["count"]["value"] == 0
        page = client.get(
            f"/api/workflows/{record['id']}/steps/lookup/ports/rows?offset=1&limit=1",
            headers=AUTH,
        ).json()
        assert page["items"][0]["id"] == "12" and page["complete"]


def test_query_input_rejected_before_any_worker_is_queued(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        request = body(graph, "normal")
        request["plan"]["steps"] = [
            {
                "id": "query",
                "operation": "edge-filter",
                "input": {"input": "main"},
                "parameters": {
                    "edge_filters": [
                        {"field": "attributes.invented", "op": "eq", "value": 10}
                    ]
                },
            }
        ]
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 422, response.text
        assert "Unknown attribute field: attributes.invented" in response.text


def _service(settings, database, graph_store):
    return AnalyticsService(settings, database, graph_store, EventBus(database))


async def test_plan_preview_flags_large_exact_searches_and_slow_past_runs(
    settings, database, graph_store, monkeypatch
):
    service = _service(settings, database, graph_store)

    async def capabilities():
        return {
            "operations": [
                {
                    "id": "maximal-cliques",
                    "title": "Maximal cliques",
                    "quality": "exact",
                    "family": "cliques",
                },
                {
                    "id": "pagerank",
                    "title": "PageRank",
                    "quality": "numerical",
                    "family": "centrality",
                },
            ]
        }

    monkeypatch.setattr(service, "capabilities", capabilities)

    def record(workflow_id, operation, **extra):
        steps = [{"id": "core", "operation": operation, "device": "cpu"}]
        return {
            "id": workflow_id,
            "session_id": "s",
            "revision": 1,
            "validation": {"plan": {"steps": steps}},
            **extra,
        }

    def graph(edges):
        data = {
            "vertices": [{"id": i} for i in range(100)],
            "edges": [
                {"source": i % 100, "target": (i + 1) % 100} for i in range(edges)
            ],
        }
        return {"main": {"kind": "graph", "data": data}}

    cliques, large = record("new-cliques", "maximal-cliques"), graph(6000)
    service._write(service._directory(cliques) / "inputs.json", large)
    preview = await service._preview(cliques, large)
    assert preview["steps"][0]["search"] and preview["expensive"]
    assert "exact search on 6,000 connections" in preview["reasons"][0]
    assert preview["inputs"]["main"] == {"vertices": 100, "edges": 6000}
    rank, small = record("new-rank", "pagerank"), graph(10)
    service._write(service._directory(rank) / "inputs.json", small)
    assert not (await service._preview(rank, small))["expensive"]
    earlier = record(
        "earlier-rank",
        "pagerank",
        status="completed",
        started_at="2026-10-14T10:00:00+00:00",
        finished_at="2026-10-14T10:05:00+00:00",
    )
    service._write(service._directory(earlier) / "inputs.json", small)
    service._save(earlier)
    preview = await service._preview(rank, small)
    assert preview["past_runs"] == {"count": 1, "median_seconds": 300.0}
    assert "took about 5 minutes" in preview["reasons"][0]


def test_group_graph_reads_members_from_the_full_input(
    settings, database, graph_store, session, monkeypatch
):
    service = _service(settings, database, graph_store)
    record = {
        "id": "groups",
        "session_id": session.id,
        "revision": 1,
        "status": "completed",
        "validation": {"plan": {"steps": [{"id": "core", "input": {"input": "main"}}]}},
    }
    service._save(record)
    vertices = [{"id": i, "label": f"v{i}"} for i in range(3000)]
    edges = [{"source": 2900, "target": 2901}, {"source": 2901, "target": 5}]
    service._write(
        service._directory(record) / "inputs.json",
        {
            "main": {
                "kind": "graph",
                "data": {"graph": {}, "vertices": vertices, "edges": edges},
            }
        },
    )
    groups = {"type": "vertex_groups", "value": [{"vertices": [2900, 2901]}]}
    monkeypatch.setattr(
        service, "_saved", lambda *_a, **_k: {"result": {"ports": {"cliques": groups}}}
    )
    graph = service.group_graph("groups", "core", "cliques", 0)
    # Both members lie beyond a 500-vertex preview; only their own edge is kept.
    assert [v["id"] for v in graph["vertices"]] == [2900, 2901]
    assert graph["edges"] == [edges[0]] and not graph["vertices_truncated"]


def test_long_outputs_are_summarized_and_paged_with_search_and_sort(
    settings, database, graph_store, session
):
    service = _service(settings, database, graph_store)
    record = {
        "id": "big",
        "session_id": session.id,
        "revision": 1,
        "status": "completed",
    }
    service._save(record)
    rows = [{"vertex": f"v{i}", "score": i % 7} for i in range(5000)]
    saved = {
        "steps": {
            "rank": {
                "status": "completed",
                "result": {
                    "ports": {"scores": {"type": "vertex_scores", "value": rows}}
                },
            }
        }
    }
    service._write(service._directory(record) / "result.json", saved)
    service._write(
        service._directory(record) / "step-rank.json", saved["steps"]["rank"]
    )
    record["steps"] = {"rank": {"status": "completed"}}
    record["validation"] = {"plan": {"steps": [{"id": "rank"}]}}
    service._save(record)
    summary = service.result_summary("big", limit=100)
    port = summary["steps"]["rank"]["result"]["ports"]["scores"]
    assert len(port["value"]) == 100 and port["value_truncated"]
    assert port["total_items"] == 5000
    # The cached full result is untouched by summaries.
    assert (
        len(
            service.result("big")["steps"]["rank"]["result"]["ports"]["scores"]["value"]
        )
        == 5000
    )
    page = service.port_page("big", "rank", "scores", 0, 3, search="v49")
    assert page["matched_items"] == 111 and page["total_items"] == 5000
    assert [row["vertex"] for row in page["items"]] == ["v49", "v490", "v491"]
    exact = service.port_page("big", "rank", "scores", 0, 5, search='vertex:"v4999"')
    assert exact["items"] == [rows[4999]] and exact["positions"] == [4999]
    ranked = service.port_page(
        "big", "rank", "scores", 0, 2, sort="score", descending=True
    )
    assert [row["score"] for row in ranked["items"]] == [6, 6]


async def test_health_and_metrics_describe_the_engine_people_use(
    settings, database, graph_store, monkeypatch
):
    service = _service(settings, database, graph_store)

    async def capabilities(refresh=False):
        return {
            "operations": [
                {"id": "a", "execution": {"cpu": True, "gpu": False}},
                {"id": "b", "execution": {"cpu": False, "gpu": False}},
            ]
        }

    monkeypatch.setattr(service, "_native_capabilities", capabilities)
    # Health reads the shared verification; it never waits for a worker.
    service.capability_cache = (
        service._capability_key(),
        time.monotonic() + 300,
        await capabilities(),
    )
    now = datetime.now(timezone.utc)
    at = lambda minutes: (now - timedelta(minutes=minutes)).isoformat()
    for workflow_id, status, approved, started, finished in [
        ("ok", "completed", at(30), at(29), at(20)),
        ("bad", "failed", at(15), at(10), at(9)),
        ("waiting", "queued", at(2), None, None),
    ]:
        service._save(
            {
                "id": workflow_id,
                "session_id": "s",
                "status": status,
                "approved_at": approved,
                **({"started_at": started} if started else {}),
                **({"finished_at": finished} if finished else {}),
                **({"error": {"code": "resource_limit"}} if status == "failed" else {}),
            }
        )
    health = await service.health()
    assert health["native"] == {
        "status": "ok",
        "admitted_operations": 1,
        "operations": 2,
    }
    assert health["workflows"]["queued"] == 1
    assert health["workflows"]["oldest_queued_seconds"] >= 119
    assert health["workflows"]["failed_24h"] == 1
    assert health["workflows"]["recent_failures"][0]["code"] == "resource_limit"
    metrics = service.metrics(
        [
            {"stage": "family", "seconds": 4.0, "outcome": "ok"},
            {"stage": "family", "seconds": 20.0, "outcome": "ok"},
            {"stage": "plan", "seconds": 30.0, "outcome": "planner_truncated"},
        ]
    )
    assert metrics["planning_seconds"]["family"]["count"] == 2
    assert metrics["planning_outcomes"] == {"ok": 2, "planner_truncated": 1}
    assert metrics["failure_rate_24h"] == 0.5
    assert metrics["queue_seconds"]["count"] == 2
    assert metrics["run_seconds"]["p95"] == 540.0


def test_queue_position_counts_only_earlier_pending_work(
    settings, database, graph_store
):
    service = _service(settings, database, graph_store)
    for workflow_id, status, approved in [
        ("done", "completed", "0"),
        ("running", "running", "1"),
        ("first", "queued", "2"),
        ("second", "queued", "3"),
    ]:
        service._save(
            {
                "id": workflow_id,
                "session_id": "s",
                "status": status,
                "approved_at": approved,
            }
        )
    assert service.queue_position({"status": "queued", "approved_at": "2"}) == 2
    assert service.queue_position({"status": "queued", "approved_at": "3"}) == 3
    assert service.queue_position({"status": "running", "approved_at": "1"}) is None


async def test_capabilities_share_one_verification_until_evidence_changes(
    settings, database, graph_store, monkeypatch
):
    service = _service(settings, database, graph_store)
    calls, release = [], asyncio.Event()

    async def call(request, **_):
        calls.append(request["command"])
        await release.wait()
        return {"operations": []}

    async def probe():
        return []

    monkeypatch.setattr(service, "_call", call)
    monkeypatch.setattr(service.scheduler, "probe", probe)
    viewers = [asyncio.create_task(service.capabilities()) for _ in range(4)]
    await asyncio.sleep(0)
    viewers[0].cancel()  # A disconnected viewer cannot cancel the shared check.
    release.set()
    first, *_ = await asyncio.gather(*viewers[1:])
    assert calls == ["capabilities"]
    first["operations"].append("caller-owned copy")
    assert (await service.capabilities())["operations"] == []
    assert calls == ["capabilities"]
    await service.capabilities(refresh=True)
    assert len(calls) == 2
    monkeypatch.setattr(service, "_capability_key", lambda: ("rebuilt",))
    await service.capabilities()
    assert len(calls) == 3


def test_live_failed_step_recovery_reuses_only_valid_steps(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        request = body(graph, "normal")
        request["plan"]["steps"][0]["budget"] = {"max_output_items": 1}
        request["plan"]["steps"].append(
            {
                "id": "independent",
                "operation": "triangle-counting",
                "input": {"input": "main"},
            }
        )
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = wait(client, response.json()["id"])
        assert record["status"] == "failed"
        assert record["steps"]["rank"]["status"] == "blocked"
        assert record["steps"]["independent"]["status"] == "completed"
        partial = client.get(
            f"/api/workflows/{record['id']}/steps/independent/result", headers=AUTH
        )
        assert partial.status_code == 200, partial.text
        assert partial.json()["result"]["ports"]["count"]["value"] == 1
        assert (
            client.get(
                f"/api/workflows/{record['id']}/steps/rank/result", headers=AUTH
            ).status_code
            == 409
        )
        assert (
            client.get(
                f"/api/workflows/{record['id']}/steps/independent/result"
            ).status_code
            == 401
        )
        request.update(mode="interactive", expected_revision=1)
        request["plan"]["steps"][0]["budget"] = {"max_output_items": 100}
        revised = client.post(
            f"/api/workflows/{record['id']}/revise", headers=AUTH, json=request
        ).json()
        approve(client, revised)
        final = wait(client, record["id"])
        assert final["status"] == "completed", final
        assert final["steps"]["independent"]["reused"]
        assert not final["steps"]["core"]["reused"]


def test_live_evidence_is_rechecked_at_execution(settings, triangle_graph, tmp_path):
    app = create_app(settings)
    with TestClient(app) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph)
        )
        assert response.status_code == 201, response.text
        record = response.json()
        # Move only the worker's evidence root to an empty temporary repository.
        # No real source/report is modified and no verification is bypassed.
        app.state.runtime.analytics.settings = replace(
            settings,
            repository_root=tmp_path,
            analytics_python=settings.repository_root / ".venv-analytics/bin/python",
        )
        approve(client, record)
        final = wait(client, record["id"])
        assert final["status"] == "failed" and "evidence" in final["error"]["message"]
        assert final["steps"] == {}


def test_live_cancel_endpoint(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph)
        )
        assert response.status_code == 201, response.text
        record = response.json()
        approve(client, record)
        cancelled = client.delete(f"/api/workflows/{record['id']}", headers=AUTH)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert not cancelled.json()["complete"]


@pytest.mark.parametrize("gpu_index", [0, 1])
def test_live_configured_gpu_workflow(settings, triangle_graph, gpu_index):
    configured = os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS", "").split(",")
    if len(configured) != 2 or not all(configured):
        pytest.skip(
            "Set GRAPHMINE_ANALYTICS_TEST_GPUS to two GPU UUIDs for application GPU checks"
        )
    device = configured[gpu_index]
    selected = replace(
        settings, graph_gpu_uuid=device, llm_gpu_uuid=None, job_timeout_seconds=30
    )
    with TestClient(create_app(selected)) as client:
        session, graph = upload(client, triangle_graph)
        request = body(graph, "normal")
        request["plan"]["device"] = "gpu"
        request["plan"]["steps"][1]["parameters"] = {"mode": "ego", "radius": 0}
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = wait(client, response.json()["id"])
        assert record["status"] == "completed", record
        result = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()
        for step in result["steps"].values():
            backend = step["result"]["backend"]
            assert backend["device"] == "gpu" and backend["hardware"]["uuid"] == device
        assert [
            r["score"] for r in result["steps"]["rank"]["result"]["result"]["vertices"]
        ] == pytest.approx([1 / 3] * 3, abs=1e-8)


def _sleeping_worker(tmp_path):
    script = tmp_path / "sleeping-worker"
    pidfile = tmp_path / "worker-pids.json"
    script.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json, os, pathlib, subprocess, sys, time
        json.load(sys.stdin)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        pathlib.Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), child.pid]))
        time.sleep(60)
        """)
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, pidfile


def _not_running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_process_group_cancellation_and_deadline(
    settings, database, graph_store, tmp_path, cancel
):
    script, pidfile = _sleeping_worker(tmp_path)
    service = _service(
        replace(settings, analytics_python=script, job_timeout_seconds=1),
        database,
        graph_store,
    )
    service.open()
    try:
        task = asyncio.create_task(
            service._call({"command": "run", "plan": {"device": "cpu"}})
        )
        for _ in range(150):
            if pidfile.exists():
                break
            await asyncio.sleep(0.01)
        assert pidfile.exists()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(AnalyticsError, match="deadline"):
                await task
        for _ in range(100):
            if all(_not_running(pid) for pid in json.loads(pidfile.read_text())):
                break
            await asyncio.sleep(0.01)
        assert all(_not_running(pid) for pid in json.loads(pidfile.read_text()))
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_ledger_restart_and_exclusive_ownership(
    settings, database, graph_store, session
):
    owner = _service(settings, database, graph_store)
    owner.open()
    record = {
        "id": "synthetic-ledger-fixture",
        "session_id": session.id,
        "status": "queued",
    }
    owner._save(record)
    competitor = _service(settings, database, graph_store)
    with pytest.raises(RuntimeError, match="already owned"):
        competitor.open()
    await competitor.close()
    assert owner.get(record["id"])["status"] == "queued"
    owner.owner.release()  # simulate an exited process, without graceful shutdown
    restarted = _service(settings, database, graph_store)
    restarted.open()
    assert restarted.get(record["id"])["status"] == "interrupted"
    await restarted.close()


@pytest.mark.asyncio
async def test_cpu_process_cannot_see_configured_gpu(
    settings, database, graph_store, tmp_path
):
    script = tmp_path / "inspect-environment"
    script.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\njson.load(sys.stdin)\nprint(json.dumps({'event':'complete','result':{'cuda':os.getenv('CUDA_VISIBLE_DEVICES')}}))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    service = _service(
        replace(settings, analytics_python=script), database, graph_store
    )
    result = await service._call({"command": "run", "plan": {"device": "cpu"}})
    assert result == {"cuda": ""}


@pytest.mark.asyncio
async def test_missing_worker_does_not_affect_application_start(
    settings, database, graph_store, tmp_path
):
    configured = replace(settings, analytics_python=tmp_path / "missing-python")
    service = _service(configured, database, graph_store)
    with pytest.raises(AnalyticsError, match="environment is unavailable"):
        await service.capabilities()
