from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .config import Settings
from .llm import LLMError, OpenAICompatibleModel, RuleBasedModel
from .models import ExecutionPlan, LLMMode, RouteDecision
from .planning import (
    PlanValidationError,
    PlanValidator,
    bind_unique_required_auxiliary_inputs,
    normalize_route,
)


async def evaluate_routing(
    settings: Settings,
    cases_path: Path,
    *,
    split: str = "held_out_evaluation",
    concurrency: int = 8,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    catalog = Catalog(settings)
    document = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = [
        item
        for item in document["cases"]
        if item["split"] == split and (case_ids is None or item["id"] in case_ids)
    ]
    model = (
        OpenAICompatibleModel(settings) if settings.llm_enabled else RuleBasedModel()
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            domain = catalog.domain(case["domain_id"])
            expected = case["expected"]
            started = time.monotonic()
            raw_decision: RouteDecision | None = None
            try:
                raw_decision = await model.generate(
                    mode=LLMMode.planner,
                    schema=RouteDecision,
                    user_payload={
                        "task": "Identify exactly one formal graph problem and runnable operation, or report ambiguity/unsupported intent.",
                        "message": case["user_query"],
                        "graph_metadata": {
                            "directed": None,
                            "vertex_count": None,
                            "edge_count": None,
                            "has_weights": None,
                            "has_timestamps": None,
                        },
                        "routing_context": catalog.routing_context(domain.id),
                    },
                )
                decision = normalize_route(catalog, raw_decision)
                passed = (
                    decision.problem_id == expected["problem_id"]
                    and decision.operation_id == expected["operation_id"]
                    and decision.supported == expected["supported"]
                )
                observed = decision.model_dump(mode="json")
                error_message = None
            except (LLMError, PlanValidationError) as error:
                passed = False
                observed = None
                error_message = str(error)
            return {
                "id": case["id"],
                "domain_id": domain.id,
                "passed": passed,
                "expected": {
                    key: expected[key]
                    for key in ("problem_id", "operation_id", "supported")
                },
                "observed": observed,
                "raw_observed": (
                    raw_decision.model_dump(mode="json")
                    if raw_decision is not None
                    else None
                ),
                "latency_seconds": round(time.monotonic() - started, 3),
                "error": error_message,
            }

    try:
        details = list(await asyncio.gather(*(evaluate_case(case) for case in cases)))
    finally:
        await model.close()
    passed_count = sum(item["passed"] for item in details)
    by_domain: dict[str, dict[str, int]] = {}
    for item in details:
        group = by_domain.setdefault(item["domain_id"], {"passed": 0, "total": 0})
        group["total"] += 1
        group["passed"] += int(item["passed"])
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "model": settings.llm_model if settings.llm_enabled else "rule-based-fallback",
        "routing_configuration": {
            "reasoning_effort": settings.llm_route_reasoning_effort,
            "max_completion_tokens": settings.llm_route_max_tokens,
            "temperature": 0.0,
            "seed": 0,
            "concurrency": max(1, concurrency),
        },
        "split": split,
        "passed": passed_count,
        "total": len(details),
        "accuracy": 0.0 if not details else passed_count / len(details),
        "by_domain": by_domain,
        "cases": details,
    }


def run_evaluation(
    settings: Settings,
    cases_path: Path,
    *,
    split: str,
    concurrency: int = 8,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        evaluate_routing(
            settings,
            cases_path,
            split=split,
            concurrency=concurrency,
            case_ids=case_ids,
        )
    )


def _synthetic_graph_metadata(operation_id: str) -> dict[str, Any]:
    temporal = operation_id == "temporal-motif-mining"
    return {
        "graph_id": "file_graph",
        "name": "evaluation-graph",
        "directed": temporal,
        "allows_self_loops": False,
        "allows_parallel_edges": temporal,
        "vertex_count": 100,
        "edge_count": 300,
        "density": 0.03 if temporal else 0.06,
        "minimum_degree": 0,
        "maximum_degree": 12,
        "average_degree": 6.0,
        "isolated_vertex_count": 1,
        "has_weights": False,
        "has_timestamps": temporal,
    }


async def evaluate_planning(
    settings: Settings,
    cases_path: Path,
    *,
    split: str = "held_out_evaluation",
    concurrency: int = 2,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Evaluate operation-specific plans without spending a second call on routing."""

    catalog = Catalog(settings)
    validator = PlanValidator(catalog)
    document = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = [
        item
        for item in document["cases"]
        if item["split"] == split and (case_ids is None or item["id"] in case_ids)
    ]
    model = (
        OpenAICompatibleModel(settings) if settings.llm_enabled else RuleBasedModel()
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            expected = case["expected"]
            operation = catalog.operation(expected["operation_id"])
            metadata = _synthetic_graph_metadata(operation.id)
            available_files: list[dict[str, Any]] = [
                {
                    "id": "file_graph",
                    "role": "graph",
                    "name": "evaluation-graph.json",
                    "metadata": metadata,
                }
            ]
            role_to_ids: dict[str, list[str]] = {}
            for index, role in enumerate(expected.get("auxiliary_roles", []), 1):
                file_id = f"file_{role}_{index}"
                role_to_ids.setdefault(role, []).append(file_id)
                available_files.append(
                    {
                        "id": file_id,
                        "role": role,
                        "name": f"attached-{role}-{index}.json",
                        "metadata": (
                            metadata
                            if role in {"motif", "query_graph"}
                            else {"item_count": 10}
                        ),
                    }
                )
            payload = {
                "task": "Produce a complete GraphMine ExecutionPlan. Preserve user-supplied values. Use missing_inputs rather than inventing required values.",
                "message": case["user_query"],
                "session_id": "session_evaluation",
                "graph_id": "file_graph",
                "domain": catalog.domain(case["domain_id"]).model_dump(mode="json"),
                "graph_metadata": metadata,
                "selected_operation": {
                    "problem_id": expected["problem_id"],
                    "operation_id": operation.id,
                },
                "operation_context": catalog.operation_context(operation.id),
                "available_files": available_files,
                "requested_backend": None,
                "supplied_parameters": {},
                "requested_optional_outputs": [],
                "supplied_auxiliary_inputs": {},
                "allow_directed_projection": False,
            }
            started = time.monotonic()
            raw_plan: ExecutionPlan | None = None
            try:
                raw_plan = await model.generate(
                    mode=LLMMode.planner,
                    schema=ExecutionPlan,
                    user_payload=payload,
                )
                candidate = raw_plan.model_copy(
                    update={
                        "session_id": "session_evaluation",
                        "graph_id": "file_graph",
                        "problem_id": expected["problem_id"],
                        "operation_id": operation.id,
                        "allow_directed_projection": False,
                    }
                )
                candidate = bind_unique_required_auxiliary_inputs(
                    candidate, operation, available_files
                )
                normalized = validator.validate(candidate, for_execution=False)
                expected_parameters = expected.get("parameters", {})
                parameters_match = all(
                    normalized.parameters.get(name) == value
                    for name, value in expected_parameters.items()
                )
                unexpected_parameters = {
                    name: value
                    for name, value in normalized.parameters.items()
                    if name not in expected_parameters
                    and operation.instruction["parameters"][name].get("default")
                    != value
                }
                outputs_match = set(normalized.optional_outputs) == set(
                    expected.get("optional_outputs", [])
                )
                selected_roles = {
                    specification["role"]
                    for name, specification in operation.instruction[
                        "auxiliary_inputs"
                    ].items()
                    if normalized.auxiliary_inputs.get(name)
                }
                auxiliary_match = selected_roles == set(
                    expected.get("auxiliary_roles", [])
                )
                selected_files_exist = all(
                    file_id
                    in {
                        candidate
                        for values in role_to_ids.values()
                        for candidate in values
                    }
                    for values in normalized.auxiliary_inputs.values()
                    for file_id in values
                )
                checks = {
                    "parameters": parameters_match and not unexpected_parameters,
                    "optional_outputs": outputs_match,
                    "auxiliary_roles": auxiliary_match and selected_files_exist,
                    "no_missing_inputs": not normalized.missing_inputs,
                    "backend_allowed": normalized.backend_id
                    in operation.allowed_backends,
                }
                passed = all(checks.values())
                observed = normalized.model_dump(mode="json")
                error_message = None
            except (LLMError, PlanValidationError, KeyError) as error:
                passed = False
                checks = {}
                unexpected_parameters = {}
                observed = None
                error_message = str(error)
            return {
                "id": case["id"],
                "domain_id": case["domain_id"],
                "passed": passed,
                "expected": {
                    "problem_id": expected["problem_id"],
                    "operation_id": expected["operation_id"],
                    "parameters": expected.get("parameters", {}),
                    "optional_outputs": expected.get("optional_outputs", []),
                    "auxiliary_roles": expected.get("auxiliary_roles", []),
                },
                "checks": checks,
                "unexpected_parameters": unexpected_parameters,
                "observed": observed,
                "raw_observed": (
                    raw_plan.model_dump(mode="json") if raw_plan is not None else None
                ),
                "latency_seconds": round(time.monotonic() - started, 3),
                "error": error_message,
            }

    try:
        details = list(await asyncio.gather(*(evaluate_case(case) for case in cases)))
    finally:
        await model.close()
    passed_count = sum(item["passed"] for item in details)
    by_domain: dict[str, dict[str, int]] = {}
    for item in details:
        group = by_domain.setdefault(item["domain_id"], {"passed": 0, "total": 0})
        group["total"] += 1
        group["passed"] += int(item["passed"])
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "model": settings.llm_model if settings.llm_enabled else "rule-based-fallback",
        "planning_configuration": {
            "reasoning_effort": settings.llm_plan_reasoning_effort,
            "max_completion_tokens": settings.llm_plan_max_tokens,
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 20,
            "seed": 0,
            "concurrency": max(1, concurrency),
        },
        "split": split,
        "passed": passed_count,
        "total": len(details),
        "accuracy": 0.0 if not details else passed_count / len(details),
        "by_domain": by_domain,
        "cases": details,
    }


def run_planning_evaluation(
    settings: Settings,
    cases_path: Path,
    *,
    split: str,
    concurrency: int,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        evaluate_planning(
            settings,
            cases_path,
            split=split,
            concurrency=concurrency,
            case_ids=case_ids,
        )
    )
