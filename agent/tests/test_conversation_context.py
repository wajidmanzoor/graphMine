"""Selected-result and dataset boundaries with authored model responses."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    JobRecord,
    JobStatus,
    PlanConfiguration,
    PlanDraft,
    ResultRecord,
    RouteDecision,
    SessionRecord,
    TurnDecision,
)

AUTH = {"Authorization": "Bearer test-secret"}


def graph_file(runtime, session, content, name):
    graph = json.loads(content)
    graph["graph"]["id"] = name
    for edge in graph["edges"]:
        edge["attributes"] = {"year": 2025}
    return runtime.graph_store.ingest(
        session_id=session.id,
        role="graph",
        filename=name + ".json",
        content=json.dumps(graph).encode(),
        media_type="application/json",
    )


def saved_result(runtime, session, graph, year):
    plan = ExecutionPlan(
        session_id=session.id,
        graph_id=graph.id,
        operation_id="k-cliques",
        problem_id="k_clique_counting_enumeration",
        parameters={"k": 3},
        application_intent=ApplicationIntent(
            objective=f"Find trios using the {year} relationships.",
            filters=[
                {
                    "target": "edges",
                    "field": "attributes.year",
                    "operator": "eq",
                    "value": year,
                }
            ],
        ),
    )
    job = runtime.database.save_job(
        JobRecord(
            session_id=session.id,
            plan=plan,
            status=JobStatus.completed,
        )
    )
    return runtime.database.save_result(
        ResultRecord(
            job_id=job.id,
            session_id=session.id,
            operation_id=plan.operation_id,
            payload={"output": {"complete": False}},
            summary={},
            answer={
                "question": plan.application_intent.objective,
                "facts": [],
                "result_status": {"instances": "incomplete"},
            },
        )
    )


def model_for_scope(runtime, graph, result, question):
    calls = []

    async def model(**kwargs):
        payload = kwargs["user_payload"]
        calls.append(kwargs["schema"].__name__)
        assert payload["message"] == question
        if kwargs["schema"] in {TurnDecision, RouteDecision}:
            state = payload["conversation_state"]
            assert state["graph_id"] == graph.id
            assert state["graph_sha256"] == graph.sha256
            assert state["result_id"] == (result.id if result else None)
            if result:
                assert state["previous_result_status"] == {"instances": "incomplete"}
                expected_intent = runtime.database.get_job(
                    result.job_id
                ).plan.application_intent
                assert payload["active_constraints"] == expected_intent.model_dump(
                    mode="json"
                )
            else:
                assert payload["active_constraints"] is None
        if kwargs["schema"] is TurnDecision:
            # A lossy rewrite must not replace the user's actual conditions.
            return TurnDecision(
                action="analyze", request="Count every trio; ignore filters."
            )
        if kwargs["schema"] is RouteDecision:
            if "followup_interpretation" in payload:
                assert (
                    payload["followup_interpretation"]["request"]
                    == "Count every trio; ignore filters."
                )
            return RouteDecision(
                problem_id="k_clique_counting_enumeration",
                operation_id="k-cliques",
                supported=True,
                confidence=1,
                explanation="Authored fixture.",
            )
        assert kwargs["schema"] is PlanDraft
        return PlanDraft(
            status="ready", message="Ready", plan=PlanConfiguration(parameters={"k": 3})
        )

    runtime.agent.model.generate = model
    return calls


@pytest.mark.parametrize("endpoint", ["chat", "plan"])
def test_selected_older_result_supplies_the_dataset_and_filters(
    settings, triangle_graph, endpoint
):
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        session = runtime.database.create_session(SessionRecord())
        graph = graph_file(runtime, session, triangle_graph, "older-dataset")
        selected = saved_result(runtime, session, graph, 2025)
        saved_result(runtime, session, graph, 2026)
        graph_file(runtime, session, triangle_graph, "newer-dataset")
        question = (
            "List the exact trios using the same selection. Keep the year filter."
        )
        calls = model_for_scope(runtime, graph, selected, question)
        request = {"message": question, "result_id": selected.id}
        if endpoint == "plan":
            request["graph_id"] = graph.id
        else:
            request["execute"] = False
        response = client.post(
            f"/api/sessions/{session.id}/{endpoint}", headers=AUTH, json=request
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["plan"]["graph_id"] == graph.id
        intent = body["plan"]["application_intent"]
        assert intent["objective"] == question
        assert [condition["value"] for condition in intent["filters"]] == [2025]
        assert calls == (["TurnDecision"] if endpoint == "chat" else []) + [
            "RouteDecision",
            "PlanDraft",
        ]
        assert len(runtime.database.list_jobs(session.id)) == 2
        contexts = [
            event["data"]
            for event in runtime.database.history.session_events(session.id)
            if event["type"] == "conversation.context"
        ]
        assert contexts and all(state["result_id"] == selected.id for state in contexts)


def test_latest_result_lookup_is_scoped_to_the_requested_graph(
    settings, triangle_graph
):
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        session = runtime.database.create_session(SessionRecord())
        graph = graph_file(runtime, session, triangle_graph, "selected")
        selected = saved_result(runtime, session, graph, 2025)
        other = graph_file(runtime, session, triangle_graph, "other")
        saved_result(runtime, session, other, 2026)
        question = "Keep the selection and count the trios."
        calls = model_for_scope(runtime, graph, selected, question)
        response = client.post(
            f"/api/sessions/{session.id}/chat",
            headers=AUTH,
            json={
                "message": question,
                "graph_id": graph.id,
                "execute": False,
            },
        )
        assert response.status_code == 200, response.text
        assert (
            response.json()["plan"]["application_intent"]["filters"][0]["value"] == 2025
        )
        assert calls == ["TurnDecision", "RouteDecision", "PlanDraft"]
        assert (
            runtime.database.latest_result(session.id, graph_id="no-such-graph") is None
        )


@pytest.mark.parametrize("stale_browser_result", [False, True])
def test_new_dataset_does_not_inherit_old_results_or_filters(
    settings, triangle_graph, stale_browser_result
):
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        session = runtime.database.create_session(SessionRecord())
        old_graph = graph_file(runtime, session, triangle_graph, "old")
        old = saved_result(runtime, session, old_graph, 2025)
        graph = graph_file(runtime, session, triangle_graph, "new")
        question = "Count the trios in this dataset."
        calls = model_for_scope(runtime, graph, None, question)
        request = {"message": question, "execute": False}
        if stale_browser_result:
            request.update(graph_id=graph.id, result_id=old.id)
        response = client.post(
            f"/api/sessions/{session.id}/chat", headers=AUTH, json=request
        )
        assert response.status_code == 200, response.text
        plan = response.json()["plan"]
        assert (
            plan["graph_id"] == graph.id and plan["application_intent"]["filters"] == []
        )
        assert calls == ["RouteDecision", "PlanDraft"]
        assert len(runtime.database.list_jobs(session.id)) == 1


@pytest.mark.parametrize("mismatch", ["plan_graph", "analyst_graph", "session"])
def test_incompatible_explicit_result_is_rejected_before_model_work(
    settings, triangle_graph, mismatch
):
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        session = runtime.database.create_session(SessionRecord())
        graph = graph_file(runtime, session, triangle_graph, "first")
        result = saved_result(runtime, session, graph, 2025)
        other_session = (
            runtime.database.create_session(SessionRecord())
            if mismatch == "session"
            else session
        )
        other_graph = graph_file(runtime, other_session, triangle_graph, "second")

        async def no_model(**kwargs):
            pytest.fail("Incompatible context must not reach the model")

        runtime.agent.model.generate = no_model
        request = {
            "message": "Explain this result",
            "graph_id": other_graph.id,
            "result_id": result.id,
        }
        endpoint = "plan" if mismatch == "plan_graph" else "chat"
        if mismatch == "analyst_graph":
            request["mode"] = "analyst"
        response = client.post(
            f"/api/sessions/{other_session.id}/{endpoint}", headers=AUTH, json=request
        )
        assert response.status_code == 422, response.text
        assert len(runtime.database.list_jobs(session.id)) == 1
        assert runtime.database.messages(other_session.id) == []
