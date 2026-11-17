import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from graphmine_agent.analytics import AnalyticsError, InputReference, WorkflowRequest
from graphmine_agent.analytics_planning import AnalyticsPlanner
from graphmine_agent.models import FileRole
from test_analytics_planning import ReplayPlanner, route, setup  # noqa: F401


class SelectLane(AnalyticsPlanner):
    def __init__(self, *args, select):
        super().__init__(*args)
        self.select, self.calls = select, []

    async def _generate(self, stage, payload, schema, catalog=None):
        assert stage == "route", "This lane must not ask a model to plan"
        self.calls.append(deepcopy(payload))
        return self.select(payload)

    async def _route_problems(self, body, routing, cards, eligible_cards, **_context):
        # These authored fixtures isolate intent-lane behavior. Catalog narrowing
        # and real transport are covered by the taxonomy and planning suites.
        return await self._generate("route", routing, {}), None


@pytest.fixture
async def normal(setup):
    settings, service, events, session, body = setup
    body.mode = "normal"
    yield settings, service, events, session, body
    await service.close()


async def test_description_uses_full_snapshot_evidence_and_no_plan(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "large", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [{"id": i, "type": "User" if i < 40 else "Business"} for i in range(80)],
             "edges": [{"id": i, "source": i, "target": i + 40} for i in range(40)]}
    file = service.graph_store.ingest(session_id=session, role=FileRole.graph, filename="large.json", content=json.dumps(graph).encode())
    body.inputs = {"main": InputReference(file_id=file.id)}
    body.message = "How many Users are loaded?"
    planner = SelectLane(settings, service, events, select=lambda payload: {
        "intent": "describe_input", "message": "ignored model count 999",
        "fact_ids": [next(fact["id"] for fact in payload["input_facts"] if fact["property"] == "vertex_type_count.User")]})
    answer = await planner.plan(session, body)
    assert answer["lane"] == "describe_input" and answer["plan"] is None
    assert answer["answer"]["facts"][0]["value"] == 40
    assert "999" not in json.dumps(answer["answer"])
    assert len(planner.calls) == 1 and service.list(session) == []


async def test_conceptual_reply_cites_only_retrieved_contracts(normal):
    settings, service, events, session, body = normal
    body.inputs = {}  # General questions do not require an uploaded graph.
    body.message = "Explain k-core versus k-truss."
    planner = SelectLane(settings, service, events, select=lambda payload: {
        "intent": "reply", "message": "Core membership uses degree; truss membership uses triangle support.",
        "source_ids": ["doc.core-truss"]})
    answer = await planner.plan(session, body)
    assert answer["lane"] == "reply" and answer["plan"] is None
    assert answer["answer"]["citations"] == [{"id": "doc.core-truss", "kind": "doc", "ref": "catalog/agent_concepts.json#core-truss"}]
    assert len(planner.calls) == 1 and service.list(session) == []


async def test_lookup_uses_code_owned_ids_and_no_planner_call(normal):
    settings, service, events, session, body = normal
    body.message = "Show the record for vertex 0."
    planner = SelectLane(settings, service, events, select=lambda payload: {
        "intent": "lookup", "message": "Look up the record.",
        "lookup_id": next(row["id"] for row in payload["lookup_choices"] if row["operation"] == "node-lookup")})
    answer = await planner.plan(session, body)
    assert answer["lane"] == "lookup" and answer["status"] == "ready"
    assert answer["plan"]["steps"][0]["parameters"] == {"vertices": [0]}
    assert answer["validation"] and len(planner.calls) == 1
    assert all("plan" not in row for row in planner.calls[0]["lookup_choices"])


async def test_normal_calculation_waits_for_a_saved_choice_then_validates_and_runs(normal):
    settings, service, events, session, body = normal
    body.message = "Count all triangles in the graph."
    planner = ReplayPlanner(settings, service, events, responses=[route("triangle-counting")])
    offered = await planner.plan(session, body)
    assert offered["status"] == "options" and offered["plan"] is None
    assert len(offered["options"]) == 2 and service.list(session) == []
    assert offered["options"][0]["operations"] == ["triangle-counting"]
    assert offered["options"][1]["operations"] != offered["options"][0]["operations"]
    choice = offered["options"][0]
    picked = body.model_copy(update={"message": "Use the first option.", "intent": "calculate",
        "operations": choice["operations"], "parameters": choice["parameters"],
        "option_id": choice["id"], "option_turn_id": offered["turn_id"]})
    ready = await planner.plan(session, picked)
    assert ready["status"] == "ready" and ready["lane"] == "calculate"
    assert len(planner.calls) == 1
    record = await service.create(session, WorkflowRequest(mode="normal", plan=ready["plan"],
        inputs=picked.inputs, planning_turn_id=ready["turn_id"]))
    await asyncio.gather(*list(service.tasks.values()))
    await asyncio.gather(*list(service.answer_tasks))
    assert service.get(record["id"])["status"] == "completed"
    assert service.result(record["id"])["steps"]["answer"]["result"]["ports"]["count"]["value"] == 1


@pytest.mark.parametrize("tamper", ["operation", "parameters", "inputs"])
async def test_choice_rejects_tampering_or_changed_inputs(normal, tamper):
    settings, service, events, session, body = normal
    planner = ReplayPlanner(settings, service, events, responses=[route("triangle-counting")])
    offered = await planner.plan(session, body)
    option = offered["options"][0]
    picked = body.model_copy(update={"intent": "calculate", "operations": option["operations"],
        "parameters": option["parameters"], "option_id": option["id"], "option_turn_id": offered["turn_id"]})
    if tamper == "operation":
        picked.operations = ["maximum-clique"]
    elif tamper == "parameters":
        picked.parameters = {"invented_parameter": "enumerate"}
    else:
        picked.inputs = {"changed": next(iter(body.inputs.values()))}
    with pytest.raises(AnalyticsError, match="match|Invalid edited parameter"):
        await planner.plan(session, picked)
    assert len(planner.calls) == 1 and service.list(session) == []


async def test_direct_shortcut_still_offers_two_options(normal):
    settings, service, events, session, body = normal
    settings = replace(settings, analytics_direct_plans=True)
    body.message = "Count triangles"
    planner = ReplayPlanner(settings, service, events, responses=[], candidate_operation="triangle-counting")
    offered = await planner.plan(session, body)
    assert offered["status"] == "options" and len(offered["options"]) == 2
    assert planner.calls == [] and len(planner.candidate_calls) == 1 and service.list(session) == []


async def test_user_parameter_edit_is_validated_without_resampling(normal):
    settings, service, events, session, body = normal
    body.message = "Find the 3-core."
    planner = ReplayPlanner(settings, service, events, responses=[route("k-core")])
    offered = await planner.plan(session, body)
    option = offered["options"][0]
    assert option["parameters"]["requested_k"] == 3
    picked = body.model_copy(update={"intent": "calculate", "operations": option["operations"],
        "parameters": {**option["parameters"], "requested_k": 2}, "option_id": option["id"], "option_turn_id": offered["turn_id"]})
    checked = await planner.plan(session, picked)
    assert checked["validation"] and checked["plan"]["steps"][0]["parameters"]["requested_k"] == 2
    assert len(planner.calls) == 1 and len(planner.candidate_calls) == 1


async def test_two_low_matches_ask_an_open_question_and_save_allowed_choices(normal):
    settings, service, events, session, body = normal
    class Disagreeing(ReplayPlanner):
        async def _generate(self, stage, payload, schema, catalog=None):
            if stage == "candidates":
                return [{"decision": {"operation": row["operation"], "parameter_choice": row["choices"][0]["id"],
                                      "interpretation": "A possible result."}, "operation_logprob": None}
                        for row in payload["choices"][:5]]
            return await super()._generate(stage, payload, schema, catalog)
    planner = Disagreeing(settings, service, events, responses=[route("triangle-counting")])
    response = await planner.plan(session, body)
    assert response["status"] == "needs_information" and response["choices"] == []
    assert response["pending_question"]["open_question"]
    assert response["pending_question"]["choices"]
    assert all(row["match"] == "Low" for row in response["option_evidence"]["candidates"])
    assert service.list(session) == []


async def test_missing_required_source_stops_before_planning(normal):
    settings, service, events, session, body = normal
    body.message = "Run breadth-first search."
    planner = ReplayPlanner(settings, service, events, responses=[route("breadth-first-search")])
    response = await planner.plan(session, body)
    assert response["status"] == "needs_information" and "sources" in response["message"]
    assert len(planner.calls) == 1 and service.list(session) == []


async def test_confirmed_weight_promotion_uses_a_copy_and_preserves_original(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "ratings", "directed": True, "allows_self_loops": False, "allows_parallel_edges": False}, "vertices": [{"id": 0}, {"id": 1}],
             "edges": [{"id": 0, "source": 0, "target": 1, "attributes": {"stars": 4}}]}
    file = service.graph_store.ingest(session_id=session, role=FileRole.graph, filename="ratings.json", content=json.dumps(graph).encode())
    body.inputs = {"main": InputReference(file_id=file.id)}
    body.intent, body.operations, body.parameters = "calculate", ["max-flow-min-cut"], {"source": 0, "sink": 1}
    planner = ReplayPlanner(settings, service, events, responses=[])
    prompt = await planner.plan(session, body)
    assert prompt["status"] == "needs_information"
    assert "Use stars as the weight." in prompt["choices"]
    reply = body.model_copy(update={"intent": None, "operations": [], "parameters": {}, "message": "Use stars as the weight."})
    ready = await planner.plan(session, reply)
    assert ready["status"] == "ready"
    prepared_alias = ready["plan"]["steps"][0]["input"]["input"]
    assert prepared_alias != "main"
    refs = {key: InputReference.model_validate(value) for key, value in ready["inputs"].items()}
    snapshots = await service.load_inputs(session, refs)
    assert snapshots[prepared_alias]["data"]["edges"][0]["weight"] == 4
    assert "weight" not in snapshots["main"]["data"]["edges"][0]
    assert planner.calls == []


async def test_timestamp_promotion_requires_confirmation_and_validates_copy(normal):
    settings, service, events, session, body = normal
    graph = {"graph": {"id": "events", "directed": True, "allows_self_loops": False, "allows_parallel_edges": False},
             "vertices": [{"id": 0}, {"id": 1}],
             "edges": [{"id": 0, "source": 0, "target": 1, "attributes": {"timestamp": 10, "duration": 1}}]}
    file = service.graph_store.ingest(session_id=session, role=FileRole.graph, filename="events.json", content=json.dumps(graph).encode())
    body.inputs = {"main": InputReference(file_id=file.id)}
    body.intent, body.operations, body.parameters = "calculate", ["temporal-paths"], {"source": 0, "ready_time": 0}
    planner = ReplayPlanner(settings, service, events, responses=[])
    prompt = await planner.plan(session, body)
    assert prompt["choices"] == ["Use attributes.timestamp as event timestamps."]
    assert not service.list(session)
    reply = body.model_copy(update={"intent": None, "operations": [], "parameters": {}, "message": prompt["choices"][0]})
    ready = await planner.plan(session, reply)
    assert ready["status"] == "ready"
    alias = ready["plan"]["steps"][0]["input"]["input"]
    assert service.graph_store.read_graph(ready["inputs"][alias]["file_id"], session)["edges"][0]["timestamp"] == 10
    assert "timestamp" not in service.graph_store.read_graph(file.id, session)["edges"][0]


async def test_removed_operations_reach_router_with_reasons(normal):
    settings, service, events, session, body = normal
    planner = SelectLane(settings, service, events, select=lambda _: {
        "intent": "needs_information", "message": "Which query graph should I use?", "choices": []})
    await planner.plan(session, body)
    removed = {row["operation"]: row["reason"] for row in planner.calls[0]["removed_operations"]}
    assert "query" in removed["subgraph-isomorphism"]
    assert "sides" in removed["maximal-bicliques"]
    assert "triangle-counting" not in removed


async def test_single_edge_type_count_includes_equivalent_total_evidence(normal):
    settings, service, events, session, body = normal
    planner = SelectLane(settings, service, events, select=lambda payload: {
        "intent": "describe_input", "message": "", "fact_ids": [next(row["id"] for row in payload["input_facts"] if row["property"].startswith("edge_type_count."))]})
    answered = await planner.plan(session, body)
    facts = answered["answer"]["facts"]
    assert len(facts) == 2 and facts[0]["value"] == facts[1]["value"]
    assert facts[1]["property"] == "edges_count"
    assert len({row["id"] for row in answered["answer"]["citations"]}) == 2
