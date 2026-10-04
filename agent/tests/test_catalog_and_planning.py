from __future__ import annotations

import json
from pathlib import Path

import pytest
from graphmine_agent.catalog import Catalog
from graphmine_agent.models import ExecutionPlan, RouteDecision
from graphmine_agent.planning import (
    PlanValidationError,
    PlanValidator,
    bind_unique_required_auxiliary_inputs,
    normalize_route,
)


LEGACY_SCOPE = json.loads(
    (
        Path(__file__).resolve().parents[1] / "evaluation" / "legacy_catalog_scope.json"
    ).read_text()
)


def value_for(specification: dict) -> object:
    if "default" in specification:
        return specification["default"]
    if "choices" in specification:
        return specification["choices"][0]
    if specification["type"] == "integer":
        return max(0, specification.get("minimum", 0))
    if specification["type"] == "number":
        return max(0.0, specification.get("minimum", 0.0))
    if specification["type"] == "boolean":
        return False
    return "value"


def test_catalog_has_full_problem_operation_and_domain_context(
    catalog: Catalog,
) -> None:
    assert len(catalog.problems) == 37
    assert len(catalog.instructions) == 18
    assert len(catalog.domains) == 9
    assert catalog.domain("fraud_detection").name == "Fraud and financial crime"
    assert all(
        catalog.problem(operation.problem_id)["library_support"]["status"]
        == "validated"
        for operation in map(catalog.operation, catalog.instructions)
    )
    temporal_context = catalog.operation_context("temporal-motif-mining")
    assert "problem_inputs" not in temporal_context["problem_semantics"]
    assert set(temporal_context["program_instruction"]["parameters"]) == {
        "max_time_span",
        "result_limit",
    }


def test_query_corpus_separates_training_seeds_and_held_out_domain_cases(
    catalog: Catalog,
) -> None:
    path = (
        Path(__file__).resolve().parents[1] / "evaluation" / "domain_query_cases.json"
    )
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert len({item["id"] for item in cases}) == len(cases)
    for split in ("future_training_seed", "held_out_evaluation"):
        selected = [item for item in cases if item["split"] == split]
        assert {item["domain_id"] for item in selected} == set(catalog.domains)
        assert {item["expected"]["operation_id"] for item in selected} == set(
            LEGACY_SCOPE["operation_ids"]
        )
        for item in selected:
            operation = catalog.operation(item["expected"]["operation_id"])
            assert operation.problem_id == item["expected"]["problem_id"]


def test_v1_evaluation_matrix_covers_every_domain_operation_and_safety_route(
    catalog: Catalog,
) -> None:
    path = Path(__file__).resolve().parents[1] / "evaluation" / "v1_query_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    matrix = [item for item in cases if item["split"] == "v1_matrix_evaluation"]
    safety = [item for item in cases if item["split"] == "v1_routing_safety_evaluation"]
    assert (
        len(matrix) == len(catalog.domains) * len(LEGACY_SCOPE["operation_ids"]) == 117
    )
    assert {
        (item["domain_id"], item["expected"]["operation_id"]) for item in matrix
    } == {
        (domain_id, operation_id)
        for domain_id in catalog.domains
        for operation_id in LEGACY_SCOPE["operation_ids"]
    }
    unsupported = {
        problem_id
        for problem_id, problem in catalog.problems.items()
        if problem_id in LEGACY_SCOPE["problem_ids"]
        and problem["library_support"]["status"] != "validated"
    }
    assert unsupported <= {
        item["expected"]["problem_id"]
        for item in safety
        if item["expected"]["problem_id"] is not None
    }
    assert sum(item["expected"]["problem_id"] is None for item in safety) == 4


def test_every_operation_can_form_a_semantically_complete_plan(
    catalog: Catalog,
) -> None:
    validator = PlanValidator(catalog)
    for operation_id in catalog.instructions:
        operation = catalog.operation(operation_id)
        parameters = {
            name: (0 if name == "source" else 1)
            if spec["type"] == "vertex_id"
            else value_for(spec)
            for name, spec in operation.instruction["parameters"].items()
            if spec.get("required")
        }
        auxiliary = {
            name: [f"file-{name}"]
            for name, spec in operation.instruction["auxiliary_inputs"].items()
            if spec.get("required")
        }
        plan = ExecutionPlan(
            session_id="session",
            graph_id="graph",
            problem_id=operation.problem_id,
            operation_id=operation_id,
            parameters=parameters,
            auxiliary_inputs=auxiliary,
        )
        normalized = validator.validate(plan, for_execution=True)
        assert not normalized.missing_inputs


def test_auto_preserves_dynamic_motif_backend_semantics(catalog: Catalog) -> None:
    validator = PlanValidator(catalog)
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id="graph_motif_counting",
        operation_id="graph-motifs",
        backend_id="auto",
        parameters={"induced": True},
        auxiliary_inputs={"motifs": ["motif"]},
    )
    assert validator.validate(
        plan, compiled_backends={"graphminer"}, for_execution=True
    )


def test_backend_specific_knobs_require_that_backend(catalog: Catalog) -> None:
    validator = PlanValidator(catalog)
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id="triangle_counting_listing",
        operation_id="triangle-counting",
        backend_id="auto",
        parameters={"wetric_spread": 9},
    )
    with pytest.raises(PlanValidationError, match="only valid for backend wetric"):
        validator.validate(plan)


def test_missing_required_input_is_reported_before_execution(catalog: Catalog) -> None:
    validator = PlanValidator(catalog)
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id="temporal_motif_mining",
        operation_id="temporal-motif-mining",
    )
    planned = validator.validate(plan)
    assert planned.missing_inputs == ["max_time_span"]
    with pytest.raises(PlanValidationError, match="missing inputs"):
        validator.validate(plan, for_execution=True)


def test_unique_required_auxiliary_file_is_bound_without_overriding_user_choice(
    catalog: Catalog,
) -> None:
    operation = catalog.operation("subgraph-isomorphism")
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id=operation.problem_id,
        operation_id=operation.id,
    )
    files = [
        {"id": "graph", "role": "graph"},
        {"id": "query", "role": "query_graph"},
    ]
    inferred = bind_unique_required_auxiliary_inputs(plan, operation, files)
    assert inferred.auxiliary_inputs == {"query_graph": ["query"]}

    protected = bind_unique_required_auxiliary_inputs(
        plan, operation, files, protected_names={"query_graph"}
    )
    assert protected.auxiliary_inputs == {}

    ambiguous = bind_unique_required_auxiliary_inputs(
        plan,
        operation,
        files + [{"id": "query-2", "role": "query_graph"}],
    )
    assert ambiguous.auxiliary_inputs == {}


def test_unknown_parameter_cannot_become_a_command_argument(catalog: Catalog) -> None:
    validator = PlanValidator(catalog)
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
        parameters={"--output /tmp/stolen": "anything"},
    )
    with pytest.raises(PlanValidationError, match="unknown parameters"):
        validator.validate(plan)


def test_null_parameter_means_cli_flag_is_absent(catalog: Catalog) -> None:
    validator = PlanValidator(catalog)
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
        parameters={"minimum_clique_size": 1, "result_limit": None},
    )
    normalized = validator.validate(plan, for_execution=True)
    assert normalized.parameters == {"minimum_clique_size": 1}


def test_catalog_support_cannot_override_an_intent_refusal(
    catalog: Catalog,
) -> None:
    normalized = normalize_route(
        catalog,
        RouteDecision(
            problem_id="maximal_clique_enumeration",
            operation_id="maximal-cliques",
            supported=False,
            confidence=1,
            explanation="Selected the matching formal problem.",
        ),
    )
    assert normalized.supported is False
    assert normalized.operation_id is None
