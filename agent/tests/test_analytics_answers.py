import json
from dataclasses import replace

import httpx
import pytest
from graphmine_agent.analytics import AnalyticsService
from graphmine_agent.analytics_answers import (
    build_facts,
    compose,
    default_fact_ids,
    numberless_lead,
    suggested_questions,
)
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
        "Maximal cliques: found 2 cliques, with 7 and 2 members; the largest: "
        "Valjean, Javert, 3, 4, 5 and 2 more."
    )
    assert "Maximal cliques: count is 2." in statements
    assert "PageRank: highest score — Javert (0.5) and Valjean (0.1235)." in statements
    assert "PageRank: a numerical calculation; its output is incomplete." in statements
    assert "Maximal cliques: exact, so it establishes the declared result." in statements
    assert len({fact["id"] for fact in facts}) == len(facts)
    # The answer leads with findings; complete-quality notes are shown beside it.
    chosen = default_fact_ids(facts)
    assert all(facts[int(key[1:]) - 1]["kind"] != "quality" for key in chosen)


PEOPLE = ["Alice", "Bob", "Carol", "Dara", "Eli", "Fatima", "Gus"]
TEAM = {
    "order": ["groups", "bridges"],
    "steps": {
        "groups": {
            "status": "completed",
            "result": {
                "operation": "community-detection",
                "quality": "heuristic",
                "complete": True,
                "ports": {
                    "partition": {
                        "type": "vertex_partition",
                        "complete": True,
                        "value": [
                            {"vertex": person, "part": 0 if index < 4 else 1}
                            for index, person in enumerate(PEOPLE)
                        ],
                    },
                    "groups": {
                        "type": "vertex_groups",
                        "complete": True,
                        "value": [
                            {"group": 0, "vertices": PEOPLE[:4]},
                            {"group": 1, "vertices": PEOPLE[4:]},
                        ],
                    },
                },
            },
        },
        "bridges": {
            "status": "completed",
            "result": {
                "operation": "betweenness-centrality",
                "quality": "numerical",
                "complete": True,
                "ports": {
                    "scores": {
                        "type": "vertex_scores",
                        "complete": True,
                        "value": [
                            {"vertex": person, "score": score}
                            for person, score in zip(
                                PEOPLE, [0, 0, 0.53333, 0.6, 0.53333, 0, 0], strict=True
                            )
                        ],
                    }
                },
            },
        },
    },
}
TEAM_TITLES = {
    "community-detection": "Divide a network into communities",
    "betweenness-centrality": "Rank vertices that connect shortest paths",
}


def test_one_grouping_is_stated_once_and_zero_scores_are_not_ranked():
    statements = [fact["statement"] for fact in build_facts(TEAM, TEAM_TITLES, {})]
    assert statements[0] == (
        "Divide a network into communities: found 2 groups covering 7 vertices, "
        "with 4 and 3 members; the largest: Alice, Bob, Carol, Dara."
    )
    assert not any("partition" in statement for statement in statements)
    assert (
        "Rank vertices that connect shortest paths: highest score — Dara (0.6), "
        "Carol (0.5333) and Eli (0.5333); 4 other vertices scored 0."
    ) in statements


def test_many_groups_report_their_largest_sizes_separately():
    saved = {
        "order": ["cliques"],
        "steps": {"cliques": {"status": "completed", "result": {
            "operation": "maximal-cliques", "complete": True, "ports": {
                "cliques": {"type": "vertex_groups", "value": [
                    {"group": index, "vertices": list(range(size))}
                    for index, size in enumerate([6, 5, 4, 3, 3, 2, 1])
                ]},
            },
        }}},
    }
    statements = [fact["statement"] for fact in build_facts(saved, TITLES, {})]
    assert statements[0].startswith("Maximal cliques: found 7 cliques; the largest has 6 members:")
    assert "Maximal cliques: the five largest cliques have 6, 5, 4, 3 and 3 members." in statements


def test_suggestions_skip_answered_questions_and_carry_checked_actions():
    facts = build_facts(TEAM, TEAM_TITLES, {})
    suggestions = suggested_questions(TEAM, facts)
    texts = [row["text"] for row in suggestions]
    assert "How many groups were found?" not in texts
    assert suggestions[0] == {
        "text": "Show the largest group.",
        "action": {"intent": "view", "view": {"kind": "show_group", "group": "largest"}},
    }
    assert suggestions[1]["action"] == {
        "intent": "view", "view": {"kind": "highlight", "vertices": ["Dara", "Carol", "Eli"]},
    }
    guarantees = suggestions[2]
    assert guarantees["text"] == "What guarantees does this calculation provide?"
    assert {facts[int(key[1:]) - 1]["kind"] for key in guarantees["action"]["fact_ids"]} == {"quality"}


@pytest.mark.parametrize(
    ("lead", "kept"),
    [
        ("Dara links the two teams.", False),
        ("The network splits into three communities.", False),
        ("There are 9 groups.", False),
        ("Twenty-one people are central.", False),
        ("Dara links the teams, ahead of Carol and Eli.", True),
        ("One of the groups is centered on Alice.", True),
        ("No one outside the core links the teams.", True),
    ],
)
def test_leads_never_state_numbers_in_digits_or_words(lead, kept):
    assert numberless_lead(lead) == (lead if kept else "")


def _reply(content):
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
    )


@pytest.mark.asyncio
async def test_model_selects_facts_and_code_renders_cited_numbers(settings, monkeypatch):
    facts = build_facts(SAVED, TITLES, LABELS)
    replies = [
        {"text": "Here are the results.\n{{f1}}\n{{f2}}", "source_ids": ["f1", "f2"]},
    ]
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "graphmine_agent.analytics_answers.httpx.AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda _request: _reply(replies.pop(0))),
            **kwargs,
        ),
    )
    configured = replace(settings, llm_enabled=True, llm_base_url="http://model.test/v1")
    chosen = await compose(configured, "Which groups are tight?", facts)
    assert chosen["text"] == "Here are the results.\n" + facts[0]["text"] + "\n" + facts[1]["text"]
    assert chosen["fact_ids"] == ["f1", "f2"]
    assert [c["id"] for c in chosen["citations"]] == ["f1", "f2"]
    assert chosen["source"] == "model" and chosen["grounding"]["attempts"] == 1


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

    def respond(request):
        if not model_works:
            raise httpx.ConnectError("model offline")
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert payload["question"] == "Find tight groups"
        return _reply({"text": "Here are the results.\n{{f1}}", "source_ids": ["f1"]})

    monkeypatch.setattr(service, "capabilities", capabilities)
    monkeypatch.setattr(service, "result", lambda _id, **_kwargs: SAVED)
    original = httpx.AsyncClient
    monkeypatch.setattr("graphmine_agent.analytics_answers.httpx.AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
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
    first, answer = [
        event.payload
        for event in database.events(session.id)
        if event.type == "workflow.answer"
    ]
    # The computed facts are shown at once; the introduction follows.
    assert first["source"] == "facts" and first["pending"] is True and first["lead"] == ""
    assert answer["pending"] is False
    assert answer["workflow_id"] == "w1" and answer["turn_id"] == "t1"
    assert answer["source"] == ("model" if model_works else "facts")
    assert answer["facts"][0]["statement"].startswith("Maximal cliques: found 2")
    if model_works:
        assert answer["text"].startswith("Here are the results.\nfound 2 cliques")
        assert answer["fact_ids"] == ["f1"]
    else:
        assert answer["lead"] == "" and answer["fact_ids"][0] == "f1"
    started = [event.payload for event in database.events(session.id) if event.type == "workflow.model_call"]
    diagnostics = [event.payload for event in database.events(session.id) if event.type == "workflow.diagnostics"]
    assert len(started) == len(diagnostics) == 1
    assert started[0]["call_id"] == diagnostics[0]["call_id"]
    assert diagnostics[0]["stage"] == "answer" and diagnostics[0]["turn_id"] == "t1"
    assert diagnostics[0]["outcome"] == ("ok" if model_works else "failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning_field", [None, "reasoning", "reasoning_content"])
async def test_answer_activity_records_the_actual_model_call_without_training_capture(
    settings, database, graph_store, session, monkeypatch, reasoning_field
):
    service = AnalyticsService(replace(settings, llm_enabled=True, llm_base_url="http://model.test/v1"),
                               database, graph_store, EventBus(database))
    async def capabilities():
        return {"operations": [{"id": key, "title": value} for key, value in TITLES.items()]}
    monkeypatch.setattr(service, "capabilities", capabilities)
    monkeypatch.setattr(service, "result", lambda _id, **_kwargs: SAVED)
    raw = "Raw model text\n  preserved exactly."
    message = {"content": json.dumps({"text": "Here are the results.\n{{f1}}", "source_ids": ["f1"]})}
    if reasoning_field:
        message[reasoning_field] = raw
    original = httpx.AsyncClient
    monkeypatch.setattr("graphmine_agent.analytics_answers.httpx.AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}})), **kwargs))
    await service.events.publish(session.id, "workflow.chat", {"turn_id": "t1", "role": "user", "message": "Find groups"})
    await service._answer({"id": "w1", "session_id": session.id, "revision": 1, "planning_turn_id": "t1"})
    events = database.events(session.id)
    starts = [e.payload for e in events if e.type == "workflow.model_call"]
    ends = [e.payload for e in events if e.type == "workflow.diagnostics"]
    reasoning = [e.payload for e in events if e.type == "workflow.reasoning"]
    assert database.capture is None and len(starts) == len(ends) == 1
    assert starts[0]["call_id"] == ends[0]["call_id"]
    assert ends[0]["stage"] == "answer" and ends[0]["outcome"] == "ok"
    assert ends[0]["usage"]["total_tokens"] == 30
    assert [r["text"] for r in reasoning] == ([raw] if reasoning_field else [])
    if reasoning:
        assert reasoning[0]["call_id"] == starts[0]["call_id"]
