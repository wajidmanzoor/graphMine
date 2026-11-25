"""Cypher snapshots, bounded model context, and real validated biclique execution."""

import asyncio
import json
from copy import deepcopy

import jsonschema
import pytest
from neo4j import Record
from neo4j.graph import Graph, Node

from graphmine_agent.analytics import InputReference, WorkflowRequest
from graphmine_agent.analytics_bipartite import CONVERT_CHOICE, KEEP_CHOICE
from graphmine_agent.database_queries import execute_query
from graphmine_agent.graph_context import infer_bipartition
from graphmine_agent.models import FileRole
from test_analytics_planning import ReplayPlanner, proposal, route, setup  # noqa: F401
from test_database_query_projection import read_transaction, request
from test_database_workspace import source  # noqa: F401


@pytest.fixture
def cypher_graph(source, monkeypatch):
    driver_graph = Graph()
    users = [Node(driver_graph, f"u{i}", i, {"User"}, {"name": f"User {i}"}) for i in range(40)]
    businesses = [Node(driver_graph, f"b{i}", i + 40, {"Business"}, {"name": f"Business {i}"}) for i in range(40)]
    read_transaction(monkeypatch, [Record({"source": u, "target": b, "type": "REVIEWED"})
                                 for u, b in zip(users, businesses)])
    graph, *_ = execute_query(source, request(), 1_000_000)
    return graph


def attach(analytics, session, body, graph, alias="main"):
    file = analytics.graph_store.ingest(session_id=session, role=FileRole.graph,
                                       filename="cypher-result.json", content=json.dumps(graph).encode())
    body.inputs[alias] = InputReference(file_id=file.id, kind="graph")
    return file


async def execute(analytics, session, body, planned):
    record = await analytics.create(session, WorkflowRequest(
        mode="normal", plan=planned["plan"], inputs=planned.get("inputs", body.inputs),
        planning_turn_id=planned["turn_id"],
    ))
    if record["status"] == "awaiting_review":
        record = await analytics.start(record["id"], record["validation"]["workflow_hash"], record["revision"])
    async with asyncio.timeout(30):
        while analytics.get(record["id"])["status"] in {"queued", "running"}:
            await asyncio.sleep(.02)
    assert analytics.get(record["id"])["status"] == "completed", analytics.get(record["id"])
    await asyncio.gather(*list(analytics.tasks.values()))
    await asyncio.gather(*list(analytics.answer_tasks))
    return analytics.result(record["id"])["steps"]["answer"]["result"]


@pytest.mark.parametrize("entity_type", [None, "User", "Business"])
async def test_cypher_side_confirmation_runs_all_80_vertices(setup, cypher_graph, entity_type):
    settings, analytics, events, session, body = setup
    attach(analytics, session, body, cypher_graph)
    body.message = "Find all maximal bicliques, with Users on one side and Businesses on the other."
    planner = ReplayPlanner(settings, analytics, events, responses=[
        route("maximal-bicliques"),
        proposal("maximal-bicliques", {"entity_type": entity_type} if entity_type else {}),
    ])
    planned = await planner.plan(session, body)
    assert planned["status"] == "ready"
    params = planned["plan"]["steps"][0]["parameters"]
    assert len(params["left_partition"]) == len(params["right_partition"]) == 40
    assert params["left_partition"] == infer_bipartition(cypher_graph, entity_type)
    assert "entity_type" not in params
    _, payload, schema = planner.calls[-1]
    assert len(payload["inputs"]["main"]["vertices_sample"]) == 8
    assert payload["inputs"]["main"]["bipartition"]["entity_types"] == {"User": 40, "Business": 40}
    assert "left_partition" not in payload["problems"][0]["parameters"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal("maximal-bicliques", {"left_partition": ["invented"]}), schema)
    result = await execute(analytics, session, body, planned)
    assert result["result"]["total_count"] == 40
    assert result["complete"]
    assert [stage for stage, *_ in planner.calls] == ["route", "plan"]


async def test_missing_sides_stops_before_planning(setup):
    settings, analytics, events, session, body = setup
    body.message = "Find maximal bicliques."
    planner = ReplayPlanner(settings, analytics, events, responses=[{"intent": "needs_information", "message": "Which vertices belong on each side?", "choices": []}])
    planned = await planner.plan(session, body)
    assert planned["status"] == "needs_information" and planned["plan"] is None
    assert [stage for stage, *_ in planner.calls] == ["route"]
    assert not analytics.list(session)
    # Execution eligibility records the missing sides while the router asks
    # for the user's intended partition instead of attempting the calculation.
    assert any(row["problem"] == "maximal-bicliques"
               for row in planner.calls[0][1]["removed_problems"])
    assert planner.calls[0][1]["inputs"]["main"]["bipartition"]["available"] is False


async def test_missing_required_value_is_not_a_reasoning_retry(setup):
    settings, analytics, events, session, body = setup
    body.message = "Find a path from vertex 0."
    planner = ReplayPlanner(settings, analytics, events, responses=[
        route("query-paths"), proposal("query-paths", {"source": 0}),
    ])
    planned = await planner.plan(session, body)
    assert planned["status"] == "needs_information" and "target" in planned["message"]
    assert [stage for stage, *_ in planner.calls] == ["route"]


async def test_biclique_uses_selected_input_not_first_alias(setup, cypher_graph):
    settings, analytics, events, session, body = setup
    # main is the unrelated triangle from setup; the Cypher graph is another input.
    attach(analytics, session, body, cypher_graph, alias="reviews")
    proposed = proposal("maximal-bicliques", {"entity_type": "Business"})
    proposed["plan"]["steps"][0]["input"] = {"input": "reviews"}
    planner = ReplayPlanner(settings, analytics, events, responses=[route("maximal-bicliques"), proposed])
    pending = await planner.plan(session, body)
    assert pending["pending_question"]["kind"] == "input"
    body = body.model_copy(update={"message": "Use reviews.", "clarification_id": pending["pending_question"]["id"]})
    planned = await planner.plan(session, body)
    assert planned["status"] == "ready"
    assert planned["plan"]["steps"][0]["input"] == {"input": "reviews"}
    assert planned["plan"]["steps"][0]["parameters"]["left_partition"] == infer_bipartition(cypher_graph)
    assert len(planner.calls) == 1


@pytest.mark.parametrize("fault", ["same_side", "partial_side", "unknown_type"])
async def test_side_inference_checks_records_beyond_preview(setup, cypher_graph, fault):
    settings, analytics, events, session, body = setup
    if fault == "same_side":
        cypher_graph["edges"][-1]["target"] = cypher_graph["edges"][-2]["source"]
    elif fault == "partial_side":
        cypher_graph["vertices"][-1]["attributes"]["side"] = "right"
    else:
        cypher_graph["vertices"][-1]["type"] = "Unknown"
    attach(analytics, session, body, cypher_graph)
    planner = ReplayPlanner(settings, analytics, events, responses=[{"intent": "needs_information", "message": "Which vertices belong on each side?", "choices": []}])
    assert (await planner.plan(session, body))["status"] == "needs_information"
    assert [stage for stage, *_ in planner.calls] == ["route"]


@pytest.mark.parametrize("accept", [True, False])
async def test_directed_confirmation_preserves_original_and_resumes_without_model(setup, cypher_graph, accept):
    settings, analytics, events, session, body = setup
    cypher_graph["graph"]["directed"] = True
    original = attach(analytics, session, body, cypher_graph)
    original_bytes = analytics.graph_store.execution_path(original.id, session).read_bytes()
    planner = ReplayPlanner(settings, analytics, events, responses=[
        route("maximal-bicliques"), proposal("maximal-bicliques", {"entity_type": "User"}),
    ])
    body.message = "find all maximal bicliques"
    asked = await planner.plan(session, body)
    assert asked["status"] == "needs_information" and asked["choices"] == [CONVERT_CHOICE, KEEP_CHOICE]
    assert not analytics.list(session)
    resumed = ReplayPlanner(settings, analytics, events, responses=[])
    body.message = CONVERT_CHOICE if accept else KEEP_CHOICE
    planned = await resumed.plan(session, body)
    assert resumed.calls == []
    assert analytics.graph_store.execution_path(original.id, session).read_bytes() == original_bytes
    if not accept:
        assert planned["plan"] is None and not analytics.list(session)
        return
    assert planned["status"] == "ready"
    selected_alias = planned["plan"]["steps"][0]["input"]["input"]
    reference = planned["inputs"][selected_alias]
    assert planned["inputs"]["main"]["file_id"] == original.id
    assert reference["file_id"] != original.id
    projected = analytics.graph_store.read_graph(reference["file_id"], session)
    assert projected["graph"]["directed"] is False
    assert projected["vertices"] == cypher_graph["vertices"] and projected["edges"] == cypher_graph["edges"]
    saved = analytics.database.events(session, types=("workflow.chat",))[-1].payload
    assert saved["inputs"] == planned["inputs"]
    result = await execute(analytics, session, body, planned)
    assert result["result"]["total_count"] == 40


async def test_conversion_confirmation_cannot_apply_to_different_inputs(setup, cypher_graph):
    settings, analytics, events, session, body = setup
    cypher_graph["graph"]["directed"] = True
    attach(analytics, session, body, cypher_graph)
    planner = ReplayPlanner(settings, analytics, events, responses=[route("maximal-bicliques"), proposal("maximal-bicliques")])
    await planner.plan(session, body)
    other = deepcopy(cypher_graph)
    other["graph"]["id"] = "another-graph"
    file = attach(analytics, session, body, other)
    resumed = ReplayPlanner(settings, analytics, events, responses=[{"intent": "unsupported", "message": "Changed input."}])
    body.message = CONVERT_CHOICE
    await resumed.plan(session, body)
    assert len(resumed.calls) == 1
    assert analytics.graph_store.read_graph(file.id, session)["graph"]["directed"]


async def test_conversion_changes_only_biclique_steps_in_shared_input_workflow(setup, cypher_graph):
    settings, analytics, events, session, body = setup
    cypher_graph["graph"]["directed"] = True
    original = attach(analytics, session, body, cypher_graph)
    # Also exercise an existing input alias that looks like an application alias.
    body.inputs["biclique_input_1"] = body.inputs["main"]
    proposed = proposal("maximal-bicliques")
    proposed["plan"]["steps"].append({
        "id": "rank", "problem": "pagerank", "input": {"input": "main"},
        "parameters": {"weight_mode": "unweighted"}, "bindings": {},
    })
    planner = ReplayPlanner(settings, analytics, events, responses=[
        route("maximal-bicliques", "pagerank"), proposed,
    ])
    assert (await planner.plan(session, body))["status"] == "needs_information"
    body.message = CONVERT_CHOICE
    planned = await planner.plan(session, body)
    assert planned["status"] == "ready"
    bicliques, rank = planned["plan"]["steps"]
    assert rank["input"] == {"input": "main"}
    assert bicliques["input"]["input"] not in {"main", "biclique_input_1"}
    assert planned["inputs"]["main"]["file_id"] == original.id
    assert planned["inputs"]["biclique_input_1"]["file_id"] == original.id
    assert (await execute(analytics, session, body, planned))["result"]["total_count"] == 40


def test_inference_preserves_mixed_ids_and_declared_sides():
    graph = {"vertices": [{"id": 0, "type": "User", "attributes": {"side": "left"}},
                          {"id": "0", "type": "Business", "attributes": {"side": "right"}}],
             "edges": [{"source": 0, "target": "0"}]}
    assert infer_bipartition(graph, "User") == [0]
    assert infer_bipartition(graph, "Business") is None
    graph["vertices"][1]["attributes"].clear()
    assert infer_bipartition(graph) is None
