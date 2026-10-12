from __future__ import annotations

import asyncio
import json as jsonlib
from dataclasses import replace

import httpx
import pytest
from graphmine_agent.config import Settings
from graphmine_agent.llm import (
    LLMError,
    OpenAICompatibleModel,
    constrain_plan_schema,
    decoder_schema,
    runtime_schema,
)
from graphmine_agent.models import GroundedNarrative, LLMMode, PlanDraft, RouteDecision


def test_decoder_compatibility_preserves_logical_contract_and_other_constraints():
    logical = runtime_schema(GroundedNarrative, {})
    snapshot = jsonlib.dumps(logical, sort_keys=True)
    wire = decoder_schema(logical)
    chart = wire["$defs"]["VegaLiteDraft"]["properties"]["spec_json"]
    assert "minLength" not in chart and "maxLength" not in chart
    assert (
        logical["$defs"]["VegaLiteDraft"]["properties"]["spec_json"]["maxLength"]
        == 60000
    )
    assert jsonlib.dumps(logical, sort_keys=True) == snapshot
    bounds = {
        "type": "object",
        "required": ["label", "values"],
        "additionalProperties": False,
        "properties": {
            "label": {"type": "string", "minLength": 1, "pattern": "^[a-z]+$"},
            "values": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "integer", "minimum": 0, "maximum": 9},
            },
        },
    }
    compatible = decoder_schema(bounds)
    del bounds["properties"]["label"]["minLength"]
    assert compatible == bounds


def test_decoder_defers_only_unrepresentable_integer_bounds():
    logical = {
        "anyOf": [
            {"type": "integer", "minimum": 0, "maximum": 2**64 - 1},
            {"type": "integer", "exclusiveMinimum": -(2**63), "maximum": 100},
            {"type": "integer", "minimum": 32, "maximum": 65536, "multipleOf": 32},
        ]
    }
    wire = decoder_schema(logical)
    assert wire["anyOf"][0] == {"type": "integer", "minimum": 0}
    assert wire["anyOf"][1] == {"type": "integer", "maximum": 100}
    assert wire["anyOf"][2] == logical["anyOf"][2]
    assert logical["anyOf"][0]["maximum"] == 2**64 - 1


@pytest.mark.parametrize("spec", [jsonlib.dumps({"mark": "bar"}), "x" * 60001])
def test_escaped_chart_strings_keep_post_generation_length_validation(settings, spec):
    async def scenario():
        model = OpenAICompatibleModel(settings)
        await model._client.aclose()
        calls = []
        target = {
            "fact_ids": ["count"],
            "charts": [
                {
                    "title": "Counts",
                    "description": "Compare computed counts.",
                    "spec_json": spec,
                    "fact_ids": ["count"],
                }
            ],
        }

        def respond(request):
            body = jsonlib.loads(request.content)
            calls.append(body)
            schema = body["response_format"]["json_schema"]["schema"]
            assert (
                "maxLength"
                not in schema["$defs"]["VegaLiteDraft"]["properties"]["spec_json"]
            )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": jsonlib.dumps(target)}}]}
            )

        model._client = httpx.AsyncClient(
            base_url="http://shared/v1", transport=httpx.MockTransport(respond)
        )
        try:
            if len(spec) > 60000:
                with pytest.raises(LLMError, match="at most 60000"):
                    await model.generate(
                        mode=LLMMode.analyst,
                        schema=GroundedNarrative,
                        user_payload={},
                    )
                assert len(calls) == 2  # One bounded repair, then reject.
            else:
                result = await model.generate(
                    mode=LLMMode.analyst, schema=GroundedNarrative, user_payload={}
                )
                assert jsonlib.loads(result.charts[0].spec_json) == {"mark": "bar"}
                assert len(calls) == 1
        finally:
            await model.close()

    asyncio.run(scenario())


def test_deployed_adapter_is_routing_only_and_checks_its_fingerprint(settings):
    from graphmine_agent.models import TurnDecision

    async def scenario():
        configured = replace(
            settings,
            llm_route_base_url="http://router.test",
            llm_route_model="business-v1",
            llm_route_adapter_sha256="verified-hash",
        )
        model = OpenAICompatibleModel(configured)
        await model._client.aclose()
        await model._route_client.aclose()
        calls = []
        fingerprint = ["verified-hash"]

        def router(request):
            calls.append("adapter")
            body = jsonlib.loads(request.content)
            assert body["payload"]["message"] == "Find groups"
            return httpx.Response(
                200,
                json={
                    "identity": {
                        "model": "business-v1",
                        "adapter_sha256": fingerprint[0],
                    },
                    "decision": {
                        "problem_id": "maximal_clique_enumeration",
                        "operation_id": "maximal-cliques",
                        "supported": True,
                        "confidence": 1,
                        "ambiguity": [],
                        "missing_information": [],
                        "explanation": "Find all groups",
                    },
                },
            )

        def base(request):
            calls.append("base")
            body = jsonlib.loads(request.content)
            assert body["response_format"]["json_schema"]["name"] == "TurnDecision"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": jsonlib.dumps(
                                    {
                                        "action": "explain",
                                        "request": "Explain groups",
                                        "explanation": "Same result",
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        model._route_client = httpx.AsyncClient(
            base_url="http://router.test", transport=httpx.MockTransport(router)
        )
        model._client = httpx.AsyncClient(
            base_url="http://base.test", transport=httpx.MockTransport(base)
        )
        await model.generate(
            mode=LLMMode.planner,
            schema=RouteDecision,
            user_payload={"message": "Find groups"},
        )
        await model.generate(
            mode=LLMMode.planner,
            schema=TurnDecision,
            user_payload={"message": "Explain"},
        )
        assert calls == ["adapter", "base"]
        fingerprint[0] = "wrong-weights"
        with pytest.raises(LLMError, match="fingerprint"):
            await model.generate(
                mode=LLMMode.planner,
                schema=RouteDecision,
                user_payload={"message": "Find groups"},
            )
        assert calls == ["adapter", "base", "adapter"]  # No silent base-model fallback.
        await model.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("server_contract", ["current", "legacy-20", "unrecognized"])
def test_explicit_expanded_adapter_dispatch_checks_server_compatibility(
    settings, catalog, server_contract
):
    async def scenario():
        configured = replace(
            settings,
            llm_route_base_url="http://router.test",
            llm_route_model="business-v1",
            llm_route_adapter_sha256="verified-hash",
            llm_route_allow_expanded_catalog=True,
        )
        contract = configured.routing_contract_version
        identity = {
            "model": "business-v1",
            "adapter_sha256": "verified-hash",
            "supported_routing_contracts": ["legacy-20", contract],
            "routing_contract_version": contract
            if server_contract == "current"
            else server_contract,
        }
        model = OpenAICompatibleModel(configured)
        await model._client.aclose()
        await model._route_client.aclose()
        calls = []

        def router(request):
            calls.append(request.url.path)
            if request.url.path == "/health":
                return httpx.Response(200, json=identity)
            body = jsonlib.loads(request.content)
            assert body["payload"]["routing_context"]["contract_version"] == contract
            return httpx.Response(
                200,
                json={
                    "identity": identity,
                    "decision": {
                        "problem_id": "connected_components",
                        "operation_id": "connected-components",
                        "supported": True,
                        "confidence": 1,
                        "explanation": "Connected groups.",
                    },
                },
            )

        def base(request):
            assert request.url.path == "/models", (
                "Routing must never silently fall back"
            )
            return httpx.Response(200, json={"data": []})

        model._route_client = httpx.AsyncClient(
            base_url="http://router.test", transport=httpx.MockTransport(router)
        )
        model._client = httpx.AsyncClient(
            base_url="http://base.test", transport=httpx.MockTransport(base)
        )
        assert await model.available()
        request = {
            "mode": LLMMode.planner,
            "schema": RouteDecision,
            "user_payload": {
                "message": "Find connected groups",
                "routing_context": catalog.routing_context("general"),
            },
        }
        if server_contract == "current":
            assert (
                await model.generate(**request)
            ).operation_id == "connected-components"
        else:
            with pytest.raises(LLMError, match="different catalog"):
                await model.generate(**request)
        identity["supported_routing_contracts"] = ["legacy-20"]
        assert not await model.available()
        with pytest.raises(LLMError, match="does not accept the current catalog"):
            await model.generate(**request)
        assert calls == ["/health", "/route", "/health", "/route"]
        await model.close()

    asyncio.run(scenario())


def test_generation_schema_uses_the_exact_tool_and_available_file_allowlists(catalog):
    schema = PlanDraft.model_json_schema()
    constrain_plan_schema(
        schema,
        {
            "operation_context": catalog.operation_context("maximal-bicliques"),
            "available_files": [
                {"id": "customers", "role": "left_partition"},
                {"id": "other-graph", "role": "graph"},
            ],
        },
    )
    properties = schema["$defs"]["PlanConfiguration"]["properties"]
    assert properties["backend_id"]["const"] == "auto"
    assert properties["parameters"]["additionalProperties"] is False
    assert set(properties["parameters"]["properties"]) == set(
        catalog.operation("maximal-bicliques").instruction["parameters"]
    )
    assert properties["auxiliary_inputs"]["additionalProperties"] is False
    partition = properties["auxiliary_inputs"]["properties"]["left_partition"]
    assert partition["items"]["enum"] == ["customers"] and partition["maxItems"] == 1
    assert set(properties["optional_outputs"]["items"]["enum"]) == set(
        catalog.operation("maximal-bicliques").instruction["optional_outputs"]
    )

    schema = PlanDraft.model_json_schema()
    constrain_plan_schema(
        schema, {"operation_context": catalog.operation_context("community-detection")}
    )
    assert schema["$defs"]["PlanConfiguration"]["properties"]["auxiliary_inputs"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


class _RetryClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, path: str, *, json: dict) -> httpx.Response:
        del path, json
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("first request timed out")
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://local.test/chat/completions"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": jsonlib.dumps(
                                {
                                    "problem_id": "maximal_clique_enumeration",
                                    "operation_id": "maximal-cliques",
                                    "supported": True,
                                    "confidence": 1.0,
                                    "ambiguity": [],
                                    "missing_information": [],
                                    "explanation": "Explicit maximal-clique request.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    async def aclose(self) -> None:
        return None


def test_local_model_retries_one_transport_failure(settings: Settings) -> None:
    async def scenario() -> None:
        model = OpenAICompatibleModel(settings)
        await model._client.aclose()
        retry_client = _RetryClient()
        model._client = retry_client  # type: ignore[assignment]
        decision = await model.generate(
            mode=LLMMode.planner,
            schema=RouteDecision,
            user_payload={"message": "Enumerate every maximal clique."},
        )
        assert decision.operation_id == "maximal-cliques"
        assert retry_client.calls == 2
        await model.close()

    asyncio.run(scenario())


def test_followup_classifier_keeps_compact_json_instruction(settings):
    from graphmine_agent.models import TurnDecision

    class Responses:
        async def post(self, path, *, json):
            system = json["messages"][0]["content"]
            assert "compact JSON on one line" in system
            assert "Never pad" in system
            return httpx.Response(
                200,
                request=httpx.Request("POST", "http://local.test/chat/completions"),
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"action":"analyze","request":"Use a five-second window.","explanation":"The time window changed."}'
                            },
                        }
                    ]
                },
            )

        async def aclose(self):
            pass

    async def scenario():
        model = OpenAICompatibleModel(settings)
        await model._client.aclose()
        model._client = Responses()
        result = await model.generate(
            mode=LLMMode.planner,
            schema=TurnDecision,
            user_payload={"message": "Use a five-second window."},
        )
        assert result.action == "analyze"
        await model.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("always_invalid", [False, True])
def test_malformed_model_output_has_one_bounded_recorded_repair(
    settings, always_invalid
):
    class Responses:
        def __init__(self):
            self.calls = []

        async def post(self, path, *, json):
            self.calls.append(json)
            content = (
                '{"ambiguity":    '
                if len(self.calls) == 1 or always_invalid
                else jsonlib.dumps(
                    {
                        "supported": False,
                        "confidence": 1,
                        "explanation": "This task is not supported.",
                    }
                )
            )
            return httpx.Response(
                200,
                request=httpx.Request("POST", "http://local.test/chat/completions"),
                json={
                    "choices": [
                        {
                            "finish_reason": "length"
                            if content.endswith(" ")
                            else "stop",
                            "message": {"content": content},
                        }
                    ]
                },
            )

    class History:
        def __init__(self):
            self.events = []

        def current(self, kind, data):
            self.events.append((kind, data))

    async def scenario():
        history = History()
        model = OpenAICompatibleModel(settings, history)
        await model._client.aclose()
        responses = Responses()
        model._client = responses
        if always_invalid:
            with pytest.raises(LLMError, match="response was invalid"):
                await model.generate(
                    mode=LLMMode.planner,
                    schema=RouteDecision,
                    user_payload={"message": "Find a route"},
                )
        else:
            answer = await model.generate(
                mode=LLMMode.planner,
                schema=RouteDecision,
                user_payload={"message": "Find a route"},
            )
            assert not answer.supported
        assert len(responses.calls) == 2
        assert (
            "compact single-line JSON" in responses.calls[1]["messages"][0]["content"]
        )
        assert len([kind for kind, _ in history.events if kind == "llm.repair"]) == 1
        assert (
            "intent"
            in responses.calls[0]["response_format"]["json_schema"]["schema"][
                "required"
            ]
        )

    asyncio.run(scenario())
