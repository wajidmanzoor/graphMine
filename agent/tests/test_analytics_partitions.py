"""Complete bipartitions are resolved by the server, never from model samples."""

import json
from copy import deepcopy
from dataclasses import replace

import httpx
import jsonschema
import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.analytics_partitions import prepare_bipartitions, resolve_partitions
from graphmine_agent.analytics_planning import AnalyticsPlanner
from graphmine_agent.models import FileRole
from test_analytics_planning import ReplayPlanner, proposal, route, setup  # noqa: F401


def typed_graph():
    vertices = [
        {"id": f"neo4j:yelp:long-namespace:{kind}:{i}", "type": kind}
        for kind, count in (("User", 50), ("Business", 30))
        for i in range(count)
    ]
    return {
        "graph": {"id": "typed", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
        "vertices": vertices,
        "edges": [
            {"id": i, "source": vertices[i]["id"], "target": vertices[50 + i % 30]["id"]}
            for i in range(50)
        ],
    }


def selection(kind, alias="main"):
    return {"input_partition": {"input": alias, "type": kind}}


@pytest.mark.parametrize("invalid", ["directed", "missing_type", "third_type", "same_side"])
def test_only_complete_valid_typed_bipartitions_are_offered(invalid):
    graph = typed_graph()
    if invalid == "directed":
        graph["graph"]["directed"] = True
    elif invalid == "missing_type":
        del graph["vertices"][-1]["type"]
    elif invalid == "third_type":
        graph["vertices"][-1]["type"] = "Other"
    else:
        graph["edges"][0]["target"] = graph["vertices"][1]["id"]
    assert prepare_bipartitions({"main": {"kind": "graph", "data": graph}}) == {}


def test_partition_resolution_preserves_ids_isolates_and_explicit_literals():
    graph = typed_graph()
    graph["vertices"].append({"id": 42, "type": "User"})
    prepared = prepare_bipartitions({"main": {"kind": "graph", "data": graph}})
    plan = proposal("maximal-bicliques", {
        "left_partition": selection("User"),
        "right_partition": selection("Business"),
        "minimum_left_size": 2,
    })["plan"]
    resolved = resolve_partitions(plan, prepared)
    assert len(resolved["steps"][0]["parameters"]["left_partition"]) == 51
    assert resolved["steps"][0]["parameters"]["left_partition"][-1] == 42
    assert resolved["steps"][0]["parameters"]["minimum_left_size"] == 2
    assert resolved["steps"][0]["budget"] == {"max_candidates": 20_000_000}
    assert plan["steps"][0]["parameters"]["left_partition"] == selection("User")
    assert resolve_partitions(resolved, prepared) == resolved


def test_preparation_preserves_an_explicit_execution_budget():
    graph = typed_graph()
    prepared = prepare_bipartitions({"main": {"kind": "graph", "data": graph}})
    plan = proposal("maximal-bicliques", {"left_partition": selection("User")})["plan"]
    plan["steps"][0]["budget"] = {"max_candidates": 100, "timeout_seconds": 5}
    assert resolve_partitions(plan, prepared)["steps"][0]["budget"] == plan["steps"][0]["budget"]


@pytest.mark.parametrize("source", [{"input": "other"}, {"step": "filtered", "port": "graph"}])
def test_prepared_partitions_cannot_escape_their_original_graph(source):
    graph = typed_graph()
    prepared = prepare_bipartitions({"main": {"kind": "graph", "data": graph}})
    plan = proposal("maximal-bicliques", {"left_partition": selection("User")})["plan"]
    plan["steps"][0]["input"] = source
    with pytest.raises(AnalyticsError, match="same original graph"):
        resolve_partitions(plan, prepared)


@pytest.fixture
def partition_setup(setup):
    settings, analytics, events, session, body = setup
    graph = typed_graph()
    file = analytics.graph_store.ingest(
        session_id=session, role=FileRole.graph, filename="users-businesses.json",
        content=json.dumps(graph).encode(),
    )
    body = body.model_copy(update={
        "message": "Yes, Users on one side and Businesses on the other",
        "inputs": {"main": body.inputs["main"].model_copy(update={"file_id": file.id})},
    })
    return settings, analytics, events, session, body, graph


@pytest.mark.parametrize("left,right", [("User", "Business"), ("Business", "User")])
async def test_followup_prepares_full_partitions_before_native_validation(partition_setup, left, right):
    settings, analytics, events, session, body, graph = partition_setup
    await events.publish(session, "workflow.chat", {
        "turn_id": "earlier", "role": "user", "message": "find all maximal bicliques",
    })
    await events.publish(session, "workflow.chat", {
        "turn_id": "earlier", "role": "assistant", "status": "needs_information",
        "message": "Are the two sides all Users and all Businesses?",
    })
    planner = ReplayPlanner(settings, analytics, events, responses=[
        route("maximal-bicliques"),
        proposal("maximal-bicliques", {"left_partition": selection(left), "right_partition": selection(right)}),
    ])
    result = await planner.plan(session, body)
    assert result["status"] == "ready"
    parameters = result["plan"]["steps"][0]["parameters"]
    for name, kind in (("left_partition", left), ("right_partition", right)):
        assert parameters[name] == [v["id"] for v in graph["vertices"] if v["type"] == kind]
    assert parameters.get("result_limit") is None
    assert result["plan"]["steps"][0]["budget"] == {
        "max_candidates": 20_000_000, "max_output_items": 100_000, "timeout_seconds": 60.0,
    }
    assert [stage for stage, _, _ in planner.calls] == ["route", "plan"]
    payload = planner.calls[-1][1]
    context = payload["inputs"]["main"]
    assert len(context["vertices_sample"]) == 8
    assert context["bipartite_partitions"] == [
        {"type": "User", "vertex_count": 50, "value": selection("User")},
        {"type": "Business", "vertex_count": 30, "value": selection("Business")},
    ]
    assert "partition_rules" in payload
    assert len(payload["conversation"]) == 2


async def test_partition_references_pass_generation_schema_and_expand_to_native_arrays(partition_setup, monkeypatch):
    settings, analytics, events, session, body, graph = partition_setup
    planner = AnalyticsPlanner(replace(settings, llm_enabled=True), analytics, events)
    wire = {
        "status": "ready", "message": "Find all maximal bicliques across Users and Businesses.",
        "plan": {"version": 1, "device": "cpu", "steps": [{
            "operation": "maximal-bicliques", "input": {"source": "input", "input": "main"},
            "arguments": [
                {"name": "left_partition", "value": {"literal": selection("User")}},
                {"name": "right_partition", "value": {"literal": selection("Business")}},
            ],
        }]},
    }
    calls = []

    def reply(request):
        content = json.loads(request.content)
        payload = json.loads(content["messages"][1]["content"])
        calls.append(payload["stage"])
        response = route("maximal-bicliques") if payload["stage"] == "route" else wire
        schema = content["response_format"]["json_schema"]["schema"]
        jsonschema.validate(response, schema)
        if payload["stage"] == "plan":
            bad = deepcopy(wire)
            bad["plan"]["steps"][0]["arguments"][0]["value"]["literal"] = selection("Invented")
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr("graphmine_agent.analytics_planning.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(reply), **kwargs))
    result = await planner.plan(session, body)
    assert result["status"] == "ready"
    assert calls == ["route", "plan"]
    assert len(result["plan"]["steps"][0]["parameters"]["left_partition"]) == 50
    assert len(result["plan"]["steps"][0]["parameters"]["right_partition"]) == 30
