from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.benchmarking import (
    BenchmarkError,
    evaluate_backend_policy,
    train_backend_policy,
)
from graphmine_agent.catalog import Catalog
from graphmine_agent.database import Database
from graphmine_agent.execution import ExecutionError, GraphMineRunner
from graphmine_agent.graph_store import GraphStore
from graphmine_agent.models import ExecutionPlan, FileRole, SessionRecord
from graphmine_agent.planning import PlanValidationError, PlanValidator
from graphmine_agent.selector import BackendSelector, feature_bucket


def test_feature_bucket_is_stable() -> None:
    assert (
        feature_bucket(
            {
                "vertex_count": 500,
                "density": 0.2,
                "directed": False,
                "has_timestamps": False,
            }
        )
        == "tiny:dense:undirected:static"
    )


def test_correctness_exclusion_overrides_rankings_and_fails_closed(settings, tmp_path):
    catalog = Catalog(settings)
    # Even without a benchmark policy, auto must not fall back to CUDA-MS.
    selector = BackendSelector(
        tmp_path / "absent.json", catalog, PlanValidator(catalog)
    )
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id="maximum_clique",
        operation_id="maximum-clique",
    )
    selected = selector.select(
        plan, None, {"cuda-ms", "gpu-maximum-clique", "maximum-clique-on-gpu"}
    )
    assert selected.backend_id == "gpu-maximum-clique"
    with pytest.raises(PlanValidationError, match="correctness-approved"):
        selector.select(plan, None, {"cuda-ms"})
    with pytest.raises(PlanValidationError, match="cannot reliably certify"):
        selector.select(
            plan.model_copy(update={"backend_id": "cuda-ms"}), None, {"cuda-ms"}
        )
    selector.policy = {
        "operations": {
            "maximum-clique": {
                "global_ranked_backends": ["cuda-ms", "gpu-maximum-clique"]
            }
        }
    }
    assert "cuda-ms" not in selector.ranked_backends("maximum-clique", None)
    assert (
        selector.select(plan, None, {"cuda-ms", "gpu-maximum-clique"}).backend_id
        == "gpu-maximum-clique"
    )


def test_benchmark_policy_resolves_auto_to_valid_compiled_backend(
    settings, triangle_graph: bytes, tmp_path: Path
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "operations": {
                    "maximal-cliques": {
                        "global_ranked_backends": ["rdmce"],
                        "buckets": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    configured = replace(settings, backend_policy_path=policy_path)
    database = Database(configured.database_path)
    session = database.create_session(SessionRecord(domain_id="general"))
    store = GraphStore(configured, database)
    graph = store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="triangle.json",
        content=triangle_graph,
        media_type="application/json",
        directed=False,
    )
    catalog = Catalog(configured)
    validator = PlanValidator(catalog)
    runner = GraphMineRunner(configured, catalog, store, validator)
    runner.probe()
    command = runner.build_command(
        ExecutionPlan(
            session_id=session.id,
            graph_id=graph.id,
            problem_id="maximal_clique_enumeration",
            operation_id="maximal-cliques",
            backend_id="auto",
        ),
        tmp_path / "result.json",
    )
    assert command[command.index("--backend") + 1] == "rdmce"
    assert runner.selector.loaded


def test_invalid_policy_is_reported_and_does_not_override_auto(
    settings, tmp_path: Path
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "operations": {
                    "maximal-cliques": {
                        "global_ranked_backends": ["not-a-backend"],
                        "buckets": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    configured = replace(settings, backend_policy_path=policy_path)
    catalog = Catalog(configured)
    selector = BackendSelector(policy_path, catalog, PlanValidator(catalog))
    assert not selector.loaded
    assert "unknown backends" in (selector.error or "")


def test_malformed_or_unknown_policy_operation_falls_back_safely(
    settings, tmp_path: Path
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "operations": {
                    "not-an-operation": {
                        "global_ranked_backends": [],
                        "buckets": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    catalog = Catalog(settings)
    selector = BackendSelector(policy_path, catalog, PlanValidator(catalog))
    assert not selector.loaded
    assert "unknown operation" in (selector.error or "")


def test_incompatible_native_version_is_rejected(
    settings, fake_binary: Path, tmp_path: Path
) -> None:
    incompatible = tmp_path / "graphmine-old"
    incompatible.write_text(
        fake_binary.read_text(encoding="utf-8").replace(
            '"library_version": "1.0.0"', '"library_version": "0.9.0"'
        ),
        encoding="utf-8",
    )
    incompatible.chmod(fake_binary.stat().st_mode)
    configured = replace(settings, graphmine_binary=incompatible)
    database = Database(configured.database_path)
    catalog = Catalog(configured)
    runner = GraphMineRunner(
        configured,
        catalog,
        GraphStore(configured, database),
        PlanValidator(catalog),
    )
    report = runner.probe()
    assert report.binary_available
    assert report.library_version == "0.9.0"
    assert report.error == (
        "GraphMine binary version 0.9.0 does not match agent version 1.0.0"
    )
    with pytest.raises(ExecutionError, match="does not match") as captured:
        runner.require_ready()
    assert captured.value.code == "binary_incompatible"


def test_train_and_evaluate_backend_policy() -> None:
    records = []
    for backend, durations in {"tot": [12.0, 10.0], "wetric": [20.0, 18.0]}.items():
        for repetition, wall_ms in enumerate(durations):
            records.append(
                {
                    "case_id": "triangle",
                    "operation_id": "triangle-counting",
                    "backend_id": backend,
                    "repetition": repetition,
                    "feature_bucket": "tiny:dense:undirected:static",
                    "status": "success",
                    "correct": True,
                    "wall_ms": wall_ms,
                }
            )
    report = {"schema_version": "1.0.0", "records": records}
    policy = train_backend_policy(report)
    operation = policy["operations"]["triangle-counting"]
    assert operation["global_ranked_backends"] == ["tot", "wetric"]
    evaluation = evaluate_backend_policy(report, policy)
    assert evaluation["evaluated_cases"] == 1
    assert evaluation["oracle_matches"] == 1
    assert evaluation["median_regret_ratio"] == 1.0


def test_policy_training_rejects_any_incorrect_timing_record() -> None:
    report = {
        "schema_version": "1.0.0",
        "records": [
            {
                "case_id": "triangle",
                "operation_id": "triangle-counting",
                "backend_id": "tot",
                "feature_bucket": "tiny:dense:undirected:static",
                "status": "success",
                "correct": True,
                "wall_ms": 10.0,
            },
            {
                "case_id": "triangle",
                "operation_id": "triangle-counting",
                "backend_id": "wetric",
                "feature_bucket": "tiny:dense:undirected:static",
                "status": "failed",
                "correct": False,
                "wall_ms": 12.0,
            },
        ],
    }
    with pytest.raises(BenchmarkError, match="every timing record"):
        train_backend_policy(report)
