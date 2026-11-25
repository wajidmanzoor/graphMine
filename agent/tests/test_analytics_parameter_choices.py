from copy import deepcopy
from dataclasses import replace
import json

import httpx
import jsonschema
import pytest

from graphmine_agent.analytics_parameter_choices import constrain_literals, parameter_choices, resolve_literals
from graphmine_agent.analytics_planning import AnalyticsPlanner, decoded_plan, generation_plan_schema, plan_schema, route_schema
from test_analytics_planning import setup  # noqa: F401


def test_planner_must_select_code_values_and_cannot_write_vertex_ids():
    card = {"id": "node-lookup", "parameters": {"vertices": {"kind": "array", "required": False}},
            "output_ports": {"vertices": {"type": "vertex_ids"}}}
    entities = [{"input": "main", "id": "record-outside-preview", "matched": "Ann", "label": "Ann"}]
    choices = parameter_choices([card], "Look up Ann", entities)
    schema = constrain_literals(generation_plan_schema(plan_schema([card], {"main": {}}, "cpu")), choices)
    proposal = {"status": "ready", "message": "Find Ann.", "plan": {"version": 1, "device": "cpu", "steps": [
        {"problem": "node-lookup", "input": {"source": "input", "input": "main"},
         "arguments": [{"name": "vertices", "value": {"choice": choices[0]["id"]}}]}]}}
    jsonschema.validate(proposal, schema)
    decoded = decoded_plan(resolve_literals(proposal, choices))
    assert decoded["plan"]["steps"][0]["parameters"] == {"vertices": ["record-outside-preview"]}
    for value in ({"literal": ["record-outside-preview"]}, {"choice": "invented"}):
        invalid = deepcopy(proposal)
        invalid["plan"]["steps"][0]["arguments"][0]["value"] = value
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)


async def test_router_adapter_and_highlights_use_opaque_choices(setup, monkeypatch):
    settings, service, events, session, body = setup
    settings = replace(settings, llm_enabled=True, analytics_planner_model="native-adapter",
                       analytics_router_model="routing-adapter", analytics_router_base_url="http://router.example/v1")
    planner = AnalyticsPlanner(settings, service, events)
    calls = []
    def reply(request):
        content = json.loads(request.content)
        calls.append((str(request.url), content))
        payload = json.loads(content["messages"][1]["content"])
        assert payload["view_targets"]["entities"] == [{"id": "entity_0", "label": "Ann"}]
        result = {"intent": "view", "view": {"kind": "highlight", "vertices": ["entity_0"]}, "message": "Show Ann."}
        jsonschema.validate(result, content["response_format"]["json_schema"]["schema"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr("graphmine_agent.analytics_planning.httpx.AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply), **kwargs))
    targets = {"outputs": [{"label": "Scores"}], "groups": None, "layouts": ["circle"], "entities": [9007199254740993]}
    result = await planner._generate("route", {"question": "Highlight Ann", "view_targets": {},
                                              "matched_entities": [{"label": "Ann"}]}, route_schema([], targets=targets))
    assert result["view"]["vertices"] == [9007199254740993]
    assert calls[0][0] == "http://router.example/v1/chat/completions"
    assert calls[0][1]["model"] == "routing-adapter"
