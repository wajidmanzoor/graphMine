import json
from dataclasses import replace

import httpx
import jsonschema
import pytest
from graphmine_agent.analytics import AnalyticsService
from graphmine_agent.analytics_answers import build_facts, compose
from graphmine_agent.jobs import EventBus

SAVED = {
    "order": ["groups", "rank"],
    "steps": {
        "groups": {
            "status": "completed",
            "result": {
                "operation": "maximal-cliques",
                "quality": "exact",
                "complete": True,
                "ports": {
                    "cliques": {
                        "type": "vertex_groups",
                        "value": [
                            {"group": 0, "vertices": [1, 2]},
                            {"group": 1, "vertices": [1, 2, 3, 4, 5, 6, 7]},
                        ],
                    },
                    "count": {"type": "scalar", "value": 2},
                },
            },
        },
        "rank": {
            "status": "completed",
            "result": {
                "operation": "pagerank",
                "quality": "numerical",
                "complete": False,
                "ports": {
                    "scores": {
                        "type": "vertex_scores",
                        "value": [
                            {"vertex": 1, "score": 0.123456},
                            {"vertex": 2, "score": 0.5},
                        ],
                    }
                },
            },
        },
    },
}
TITLES = {"maximal-cliques": "Maximal cliques", "pagerank": "PageRank"}
LABELS = {json.dumps(1): "Valjean", json.dumps(2): "Javert"}


def test_facts_state_results_with_labels_and_guarantees():
    facts = build_facts(SAVED, TITLES, LABELS)
    statements = [fact["statement"] for fact in facts]
    assert statements[0] == (
        "Maximal cliques found 2 cliques; the largest has 7 members: "
        "Valjean, Javert, 3, 4, 5 and 2 more."
    )
    assert "Sizes of the largest cliques: 7, 2." in statements
    assert "Maximal cliques: count is 2." in statements
    assert "Highest score from PageRank: Javert (0.5), Valjean (0.1235)." in statements
    assert (
        "PageRank is a numerical calculation; its output is incomplete." in statements
    )
    assert len({fact["id"] for fact in facts}) == len(facts)


def _reply(content):
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
    )


@pytest.mark.asyncio
async def test_model_chooses_facts_but_cannot_write_numbers(settings, monkeypatch):
    facts = build_facts(SAVED, TITLES, LABELS)
    replies = [
        {"lead": "Here are the tightest groups.", "fact_ids": ["f1", "f2", "f1"]},
        {"lead": "There are 9 groups.", "fact_ids": ["f1"]},
        {"lead": "Invented fact.", "fact_ids": ["f99"]},
    ]
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "graphmine_agent.analytics_answers.httpx.AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda _request: _reply(replies.pop(0))),
            **kwargs,
        ),
    )
    configured = replace(settings, llm_base_url="http://model.test/v1")
    chosen = await compose(configured, "Which groups are tight?", facts)
    assert chosen == {"lead": "Here are the tightest groups.", "fact_ids": ["f1", "f2"]}
    assert (await compose(configured, "How many?", facts))["lead"] == ""
    with pytest.raises(jsonschema.ValidationError):
        await compose(configured, "Anything?", facts)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_works", [True, False])
async def test_completed_workflow_publishes_an_answer(
    settings, database, graph_store, session, monkeypatch, model_works
):
    service = AnalyticsService(
        replace(settings, llm_enabled=True), database, graph_store, EventBus(database)
    )

    async def capabilities():
        return {
            "operations": [{"id": key, "title": value} for key, value in TITLES.items()]
        }

    async def chosen(_settings, question, facts):
        if not model_works:
            raise httpx.ConnectError("model offline")
        assert question == "Find tight groups"
        return {"lead": "The tightest groups are below.", "fact_ids": ["f1"]}

    monkeypatch.setattr(service, "capabilities", capabilities)
    monkeypatch.setattr(service, "result", lambda _id: SAVED)
    monkeypatch.setattr("graphmine_agent.analytics_answers.compose", chosen)
    await service.events.publish(
        session.id,
        "workflow.chat",
        {"turn_id": "t1", "role": "user", "message": "Find tight groups"},
    )
    record = {
        "id": "w1",
        "session_id": session.id,
        "revision": 1,
        "planning_turn_id": "t1",
    }
    await service._answer(record)
    answer = next(
        event.payload
        for event in database.events(session.id)
        if event.type == "workflow.answer"
    )
    assert answer["workflow_id"] == "w1" and answer["turn_id"] == "t1"
    assert answer["source"] == ("model" if model_works else "facts")
    assert answer["facts"][0]["statement"].startswith("Maximal cliques found 2")
    if model_works:
        assert answer["lead"] == "The tightest groups are below."
        assert answer["fact_ids"] == ["f1"]
    else:
        assert answer["lead"] == "" and answer["fact_ids"][0] == "f1"
