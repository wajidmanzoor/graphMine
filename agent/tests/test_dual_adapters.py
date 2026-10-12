import asyncio
import itertools
import json
from dataclasses import replace

import httpx
import pytest
from graphmine_agent.learning.catalog_reference import reference_for_case
from graphmine_agent.learning.dual_corpus import SOURCES, graph_from_pairs
from graphmine_agent.learning.oracles import verify_output
from graphmine_agent.llm import (
    OpenAICompatibleModel,
    decoder_schema,
    runtime_messages,
    runtime_schema,
)
from graphmine_agent.models import (
    ApplicationIntent,
    GroundedNarrative,
    LLMMode,
    RouteDecision,
)


def test_shared_gpu_requires_explicit_configuration(settings):
    with pytest.raises(ValueError, match="GRAPHMINE_ALLOW_SHARED_GPU"):
        replace(settings, graph_gpu_uuid=settings.llm_gpu_uuid)
    shared = replace(
        settings, graph_gpu_uuid=settings.llm_gpu_uuid, allow_shared_gpu=True
    )
    assert shared.graph_gpu_uuid == shared.llm_gpu_uuid


def test_shared_gpu_environment_flag(monkeypatch, settings):
    from graphmine_agent.config import Settings

    monkeypatch.setenv("GRAPHMINE_LLM_GPU_UUID", "GPU-shared")
    monkeypatch.setenv("GRAPHMINE_GRAPH_GPU_UUID", "GPU-shared")
    monkeypatch.setenv("GRAPHMINE_ALLOW_SHARED_GPU", "true")
    assert Settings.from_env(settings.repository_root).allow_shared_gpu
    monkeypatch.setenv("GRAPHMINE_ALLOW_SHARED_GPU", "false")
    with pytest.raises(ValueError, match="GRAPHMINE_ALLOW_SHARED_GPU"):
        Settings.from_env(settings.repository_root)


@pytest.mark.parametrize("legacy_url", ["http://old-router:8002", None])
def test_both_stage_adapters_use_one_client_and_require_both_names(
    settings, legacy_url
):
    selected = replace(
        settings,
        llm_planner_model="planner-v2",
        llm_analyst_model="analyst-v2",
        llm_route_base_url=legacy_url,
        llm_route_allow_expanded_catalog=True,
    )
    requests = []
    names = ["planner-v2", "analyst-v2"]

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": name} for name in names]})
        body = json.loads(request.content)
        requests.append(body)
        target = (
            {
                "supported": False,
                "confidence": 1,
                "explanation": "Clarify the objective.",
            }
            if body["model"] == "planner-v2"
            else {"fact_ids": ["count"]}
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(target)}}]}
        )

    async def scenario():
        model = OpenAICompatibleModel(selected)
        assert model._route_client is None
        await model._client.aclose()
        model._client = httpx.AsyncClient(
            base_url="http://shared/v1", transport=httpx.MockTransport(respond)
        )
        assert await model.available()
        names.remove("analyst-v2")
        assert not await model.available()
        for mode, schema in [
            (LLMMode.planner, RouteDecision),
            (LLMMode.analyst, GroundedNarrative),
        ]:
            payload = {"message": "Explain these records."}
            await model.generate(mode=mode, schema=schema, user_payload=payload)
            assert requests[-1]["messages"] == runtime_messages(
                mode=mode, schema=schema, user_payload=payload
            )
            assert requests[-1]["response_format"]["json_schema"][
                "schema"
            ] == decoder_schema(runtime_schema(schema, payload))
        assert [body["model"] for body in requests] == ["planner-v2", "analyst-v2"]
        await model.close()

    asyncio.run(scenario())
    assert selected.active_routing_model == "planner-v2"
    assert not selected.routing_adapter_active
    with pytest.raises(ValueError, match="both"):
        replace(settings, llm_planner_model="planner-v2")


def case(graph, operation, parameters):
    return {
        "graph": graph,
        "attachments": {},
        "task": {
            "operation_id": operation,
            "parameters": parameters,
            "expected_status": "ready",
            "intent": ApplicationIntent().model_dump(mode="json"),
        },
    }


def test_quasi_reference_checks_inclusion_maximality():
    graph = graph_from_pairs(
        "complete-four",
        list(itertools.combinations(range(4), 2)),
        ids=["a", "b", "c", "d"],
    )
    result = reference_for_case(
        case(graph, "quasi-cliques", {"minimum_degree_ratio": 0.6, "minimum_size": 3})
    )
    assert result["expected"]["groups"] == [["a", "b", "c", "d"]]


def test_biclique_reference_uses_explicit_sides_for_any_domain():
    graph = graph_from_pairs(
        "staff-tasks",
        [(a, b) for a in range(2) for b in range(2, 5)],
        ids=["w1", "w2", "t1", "t2", "t3"],
        attributes=[{"side": "left"}] * 2 + [{"side": "right"}] * 3,
    )
    result = reference_for_case(case(graph, "maximal-biclique-counting", {}))
    assert result["expected"]["count"] == 1
    assert result["expected"]["bicliques"][0] == {
        "left": ["w1", "w2"],
        "right": ["t1", "t2", "t3"],
    }


def test_count_only_does_not_require_an_unrequested_listing():
    graph = graph_from_pairs("triangle", [(0, 1), (1, 2), (0, 2)], ids=["a", "b", "c"])
    task = {
        "operation_id": "k-cliques",
        "parameters": {"k": 3},
        "filters": [],
        "behavior": "execute",
    }
    assert verify_output(graph, task, {"count": 1}) == []
    assert verify_output(graph, task, {"count": 0})


def test_public_sources_have_single_predeclared_splits():
    assert {source["split"] for source in SOURCES.values()} == {
        "train",
        "validation",
        "test",
    }
    assert len({source["page"] for source in SOURCES.values()}) == len(SOURCES)
    assert SOURCES["email-eu-core"]["split"] == "train"
    assert SOURCES["gnutella08"]["split"] == "test"
