"""Current repaired profiles; historical expansion holdouts stay frozen."""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.answers import build_answer
from graphmine_agent.api import create_app
from graphmine_agent.execution import GraphMineRunner
from graphmine_agent.llm import constrain_plan_schema
from graphmine_agent.models import ExecutionPlan, FileRole, PlanDraft
from graphmine_agent.planning import PlanValidationError, PlanValidator
from graphmine_agent.profiles import ProfileInputError, prepare_operation_graph
from graphmine_agent.selector import BackendSelector
from jsonschema import Draft202012Validator

AUTH = {"Authorization": "Bearer test-secret"}


def graph(ids, edges, *, directed=False, sides=False):
    return {
        "graph": {
            "id": "repairs",
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {"id": v, "attributes": {"side": "left" if i < 2 else "right"}}
            if sides
            else {"id": v}
            for i, v in enumerate(ids)
        ],
        "edges": [
            {
                "id": str(i),
                "source": a,
                "target": b,
                "weight": w,
                "attributes": {"cost": w},
            }
            for i, (a, b, w) in enumerate(edges)
        ],
    }


def fixtures():
    triangle = graph([-3, 0, "0", "isolate"], [(-3, 0, 1), (0, "0", 1), ("0", -3, 1)])
    bipartite = graph(
        [-3, 0, "0", "right"],
        [(-3, "0", 1), (-3, "right", 1), (0, "0", 1), (0, "right", 1)],
        sides=True,
    )
    chain = graph([-3, 0, "0"], [(-3, 0, 1), (0, "0", 1)], directed=True)
    return {
        "acctd": ("k-truss", triangle, {}, "maximum_truss_number", 3),
        "cds": ("densest-subgraph", triangle, {}, "density", 1),
        "mbe-gpu": ("maximal-biclique-counting", bipartite, {}, "total_count", 1),
        "kpar": (
            "personalized-pagerank",
            chain,
            {"seed_vertex": "0", "top_k": 3, "restart_probability": 0.2},
            "restart_probability_used",
            0.2,
        ),
        "gamma-butterfly": ("butterfly-counting", bipartite, {}, "butterfly_count", 1),
        "gpu4gst": (
            "group-steiner-tree",
            graph([-3, 0, "0"], [(-3, 0, 2), (0, "0", 3), (-3, "0", 20)]),
            {"groups": [[-3], ["0"]]},
            "tree_weight",
            5,
        ),
        "superfuser": (
            "influence-maximization",
            chain,
            {
                "diffusion_model": "independent_cascade",
                "seed_set_size": 1,
                "sample_count": 32,
            },
            "expected_spread",
            3,
        ),
        "cuda-ms": ("maximum-clique", triangle, {}, "maximum_size", 3),
        "maximum-clique-on-gpu": ("maximum-clique", triangle, {}, "maximum_size", 3),
    }


def make_plan(catalog, backend, **updates):
    operation, _, parameters, _, _ = fixtures()[backend]
    return ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id=operation,
        problem_id=catalog.operation(operation).problem_id,
        backend_id=backend,
        parameters=copy.deepcopy(parameters),
        **updates,
    )


@pytest.mark.parametrize("backend", sorted(fixtures()))
def test_repaired_profiles_are_explicit_validated_contracts(catalog, settings, backend):
    repair = json.loads(
        (settings.repository_root / "catalog/repaired_profiles.json").read_text()
    )
    assert len(repair["backends"]) == 9
    normalized = PlanValidator(catalog).validate(
        make_plan(catalog, backend), for_execution=True
    )
    assert normalized.backend_id == backend
    original = copy.deepcopy(fixtures()[backend][1])
    assert prepare_operation_graph(original, normalized) == original
    selector = BackendSelector(
        settings.backend_policy_path, catalog, PlanValidator(catalog)
    )
    assert selector.select(normalized, None, {backend}).backend_id == backend


@pytest.mark.parametrize(
    "groups", [[], [[]], [[True]], [[1.5]], [[2**63]], [[""]], [[0]] * 17, ["0"]]
)
def test_group_schema_and_server_reject_invalid_ids(catalog, groups):
    plan = make_plan(catalog, "gpu4gst")
    plan.parameters["groups"] = groups
    with pytest.raises(PlanValidationError):
        PlanValidator(catalog).validate(plan, for_execution=True)
    schema = PlanDraft.model_json_schema()
    constrain_plan_schema(
        schema, {"operation_context": catalog.operation_context("group-steiner-tree")}
    )
    spec = schema["$defs"]["PlanConfiguration"]["properties"]["parameters"]
    Draft202012Validator.check_schema(spec)
    assert list(Draft202012Validator(spec).iter_errors({"groups": groups}))


@pytest.mark.parametrize(
    "backend,field,value",
    [
        ("kpar", "restart_probability", 0.15),
        ("kpar", "seed_vertex", True),
        ("kpar", "epsilon", 0.001),
        ("kpar", "epsilon", 0.6),
        ("kpar", "solution_quality", "exact"),
        ("kpar", "top_k", 0),
        ("superfuser", "diffusion_model", "linear_threshold"),
        ("superfuser", "require_guarantee", True),
        ("superfuser", "sample_count", 33),
        ("superfuser", "sample_count", 0),
        ("superfuser", "random_seed", -1),
    ],
)
def test_unsupported_profile_parameters_fail_before_execution(
    catalog, backend, field, value
):
    plan = make_plan(catalog, backend)
    plan.parameters[field] = value
    with pytest.raises(PlanValidationError):
        PlanValidator(catalog).validate(plan, for_execution=True)


@pytest.mark.parametrize("backend", ["kpar", "gpu4gst"])
def test_filtered_out_typed_seed_or_group_member_requires_information(catalog, backend):
    data = copy.deepcopy(fixtures()[backend][1])
    data["vertices"] = [v for v in data["vertices"] if v["id"] != "0"]
    with pytest.raises(ProfileInputError, match="absent after filtering") as error:
        prepare_operation_graph(data, make_plan(catalog, backend))
    assert error.value.status == "needs_information"


@pytest.mark.parametrize(
    "backend,invalid",
    [("superfuser", 1.01), ("superfuser", -0.1), ("gpu4gst", 0.5), ("gpu4gst", 2**53)],
)
def test_invalid_weights_are_rejected_without_rounding(catalog, backend, invalid):
    data = copy.deepcopy(fixtures()[backend][1])
    data["edges"][0]["weight"] = invalid
    with pytest.raises(ProfileInputError):
        prepare_operation_graph(data, make_plan(catalog, backend))


def test_nested_groups_and_weight_attribute_survive_command_encoding(
    settings, catalog, graph_store, session, tmp_path
):
    data = copy.deepcopy(fixtures()["gpu4gst"][1])
    data["edges"][0]["weight"] = 999
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="tree.json",
        content=json.dumps(data).encode(),
        media_type="application/json",
    )
    plan = make_plan(
        catalog,
        "gpu4gst",
        application_intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.cost",
            "weight_usage": "other",
        },
    )
    plan = plan.model_copy(update={"session_id": session.id, "graph_id": record.id})
    runner = GraphMineRunner(
        replace(settings, graphmine_binary=tmp_path / "absent"),
        catalog,
        graph_store,
        PlanValidator(catalog),
    )
    command = runner.build_command(plan, tmp_path / "job/result.json")
    assert json.loads(command[command.index("--groups") + 1]) == [[-3], ["0"]]
    prepared = json.loads(Path(command[command.index("--graph") + 1]).read_text())
    assert prepared["edges"][0]["weight"] == 2
    assert graph_store.read_graph(record.id, session.id)["edges"][0]["weight"] == 999


def test_infeasible_tree_answer_does_not_claim_zero_cost_solution(catalog):
    answer = build_answer(
        fixtures()["gpu4gst"][1],
        make_plan(catalog, "gpu4gst"),
        {
            "output": {
                "feasible": False,
                "optimal": True,
                "tree_weight": 0,
                "tree_edges": [],
                "selected_vertices": [],
            }
        },
        source_hash="fixture",
    )
    assert "tree_weight" not in answer["metrics"] and not answer["groups"]
    assert "No connected tree" in answer["facts"][0]["statement"]


@pytest.mark.skipif(
    not os.getenv("GRAPHMINE_REPAIRED_TEST_BINARY"),
    reason="Requires native GPU workers",
)
@pytest.mark.parametrize("backend", sorted(fixtures()))
def test_agent_api_runs_repaired_backend_and_builds_grounded_answer(
    settings, catalog, backend
):
    operation, data, parameters, metric, expected = fixtures()[backend]
    configured = replace(
        settings,
        graphmine_binary=Path(os.environ["GRAPHMINE_REPAIRED_TEST_BINARY"]),
        graph_gpu_uuid=None,
        job_timeout_seconds=90,
    )
    with TestClient(create_app(configured)) as client:
        session = client.post(
            "/api/sessions", headers=AUTH, json={"domain_id": "general"}
        ).json()["id"]
        upload = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("graph.json", json.dumps(data), "application/json")},
            data={"role": "graph"},
        )
        assert upload.status_code == 201, upload.text
        planned = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={
                "message": operation,
                "graph_id": upload.json()["id"],
                "parameters": parameters,
            },
        )
        assert planned.status_code == 200 and planned.json()["status"] == "ready", (
            planned.text
        )
        plan = planned.json()["plan"]
        plan["backend_id"] = backend
        submitted = client.post("/api/jobs", headers=AUTH, json=plan)
        assert submitted.status_code == 202, submitted.text
        job = submitted.json()
        deadline = time.monotonic() + 90
        while (
            job["status"] not in {"completed", "failed", "cancelled"}
            and time.monotonic() < deadline
        ):
            time.sleep(0.03)
            job = client.get(f"/api/jobs/{job['id']}", headers=AUTH).json()
        assert job["status"] == "completed", job
        result = client.get(f"/api/results/{job['result_id']}", headers=AUTH).json()[
            "payload"
        ]
        assert result["output"][metric] == expected
        assert result["provenance"]["backend"] == backend
        answer = build_answer(
            data, ExecutionPlan.model_validate(plan), result, source_hash="fixture"
        )
        assert answer["facts"]
        if backend not in {"cuda-ms", "maximum-clique-on-gpu"}:
            assert answer["metrics"][metric] == expected
        if backend == "gpu4gst":
            assert len(answer["network"]["edges"]) == 2
            assert not any(
                "does not use them as costs" in text for text in answer["limitations"]
            )
        if backend == "kpar":
            assert (
                answer["rows"][0]["id"] == "0"
                and not answer["metrics"]["error_bound_certified"]
            )
        if backend == "superfuser":
            assert (
                not answer["metrics"]["guarantee_met"] and answer["rows"][0]["id"] == -3
            )
        if backend == "mbe-gpu":
            assert not answer["groups"] and any(
                "count only" in text for text in answer["limitations"]
            )


@pytest.mark.parametrize(
    "backend", ["acctd", "cds", "mbe-gpu", "kpar", "gamma-butterfly"]
)
def test_unweighted_profiles_reject_nonunit_weights(catalog, backend):
    data = copy.deepcopy(fixtures()[backend][1])
    data["edges"][0]["weight"] = 0.75
    with pytest.raises(ProfileInputError, match="unit weights"):
        prepare_operation_graph(data, make_plan(catalog, backend))
