"""Authored CPU fixtures test the grader; they are not model/GPU evidence."""

import asyncio
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.analysis import prepare_analysis
from graphmine_agent.answers import answer_interpretation, build_answer
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import dual_workflows
from graphmine_agent.learning.catalog_replay import encoded
from graphmine_agent.learning.catalog_suite import digest
from graphmine_agent.learning.dual_corpus import graph_from_pairs
from graphmine_agent.learning.dual_workflows import grade
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    GroundedNarrative,
    GroundedStatement,
    PlanConfiguration,
    PlanDraft,
    RouteDecision,
)
from graphmine_agent.planning import PlanValidator
from graphmine_agent.terminal import agent_client
from graphmine_agent.visualization import answer_visualizations


@pytest.fixture
def authored_capture(catalog):
    graph = {
        "graph": {"id": "workflow-fixture", "directed": False},
        "vertices": [{"id": x, "label": str(x), "attributes": {}} for x in range(3)],
        "edges": [
            {"id": "a", "source": 0, "target": 1},
            {"id": "b", "source": 1, "target": 2},
        ],
    }
    question = (
        "List every fully connected group that cannot be extended by another record."
    )
    intent = ApplicationIntent(objective=question)
    task = {
        "question": question,
        "operation_id": "maximal-cliques",
        "problem_id": "maximal_clique_enumeration",
        "parameters": {},
        "optional_outputs": [],
        "intent": intent.model_dump(mode="json"),
        "expected_status": "ready",
    }
    case = {"graph": graph, "task": task, "attachments": {}}
    plan = ExecutionPlan(
        session_id="session-fixture",
        graph_id="graph-fixture",
        problem_id=task["problem_id"],
        operation_id=task["operation_id"],
        application_intent=intent,
    )
    plan = PlanValidator(catalog).validate(plan)
    graph_hash = hashlib.sha256(encoded(graph)).hexdigest()
    payload = {
        "ok": True,
        "output": {"cliques": [[0, 1], [1, 2]], "returned_count": 2, "complete": True},
        "provenance": {"test_double": True},
    }
    answer = prepare_analysis(
        build_answer(graph, plan, payload, source_hash=graph_hash)
    )
    interpretation = answer_interpretation(answer, answer_visualizations(answer))
    fact = answer["facts"][0]
    interpretation.explanation = [
        GroundedStatement(text=fact["statement"], fact_ids=[fact["id"]])
    ]
    result = {
        "id": "result-fixture",
        "job_id": "job-fixture",
        "session_id": plan.session_id,
        "payload": payload,
        "answer": answer,
        "interpretation": interpretation.model_dump(mode="json"),
        "interpretation_source": "llm",
    }
    capture = {
        "query": question,
        "session_id": plan.session_id,
        "graph": {"id": plan.graph_id, "sha256": graph_hash},
        "outcome": {"response": {"planning_status": "ready"}, "result": result},
        "jobs": [
            {
                "id": "job-fixture",
                "result_id": result["id"],
                "status": "completed",
                "plan": plan.model_dump(mode="json"),
            }
        ],
        "model_calls": [
            {
                "schema": "RouteDecision",
                "target": RouteDecision(
                    problem_id=task["problem_id"],
                    operation_id=task["operation_id"],
                    supported=True,
                    confidence=1,
                    explanation="Authored fixture.",
                    intent=intent,
                ).model_dump(mode="json"),
            },
            {
                "schema": "PlanDraft",
                "target": PlanDraft(
                    status="ready",
                    message="Authored fixture.",
                    plan=PlanConfiguration(),
                ).model_dump(mode="json"),
                "payload": {"inferred_auxiliary_inputs": {}, "available_files": []},
            },
        ],
    }
    return case, capture


def test_workflow_grader_recomputes_valid_math_and_grounding(
    settings, tmp_path, authored_capture
):
    case, capture = authored_capture
    result = grade(settings, tmp_path, case, capture)
    assert result["passed"], result


@pytest.mark.parametrize(
    "mutation,dimension",
    [
        ("dataset", "result_binding"),
        ("facts", "grounding"),
        ("fallback", "model_interpretation"),
        ("numeric", "numerical"),
    ],
)
def test_workflow_grader_rejects_tampering_and_fallback_as_model_success(
    settings, tmp_path, authored_capture, mutation, dimension
):
    case, original = authored_capture
    capture = copy.deepcopy(original)
    result = capture["outcome"]["result"]
    if mutation == "dataset":
        capture["jobs"][0]["plan"]["graph_id"] = "different-graph"
    elif mutation == "facts":
        result["answer"]["facts"][0]["statement"] = "Invented business result."
    elif mutation == "fallback":
        result["interpretation_source"] = "fallback"
    else:
        result["payload"]["output"]["cliques"] = [[0, 1, 2]]
    capture["grade"] = {"passed": True}
    scored = grade(settings, tmp_path, case, capture)
    assert not scored["passed"]
    assert scored["dimensions"][dimension] is False


def test_nonready_workflow_must_not_execute(settings, tmp_path, authored_capture):
    case, capture = authored_capture
    case["task"]["expected_status"] = "needs_information"
    capture["outcome"]["response"]["planning_status"] = "needs_information"
    scored = grade(settings, tmp_path, case, capture)
    assert not scored["passed"]
    assert not scored["dimensions"]["no_unapproved_execution"]


@pytest.mark.parametrize(
    "spec,expected",
    [
        ({"mark": "bar"}, 1),
        ({"layer": [{"mark": "bar"}, {"mark": "text"}]}, 1),
        ({"hconcat": [{"mark": "bar"}, {"mark": "rect"}]}, 2),
        (
            {
                "vconcat": [
                    {"layer": [{"mark": "bar"}, {"mark": "text"}]},
                    {"mark": "rect"},
                ]
            },
            2,
        ),
    ],
)
def test_composed_followup_requires_panels_not_just_layers(spec, expected):
    interpretation = {
        "visualizations": [{"type": "table"}, {"type": "vega_lite", "vega_lite": spec}]
    }
    assert dual_workflows.custom_panel_count(interpretation) == expected


@pytest.fixture
def paired_workflows(settings, tmp_path, authored_capture):
    case, capture = copy.deepcopy(authored_capture)
    case.update(id="fixture", split="validation")
    case["sha256"] = digest(case)
    HistoryStore.write(tmp_path / "corpus.json", {"cases": [case]})
    manifest = tmp_path / "selection.json"
    HistoryStore.write(
        manifest,
        {
            "corpus_sha256": HistoryStore.digest(tmp_path / "corpus.json"),
            "split": "validation",
            "rows": [
                {"id": "fixture", "case_id": "fixture", "case_sha256": case["sha256"]}
            ],
        },
    )
    implementation = Path(dual_workflows.__file__)
    binding = {
        "manifest_sha256": HistoryStore.digest(manifest),
        "endpoint": "http://fixture.invalid/v1",
        "sources": dual_workflows.source_bindings(),
        "workflow_sha256": HistoryStore.digest(implementation),
        "rules_sha256": HistoryStore.digest(
            implementation.with_name("dual_teacher.py")
        ),
        "profile": dual_workflows.run_profile(settings),
    }
    capture.update(id="fixture", case_id="fixture", elapsed_seconds=1.0)
    capture["grade"] = {"passed": False}
    for label in ("base", "adapters"):
        HistoryStore.write(tmp_path / label / "profile.json", binding)
        HistoryStore.write(tmp_path / label / "captures/fixture.json", capture)
    return manifest, tmp_path / "base", tmp_path / "adapters"


def test_workflow_comparison_regrades_and_counts_unreached_stages(
    settings, tmp_path, paired_workflows
):
    manifest, baseline, adapted = paired_workflows
    path = baseline / "captures/fixture.json"
    capture = json.loads(path.read_text())
    capture["jobs"] = []
    capture["grade"] = {"passed": True}
    HistoryStore.write(path, capture)
    result = dual_workflows.compare(
        settings, tmp_path, manifest, baseline, adapted, tmp_path / "comparison.json"
    )
    assert result["passed"] == {"base": 0, "adapters": 1}
    assert result["corrected"] == 1
    assert result["by_dimension"]["numerical"] == {"total": 1, "base": 0, "adapters": 1}


@pytest.mark.parametrize("mutation", ["missing", "scenario", "endpoint"])
def test_workflow_comparison_rejects_incomplete_or_mismatched_trials(
    settings, tmp_path, paired_workflows, mutation
):
    manifest, baseline, adapted = paired_workflows
    path = adapted / "captures/fixture.json"
    if mutation == "missing":
        path.unlink()
    elif mutation == "scenario":
        capture = json.loads(path.read_text())
        capture["case_id"] = "another-case"
        HistoryStore.write(path, capture)
    else:
        path = adapted / "profile.json"
        profile = json.loads(path.read_text())
        profile["endpoint"] = "http://different.invalid/v1"
        HistoryStore.write(path, profile)
    with pytest.raises(ValueError):
        dual_workflows.compare(
            settings,
            tmp_path,
            manifest,
            baseline,
            adapted,
            tmp_path / "comparison.json",
        )


def test_live_harness_injects_one_error_and_exercises_real_agent_recovery(
    settings, catalog, tmp_path, monkeypatch
):
    graph = graph_from_pairs(
        "recovery-harness", [(0, 1), (1, 2), (0, 2)], ids=["a", "b", "c"]
    )
    question = "Count and list fully connected groups of exactly three records, including those inside larger groups."
    task = {
        "question": question,
        "operation_id": "k-cliques",
        "problem_id": catalog.operation("k-cliques").problem_id,
        "parameters": {"k": 3},
        "optional_outputs": ["cliques"],
        "expected_status": "ready",
        "intent": ApplicationIntent(objective=question).model_dump(mode="json"),
    }
    case = {
        "id": "fixture",
        "graph": graph,
        "task": task,
        "domain_id": "fraud_detection",
        "attachments": {},
        "lineage": "synthetic:held-out",
        "split": "validation",
    }
    case["sha256"] = digest(case)
    HistoryStore.write(tmp_path / "corpus.json", {"cases": [case]})
    manifest = tmp_path / "selection.json"
    HistoryStore.write(
        manifest,
        {
            "corpus_sha256": HistoryStore.digest(tmp_path / "corpus.json"),
            "split": "validation",
            "rows": [
                {
                    "id": "fixture",
                    "case_id": "fixture",
                    "case_sha256": case["sha256"],
                    "clarification_first": False,
                    "chart_followup": False,
                    "inject_invalid_first_draft": True,
                }
            ],
        },
    )

    @asynccontextmanager
    async def fixture_client(configured, **kwargs):
        async with agent_client(replace(configured, llm_enabled=False), **kwargs) as (
            client,
            history,
        ):
            runtime = client._transport.app.state.runtime

            async def model(**request):
                schema = request["schema"]
                if schema is RouteDecision:
                    return RouteDecision(
                        problem_id=task["problem_id"],
                        operation_id="k-cliques",
                        supported=True,
                        confidence=1,
                        explanation="Authored CPU fixture.",
                        intent=task["intent"],
                    )
                if schema is PlanDraft:
                    return PlanDraft(
                        status="ready",
                        message="Authored CPU fixture.",
                        plan=PlanConfiguration(
                            parameters={"k": 3}, optional_outputs=["cliques"]
                        ),
                    )
                assert schema is GroundedNarrative
                fact = request["user_payload"]["answer"]["facts"][0]
                statement = GroundedStatement(
                    text=fact["statement"], fact_ids=[fact["id"]]
                )
                return GroundedNarrative(
                    fact_ids=[fact["id"]], summary=statement, findings=[statement]
                )

            async def execute(plan, workspace):
                assert plan.parameters.get("result_limit") != 0
                return {
                    "ok": True,
                    "output": {
                        "count": 1,
                        "cliques": [["a", "b", "c"]],
                        "complete": True,
                    },
                    "statistics": {},
                    "warnings": [],
                    "provenance": {"test_double": True},
                }, ["authored-cpu-fixture"]

            runtime.agent.model.generate = model
            runtime.runner.execute = execute
            runtime.runner.compiled_backends_for = lambda operation: set(
                runtime.catalog.operation(operation).allowed_backends
            )
            yield client, history

    monkeypatch.setattr(dual_workflows, "agent_client", fixture_client)
    output = tmp_path / "captured"
    asyncio.run(
        dual_workflows.evaluate(
            settings,
            tmp_path,
            manifest,
            output,
            planner="fixture-planner",
            analyst="fixture-analyst",
            base_url="http://unused.invalid/v1",
        )
    )
    capture = json.loads((output / "captures/fixture.json").read_text())
    profile = json.loads((output / "profile.json").read_text())["profile"]
    assert profile["base_model"] == settings.llm_model
    assert profile["planner_model"] == "fixture-planner"
    assert profile["analyst_model"] == "fixture-analyst"
    assert capture["injected_error"] == "invalid_result_limit_zero"
    assert capture["recovery_request_count"] == 1
    assert capture["grade"]["dimensions"]["bounded_recovery"]
    assert capture["grade"]["dimensions"]["numerical"]
    assert capture["outcome"]["result"]["interpretation_source"] == "offline_rules"
