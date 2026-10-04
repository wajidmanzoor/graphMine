from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from graphmine_agent.answers import build_answer
from graphmine_agent.api import create_app
from graphmine_agent.catalog import Catalog, CatalogError
from graphmine_agent.execution import GraphMineRunner
from graphmine_agent.llm import (
    OpenAICompatibleModel,
    ROUTING_SYSTEM_PROMPT,
    constrain_plan_schema,
)
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    FileRole,
    LLMMode,
    PlanDraft,
    RouteDecision,
)
from graphmine_agent.planning import (
    PlanValidationError,
    PlanValidator,
    normalize_route,
    route_blocker,
)
from graphmine_agent.profiles import (
    EXPANSION_OPERATIONS,
    ProfileInputError,
    prepare_operation_graph,
)

AUTH = {"Authorization": "Bearer test-secret"}


def graph(vertices, edges, directed=False):
    return {
        "graph": {
            "id": "expansion",
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": v} if not isinstance(v, dict) else v for v in vertices],
        "edges": [
            {"id": i, "source": a, "target": b, "weight": w, "attributes": {"cost": w}}
            for i, (a, b, w) in enumerate(edges)
        ],
    }


def fixtures():
    sides = [
        {"id": v, "attributes": {"side": "left" if v in ("a", "b") else "right"}}
        for v in ("a", "b", "x", "y")
    ]
    bipartite = graph(
        sides, [("a", "x", 9), ("a", "y", 1), ("b", "x", 2), ("b", "y", 8)]
    )
    return {
        "connected-components": (
            graph([0, 1, "1"], [(0, 1, 1), (1, 0, 1), (1, "1", 1)], True),
            {"connectivity_mode": "strongly_connected"},
            {},
            "component_count",
            2,
        ),
        "max-flow-min-cut": (
            graph(["0", 0], [("0", 0, 5)], True),
            {"source": "0", "sink": 0},
            {
                "requires_edge_weights": True,
                "weight_attribute": "attributes.cost",
                "weight_usage": "other",
                "requires_direction": True,
            },
            "max_flow_value",
            5,
        ),
        "linear-assignment": (
            bipartite,
            {},
            {
                "requires_edge_weights": True,
                "weight_attribute": "attributes.cost",
                "weight_usage": "other",
            },
            "objective_value",
            3,
        ),
        "transitive-closure": (
            graph([0, 1, 2], [(0, 1, 1), (1, 2, 1)], True),
            {},
            {"requires_direction": True},
            "reachable_pair_count",
            6,
        ),
        "butterfly-counting": (copy.deepcopy(bipartite), {}, {}, "butterfly_count", 1),
    }


def plan(catalog, operation, **updates):
    _, parameters, intent, _, _ = fixtures()[operation]
    return ExecutionPlan.model_validate(
        {
            "session_id": "session",
            "graph_id": "graph",
            "operation_id": operation,
            "problem_id": catalog.operation(operation).problem_id,
            "parameters": parameters,
            "application_intent": intent,
            **updates,
        }
    )


def test_expansion_catalog_preserves_all_problem_specs_and_screening(catalog, settings):
    assert len(catalog.problems) == 37
    assert (
        sum(p["library_support"]["available"] for p in catalog.problems.values()) == 17
    )
    assert len(catalog.instructions) == 18
    for record in catalog.problems.values():
        assert record["spec"] == json.loads(
            (settings.repository_root / record["source"]).read_text()
        )
        if record["source"].split("/")[1][:2] > "20":
            assert record["intent_signals"] and isinstance(
                record["expansion_screening"], list
            )
            if record["spec"]["problem_id"] != "null_model_significance_testing":
                assert record["expansion_screening"]
    context = catalog.routing_context("general")
    assert context["contract_version"] == "expanded-37-v1"
    for operation in EXPANSION_OPERATIONS:
        support = catalog.problem(catalog.operation(operation).problem_id)[
            "library_support"
        ]
        assert (
            support["validation_scope"] == "bounded_profiles_only"
            and support["profiles"]
        )
        assert (
            not {"worker_directory", "timeout_seconds"}
            & catalog.instructions[operation]["parameters"].keys()
        )


def test_catalog_rejects_duplicate_ids(settings, tmp_path):
    data = json.loads(settings.catalog_path.read_text())
    data["problems"].append(data["problems"][0])
    path = tmp_path / "duplicate-catalog.json"
    path.write_text(json.dumps(data))
    with pytest.raises(CatalogError, match="unique IDs"):
        Catalog(replace(settings, catalog_path=path))


def test_expansion_holdout_covers_every_new_problem_and_domain(catalog, settings):
    document = json.loads(
        (
            settings.repository_root / "agent/evaluation/expansion_query_cases.json"
        ).read_text()
    )
    assert document["evaluation_only"]
    cases = document["cases"]
    assert len({c["id"] for c in cases}) == len(cases) == 66
    new_problems = {
        p["spec"]["problem_id"]
        for p in catalog.problems.values()
        if p["source"].split("/")[1][:2] > "20"
    }
    assert {c["expected"]["problem_id"] for c in cases} == new_problems
    assert {
        (c["domain_id"], c["expected"]["operation_id"])
        for c in cases
        if c["expected"]["supported"]
    } == {
        (domain, operation)
        for domain in catalog.domains
        for operation in EXPANSION_OPERATIONS
    }


@pytest.mark.parametrize("operation", sorted(EXPANSION_OPERATIONS))
def test_valid_profiles_pass_without_mutating_upload(catalog, operation):
    data = fixtures()[operation][0]
    original = copy.deepcopy(data)
    normalized = PlanValidator(catalog).validate(
        plan(catalog, operation), for_execution=True
    )
    prepared = prepare_operation_graph(data, normalized)
    assert prepared == original and data == original


@pytest.mark.parametrize("value", [-1, 1.5, True, "5", 1_000_000_001])
def test_invalid_capacity_cannot_be_coerced(catalog, value):
    data = fixtures()["max-flow-min-cut"][0]
    data["edges"][0]["attributes"]["cost"] = value
    with pytest.raises(ProfileInputError, match="integer capacity"):
        prepare_operation_graph(data, plan(catalog, "max-flow-min-cut"))


def test_capacity_mapping_and_missing_fields(catalog):
    data = fixtures()["max-flow-min-cut"][0]
    data["edges"][0]["weight"] = 999
    assert (
        prepare_operation_graph(data, plan(catalog, "max-flow-min-cut"))["edges"][0][
            "weight"
        ]
        == 5
    )
    assert data["edges"][0]["weight"] == 999
    del data["edges"][0]["attributes"]["cost"]
    with pytest.raises(ProfileInputError) as error:
        prepare_operation_graph(data, plan(catalog, "max-flow-min-cut"))
    assert error.value.status == "needs_information"


@pytest.mark.parametrize(
    "parameters",
    [
        {"source": True, "sink": 0},
        {"source": 0.5, "sink": 0},
        {"source": 0, "sink": 0},
        {"source": 2**63, "sink": 0},
        {"source": "0", "sink": 0, "unit_capacity": True},
        {"source": "0", "sink": 0, "worker_directory": "/tmp"},
    ],
)
def test_invalid_flow_plan_is_rejected(catalog, parameters):
    with pytest.raises(PlanValidationError):
        PlanValidator(catalog).validate(
            plan(catalog, "max-flow-min-cut", parameters=parameters), for_execution=True
        )


def test_profiles_reject_missing_terminals_sparse_assignment_bad_sides_and_large_closure(
    catalog,
):
    data = fixtures()["max-flow-min-cut"][0]
    with pytest.raises(ProfileInputError, match="not present"):
        prepare_operation_graph(
            data,
            plan(
                catalog, "max-flow-min-cut", parameters={"source": "missing", "sink": 0}
            ),
        )
    data = fixtures()["linear-assignment"][0]
    data["edges"].pop()
    with pytest.raises(ProfileInputError, match="every possible pair"):
        prepare_operation_graph(data, plan(catalog, "linear-assignment"))
    data = fixtures()["butterfly-counting"][0]
    data["vertices"][0]["attributes"]["side"] = []
    with pytest.raises(ProfileInputError) as error:
        prepare_operation_graph(data, plan(catalog, "butterfly-counting"))
    assert error.value.status == "needs_information"
    with pytest.raises(ProfileInputError, match="1,024"):
        prepare_operation_graph(
            graph(range(1025), [], True), plan(catalog, "transitive-closure")
        )


@pytest.mark.parametrize("operation", sorted(EXPANSION_OPERATIONS))
def test_projection_is_never_silently_applied(catalog, operation):
    with pytest.raises(PlanValidationError, match="directed projection"):
        PlanValidator(catalog).validate(
            plan(catalog, operation, allow_directed_projection=True)
        )


def test_new_capabilities_do_not_enable_weighted_centrality_or_weak_directed_paths(
    catalog,
):
    old = ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id="betweenness-centrality",
        problem_id="centrality_influential_node_mining",
        application_intent=ApplicationIntent(requires_edge_weights=True),
    )
    with pytest.raises(PlanValidationError, match="does not use"):
        PlanValidator(catalog).validate(old)
    weak = plan(
        catalog,
        "connected-components",
        parameters={"connectivity_mode": "weakly_connected"},
        application_intent={"requires_direction": True},
    )
    with pytest.raises(PlanValidationError, match="ignores direction"):
        PlanValidator(catalog).validate(weak)


def test_unsupported_problem_keeps_its_identity_and_blocker(catalog):
    decision = normalize_route(
        catalog,
        RouteDecision(
            problem_id="group_steiner_tree",
            supported=True,
            confidence=1,
            explanation="Find a minimum tree.",
        ),
    )
    assert not decision.supported and decision.operation_id is None
    assert decision.problem_id == "group_steiner_tree"
    assert "singleton" in route_blocker(catalog, decision)[1].lower()


def test_terminal_schema_accepts_typed_ids_and_no_arbitrary_paths(catalog):
    schema = PlanDraft.model_json_schema()
    constrain_plan_schema(
        schema, {"operation_context": catalog.operation_context("max-flow-min-cut")}
    )
    Draft202012Validator.check_schema(schema)
    parameters = schema["$defs"]["PlanConfiguration"]["properties"]["parameters"]
    check = Draft202012Validator(parameters)
    check.validate({"source": "0", "sink": 0})
    assert list(check.iter_errors({"source": True, "sink": 0}))
    assert list(check.iter_errors({"source": 1.2, "sink": 0}))
    assert list(check.iter_errors({"source": 0, "sink": 1, "worker_directory": "/tmp"}))


def test_command_preserves_typed_ids_and_maps_only_selected_weights(
    settings, catalog, graph_store, session, tmp_path
):
    data = fixtures()["max-flow-min-cut"][0]
    data["edges"][0]["weight"] = 999
    record = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="capacity.json",
        content=json.dumps(data).encode(),
        media_type="application/json",
    )
    runner = GraphMineRunner(
        replace(settings, graphmine_binary=tmp_path / "unbuilt"),
        catalog,
        graph_store,
        PlanValidator(catalog),
    )
    command = runner.build_command(
        plan(catalog, "max-flow-min-cut", session_id=session.id, graph_id=record.id),
        tmp_path / "job/result.json",
    )
    assert command[command.index("--source") + 1] == '"0"'
    assert command[command.index("--sink") + 1] == "0"
    assert (
        json.loads(Path(command[command.index("--graph") + 1]).read_text())["edges"][0][
            "weight"
        ]
        == 5
    )
    assert graph_store.read_graph(record.id, session.id)["edges"][0]["weight"] == 999
    assert runner._environment()["GRAPHMINE_WORKER_INHERIT_PROCESS_GROUP"] == "1"
    assert runner.capabilities.operation_count == 18


def test_expanded_routing_uses_base_model_and_keeps_legacy_prompt(settings, catalog):
    assert (
        hashlib.sha256(ROUTING_SYSTEM_PROMPT.encode()).hexdigest()
        == "689c94ceb762736604a20faf31dc13359b0e2da46da965db8b3ddcfc08470e32"
    )

    async def scenario():
        configured = replace(settings, llm_route_base_url="http://legacy.test")
        model = OpenAICompatibleModel(configured)
        await model._client.aclose()
        await model._route_client.aclose()
        calls = []

        def base(request):
            calls.append(request.url.path)
            if request.url.path == "/models":
                return httpx.Response(200, json={"data": []})
            payload = json.loads(request.content)
            prompt = payload["messages"][0]["content"]
            assert "nonnegative integer edge capacities" in prompt
            assert "No current native operation uses edge weights" not in prompt
            decision = {
                "problem_id": "connected_components",
                "operation_id": "connected-components",
                "supported": True,
                "confidence": 1,
                "explanation": "Connected groups.",
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(decision)}}]}
            )

        def legacy(request):
            pytest.fail(
                "Expanded routing must not call the legacy adapter, even its health endpoint"
            )

        model._client = httpx.AsyncClient(
            base_url="http://base.test", transport=httpx.MockTransport(base)
        )
        model._route_client = httpx.AsyncClient(
            base_url="http://legacy.test", transport=httpx.MockTransport(legacy)
        )
        assert await model.available()
        decision = await model.generate(
            mode=LLMMode.planner,
            schema=RouteDecision,
            user_payload={
                "message": "Connected groups",
                "routing_context": catalog.routing_context("general"),
            },
        )
        assert decision.operation_id == "connected-components" and len(calls) == 2
        assert configured.active_routing_model == configured.llm_model
        await model.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", sorted(EXPANSION_OPERATIONS))
def test_planning_preflight_for_new_profiles(settings, catalog, operation):
    data, parameters, intent, _, _ = fixtures()[operation]
    with TestClient(create_app(settings)) as client:
        session = client.post(
            "/api/sessions", headers=AUTH, json={"domain_id": "general"}
        ).json()["id"]
        file = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("graph.json", json.dumps(data), "application/json")},
            data={"role": "graph"},
        ).json()["id"]
        runtime = client.app.state.runtime
        original = runtime.agent.model.generate

        async def model(**kwargs):
            decision = await original(**kwargs)
            if kwargs["schema"] is RouteDecision:
                return decision.model_copy(
                    update={"intent": ApplicationIntent(**intent)}
                )
            return decision

        runtime.agent.model.generate = model
        response = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={"message": operation, "graph_id": file, "parameters": parameters},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ready", response.text
        assert response.json()["plan"]["operation_id"] == operation


@pytest.mark.skipif(
    not os.getenv("GRAPHMINE_EXPANSION_TEST_BINARY"),
    reason="Set GRAPHMINE_EXPANSION_TEST_BINARY to run native GPU integration",
)
@pytest.mark.parametrize("operation", sorted(EXPANSION_OPERATIONS))
def test_agent_runs_native_profile_and_builds_grounded_answer(
    settings, catalog, operation
):
    data, parameters, intent, metric, expected = fixtures()[operation]
    configured = replace(
        settings,
        graphmine_binary=Path(os.environ["GRAPHMINE_EXPANSION_TEST_BINARY"]),
        graph_gpu_uuid=None,
        job_timeout_seconds=60,
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
        file = upload.json()["id"]
        planned = client.post(
            f"/api/sessions/{session}/plan",
            headers=AUTH,
            json={"message": operation, "graph_id": file, "parameters": parameters},
        )
        assert planned.status_code == 200 and planned.json()["status"] == "ready", (
            planned.text
        )
        execution_plan = planned.json()["plan"]
        execution_plan["application_intent"] = intent
        submitted = client.post("/api/jobs", headers=AUTH, json=execution_plan)
        assert submitted.status_code == 202, submitted.text
        job = submitted.json()
        deadline = time.monotonic() + 60
        while (
            job["status"] not in {"completed", "failed", "cancelled"}
            and time.monotonic() < deadline
        ):
            time.sleep(0.03)
            job = client.get(f"/api/jobs/{job['id']}", headers=AUTH).json()
        assert job["status"] == "completed", job
        result = client.get(f"/api/results/{job['result_id']}", headers=AUTH).json()
        assert result["payload"]["output"][metric] == expected
        answer = build_answer(
            data,
            ExecutionPlan.model_validate(execution_plan),
            result["payload"],
            source_hash="fixture",
        )
        assert answer["metrics"][metric] == expected and answer["facts"]
        assert (
            not any(
                "does not use them as costs" in text for text in answer["limitations"]
            )
            if operation in {"linear-assignment", "max-flow-min-cut"}
            else True
        )
        if operation == "linear-assignment":
            assert (
                sum(row["Assignment cost"] for row in answer["tables"]["members"]) == 3
            )


@pytest.mark.skipif(
    not os.getenv("GRAPHMINE_EXPANSION_TEST_BINARY"),
    reason="Requires the compiled native worker launcher",
)
def test_job_process_group_contains_native_worker_for_cancellation(tmp_path):
    data = tmp_path / "input.json"
    data.write_text(json.dumps(fixtures()["connected-components"][0]))
    worker = tmp_path / "graphmine-worker-ecl-scc"
    pidfile = tmp_path / "worker.pid"
    worker.write_text(
        "#!/usr/bin/env python3\nimport os, signal\nfrom pathlib import Path\nPath("
        + repr(str(pidfile))
        + ").write_text(str(os.getpid()))\nsignal.pause()\n"
    )
    worker.chmod(0o700)
    process = subprocess.Popen(
        [
            os.environ["GRAPHMINE_EXPANSION_TEST_BINARY"],
            "run",
            "connected-components",
            "--graph",
            str(data),
            "--connectivity-mode",
            "strongly_connected",
            "--worker-directory",
            str(tmp_path),
            "--timeout-seconds",
            "30",
        ],
        env={**os.environ, "GRAPHMINE_WORKER_INHERIT_PROCESS_GROUP": "1"},
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pidfile.exists(), "Native worker never started"
        worker_pid = int(pidfile.read_text())
        assert os.getpgid(worker_pid) == process.pid
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        state = Path(f"/proc/{worker_pid}/stat")
        while (
            state.exists()
            and state.read_text().split()[2] != "Z"
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert not state.exists() or state.read_text().split()[2] == "Z", (
            "Cancelled job left its native worker running"
        )
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
