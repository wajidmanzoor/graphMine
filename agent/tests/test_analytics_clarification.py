"""Clarifications resume persisted intent; no router or guessed values on reply."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from graphmine_agent.analytics import AnalyticsError, InputReference, WorkflowRequest
from graphmine_agent.analytics_clarification import detect_gap, validator_gap
from graphmine_agent.analytics_planning import AnalyticsPlanner
from graphmine_agent.models import FileRole, SessionRecord
from test_analytics_lanes import SelectLane, normal  # noqa: F401
from test_analytics_planning import ReplayPlanner, proposal, route, setup  # noqa: F401


def reply(body, response, text=None, index=None):
    pending = response["pending_question"]
    updates = {"intent": None, "operations": [], "parameters": {}, "option_id": None, "option_turn_id": None,
               "message": text or pending["choices"][index or 0]["label"], "clarification_id": pending["id"],
               "inputs": {key: InputReference.model_validate(ref) for key, ref in response.get("inputs", pending["inputs"]).items()}}
    if index is not None:
        updates["clarification_choice"] = pending["choices"][index]["id"]
    return body.model_copy(update=updates)


def attach(service, session, body, graph, alias="main"):
    file = service.graph_store.ingest(session_id=session, role=FileRole.graph,
        filename="clarification.json", content=json.dumps(graph).encode())
    body.inputs[alias] = InputReference(file_id=file.id)
    return file


async def test_required_value_resume_after_new_planner_and_invalid_reply_stays_same_question(normal):
    settings, service, events, session, body = normal
    body.message = "Run k-cliques."
    planner = ReplayPlanner(settings, service, events, responses=[route("k-cliques")])
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["parameter"] == "k"
    fresh = ReplayPlanner(settings, service, events, responses=[], candidate_operation="k-cliques")
    invalid = await fresh.plan(session, reply(body, asked, "1"))
    assert invalid["pending_question"]["id"] == asked["pending_question"]["id"]
    assert invalid["pending_question"]["answer_error"]
    offered = await fresh.plan(session, reply(body, invalid, "Use 3."))
    assert offered["status"] == "options" and len(offered["options"]) == 1
    assert offered["options"][0]["parameters"]["k"] == 3
    assert fresh.calls == [] and len(planner.calls) == 1 and not service.list(session)
    with pytest.raises(AnalyticsError, match="no longer pending"):
        await fresh.plan(session, reply(body, asked, "4"))


async def test_required_sources_accept_full_snapshot_name_beyond_suggestions(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "many", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": i, "label": f"Person {i}"} for i in range(80)], "edges": []}
    attach(service, session, body, graph)
    body.message = "Run breadth-first-search."
    planner = ReplayPlanner(settings, service, events, responses=[route("breadth-first-search")])
    asked = await planner.plan(session, body)
    assert len(asked["choices"]) == 8
    offered = await planner.plan(session, reply(body, asked, "Person 79"))
    assert offered["options"][0]["parameters"]["sources"] == [79]
    assert len(planner.calls) == 1


async def test_ambiguous_lookup_waits_for_specific_entity_and_keeps_typed_id(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "duplicates", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": 7, "label": "Ann"}, {"id": "7", "label": "Ann"}], "edges": []}
    attach(service, session, body, graph)
    body.message = "Show Ann's record."
    planner = SelectLane(settings, service, events, select=lambda payload: {"intent": "lookup", "message": "Look up Ann.",
        "lookup_id": next(row['id'] for row in payload['lookup_choices'] if row['operation'] == 'node-lookup')})
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["kind"] == "entity" and len(asked["choices"]) == 2
    ready = await planner.plan(session, reply(body, asked, index=1))
    assert ready["status"] == "ready" and ready["lane"] == "lookup"
    assert ready["plan"]["steps"][0]["parameters"]["vertices"] == ["7"]
    assert len(planner.calls) == 1


async def test_input_selection_uses_answer_not_main_alias(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "other", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [], "edges": []}
    attach(service, session, body, graph, "other")
    planner = ReplayPlanner(settings, service, events, responses=[route("triangle-counting")])
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["kind"] == "input"
    offered = await planner.plan(session, reply(body, asked, "other"))
    assert offered["status"] == "options" and offered["options"][0]["input"] == "other"
    assert len(planner.calls) == 1


async def test_expert_uses_defaults_and_waits_for_review_before_execution(normal):
    settings, service, events, session, body = normal
    body.mode, body.message = "expert", "Find the densest subgraph."
    body.intent, body.operations = "calculate", ["densest-subgraph"]
    planner = ReplayPlanner(settings, service, events, responses=[])
    ready = await planner.plan(session, body)
    assert ready["status"] == "ready"
    record = await service.create(session, WorkflowRequest(mode="expert", inputs=body.inputs,
        plan=ready["plan"], planning_turn_id=ready["turn_id"]))
    assert record["status"] == "ready" and record["approved_hash"] is None
    assert not service.tasks and not planner.calls


@pytest.mark.parametrize("mode", ["normal", "expert"])
async def test_modes_keep_native_quality_default_without_optional_questions(normal, mode):
    settings, service, events, session, body = normal
    body.mode = mode
    body.intent, body.operations = "calculate", ["densest-subgraph"]
    planner = ReplayPlanner(settings, service, events, responses=[])
    ready = await planner.plan(session, body)
    assert ready["status"] == "ready"
    assert ready["plan"]["steps"][0]["parameters"].get("solution_quality", "exact") == "exact"


async def test_missing_sides_refusal_becomes_specific_pending_gap(normal):
    settings, service, events, session, body = normal
    body.message = "Find all maximal bicliques."
    planner = ReplayPlanner(settings, service, events, responses=[{"intent": "unsupported", "message": "No sides."}])
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["kind"] == "sides" and not service.list(session)
    invalid = await planner.plan(session, reply(body, asked, '{"left_partition":[0],"right_partition":[1,2,3,4]}'))
    assert invalid["pending_question"]["id"] == asked["pending_question"]["id"]
    assert invalid["pending_question"]["answer_error"] and not service.list(session)


async def test_user_supplied_partitions_create_copy_preserve_source_and_validate(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "one-type", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": i} for i in range(4)], "edges": [{"id": f"{u}-{v}", "source": u, "target": v} for u in range(2) for v in range(2, 4)]}
    original = attach(service, session, body, graph)
    body.intent, body.operations = "calculate", ["maximal-bicliques"]
    planner = ReplayPlanner(settings, service, events, responses=[])
    asked = await planner.plan(session, body)
    ready = await planner.plan(session, reply(body, asked, '{"left_partition":[0,1],"right_partition":[2,3]}'))
    assert ready["status"] == "ready" and ready["validation"]
    step = ready["plan"]["steps"][0]
    assert step["parameters"]["left_partition"] == [0, 1]
    copied = service.graph_store.read_graph(ready["inputs"][step["input"]["input"]]["file_id"], session)
    assert {row["attributes"]["side"] for row in copied["vertices"]} == {"left", "right"}
    assert all("side" not in row.get("attributes", {}) for row in service.graph_store.read_graph(original.id, session)["vertices"])


@pytest.mark.parametrize("change", ["input", "device", "mode", "session", "choice"])
async def test_pending_reply_cannot_change_scope_or_inject_choice(normal, change):
    settings, service, events, session, body = normal
    planner = ReplayPlanner(settings, service, events, responses=[route("breadth-first-search")])
    asked = await planner.plan(session, body)
    answered = reply(body, asked, index=0)
    if change == "input": answered.inputs = {"other": body.inputs["main"]}
    elif change == "device": answered.device = "auto"
    elif change == "mode": answered.mode = "expert"
    elif change == "session":
        session = service.database.create_session(SessionRecord(domain_id="general")).id
        answered.inputs = {}
    else: answered.clarification_choice = "made_up_id"
    if change == "choice":
        invalid = await planner.plan(session, answered)
        assert invalid["pending_question"]["id"] == asked["pending_question"]["id"]
        assert invalid["pending_question"]["answer_error"]
    else:
        with pytest.raises(AnalyticsError): await planner.plan(session, answered)
    assert len(planner.calls) == 1


async def test_objective_choice_cancels_or_resumes_without_routing(normal):
    settings, service, events, session, body = normal
    planner = ReplayPlanner(settings, service, events, candidate_operation="maximum-clique", responses=[{"intent": "needs_information", "message": "Which groups?",
        "choices": ["Use Find the largest fully connected group."]}])
    asked = await planner.plan(session, body)
    offered = await planner.plan(session, reply(body, asked, index=0))
    assert offered["options"][0]["operations"] == ["maximum-clique"] and len(planner.calls) == 1
    fresh = ReplayPlanner(settings, service, events, responses=[route("breadth-first-search")])
    asked = await fresh.plan(session, body)
    cancelled = await fresh.plan(session, reply(body, asked, "Cancel.").model_copy(update={"clarification_cancel": True}))
    assert cancelled["status"] == "answered" and cancelled["plan"] is None


async def test_ambiguous_objective_with_suggested_operation_still_waits_for_answer(normal):
    settings, service, events, session, body = normal
    body.message = "Who is important in this network?"
    planner = ReplayPlanner(settings, service, events, candidate_operation="pagerank", responses=[{
        "intent": "needs_information", "operation": "degree-centrality",
        "message": "What kind of importance matters?"}])
    asked = await planner.plan(session, body)
    assert asked["status"] == "needs_information"
    assert asked["pending_question"]["kind"] == "objective"
    assert not planner.candidate_calls and not service.list(session)
    offered = await planner.plan(session, reply(body, asked, "pagerank"))
    assert offered["options"][0]["operations"] == ["pagerank"]
    assert len(planner.calls) == 1  # Continue the saved objective without re-routing.


async def test_scoped_shortest_paths_ask_both_endpoints_instead_of_using_all_vertices(normal):
    settings, service, events, session, body = normal
    body.message = "Find the shortest path between two accounts."
    planner = ReplayPlanner(settings, service, events, responses=[route("many-source-shortest-paths")])
    first = await planner.plan(session, body)
    assert first["pending_question"]["parameter"] == "origins"
    assert not planner.candidate_calls and not service.list(session)
    invalid = await planner.plan(session, reply(body, first, "[999999]"))
    assert invalid["pending_question"]["id"] == first["pending_question"]["id"]
    assert invalid["pending_question"]["answer_error"]
    second = await planner.plan(session, reply(body, invalid, "[0]"))
    assert second["pending_question"]["parameter"] == "destinations"
    offered = await planner.plan(session, reply(body, second, "[1]"))
    choice = offered["options"][0]
    assert choice["parameters"]["origins"] == [0]
    assert choice["parameters"]["destinations"] == [1]
    assert len(planner.calls) == 1 and not service.list(session)
    picked = body.model_copy(update={"intent": "calculate", "operations": choice["operations"],
        "parameters": choice["parameters"], "option_id": choice["id"], "option_turn_id": offered["turn_id"]})
    ready = await planner.plan(session, picked)
    assert ready["status"] == "ready" and ready["validation"]
    assert ready["plan"]["steps"][0]["parameters"]["origins"] == [0]
    assert ready["plan"]["steps"][0]["parameters"]["destinations"] == [1]


@pytest.mark.parametrize('question,origins,destinations', [
    ("Compute all-pairs shortest paths.", None, None),
    ("Shortest paths between all vertices.", None, None),
    ("Shortest paths from vertex 0 to vertex 1.", [0], [1]),
    ("Shortest paths between vertex 0 and vertex 1.", [0], [1]),
    ("Shortest paths from vertex 0 to all vertices.", [0], None),
])
async def test_shortest_paths_preserve_explicit_scope_and_all_pairs_default(normal, question, origins, destinations):
    settings, service, events, session, body = normal
    body.message = question
    planner = ReplayPlanner(settings, service, events, responses=[route("many-source-shortest-paths")])
    offered = await planner.plan(session, body)
    assert offered["status"] == "options"
    assert offered["options"][0]["parameters"]["origins"] == origins
    assert offered["options"][0]["parameters"]["destinations"] == destinations


async def test_paths_to_all_vertices_still_require_unspecified_origins(normal):
    settings, service, events, session, body = normal
    body.message = "Shortest paths from two accounts to all vertices."
    planner = ReplayPlanner(settings, service, events, responses=[route("many-source-shortest-paths")])
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["parameter"] == "origins"
    assert not planner.candidate_calls


async def test_native_parameter_failure_maps_to_one_specific_gap(normal):
    settings, service, events, session, body = normal
    body.intent, body.operations, body.parameters = "calculate", ["k-cliques"], {"k": 1}
    planner = ReplayPlanner(settings, service, events, responses=[])
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["parameter"] == "k"
    assert "k must be >= 2" in asked["pending_question"]["validation_error"]
    ready = await planner.plan(session, reply(body, asked, "3"))
    assert ready["status"] == "ready" and not planner.calls


async def test_gap_priority_required_then_entity_then_input_then_native_defaults(normal):
    settings, service, events, session, body = normal
    inputs = await service.load_inputs(session, body.inputs)
    inputs["other"] = deepcopy(inputs["main"])
    caps = await service.capabilities()
    card = next(row for row in caps["operations"] if row["id"] == "max-flow-min-cut")
    entities = [{"id": 0, "input": key, "matched": "Ann"} for key in inputs]
    values = {}
    assert detect_gap(card, inputs, values, None, entities)["parameter"] == "source"
    values.update(source=0, sink=1)
    assert detect_gap(card, inputs, values, None, entities)["kind"] == "entity"
    assert detect_gap(card, inputs, values, None, entities, ["entity:ann"])["kind"] == "input"
    assert detect_gap(card, inputs, values, "main", []) is None


async def test_added_query_input_resumes_same_operation_without_routing(normal):
    settings, service, events, session, body = normal
    body.message = "Run subgraph-isomorphism."
    planner = ReplayPlanner(settings, service, events, candidate_operation="subgraph-isomorphism", responses=[{"intent": "needs_information", "operation": "subgraph-isomorphism", "message": "Which query graph?"}])
    asked = await planner.plan(session, body)
    query = {"graph": {"id": "pattern", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [{"id": "q"}], "edges": []}
    new_body = body.model_copy(update={"inputs": dict(body.inputs)})
    file = attach(service, session, new_body, query, "new")
    answered = reply(body, asked, index=0)
    answered.inputs = {"main": InputReference(file_id=file.id)}
    offered = await planner.plan(session, answered)
    assert offered["status"] == "options"
    option = offered["options"][0]
    ready = await planner.plan(session, body.model_copy(update={"message": "Use this option.", "intent": "calculate", "operations": option["operations"],
        "parameters": option["parameters"], "option_id": option["id"], "option_turn_id": offered["turn_id"],
        "inputs": {key: InputReference.model_validate(value) for key, value in offered["inputs"].items()}}))
    assert ready["status"] == "ready"
    assert ready["plan"]["steps"][0]["bindings"]["query_graph"] == {"input": "added_input"}
    assert len(planner.calls) == 1


async def test_later_step_gap_preserves_entire_selected_plan(normal):
    settings, service, events, session, body = normal
    body.intent, body.operations = "calculate", ["triangle-counting", "k-cliques"]
    planned = proposal()
    later = proposal("k-cliques")["plan"]["steps"][0]
    later["id"] = "groups"
    planned["plan"]["steps"].append(later)
    planner = ReplayPlanner(settings, service, events, responses=[planned])
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["parameter"] == "k"
    ready = await planner.plan(session, reply(body, asked, "3"))
    assert ready["status"] == "ready" and ready["validation"]
    assert [row['operation'] for row in ready['plan']['steps']] == body.operations
    assert ready['plan']['steps'][1]['parameters']['k'] == 3
    assert [row[0] for row in planner.calls] == ["plan"]


async def test_failed_reply_can_retry_the_same_pending_question(normal, monkeypatch):
    settings, service, events, session, body = normal
    body.intent, body.operations = "calculate", ["k-cliques"]
    planner = ReplayPlanner(settings, service, events, responses=[])
    asked = await planner.plan(session, body)
    validate = service.validate
    async def unavailable(*args, **kwargs):
        raise AnalyticsError("Worker unavailable", "worker_unavailable", 503)
    monkeypatch.setattr(service, "validate", unavailable)
    with pytest.raises(AnalyticsError, match="unavailable"):
        await planner.plan(session, reply(body, asked, "3"))
    monkeypatch.setattr(service, "validate", validate)
    ready = await planner.plan(session, reply(body, asked, "3"))
    assert ready["status"] == "ready" and not planner.calls


async def test_open_objective_can_select_named_contract_outside_suggestions(normal):
    settings, service, events, session, body = normal
    planner = ReplayPlanner(settings, service, events, candidate_operation="pagerank", responses=[{"intent": "needs_information", "message": "Which result do you want?"}])
    asked = await planner.plan(session, body)
    assert len(asked["pending_question"]["choices"]) > len(asked["choices"])
    offered = await planner.plan(session, reply(body, asked, "Use pagerank please."))
    assert offered["options"][0]["operations"] == ["pagerank"] and len(planner.calls) == 1


@pytest.mark.parametrize("legacy_plan", [False, True])
async def test_entity_choice_is_kept_when_continuing_multiple_operations(normal, legacy_plan):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "names", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": 0, "label": "Ann"}, {"id": 1, "label": "Ann"}], "edges": []}
    attach(service, session, body, graph)
    body.message = "Count triangles and show Ann's record."
    body.mode = "expert" if legacy_plan else "normal"
    if not legacy_plan:
        body.intent, body.operations = "calculate", ["triangle-counting", "node-lookup"]
    plan = proposal("triangle-counting", {"mode": "count"})
    record = proposal("node-lookup", {"vertices": [0 if legacy_plan else 1]})["plan"]["steps"][0]
    record["id"] = "record"
    plan["plan"]["steps"].append(record)
    responses = [route("triangle-counting", "node-lookup"), plan] if legacy_plan else [plan]
    planner = ReplayPlanner(settings, service, events, responses=responses)
    asked = await planner.plan(session, body)
    assert asked["pending_question"]["kind"] == "entity"
    ready = await planner.plan(session, reply(body, asked, index=1))
    assert ready["status"] == "ready"
    assert ready["plan"]["steps"][1]["parameters"]["vertices"] == [1]
    assert [row[0] for row in planner.calls] == (["route", "plan"] if legacy_plan else ["plan"])
    if not legacy_plan:
        assert [row['id'] for row in planner.calls[0][1]['matched_entities']] == [1]


async def test_explicit_source_id_array_disambiguates_duplicate_names(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "names", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": 0, "label": "Ann"}, {"id": 1, "label": "Ann"}], "edges": []}
    attach(service, session, body, graph)
    body.message = "Run breadth-first-search."
    planner = ReplayPlanner(settings, service, events, responses=[route("breadth-first-search")])
    asked = await planner.plan(session, body)
    offered = await planner.plan(session, reply(body, asked, "[0,1]"))
    assert offered["status"] == "options"
    assert offered["options"][0]["parameters"]["sources"] == [0,1]
