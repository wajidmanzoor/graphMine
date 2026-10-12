"""Bounded planning recovery; model responses and computation are CPU fixtures."""

from __future__ import annotations

import json
import stat
import textwrap
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.models import (
    AnalysisTask,
    ApplicationIntent,
    DataInspection,
    PlanConfiguration,
    PlanDraft,
    RouteDecision,
)
from graphmine_agent.planning import preserve_review_intent

AUTH = {"Authorization": "Bearer test-secret"}
# The inspected development regression, not an untouched evaluation question.
# Source: evaluation/reports/business-payment-regression-replay-v1.json.
QUESTION = (
    "Give me all three-account mutual-payment sets for our review queue. "
    "Keep sets that are part of bigger circles as well. The output should "
    "describe the recorded pattern, not infer misconduct."
)


def upload(client, *, directed=False):
    session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
    graph = {
        "graph": {
            "id": "recovery",
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {"id": f"account-{i}", "label": f"Account {i}", "type": "account"}
            for i in range(7)
        ],
        "edges": [
            {
                "id": i,
                "source": f"account-{a}",
                "target": f"account-{b}",
                "attributes": {"year": 2026, "capacity": 2},
            }
            for i, (a, b) in enumerate(
                [
                    (0, 1),
                    (0, 2),
                    (0, 3),
                    (1, 2),
                    (1, 3),
                    (2, 3),
                    (3, 4),
                    (4, 5),
                    (4, 6),
                    (5, 6),
                ]
            )
        ],
    }
    response = client.post(
        f"/api/sessions/{session}/files",
        headers=AUTH,
        files={"file": ("recovery.json", json.dumps(graph), "application/json")},
        data={"role": "graph"},
    )
    assert response.status_code == 201, response.text
    return session, response.json()["id"]


def route(catalog, operation, intent=None, **kwargs):
    return RouteDecision(
        problem_id=catalog.operation(operation).problem_id,
        operation_id=operation,
        supported=True,
        confidence=1,
        explanation="Authored recovery fixture.",
        intent=intent or ApplicationIntent(),
        **kwargs,
    )


def ready(**kwargs):
    return PlanDraft(status="ready", message="Ready", plan=PlanConfiguration(**kwargs))


def refused():
    return PlanDraft(
        status="unsupported",
        message="The selected computation does not enumerate every exact three-member group within larger groups.",
    )


def assert_no_jobs(client, session):
    assert (
        client.get("/api/jobs", headers=AUTH, params={"session_id": session}).json()
        == []
    )


def test_real_regression_can_recover_through_execution_and_grounded_answer(
    settings, catalog, tmp_path
):
    """Replay saved intent shapes; the recovery response is authored, not inference."""
    binary = tmp_path / "cpu-clique-fixture"
    binary.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env python3
        import itertools
        import json
        import sys
        from pathlib import Path
        if sys.argv[1] == "list":
            print(json.dumps({"operation_count": 1, "library_version": "1.0.0", "validated_backend_count": 1, "compiled_backend_count": 1, "operations": [{"id": "k-cliques", "backends": [{"id": "kcgpu", "compiled": True, "validated": True}]}]}))
        elif sys.argv[1:3] == ["run", "k-cliques"]:
            graph = json.loads(Path(sys.argv[sys.argv.index("--graph") + 1]).read_text())
            k = int(sys.argv[sys.argv.index("--k") + 1])
            edges = {frozenset((edge["source"], edge["target"])) for edge in graph["edges"]}
            groups = [list(group) for group in itertools.combinations([node["id"] for node in graph["vertices"]], k) if all(frozenset(pair) in edges for pair in itertools.combinations(group, 2))]
            Path(sys.argv[sys.argv.index("--output") + 1]).write_text(json.dumps({"ok": True, "provenance": {"backend": "kcgpu", "test_double": True, "cpu_reference_fixture": True}, "warnings": [], "statistics": {}, "output": {"cliques": groups, "count": len(groups), "complete": True}}))
        else:
            raise SystemExit(2)
        """)
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    with TestClient(create_app(replace(settings, graphmine_binary=binary))) as client:
        session, graph_id = upload(client)
        calls = []
        fallback = client.app.state.runtime.agent.model.generate
        # These differences reproduce the two saved routes: the correct route
        # fills absent pattern details and paraphrases the relationship meaning.
        original_intent = ApplicationIntent(
            objective=QUESTION,
            entity_type="account",
            relationship_meaning="exchanged payments",
            filter_mode="replace",
        )
        corrected_intent = ApplicationIntent(
            entity_type="account",
            relationship_meaning="mutual payment exchange",
            pattern_vertex_count=3,
            pattern_edges=[[0, 1], [1, 2], [0, 2]],
        )

        async def model(**kwargs):
            if kwargs["schema"] not in {RouteDecision, PlanDraft}:
                return await fallback(**kwargs)
            payload = kwargs["user_payload"]
            calls.append((kwargs["schema"].__name__, payload))
            assert not client.app.state.runtime.database.messages(session), (
                "Intermediate outcomes must not become conversation history"
            )
            if kwargs["schema"] is RouteDecision:
                if "routing_review" in payload:
                    assert payload["message"] == QUESTION
                    assert (
                        payload["routing_review"]["failure"]["code"]
                        == "selected_operation_refused"
                    )
                    return route(catalog, "k-cliques", corrected_intent)
                return route(catalog, "maximal-cliques", original_intent)
            assert kwargs["schema"] is PlanDraft
            if payload["selected_operation"]["operation_id"] == "maximal-cliques":
                return refused()
            assert payload["message"] == QUESTION
            assert payload["application_intent"]["pattern_vertex_count"] == 3
            assert payload["application_intent"]["filter_mode"] == "replace"
            assert "routing_review" in payload
            return ready(parameters={"k": 3}, optional_outputs=["cliques"])

        client.app.state.runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"graph_id": graph_id, "message": QUESTION, "execute": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (
            body["planning_status"] == "ready"
            and body["plan"]["operation_id"] == "k-cliques"
        )
        assert [name for name, _ in calls] == [
            "RouteDecision",
            "PlanDraft",
            "RouteDecision",
            "PlanDraft",
        ]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{body['job_id']}", headers=AUTH).json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert job["status"] == "completed", job
        result = client.get(f"/api/results/{job['result_id']}", headers=AUTH).json()
        groups = {frozenset(group["vertices"]) for group in result["answer"]["groups"]}
        assert len(groups) == 5 and all(len(group) == 3 for group in groups)
        assert frozenset({"account-0", "account-1", "account-2"}) in groups
        assert frozenset({"account-4", "account-5", "account-6"}) in groups
        assert result["payload"]["provenance"]["cpu_reference_fixture"] is True
        messages = client.app.state.runtime.database.messages(session)
        assert len([message for message in messages if message["role"] == "user"]) == 1
        assert all(
            "does not enumerate" not in message["payload"].get("message", "")
            for message in messages
        )
        events = list(client.app.state.runtime.database.history.session_events(session))
        assert (
            sum(event["type"] == "planning.recovery.request" for event in events) == 1
        )
        assert any(
            event["type"] == "planning.recovery.outcome"
            and event["data"]["status"] == "ready"
            for event in events
        )


def test_invalid_plan_retry_preserves_explicit_backend_parameters_and_outputs(
    settings, catalog
):
    with TestClient(create_app(settings)) as client:
        session, graph_id = upload(client)
        calls = []

        async def model(**kwargs):
            payload = kwargs["user_payload"]
            calls.append(kwargs["schema"].__name__)
            if kwargs["schema"] is RouteDecision:
                if "routing_review" in payload:
                    failure = payload["routing_review"]["failure"]
                    assert failure["code"] == "invalid_plan" and failure["errors"]
                    assert payload["routing_review"]["step_request"]["parameters"] == {
                        "result_limit": 7
                    }
                return route(catalog, "k-cliques")
            assert payload["requested_backend"] == "kcgpu"
            return ready(
                parameters={
                    "k": 3 if "routing_review" in payload else 0,
                    "result_limit": 999,
                },
                optional_outputs=[],
            )

        client.app.state.runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "graph_id": graph_id,
                "message": QUESTION,
                "backend_id": "kcgpu",
                "parameters": {"result_limit": 7},
                "optional_outputs": ["cliques"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ready", body
        assert body["plan"]["backend_id"] == "kcgpu"
        assert body["plan"]["parameters"]["result_limit"] == 7
        assert body["plan"]["optional_outputs"] == ["cliques"]
        assert calls == ["RouteDecision", "PlanDraft", "RouteDecision", "PlanDraft"]
        assert_no_jobs(client, session)


def test_review_cannot_remove_weights_or_direction_to_make_a_substitute_ready(
    settings, catalog
):
    with TestClient(create_app(settings)) as client:
        session, graph_id = upload(client, directed=True)
        calls = []

        async def model(**kwargs):
            calls.append(kwargs["schema"].__name__)
            if kwargs["schema"] is RouteDecision:
                if "routing_review" in kwargs["user_payload"]:
                    return route(catalog, "betweenness-centrality")
                return route(
                    catalog,
                    "max-flow-min-cut",
                    ApplicationIntent(
                        requires_edge_weights=True,
                        weight_attribute="attributes.capacity",
                        weight_usage="other",
                        requires_direction=True,
                    ),
                )
            return refused()

        client.app.state.runtime.agent.model.generate = model
        body = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "graph_id": graph_id,
                "message": "Use capacities and directions to find the maximum throughput.",
            },
        ).json()
        assert body["status"] == "unsupported" and body["plan"] is None
        assert body["decision"]["intent"]["requires_edge_weights"] is True
        assert body["decision"]["intent"]["requires_direction"] is True
        assert body["decision"]["intent"]["weight_attribute"] == "attributes.capacity"
        assert calls == ["RouteDecision", "PlanDraft", "RouteDecision"]
        assert_no_jobs(client, session)


def test_explicit_empty_output_selection_survives_recovery(settings, catalog):
    with TestClient(create_app(settings)) as client:
        session, graph_id = upload(client)

        async def model(**kwargs):
            if kwargs["schema"] is RouteDecision:
                return route(catalog, "k-cliques")
            payload = kwargs["user_payload"]
            assert "optional_outputs" in payload["explicit_request_fields"]
            return ready(
                parameters={"k": 3 if "routing_review" in payload else 0},
                optional_outputs=["cliques"],
            )

        client.app.state.runtime.agent.model.generate = model
        body = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "graph_id": graph_id,
                "message": "Count the fully connected groups of three.",
                "optional_outputs": [],
            },
        ).json()
        assert body["status"] == "ready"
        assert body["plan"]["optional_outputs"] == []
        assert body["plan"]["parameters"]["k"] == 3
        assert_no_jobs(client, session)


@pytest.mark.parametrize(
    "field,value",
    [
        ("weight_attribute", "attributes.other"),
        ("time_unit", "milliseconds"),
        ("pattern_vertex_count", 4),
    ],
)
def test_conflicting_known_constraints_are_reported(field, value):
    original = ApplicationIntent(
        requires_edge_weights=True,
        requires_direction=True,
        weight_attribute="attributes.cost",
        time_unit="seconds",
        time_window=2,
        pattern_vertex_count=3,
    )
    proposed = original.model_copy(
        update={
            field: value,
            "requires_edge_weights": False,
            "requires_direction": False,
        }
    )
    protected, conflicts = preserve_review_intent(original, proposed)
    assert conflicts == [field]
    assert protected.requires_edge_weights and protected.requires_direction
    assert getattr(protected, field) == getattr(original, field)


def test_review_keeps_existing_filters_and_rejects_scope_expansion():
    original = ApplicationIntent(
        filters=[
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "gte",
                "value": 2026,
            }
        ],
        filter_mode="replace",
    )
    protected, conflicts = preserve_review_intent(
        original, ApplicationIntent(filter_mode="clear")
    )
    assert not conflicts and protected.filters == original.filters
    assert protected.filter_mode == "replace"
    changed = original.model_copy(
        update={"filters": [original.filters[0].model_copy(update={"value": 2025})]}
    )
    protected, conflicts = preserve_review_intent(original, changed)
    assert conflicts == ["filters"] and protected.filters == original.filters


def test_only_one_recovery_is_allowed_across_all_required_steps(settings, catalog):
    with TestClient(create_app(settings)) as client:
        session, graph_id = upload(client)
        calls = []
        supporting = AnalysisTask(
            question="Identify the accounts that connect these groups.",
            problem_id=catalog.operation("maximal-cliques").problem_id,
            operation_id="maximal-cliques",
        )

        async def model(**kwargs):
            calls.append(kwargs["schema"].__name__)
            payload = kwargs["user_payload"]
            if kwargs["schema"] is RouteDecision:
                if "routing_review" in payload:
                    return route(
                        catalog, "k-cliques"
                    )  # Omission cannot drop the supporting task.
                return route(
                    catalog, "maximal-cliques", additional_analyses=[supporting]
                )
            if payload["selected_operation"]["operation_id"] == "k-cliques":
                return ready(parameters={"k": 3}, optional_outputs=["cliques"])
            return refused()

        client.app.state.runtime.agent.model.generate = model
        body = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "graph_id": graph_id,
                "message": QUESTION + " Identify the accounts connecting groups too.",
            },
        ).json()
        assert (
            body["status"] == "needs_information"
            and body["plans"] == []
            and body["plan"] is None
        )
        assert calls == [
            "RouteDecision",
            "PlanDraft",
            "RouteDecision",
            "PlanDraft",
            "PlanDraft",
        ]
        messages = client.app.state.runtime.database.messages(session)
        assert len(messages) == 2 and "plan" not in messages[-1]["payload"]
        assert_no_jobs(client, session)


def test_recovery_updates_the_supporting_step_without_changing_the_primary(
    settings, catalog
):
    with TestClient(create_app(settings)) as client:
        session, graph_id = upload(client)
        supporting = AnalysisTask(
            question="Rank accounts by how often they mediate shortest routes.",
            problem_id=catalog.operation("maximal-cliques").problem_id,
            operation_id="maximal-cliques",
        )
        question = QUESTION + " " + supporting.question
        drafts = []

        async def model(**kwargs):
            payload = kwargs["user_payload"]
            if kwargs["schema"] is RouteDecision:
                if "routing_review" in payload:
                    assert payload["message"] == supporting.question
                    assert (
                        payload["routing_review"]["original_request"]["message"]
                        == question
                    )
                    return route(catalog, "betweenness-centrality")
                return route(catalog, "k-cliques", additional_analyses=[supporting])
            operation = payload["selected_operation"]["operation_id"]
            drafts.append(operation)
            if operation == "maximal-cliques":
                return refused()
            return ready(parameters={"k": 3} if operation == "k-cliques" else {})

        client.app.state.runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={"graph_id": graph_id, "message": question},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ready"
        assert [plan["operation_id"] for plan in body["plans"]] == [
            "k-cliques",
            "betweenness-centrality",
        ]
        assert drafts == ["k-cliques", "maximal-cliques", "betweenness-centrality"]
        assert body["decision"]["additional_analyses"] == [
            {
                "question": supporting.question,
                "operation_id": "betweenness-centrality",
                "problem_id": catalog.operation("betweenness-centrality").problem_id,
            }
        ]
        messages = client.app.state.runtime.database.messages(session)
        assert len(messages) == 2
        assert messages[0]["payload"]["message"] == question
        assert [plan["operation_id"] for plan in messages[1]["payload"]["plans"]] == [
            "k-cliques",
            "betweenness-centrality",
        ]
        assert_no_jobs(client, session)


@pytest.mark.parametrize("repeat_inspection", [False, True])
def test_recovery_inspection_is_bounded_and_does_not_approve_execution(
    settings, catalog, repeat_inspection
):
    with TestClient(create_app(settings)) as client:
        session, graph_id = upload(client)
        calls = []

        async def model(**kwargs):
            payload = kwargs["user_payload"]
            calls.append(kwargs["schema"].__name__)
            if kwargs["schema"] is RouteDecision:
                if "routing_review" not in payload:
                    return route(catalog, "maximal-cliques")
                if payload.get("remaining_inspection_rounds") == 0:
                    assert payload["inspection_results"]
                    if not repeat_inspection:
                        return route(catalog, "k-cliques")
                return route(
                    catalog,
                    "k-cliques",
                    inspections=[
                        DataInspection(target="vertices", fields=["label"], limit=2)
                    ],
                )
            if payload["selected_operation"]["operation_id"] == "k-cliques":
                return ready(parameters={"k": 3}, optional_outputs=["cliques"])
            return refused()

        client.app.state.runtime.agent.model.generate = model
        body = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={"graph_id": graph_id, "message": QUESTION},
        ).json()
        assert body["status"] == ("needs_information" if repeat_inspection else "ready")
        assert calls.count("RouteDecision") == 3
        assert calls.count("PlanDraft") == (1 if repeat_inspection else 2)
        assert_no_jobs(client, session)
