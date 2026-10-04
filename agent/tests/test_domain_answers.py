from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.answers import answer_interpretation, build_answer
from graphmine_agent.api import create_app
from graphmine_agent.graph_context import (
    infer_bipartition,
    inspect_records,
    project_graph,
    semantic_context,
)
from graphmine_agent.models import (
    ApplicationIntent,
    DataFilter,
    DataInspection,
    ExecutionPlan,
    PlanConfiguration,
    PlanDraft,
    RouteDecision,
    TurnDecision,
)
from graphmine_agent.planning import PlanValidationError, PlanValidator
from graphmine_agent.visualization import answer_visualizations, sanitize_visualizations
from pydantic import ValidationError

AUTH = {"Authorization": "Bearer test-secret"}


def graph():
    return {
        "graph": {
            "id": "teams",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {
                "id": i,
                "label": f"Person {i}",
                "type": "employee",
                "attributes": {
                    "department": "Design" if i < 3 else "Operations",
                    "tenure": i + 1,
                },
            }
            for i in range(6)
        ],
        "edges": [
            {
                "id": i,
                "source": a,
                "target": b,
                "attributes": {"year": 2026 if i != 6 else 2025},
            }
            for i, (a, b) in enumerate(
                [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5), (2, 3)]
            )
        ],
    }


def plan(operation="community-detection", **kwargs):
    problem = {
        "community-detection": "community_detection",
        "k-core": "k_core_decomposition",
        "temporal-motif-mining": "temporal_motif_mining",
        "maximal-cliques": "maximal_clique_enumeration",
        "betweenness-centrality": "centrality_influential_node_mining",
    }[operation]
    return ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id=problem,
        operation_id=operation,
        **kwargs,
    )


def payload(output):
    return {
        "ok": True,
        "warnings": [],
        "output": output,
        "provenance": {"test_double": True},
    }


def communities():
    return payload(
        {
            "community_count": 2,
            "modularity": 0.35,
            "assignment_by_vertex": [
                {"vertex": i, "community": int(i >= 3)} for i in range(6)
            ],
        }
    )


def test_context_includes_domain_types_attributes_and_bounded_record_inspection():
    context = semantic_context(graph())
    assert context["entity_types"] == {"employee": 6}
    assert context["vertex_attributes"]["attributes.department"]["distinct_count"] == 2
    request = DataInspection(
        target="vertices",
        filters=[
            DataFilter(
                target="vertices",
                field="attributes.department",
                operator="eq",
                value="Design",
            )
        ],
        fields=["label", "attributes.tenure"],
        limit=2,
    )
    result = inspect_records(graph(), request)
    assert result["matched_count"] == 3 and result["samples_truncated"]
    assert result["field_statistics"]["attributes.tenure"]["mean"] == 2
    assert list(result["sample_rows"][0]) == ["label", "attributes.tenure"]
    with pytest.raises(ValueError, match="not present"):
        inspect_records(graph(), DataInspection(target="vertices", fields=["secret"]))


def test_projection_preserves_attributes_original_graph_and_isolated_vertices():
    original = graph()
    selected = project_graph(
        original,
        [
            DataFilter(
                target="edges", field="attributes.year", operator="gte", value=2026
            )
        ],
    )
    assert len(selected["edges"]) == 6
    assert len(original["edges"]) == 7
    assert selected["vertices"] == original["vertices"]
    assert selected["edges"][0]["attributes"] == {"year": 2026}
    with pytest.raises(ValueError, match="no field"):
        project_graph(
            original,
            [DataFilter(target="vertices", field="imagined", operator="eq", value="x")],
        )


def test_groups_join_all_original_attributes_and_count_real_boundary_connections():
    answer = build_answer(graph(), plan(), communities(), source_hash="abc")
    assert [group["external_connections"] for group in answer["groups"]] == [1, 1]
    assert [group["internal_connections"] for group in answer["groups"]] == [3, 3]
    assert answer["rows"][0]["label"] == "Person 0"
    assert answer["rows"][0]["attributes"]["department"] == "Design"
    assert answer["groups"][1]["attribute_summary"]["attributes.department"][
        "examples"
    ] == [{"value": "Operations", "count": 3}]
    assert len(answer["network"]["nodes"]) == 6 and len(answer["network"]["edges"]) == 7
    assert answer["provenance"]["source_sha256"] == "abc"
    views = answer_visualizations(answer)
    assert sanitize_visualizations(views, {"answer": answer}) == views
    explanation = answer_interpretation(answer, views, fact_ids=["nonexistent"])
    assert explanation.evidence[0].value == {
        "community_count": 2,
        "assigned_entities": 6,
    }
    assert all(
        item.data_ref.startswith("answer.facts.") for item in explanation.evidence
    )


def test_answer_selection_joins_vertices_beyond_the_upload_preview():
    data = graph()
    data["vertices"] = [{"id": i, "label": f"Name {i}"} for i in range(650)]
    data["edges"] = [{"id": 1, "source": 610, "target": 620}]
    answer = build_answer(
        data,
        plan("maximal-cliques"),
        payload({"cliques": [[610, 620]], "returned_count": 1, "complete": True}),
        source_hash="hash",
    )
    assert {row["label"] for row in answer["network"]["nodes"]} == {
        "Name 610",
        "Name 620",
    }
    assert len(answer["network"]["edges"]) == 1


def test_requested_core_selects_exactly_the_survivors():
    answer = build_answer(
        graph(),
        plan("k-core", parameters={"requested_k": 3}),
        payload(
            {
                "core_number_by_vertex": [
                    {"vertex": i, "core_number": 3 if i < 4 else 2} for i in range(6)
                ],
                "degeneracy": 3,
            }
        ),
        source_hash="hash",
    )
    assert [row["id"] for row in answer["rows"]] == [0, 1, 2, 3]
    assert len(answer["network"]["nodes"]) == 4


def test_result_ids_keep_numeric_and_string_identifiers_distinct():
    data = graph()
    data["vertices"] = [{"id": 1, "label": "Numeric"}, {"id": "1", "label": "Text"}]
    data["edges"] = [{"id": 0, "source": 1, "target": "1"}]
    answer = build_answer(
        data,
        plan("maximal-cliques"),
        payload({"cliques": [[1, "1"]], "returned_count": 1, "complete": True}),
        source_hash="h",
    )
    assert {row["key"] for row in answer["rows"]} == {"1", '"1"'}


def test_temporal_events_rejoin_times_and_count_unused_edges():
    data = graph()
    data["graph"]["directed"] = True
    for index, edge in enumerate(data["edges"]):
        edge["timestamp"] = index * 10
    answer = build_answer(
        data,
        plan("temporal-motif-mining"),
        payload(
            {
                "count": 1,
                "instances_complete": True,
                "instances": [
                    {
                        "vertices_by_role": [0, 1, 2],
                        "edges_in_temporal_order": [0, 1, 2],
                    }
                ],
            }
        ),
        source_hash="h",
    )
    assert [row["timestamp"] for row in answer["events"]] == [0, 10, 20]
    assert answer["facts"][1]["value"] == {"used": 3, "unused": 4}
    assert len(answer["network"]["edges"]) == 3


def test_types_infer_customer_partition_only_when_edges_validate_it():
    data = graph()
    for row in data["vertices"]:
        row["type"] = "customer" if row["id"] < 3 else "product"
    data["edges"] = [{"id": i, "source": i, "target": i + 3} for i in range(3)]
    assert infer_bipartition(data) == [0, 1, 2]
    data["edges"].append({"id": "bad", "source": 0, "target": 1})
    assert infer_bipartition(data) is None


def test_nonready_draft_cannot_contain_a_plan():
    with pytest.raises(ValidationError, match="only a ready"):
        PlanDraft(
            status="unsupported", message="Not supported", plan=PlanConfiguration()
        )
    with pytest.raises(ValidationError, match="only a ready"):
        PlanDraft(status="ready", message="Ready", plan=None)


@pytest.mark.parametrize(
    "intent",
    [
        ApplicationIntent(
            pattern_vertex_count=4, pattern_edges=[[0, 1], [1, 2], [2, 3]]
        ),
        ApplicationIntent(
            pattern_vertex_count=3, pattern_edges=[[0, 1], [1, 2], [2, 0]]
        ),
    ],
)
def test_temporal_semantic_mismatch_cannot_execute(catalog, intent):
    with pytest.raises(PlanValidationError, match="cannot be substituted"):
        PlanValidator(catalog).validate(
            plan(
                "temporal-motif-mining",
                application_intent=intent,
                parameters={"max_time_span": 60},
            ),
            for_execution=True,
        )


def test_weighted_request_cannot_become_unweighted_execution(catalog):
    with pytest.raises(PlanValidationError, match="connection costs or strengths"):
        PlanValidator(catalog).validate(
            plan(application_intent=ApplicationIntent(requires_edge_weights=True)),
            for_execution=True,
        )


def upload(client, data=None):
    session = client.post(
        "/api/sessions", headers=AUTH, json={"domain_id": "social_networks"}
    ).json()["id"]
    record = client.post(
        f"/api/sessions/{session}/files",
        headers=AUTH,
        files={"file": ("graph.json", json.dumps(data or graph()), "application/json")},
        data={"role": "graph"},
    ).json()
    return session, record["id"]


def test_late_planner_refusal_enqueues_zero_jobs(settings):
    with TestClient(create_app(settings)) as client:
        session, file_id = upload(client)
        original = client.app.state.runtime.agent.model.generate

        async def model(**kwargs):
            if kwargs["schema"] is PlanDraft:
                return PlanDraft(
                    status="unsupported", message="That event pattern is not supported."
                )
            return await original(**kwargs)

        client.app.state.runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"graph_id": file_id, "message": "Find communities"},
        ).json()
        assert response["job_id"] is None and response["plan"] is None
        assert "not supported" in response["message"]
        assert (
            client.get("/api/jobs", headers=AUTH, params={"session_id": session}).json()
            == []
        )


@pytest.mark.parametrize(
    (
        "source_unit",
        "requested_unit",
        "window",
        "supplied",
        "expected_status",
        "expected_span",
    ),
    [
        ("milliseconds", "seconds", 60, {}, "ready", 60000),
        ("seconds", "milliseconds", 60000, {}, "ready", 60),
        ("seconds", "milliseconds", 500, {}, "unsupported", None),
        (None, "seconds", 60, {}, "needs_information", None),
        (None, "unspecified", None, {"max_time_span": 17}, "ready", 17),
    ],
)
def test_temporal_window_uses_original_request_exactly_once(
    settings,
    source_unit,
    requested_unit,
    window,
    supplied,
    expected_status,
    expected_span,
):
    data = graph()
    data["graph"]["directed"] = True
    if source_unit:
        data["graph"]["attributes"] = {"timestamp_unit": source_unit}
    for index, edge in enumerate(data["edges"]):
        edge["timestamp"] = index * 1000
    with TestClient(create_app(settings)) as client:
        session, file_id = upload(client, data)

        async def model(**kwargs):
            if kwargs["schema"] is RouteDecision:
                return RouteDecision(
                    problem_id="temporal_motif_mining",
                    operation_id="temporal-motif-mining",
                    supported=True,
                    confidence=1,
                    explanation="Ordered event sequence",
                    intent=ApplicationIntent(
                        pattern_vertex_count=3,
                        pattern_edges=[[0, 1], [1, 2], [0, 2]],
                        time_unit=requested_unit,
                        time_window=window,
                    ),
                )
            assert kwargs["schema"] is PlanDraft
            # The original intent, not this potentially already-converted
            # model-supplied parameter, must determine the window.
            return PlanDraft(
                status="ready",
                message="Find matching events",
                plan=PlanConfiguration(parameters={"max_time_span": 60000}),
            )

        client.app.state.runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "graph_id": file_id,
                "message": "Find the requested sequence",
                "parameters": supplied,
            },
        )
        assert response.status_code == 200, response.text
        outcome = response.json()
        assert outcome["status"] == expected_status, outcome
        if expected_span is not None:
            assert outcome["plan"]["parameters"]["max_time_span"] == expected_span
        else:
            assert outcome["plan"] is None and outcome["plans"] == []
        assert (
            client.get("/api/jobs", headers=AUTH, params={"session_id": session}).json()
            == []
        )


def test_directed_projection_requires_explicit_chat_consent(settings):
    data = graph()
    data["graph"]["directed"] = True
    with TestClient(create_app(settings)) as client:
        session, file_id = upload(client, data)
        request = {"graph_id": file_id, "message": "Find communities", "execute": False}
        declined = client.post(
            f"/api/sessions/{session}/chat", headers=AUTH, json=request
        ).json()
        assert (
            declined["planning_status"] == "needs_information"
            and declined["plan"] is None
        )
        approved = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={**request, "allow_directed_projection": True},
        ).json()
        assert (
            approved["planning_status"] == "ready"
            and approved["plan"]["allow_directed_projection"]
        )


def test_multistep_domain_request_combines_results_and_natural_followup(settings):
    with TestClient(create_app(settings)) as client:
        session, file_id = upload(client)
        runtime = client.app.state.runtime
        original = runtime.agent.model.generate

        async def model(**kwargs):
            if kwargs["schema"] is RouteDecision:
                return RouteDecision(
                    problem_id="community_detection",
                    operation_id="community-detection",
                    supported=True,
                    confidence=1,
                    explanation="Find groups and connectors",
                    intent=ApplicationIntent(objective="Groups and connectors"),
                    additional_analyses=[
                        {
                            "question": "Who connects groups?",
                            "operation_id": "betweenness-centrality",
                            "problem_id": "centrality_influential_node_mining",
                        }
                    ],
                )
            if kwargs["schema"] is TurnDecision:
                return TurnDecision(
                    action="analyze", request=kwargs["user_payload"]["message"]
                )
            return await original(**kwargs)

        async def execute(current, workspace):
            if current.operation_id == "community-detection":
                return communities(), ["test-double", current.operation_id]
            return payload(
                {
                    "score_by_vertex": [
                        {"vertex": i, "score": 12 if i in (2, 3) else 0}
                        for i in range(6)
                    ]
                }
            ), ["test-double", current.operation_id]

        runtime.agent.model.generate = model
        runtime.runner.execute = execute
        runtime.runner.compiled_backends_for = lambda operation: set(
            runtime.catalog.operation(operation).backends
        )

        def ask(message):
            response = client.post(
                f"/api/sessions/{session}/chat",
                headers=AUTH,
                json={"message": message, "graph_id": file_id},
            ).json()
            assert len(response["job_ids"]) == 2
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                job = client.get(f"/api/jobs/{response['job_id']}", headers=AUTH).json()
                if job["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.02)
            assert job["status"] == "completed", job
            return client.get(f"/api/results/{job['result_id']}", headers=AUTH).json()

        result = ask("Which people mostly work together and who connects those groups?")
        assert len(result["answer"]["steps"]) == 2
        assert any(
            "connecting shortest routes" in fact["statement"]
            for fact in result["answer"]["facts"]
        )
        ask("Which people connect our teams? Rank their names.")
        assert (
            len(
                client.get(
                    "/api/jobs", headers=AUTH, params={"session_id": session}
                ).json()
            )
            == 4
        )
