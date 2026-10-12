import copy
import json

import pytest
from graphmine_agent.learning.dual_review import verified_target
from graphmine_agent.learning.dual_teacher import check_target, teacher_transport_schema
from graphmine_agent.models import (
    ApplicationIntent,
    PlanConfiguration,
    PlanDraft,
    RouteDecision,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def plan_job(catalog, operation="k-cliques"):
    return {
        "reference_contract": {
            "operation_id": operation,
            "problem_id": catalog.operation(operation).problem_id,
            "question": "List all fully connected groups of exactly three records.",
            "expected_status": "ready",
            "parameters": {"k": 3} if operation == "k-cliques" else {},
            "optional_outputs": ["cliques"] if operation == "k-cliques" else [],
            "intent": ApplicationIntent().model_dump(mode="json"),
        },
        "user_payload": {
            "verified_projection": {"selected_vertices": 4},
            "inferred_auxiliary_inputs": {},
            "available_files": [],
        },
    }


def draft(**parameters):
    return PlanDraft(
        status="ready",
        message="List the requested groups.",
        plan=PlanConfiguration(
            parameters={"k": 3, **parameters}, optional_outputs=["cliques"]
        ),
    )


def test_semantic_plan_checks_accept_nontruncating_limit_but_reject_changed_task(
    settings, catalog, tmp_path
):
    job = plan_job(catalog)
    check_target(settings, tmp_path, job, draft(result_limit=4))
    with pytest.raises(ValueError, match="result_limit"):
        check_target(settings, tmp_path, job, draft(result_limit=3))
    with pytest.raises(ValueError, match="Requested parameter changed: k"):
        check_target(settings, tmp_path, job, draft(k=4))


def test_required_unique_attachment_uses_production_binding(
    settings, catalog, tmp_path
):
    job = plan_job(catalog, "subgraph-isomorphism")
    job["user_payload"]["available_files"] = [{"id": "query-1", "role": "query_graph"}]
    target = PlanDraft(
        status="ready", message="Match this pattern.", plan=PlanConfiguration()
    )
    check_target(settings, tmp_path, job, target)
    target.plan.auxiliary_inputs = {"query_graph": ["query-1"]}
    check_target(settings, tmp_path, job, target)
    target.plan.auxiliary_inputs = {"query_graph": ["query-2"]}
    with pytest.raises(ValueError, match="Attached inputs changed"):
        check_target(settings, tmp_path, job, target)


def test_recognized_operation_may_still_request_required_clarification(
    settings, catalog, tmp_path
):
    job = plan_job(catalog)
    job["reference_contract"].update(
        expected_status="needs_information", problem_id=None, operation_id=None
    )
    target = RouteDecision(
        problem_id=catalog.operation("k-cliques").problem_id,
        operation_id="k-cliques",
        supported=True,
        confidence=0.6,
        explanation="The required group size is unspecified.",
        ambiguity=["How many records must each fully connected group contain?"],
    )
    check_target(settings, tmp_path, job, target)
    target.ambiguity = []
    with pytest.raises(ValueError, match="concrete clarification"):
        check_target(settings, tmp_path, job, target)


def test_exact_three_clique_triangle_equivalence_does_not_extend_to_other_objectives(
    settings, catalog, tmp_path
):
    job = plan_job(catalog)
    target = RouteDecision(
        problem_id=catalog.operation("triangle-counting").problem_id,
        operation_id="triangle-counting",
        supported=True,
        confidence=1,
        explanation="Every requested fully connected triple is a triangle.",
    )
    check_target(settings, tmp_path, job, target)
    job["reference_contract"]["parameters"]["k"] = 4
    with pytest.raises(ValueError, match="Formal operation differs"):
        check_target(settings, tmp_path, job, target)
    job["reference_contract"]["parameters"]["k"] = 3
    target.operation_id = "maximal-cliques"
    target.problem_id = catalog.operation("maximal-cliques").problem_id
    with pytest.raises(ValueError, match="Formal operation differs"):
        check_target(settings, tmp_path, job, target)


def test_teacher_transport_relaxes_only_unsafe_bounds_and_original_schema_still_rejects():
    original = {
        "type": "object",
        "properties": {
            "vertex": {"type": "integer", "minimum": -(2**63), "maximum": 2**63 - 1},
            "count": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    }
    before = copy.deepcopy(original)
    transported = teacher_transport_schema(original)
    assert original == before
    assert transported["properties"]["vertex"] == {"type": "integer"}
    assert transported["properties"]["count"] == original["properties"]["count"]
    excessive = {"vertex": 2**63, "count": 2}
    Draft202012Validator(transported).validate(excessive)
    with pytest.raises(ValidationError):
        Draft202012Validator(original).validate(excessive)


def test_target_export_replays_raw_response_instead_of_trusting_saved_acceptance(
    settings, tmp_path
):
    payload = RouteDecision(
        supported=False,
        confidence=1,
        explanation="Clarify.",
        ambiguity=["Which objective?"],
    ).model_dump(mode="json")
    events = [
        {"type": "thread.started"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(payload)},
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 100, "output_tokens": 100},
        },
    ]
    artifact = {
        "status": "accepted",
        "input_sha256": "bound",
        "profile": {
            "provider": "codex",
            "reasoning_effort": "max",
            "max_output_tokens": 1000,
        },
        "codex_cli": {"reasoning_effort": "max", "exit_code": 0},
        "raw_response": "\n".join(json.dumps(event) for event in events),
        "target": copy.deepcopy(payload),
    }
    job = {
        "sha256": "bound",
        "schema": "RouteDecision",
        "output_schema": RouteDecision.model_json_schema(),
        "reference_contract": {
            "expected_status": "needs_information",
            "problem_id": None,
        },
    }
    assert verified_target(settings, tmp_path, job, artifact).ambiguity
    artifact["target"]["explanation"] = "Rewritten after generation."
    with pytest.raises(ValueError, match="differs from the actual teacher response"):
        verified_target(settings, tmp_path, job, artifact)
