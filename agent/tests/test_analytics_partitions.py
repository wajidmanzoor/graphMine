"""Complete bipartitions are resolved by the server, never from model samples."""

import json
from copy import deepcopy
from dataclasses import replace

import httpx
import jsonschema
import pytest

from graphmine_agent.analytics import AnalyticsError
from graphmine_agent.analytics_bipartite import complete_partitions, planning_cards
from graphmine_agent.analytics_parameter_choices import parameter_choices
from graphmine_agent.analytics_partitions import prepare_bipartitions, resolve_partitions
from graphmine_agent.analytics_planning import AnalyticsPlanner, plan_schema
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


def test_code_owned_full_partitions_preserve_production_budget_and_user_limits():
    inputs = {"main": {"kind": "graph", "data": typed_graph()}}
    plan = proposal("maximal-bicliques", {"entity_type": "User"})["plan"]
    prepared, gap, directed = complete_partitions(plan, inputs)
    assert gap is None and not directed
    assert prepared["steps"][0]["budget"] == {"max_candidates": 20_000_000}
    plan["steps"][0]["budget"] = {"max_candidates": 100, "timeout_seconds": 5}
    prepared, _, _ = complete_partitions(plan, inputs)
    assert prepared["steps"][0]["budget"] == plan["steps"][0]["budget"]


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
        proposal("maximal-bicliques", {"entity_type": left}),
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
    assert context["bipartition"]["entity_types"] == {"User": 50, "Business": 30}
    assert context["bipartition"]["application_fills_partitions"]
    assert "left_partition" not in payload["operations"][0]["parameters"]
    assert "right_partition" not in payload["operations"][0]["parameters"]
    assert len(payload["conversation"]) == 2


async def test_partition_type_choices_pass_generation_schema_and_expand_to_native_arrays(partition_setup, monkeypatch):
    settings, analytics, events, session, body, graph = partition_setup
    planner = AnalyticsPlanner(replace(settings, llm_enabled=True), analytics, events)
    inputs = await analytics.load_inputs(session, body.inputs)
    cards = planning_cards([card for card in (await analytics.capabilities())["operations"]
                            if card["id"] == "maximal-bicliques"], inputs)
    choices = parameter_choices(cards, body.message)
    wire = {
        "status": "ready", "message": "Find all maximal bicliques across Users and Businesses.",
        "plan": {"version": 1, "device": "cpu", "steps": [{
            "operation": "maximal-bicliques", "input": {"source": "input", "input": "main"},
            "arguments": [
                {"name": "entity_type", "value": {"choice": "selected-by-code"}},
            ],
        }]},
    }
    calls = []

    def reply(request):
        content = json.loads(request.content)
        payload = json.loads(content["messages"][1]["content"])
        calls.append(payload["stage"])
        response = deepcopy(wire)
        schema = content["response_format"]["json_schema"]["schema"]
        if payload["stage"] == "plan":
            assert all('value' not in row for row in payload["parameter_choices"])
            choice = next(row for row in payload["parameter_choices"]
                          if row["parameter"] == "entity_type" and row["description"] == "Use User for entity_type.")
            response["plan"]["steps"][0]["arguments"][0]["value"]["choice"] = choice["id"]
            bad = deepcopy(response)
            bad["plan"]["steps"][0]["arguments"][0]["value"]["choice"] = "Invented"
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)
        jsonschema.validate(response, schema)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr("graphmine_agent.analytics_planning.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(reply), **kwargs))
    result = await planner._generate("plan", {"question": body.message, "parameter_choices": choices},
                                     plan_schema(cards, inputs, body.device))
    prepared, gap, directed = complete_partitions(result["plan"], inputs)
    assert gap is None and not directed
    checked = await analytics.validate(session, body.inputs, prepared, inputs)
    assert calls == ["plan"]
    assert len(checked["plan"]["steps"][0]["parameters"]["left_partition"]) == 50
    assert len(checked["plan"]["steps"][0]["parameters"]["right_partition"]) == 30
