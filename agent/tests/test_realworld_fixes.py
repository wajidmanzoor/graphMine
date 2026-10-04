from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.answers import answer_interpretation, build_answer
from graphmine_agent.api import create_app
from graphmine_agent.learning.presentation_checks import check_presentation
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    PlanConfiguration,
    PlanDraft,
    RouteDecision,
)
from graphmine_agent.planning import application_capability_errors
from graphmine_agent.visualization import answer_visualizations

AUTH = {"Authorization": "Bearer test-secret"}


def source(kind="protein"):
    return {
        "graph": {
            "id": "sample",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {
                "id": i,
                "label": f"Named {i}",
                "type": kind,
                "attributes": {
                    "department": "Design" if i < 2 else "Support",
                    "string_id": f"original-{i}",
                },
            }
            for i in range(3)
        ],
        "edges": [
            {
                "id": i,
                "source": a,
                "target": b,
                "attributes": {"score": score, "ascore": 0.0},
            }
            for i, (a, b, score) in enumerate(
                [(0, 1, 0.705), (1, 2, 0.88), (0, 2, 0.999)]
            )
        ],
    }


def make_plan(intent=None, operation="maximal-cliques"):
    return ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id=operation,
        problem_id="maximal_clique_enumeration"
        if operation == "maximal-cliques"
        else "k_core_decomposition",
        parameters={"minimum_clique_size": 3}
        if operation == "maximal-cliques"
        else {"requested_k": 2},
        application_intent=intent,
    )


def test_false_assumption_cannot_become_a_displayed_fact_and_columns_stay_distinct():
    intent = ApplicationIntent(
        filters=[
            {
                "target": "edges",
                "field": "attributes.score",
                "operator": "eq",
                "value": 0,
            }
        ],
        assumptions=["score has 3 links with value zero"],
    )
    answer = build_answer(
        source(),
        make_plan(intent),
        {
            "warnings": ["internal-backend-note"],
            "output": {
                "cliques": [],
                "total_count": 0,
                "returned_count": 0,
                "complete": True,
            },
        },
        source_hash="bound-to-source",
    )
    presentation = answer_interpretation(
        answer, answer_visualizations(answer), fact_ids=["fact_0"]
    )
    assert (
        presentation.summary == "No groups of proteins match the requested conditions."
    )
    shown = json.dumps(presentation.model_dump(mode="json"))
    assert "score has 3 links" not in shown and "internal-backend-note" not in shown
    assert "0.705" in shown and "0.999" in shown
    evidence = answer["provenance"]["filter_evidence"][0]
    assert evidence["matched_records"] == 0
    assert evidence["field_statistics"]["minimum"] == 0.705
    assert answer["diagnostics"]["unverified_planner_notes"] == intent.assumptions


def test_readable_memberships_color_defaults_and_followups_are_source_bound():
    answer = build_answer(
        source("participant"),
        make_plan(),
        {"output": {"cliques": [[0, 1, 2]], "returned_count": 1, "complete": True}},
        source_hash="h",
    )
    assert "participants" in answer["facts"][0]["statement"]
    assert answer["tables"]["groups"][0] == {
        "Group": "Group 1",
        "Name": "Named 0",
        "Department": "Design",
        "STRING ID": "original-0",
    }
    views = answer_visualizations(answer)
    assert (
        next(v for v in views if v.id == "network").encodings["node_color"]
        == "attributes.department"
    )
    assert next(v for v in views if v.id == "groups").data_ref == "answer.tables.groups"
    interpretation = answer_interpretation(
        answer,
        views,
        followups=["Run an invented kernel", "Compute k-core decomposition"],
    )
    assert "invented" not in str(interpretation.suggested_followups)
    assert "k-core" not in str(interpretation.suggested_followups)
    assert all(
        a.view_id in {v.id for v in views}
        for a in interpretation.followup_actions
        if a.kind == "show_view"
    )


def test_core_group_can_be_selected_in_network_and_combined_views_have_valid_actions():
    answer = build_answer(
        source("participant"),
        make_plan(operation="k-core"),
        {
            "output": {
                "core_number_by_vertex": [
                    {"vertex": i, "core_number": 2} for i in range(3)
                ]
            }
        },
        source_hash="h",
    )
    assert all(row["groups"] == ["core"] for row in answer["network"]["nodes"])
    composite = {**answer, "steps": {"step_0": answer, "step_1": answer}}
    views = answer_visualizations(composite)
    interpretation = answer_interpretation(composite, views)
    assert all(
        a.view_id in {v.id for v in views}
        for a in interpretation.followup_actions
        if a.kind == "show_view"
    )


@pytest.mark.parametrize(
    "tamper", ["summary", "limitation", "statistics", "action", "table"]
)
def test_presentation_gate_detects_ungrounded_or_unusable_answers(tamper):
    graph = source()
    intent = ApplicationIntent(
        filters=[
            {
                "target": "edges",
                "field": "attributes.score",
                "operator": "eq",
                "value": 0,
            }
        ]
    )
    answer = build_answer(
        graph,
        make_plan(intent),
        {
            "output": {
                "cliques": [],
                "returned_count": 0,
                "complete": True,
            }
        },
        source_hash="original",
    )
    interpretation = answer_interpretation(
        answer, answer_visualizations(answer)
    ).model_dump(mode="json")
    outcome = {"result": {"answer": answer, "interpretation": interpretation}}
    task = {"behavior": "execute", "filters": [x.model_dump() for x in intent.filters]}
    assert not check_presentation(graph, task, outcome)
    outcome = copy.deepcopy(outcome)
    result = outcome["result"]
    if tamper == "summary":
        result["interpretation"]["summary"] = "There are eight zero-score links."
    elif tamper == "limitation":
        result["interpretation"]["limitations"].append("Assumption: score has zeros")
    elif tamper == "statistics":
        result["answer"]["provenance"]["filter_evidence"][0]["field_statistics"][
            "minimum"
        ] = 0
    elif tamper == "action":
        result["interpretation"]["followup_actions"][0]["view_id"] = "missing"
    else:
        result["answer"]["tables"]["members"] = [{"Name": "Invented protein"}]
    assert check_presentation(graph, task, outcome)


def test_jargon_is_rejected_in_a_novice_clarification():
    assert check_presentation(
        source(),
        {"behavior": "clarify"},
        {
            "response": {"message": "Do you mean betweenness or k-core?"},
        },
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"weight_attribute": "attributes.score"},
        {"weight_usage": "path_length"},
        {"requires_edge_weights": True},
    ],
)
def test_explicit_weight_use_cannot_hide_behind_a_false_boolean(extra):
    assert application_capability_errors(ApplicationIntent(**extra), "maximal-cliques")
    assert not application_capability_errors(
        ApplicationIntent(
            filters=[
                {
                    "target": "edges",
                    "field": "attributes.score",
                    "operator": "eq",
                    "value": 0.999,
                }
            ]
        ),
        "maximal-cliques",
    )


@pytest.mark.parametrize("weighted", [False, True])
def test_scope_review_corrects_empty_filter_refusal_without_bypassing_weight_safety(
    settings, weighted
):
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        uploaded = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("sample.json", json.dumps(source()), "application/json")},
            data={"role": "graph"},
        ).json()
        calls = []

        async def model(**kw):
            calls.append(kw)
            if kw["schema"] is RouteDecision:
                reviewed = "scope_review" in kw["user_payload"]
                return RouteDecision(
                    problem_id="maximal_clique_enumeration",
                    operation_id="maximal-cliques" if reviewed else None,
                    supported=reviewed,
                    confidence=0.9,
                    explanation="Check scope",
                    intent=ApplicationIntent(
                        filters=[
                            {
                                "target": "edges",
                                "field": "attributes.score",
                                "operator": "eq",
                                "value": 0,
                            }
                        ],
                        requires_edge_weights=weighted,
                        weight_attribute="attributes.score" if weighted else None,
                        weight_usage="strength" if weighted else None,
                    ),
                    missing_information=[] if reviewed else ["No links match"],
                )
            assert kw["schema"] is PlanDraft
            assert kw["user_payload"]["verified_projection"]["selected_edges"] == 0
            assert (
                kw["user_payload"]["application_preprocessing"]["attribute_filters"][
                    "requires_kernel_weight_support"
                ]
                is False
            )
            return PlanDraft(
                status="ready",
                message="Ready",
                plan=PlanConfiguration(parameters={"minimum_clique_size": 3}),
            )

        client.app.state.runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "graph_id": uploaded["id"],
                "message": "Keep score zero links and find the groups.",
            },
        ).json()
        assert response["status"] == ("unsupported" if weighted else "ready")
        assert sum(c["schema"] is RouteDecision for c in calls) == 2
        assert sum(c["schema"] is PlanDraft for c in calls) == (0 if weighted else 1)
        if not weighted:
            assert response["plan"]["application_intent"]["filters"][0]["value"] == 0
