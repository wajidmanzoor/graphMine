from __future__ import annotations

import copy
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.agent_service import AgentService
from graphmine_agent.api import create_app
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import corpus, oracles, workflows
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    JobRecord,
    JobStatus,
    ResultRecord,
    RouteDecision,
    SessionRecord,
    TurnDecision,
)
from graphmine_agent.planning import (
    application_capability_errors,
    normalize_route,
    route_blocker,
)

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.fixture
def synthetic(tmp_path):
    root = tmp_path / "corpus"
    manifest = corpus.generate_corpus(root, seed=271828, graphs_per_family=2)
    _, graphs = corpus.load_corpus(root)
    return root, manifest, graphs


def test_workflows_are_reproducible_independently_labeled_and_not_test_data(synthetic):
    _, manifest, graphs = synthetic
    snapshot = copy.deepcopy(manifest)
    cases = workflows.build_workflows(manifest, graphs)
    assert cases == workflows.build_workflows(manifest, graphs)
    assert manifest == snapshot
    assert len(cases) == 6
    assert sum(len(case["steps"]) for case in cases) == 21
    assert len({case["domain"] for case in cases}) == 6
    test_ids = {
        row["graph_id"] for row in manifest["examples"] if row["split"] == "test"
    }
    for case in cases:
        assert case["graph_id"] not in test_ids
        for step in case["steps"]:
            assert step["task"]["oracle"] == oracles.expected_answer(
                graphs[case["graph_id"]], step["task"]
            )
            assert (
                step["query"]
                == step["task"]["query"]
                == step["task"]["intent"]["objective"]
            )
    by_id = {case["id"]: case for case in cases}
    assert [
        step["task"]["filters"] for step in by_id["scope-corrections"]["steps"][:3]
    ] == [
        [
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "eq",
                "value": 2026,
            }
        ],
        [
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "eq",
                "value": 2025,
            }
        ],
        [],
    ]
    event = by_id["event-window"]["steps"][-1]["task"]
    assert (
        event["intent"]["time_window"] == 20000
        and event["intent"]["time_unit"] == "milliseconds"
    )


@pytest.mark.parametrize("supported", [True, False])
@pytest.mark.parametrize("has_cost_data", [True, False])
def test_weighted_missing_data_is_unsupported_before_drafting(
    settings, supported, has_cost_data
):
    graph = {
        "graph": {
            "id": "costs",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": i, "label": f"Station {i}"} for i in range(3)],
        "edges": [
            {
                "id": i,
                "source": a,
                "target": b,
                **({"weight": 8, "attributes": {"cost": 8}} if has_cost_data else {}),
            }
            for i, (a, b) in enumerate([(0, 1), (1, 2), (0, 2)])
        ],
    }
    with TestClient(create_app(settings)) as client:
        session = client.post(
            "/api/sessions",
            headers=AUTH,
            json={"domain_id": "communications_infrastructure"},
        ).json()["id"]
        file = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("costs.json", json.dumps(graph), "application/json")},
            data={"role": "graph"},
        ).json()["id"]
        calls = []

        async def model(**kwargs):
            calls.append(kwargs["schema"].__name__)
            assert kwargs["schema"] is RouteDecision, (
                "Capability failure must not reach drafting"
            )
            return RouteDecision(
                problem_id="centrality_influential_node_mining",
                operation_id="betweenness-centrality" if supported else None,
                supported=supported,
                confidence=1,
                missing_information=["Upload monetary costs"],
                explanation="Please upload a cost file.",
                intent=ApplicationIntent(requires_edge_weights=True),
            )

        client.app.state.runtime.agent.model.generate = model
        question = "Which stations connect cheapest routes? Use the connection costs."
        response = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"graph_id": file, "message": question},
        ).json()
        assert response["planning_status"] == "unsupported"
        assert response["job_id"] is None and response["plan"] is None
        assert "Adding cost data would not enable" in response["message"]
        assert "Please upload" not in response["message"] and calls == ["RouteDecision"]
        assert (
            client.get("/api/jobs", headers=AUTH, params={"session_id": session}).json()
            == []
        )
        last = client.app.state.runtime.database.messages(session)[-1]["payload"]
        assert last["status"] == "unsupported" and last["graph_id"] == file
        assert last["pending_question"] == question


def test_input_clarification_is_not_mislabeled_as_missing_capability(catalog):
    missing_goal = RouteDecision(
        supported=False,
        confidence=0.2,
        explanation="What matters to you?",
        ambiguity=["Closely connected groups or connections between them?"],
    )
    assert (
        route_blocker(catalog, normalize_route(catalog, missing_goal))[0]
        == "needs_information"
    )
    missing_threshold = RouteDecision(
        problem_id="k_core_decomposition",
        operation_id="k-core",
        supported=True,
        confidence=1,
        explanation="How many remaining partners should each have?",
        missing_information=["minimum number of partners"],
    )
    assert route_blocker(catalog, missing_threshold)[0] == "needs_information"
    assert (
        route_blocker(
            catalog, missing_threshold.model_copy(update={"missing_information": []})
        )
        is None
    )


@pytest.mark.parametrize("weighted", [True, False])
def test_uncertain_followup_reaches_full_planner_with_original_question(
    settings, triangle_graph, weighted
):
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        session = runtime.database.create_session(
            SessionRecord(domain_id="social_networks")
        )
        graph = runtime.graph_store.ingest(
            session_id=session.id,
            role="graph",
            filename="triangle.json",
            content=triangle_graph,
            media_type="application/json",
        )
        plan = ExecutionPlan(
            session_id=session.id,
            graph_id=graph.id,
            operation_id="maximal-cliques",
            problem_id="maximal_clique_enumeration",
            parameters={"minimum_clique_size": 3},
            application_intent=ApplicationIntent(),
        )
        job = runtime.database.save_job(
            JobRecord(session_id=session.id, plan=plan, status=JobStatus.completed)
        )
        runtime.database.save_result(
            ResultRecord(
                job_id=job.id,
                session_id=session.id,
                operation_id=plan.operation_id,
                payload={},
                summary={},
                answer={"question": "Find every qualifying group", "facts": []},
            )
        )
        question = (
            "Rank everyone using connection costs."
            if weighted
            else "Which people matter?"
        )
        calls = []

        async def model(**kwargs):
            calls.append(kwargs["schema"].__name__)
            assert kwargs["user_payload"]["message"] == question
            if kwargs["schema"] is TurnDecision:
                assert kwargs["user_payload"]["previous_parameters"] == {
                    "minimum_clique_size": 3
                }
                return TurnDecision(action="clarify", request="Which starting point?")
            assert kwargs["schema"] is RouteDecision
            return RouteDecision(
                problem_id="centrality_influential_node_mining" if weighted else None,
                supported=False,
                confidence=0.8,
                explanation="Costs are unavailable"
                if weighted
                else "What would you like to learn?",
                intent=ApplicationIntent(requires_edge_weights=weighted),
                ambiguity=[]
                if weighted
                else ["Closely connected groups or people connecting them?"],
                missing_information=["cost"] if weighted else [],
            )

        runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session.id}/chat",
            headers=AUTH,
            json={"graph_id": graph.id, "message": question},
        ).json()
        assert calls == ["TurnDecision", "RouteDecision"]
        assert response["planning_status"] == (
            "unsupported" if weighted else "needs_information"
        )
        assert response["plan"] is None and response["job_id"] is None
        assert "Which starting point?" not in response["message"]
        assert len(runtime.database.list_jobs(session.id)) == 1


def test_unavailable_catalog_problem_does_not_invite_more_uploads(catalog):
    problem_id = next(
        name
        for name, value in catalog.problems.items()
        if value["library_support"]["status"] != "validated"
    )
    decision = normalize_route(
        catalog,
        RouteDecision(
            problem_id=problem_id,
            supported=False,
            confidence=1,
            explanation="Upload a new input to enable this.",
            missing_information=["some input"],
        ),
    )
    status, message = route_blocker(catalog, decision)
    assert status == "unsupported" and "Upload a new input" not in message
    assert "would not enable" in message


@pytest.mark.parametrize(
    "intent",
    [
        ApplicationIntent(
            pattern_vertex_count=4, pattern_edges=[[0, 1], [1, 2], [2, 3]]
        ),
        ApplicationIntent(
            pattern_vertex_count=3, pattern_edges=[[0, 1], [1, 2], [2, 0]]
        ),
        ApplicationIntent(pattern_vertex_count=4),
    ],
)
def test_unsupported_event_pattern_outranks_missing_units(catalog, intent):
    decision = normalize_route(
        catalog,
        RouteDecision(
            problem_id="temporal_motif_mining",
            supported=False,
            confidence=1,
            intent=intent,
            missing_information=["timestamp units"],
            explanation="Please provide units.",
        ),
    )
    status, message = route_blocker(catalog, decision)
    assert status == "unsupported" and "three-entity pattern" in message


def test_routing_does_not_invent_a_missing_event_pattern():
    intent = ApplicationIntent()
    assert not application_capability_errors(intent, "temporal-motif-mining")
    assert application_capability_errors(
        intent, "temporal-motif-mining", require_complete_pattern=True
    )


def test_pending_question_is_graph_scoped_and_never_revives_stale_turns():
    pending = {
        "role": "assistant",
        "payload": {
            "status": "needs_information",
            "graph_id": "current",
            "pending_question": "Use the recent events",
            "message": "What period?",
            "decision": {"intent": {"time_unit": "unspecified"}},
        },
    }
    assert (
        AgentService._pending_request([pending], "current")["question"]
        == "Use the recent events"
    )
    assert AgentService._pending_request([pending], "other") is None
    assert (
        AgentService._pending_request(
            [pending, {"role": "assistant", "payload": {"result_id": "complete"}}],
            "current",
        )
        is None
    )
    legacy = copy.deepcopy(pending)
    legacy["payload"].pop("graph_id")
    assert AgentService._pending_request([legacy], "current") is None
    assert AgentService._pending_request([], "current") is None


def test_workflow_checker_rejects_event_requirement_changes_even_for_equal_counts(
    synthetic,
):
    _, manifest, graphs = synthetic
    case = next(
        case
        for case in workflows.build_workflows(manifest, graphs)
        if case["id"] == "event-window"
    )
    task = case["steps"][0]["task"]
    # The incomplete outcome already fails execution; this additional check
    # proves coincidental matching counts cannot waive requested semantics.
    result = {
        "job": {
            "plan": {
                "application_intent": {
                    "requires_direction": False,
                    "pattern_vertex_count": 4,
                    "pattern_edges": [],
                }
            }
        }
    }
    issues = workflows.check_workflow_step(graphs[case["graph_id"]], task, result)
    assert "Requested requires_direction changed" in issues
    assert "Requested event pattern_vertex_count changed" in issues


@pytest.mark.asyncio
async def test_workflow_runner_keeps_trials_and_feedback_separate(
    settings, synthetic, tmp_path, monkeypatch
):
    root, _, _ = synthetic
    sessions, feedbacks, observed_queries = [], [], []

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield object(), tmp_path / "history"

    class FakeTerminal:
        def __init__(self, *args, **kwargs):
            self.session_id = self.turn_id = None

        async def start(self, **kwargs):
            self.session_id = f"session-{len(sessions)}"
            sessions.append(self.session_id)

        async def load(self, path):
            assert path.is_file()

        async def ask(self, query):
            self.turn_id = "turn-" + str(len(observed_queries))
            observed_queries.append(query)
            return {
                "response": {
                    "planning_status": "unsupported",
                    "message": "No computation",
                }
            }

        async def feedback(self, wrong, expected, *, source):
            feedbacks.append((wrong, expected, source))
            return {"id": f"feedback-{len(feedbacks)}"}

    monkeypatch.setattr(workflows, "agent_client", client)
    monkeypatch.setattr(workflows, "Terminal", FakeTerminal)
    monkeypatch.setattr(
        workflows,
        "check_workflow_step",
        lambda graph, task, outcome: ["fixture failure"],
    )
    output = tmp_path / "report.json"
    result = await workflows.evaluate_workflows(
        replace(settings, llm_enabled=True, llm_base_url="http://127.0.0.1:8001/v1"),
        corpus=root,
        output=output,
        data_dir=tmp_path / "isolated",
        case_ids={"event-window"},
        repeats=2,
    )
    assert result["total"] == 8 and result["passed"] == result["workflows_passed"] == 0
    assert len(sessions) == 2 and len(set(sessions)) == 2
    assert len(feedbacks) == 8 and all(
        row[2] == "assistant_evaluation" for row in feedbacks
    )
    assert observed_queries[:4] == observed_queries[4:]
    assert result["finished_at"] and result["training_started"] is False
    assert len(result["source_sha256"]) >= 8
    assert output.stat().st_mode & 0o777 == 0o600
    for session in sessions:
        assert (tmp_path / "history" / session / "workflow-evaluation.json").is_file()
    original_digest = HistoryStore.digest(output)
    rechecked = workflows.recheck_workflows(
        corpus=root, report_path=output, output=tmp_path / "rechecked.json"
    )
    assert rechecked["total"] == 8 and rechecked["passed"] == 0
    assert rechecked["original_report"]["sha256"] == original_digest
    assert HistoryStore.digest(output) == original_digest
    assert len(observed_queries) == 8  # Offline rechecking performs no model calls.
    tampered = copy.deepcopy(result)
    tampered["trials"][0]["steps"][0]["query"] = "Changed question"
    HistoryStore.write(tmp_path / "tampered.json", tampered)
    with pytest.raises(ValueError, match="Observed question changed"):
        workflows.recheck_workflows(
            corpus=root,
            report_path=tmp_path / "tampered.json",
            output=tmp_path / "bad-recheck.json",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "disabled_model",
        "existing_store",
        "unknown_case",
        "too_many_repeats",
        "remote_model",
    ],
)
async def test_workflow_preflight_does_not_run_invalid_evaluations(
    settings, synthetic, tmp_path, kind
):
    root, _, _ = synthetic
    current = replace(
        settings, llm_enabled=True, llm_base_url="http://127.0.0.1:8001/v1"
    )
    store = tmp_path / "runtime"
    kwargs = {}
    if kind == "disabled_model":
        current = replace(current, llm_enabled=False)
    elif kind == "existing_store":
        store.mkdir()
    elif kind == "unknown_case":
        kwargs["case_ids"] = {"unknown"}
    elif kind == "too_many_repeats":
        kwargs["repeats"] = 4
    else:
        current = replace(current, llm_base_url="https://remote.example/v1")
    with pytest.raises(ValueError):
        await workflows.evaluate_workflows(
            current,
            corpus=root,
            output=tmp_path / "report.json",
            data_dir=store,
            **kwargs,
        )
    assert not (tmp_path / "report.json").exists()


@pytest.fixture
def cached_evidence(synthetic, tmp_path):
    import shutil

    root, manifest, graphs = synthetic
    case = workflows.build_workflows(manifest, graphs)[0]
    task = case["steps"][2]["task"]
    graph = graphs[case["graph_id"]]
    session_id, result_id, job_id, graph_id = (
        "session-cache",
        "result-cache",
        "job-cache",
        "graph-cache",
    )
    history = tmp_path / "history"
    session = history / session_id
    source = root / case["graph_path"]
    original = session / "files" / graph_id / "original"
    metadata_path = session / "files" / graph_id / "metadata.json"
    HistoryStore.write(
        metadata_path,
        {
            "file": {
                "id": graph_id,
                "session_id": session_id,
                "sha256": HistoryStore.digest(source),
            }
        },
    )
    shutil.copyfile(source, original)
    job = {
        "id": job_id,
        "session_id": session_id,
        "status": "completed",
        "result_id": result_id,
        "plan": {
            "graph_id": graph_id,
            "parameters": task["parameters"],
            "application_intent": task["intent"],
        },
    }
    interpretation = {"visualizations": [{"type": "table"}]}
    result = {
        "id": result_id,
        "session_id": session_id,
        "job_id": job_id,
        "operation_id": task["operation_id"],
        "payload": {
            "output": {
                "cliques": task["oracle"]["groups"],
                "returned_count": task["oracle"]["count"],
                "complete": True,
            }
        },
        "answer": {
            "rows": [],
            "facts": ["computed fixture"],
            "provenance": {"input_edges": len(graph["edges"])},
        },
        "interpretation": interpretation,
    }
    job_path, result_path = (
        session / "jobs" / job_id / "job.json",
        session / "results" / result_id / "result.json",
    )
    HistoryStore.write(job_path, job)
    HistoryStore.write(result_path, result)
    outcome = {
        "response": {
            "mode": "analyst",
            "result_id": result_id,
            "interpretation": interpretation,
        }
    }
    return {
        "outcome": outcome,
        "history": history,
        "session_id": session_id,
        "source_graph": source,
        "job_path": job_path,
        "result_path": result_path,
        "metadata_path": metadata_path,
        "task": task,
        "graph": graph,
    }


def restored(evidence):
    return workflows.restore_reused_outcome(
        **{
            name: evidence[name]
            for name in (
                "outcome",
                "history",
                "session_id",
                "source_graph",
            )
        }
    )


def test_exact_cached_answer_is_valid_without_a_new_computation(cached_evidence):
    checked = restored(cached_evidence)
    assert checked["reused_result"] is True and len(checked["reuse_evidence"]) == 4
    assert not workflows.check_workflow_step(
        cached_evidence["graph"], cached_evidence["task"], checked
    )
    assert "job" not in cached_evidence["outcome"]


@pytest.mark.parametrize(
    "mutation", ["other_session", "source_changed", "wrong_job", "path_escape"]
)
def test_cached_result_bindings_fail_closed(cached_evidence, mutation):
    if mutation == "path_escape":
        cached_evidence["outcome"]["response"]["result_id"] = "../secret"
    elif mutation == "source_changed":
        metadata = json.loads(cached_evidence["metadata_path"].read_text())
        metadata["file"]["sha256"] = "different-source"
        HistoryStore.write(cached_evidence["metadata_path"], metadata)
    else:
        result = json.loads(cached_evidence["result_path"].read_text())
        result["session_id" if mutation == "other_session" else "id"] = "other-id"
        HistoryStore.write(cached_evidence["result_path"], result)
    with pytest.raises(ValueError):
        restored(cached_evidence)


@pytest.mark.parametrize(
    "mutation", ["changed_threshold", "changed_filter", "wrong_membership"]
)
def test_cached_answer_must_still_pass_semantic_and_numeric_checks(
    cached_evidence, mutation
):
    path = (
        cached_evidence["result_path"]
        if mutation == "wrong_membership"
        else cached_evidence["job_path"]
    )
    value = json.loads(path.read_text())
    if mutation == "changed_threshold":
        value["plan"]["parameters"]["minimum_clique_size"] = 4
    elif mutation == "changed_filter":
        value["plan"]["application_intent"]["filters"] = [
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "eq",
                "value": 2026,
            }
        ]
    else:
        value["payload"]["output"]["cliques"] = [["not-a-source-entity"]]
    HistoryStore.write(path, value)
    checked = restored(cached_evidence)
    assert workflows.check_workflow_step(
        cached_evidence["graph"], cached_evidence["task"], checked
    )
