from __future__ import annotations

import math
from typing import Any

from .catalog import Catalog, OperationContract
from .models import ApplicationIntent, ExecutionPlan, RouteDecision

APPLICATION_PREPROCESSING = {
    "attribute_filters": {
        "stage": "before the native operation",
        "targets": ["vertices", "edges"],
        "operators": ["eq", "ne", "gt", "gte", "lt", "lte", "in"],
        "fields": "Any field listed in graph_context; original attributes are retained.",
        "requires_kernel_weight_support": False,
    },
    "empty_selection": "A valid result, not missing information; complete the requested analysis with the selected scope.",
    "weighted_computation": "Only max-flow-min-cut (nonnegative integer edge capacities) and linear-assignment (integer costs 0..999 in a complete square bipartite graph) use numeric weights. Select the exact field with weight_attribute and weight_usage=other. Weighted path lengths, centrality and grouping remain unsupported.",
}


def route_request_payload(
    *,
    message,
    graph_context,
    graph_metadata,
    routing_context,
    active_constraints=None,
    pending_request=None,
):
    """The same input contract for production routing and local SFT exports."""
    return {
        "task": "Understand the application question using the data's domain meaning. Describe its intent and requirements, then choose a supported primary analysis and any necessary independent supporting analyses. Ask a concrete domain-language clarification or report unsupported intent if needed.",
        "message": message,
        "graph_context": graph_context,
        "active_constraints": active_constraints,
        "pending_request": pending_request,
        "graph_metadata": graph_metadata,
        "routing_context": routing_context,
        "application_preprocessing": APPLICATION_PREPROCESSING,
    }


def resolve_route_scope(catalog, decision, previous_intent=None):
    decision = normalize_route(catalog, decision)
    if previous_intent and decision.intent.filter_mode == "inherit":
        merged = {
            (item.target, item.field, item.operator): item
            for item in previous_intent.filters
        }
        merged.update(
            {
                (item.target, item.field, item.operator): item
                for item in decision.intent.filters
            }
        )
        return decision.model_copy(
            update={
                "intent": decision.intent.model_copy(
                    update={"filters": list(merged.values())}
                )
            }
        )
    if decision.intent.filter_mode == "clear":
        return decision.model_copy(
            update={"intent": decision.intent.model_copy(update={"filters": []})}
        )
    return decision


class PlanValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def application_capability_errors(
    intent: ApplicationIntent | None,
    operation_id: str | None,
    *,
    require_complete_pattern: bool = False,
) -> list[str]:
    """Server-owned semantic limitations, independent of missing input data.

    Routing only rejects explicitly known requirements. Final plan validation
    also requires a complete supported event pattern before anything can run.
    """
    if intent is None:
        return []
    errors = []
    weighted = (
        intent.requires_edge_weights or intent.weight_attribute or intent.weight_usage
    )
    if weighted and operation_id not in {"max-flow-min-cut", "linear-assignment"}:
        errors.append(
            "This question needs connection costs or strengths to affect the calculation, "
            "but this analysis does not use those values. Adding cost data would "
            "not enable that calculation. I have not run an unweighted substitute."
        )
    if (
        weighted
        and operation_id in {"max-flow-min-cut", "linear-assignment"}
        and intent.weight_usage in {"path_length", "strength"}
    ):
        errors.append(
            "This operation accepts capacities or assignment costs, not weighted path lengths or relationship strengths."
        )
    if (
        intent.requires_direction
        and operation_id
        and operation_id
        not in {
            "temporal-motif-mining",
            "connected-components",
            "max-flow-min-cut",
            "transitive-closure",
        }
    ):
        errors.append(
            "This calculation cannot preserve which way each relationship points. "
            "I have not treated directed connections as two-way."
        )
    if operation_id == "temporal-motif-mining":
        edges = intent.pattern_edges
        ids = list(dict.fromkeys(value for edge in edges for value in edge))
        normalized = [[ids.index(value) for value in edge] for edge in edges]
        if (
            (
                intent.pattern_vertex_count is not None
                and intent.pattern_vertex_count != 3
            )
            or (edges and normalized != [[0, 1], [1, 2], [0, 2]])
            or (
                require_complete_pattern
                and (intent.pattern_vertex_count is None or not edges)
            )
        ):
            errors.append(
                "Only the ordered three-entity pattern A→B, B→C, A→C is supported; "
                "the requested pattern cannot be substituted."
            )
    return errors


def route_blocker(catalog: Catalog, decision: RouteDecision) -> tuple[str, str] | None:
    """Capability limitations outrank input requests that cannot resolve them."""
    operation_id = decision.operation_id
    unavailable = False
    if decision.problem_id:
        support = catalog.problem(decision.problem_id)["library_support"]
        unavailable = support["status"] != "validated"
        if operation_id is None and len(support.get("operation_ids", [])) == 1:
            operation_id = support["operation_ids"][0]
    errors = application_capability_errors(decision.intent, operation_id)
    if errors:
        return "unsupported", " ".join(errors)
    if unavailable:
        return (
            "unsupported",
            "This analysis is not available in the current system. Providing more inputs would not enable it. "
            + support["reason"],
        )
    if (
        not decision.supported
        or not decision.problem_id
        or not decision.operation_id
        or decision.ambiguity
        or decision.missing_information
    ):
        if decision.ambiguity:
            message = " ".join(decision.ambiguity)
        elif decision.missing_information:
            message = "I need one more detail: " + "; ".join(
                decision.missing_information
            )
        else:
            message = decision.explanation
        return (
            "needs_information"
            if decision.ambiguity or decision.missing_information
            else "unsupported",
            message,
        )
    return None


def normalize_route(catalog: Catalog, decision: RouteDecision) -> RouteDecision:
    """Validate model-selected identity and derive support from the catalog."""

    if not decision.problem_id:
        return decision.model_copy(update={"supported": False, "operation_id": None})
    try:
        problem = catalog.problem(decision.problem_id)
    except Exception as error:
        if not decision.supported:
            return decision.model_copy(
                update={"problem_id": None, "operation_id": None}
            )
        raise PlanValidationError([str(error)]) from error
    # Catalog availability is necessary, not sufficient. Never turn a model's
    # explicit refusal into permission to execute a superficially similar task.
    expected_support = (
        decision.supported and problem["library_support"]["status"] == "validated"
    )
    if decision.operation_id:
        try:
            operation = catalog.operation(decision.operation_id)
        except Exception as error:
            raise PlanValidationError([str(error)]) from error
        if operation.problem_id != decision.problem_id:
            raise PlanValidationError(
                ["route operation does not belong to selected problem"]
            )
    return decision.model_copy(
        update={
            "supported": expected_support,
            "operation_id": decision.operation_id if expected_support else None,
        }
    )


def _value_matches(value: Any, specification: dict[str, Any]) -> bool:
    kind = specification["type"]
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if kind == "string":
        return isinstance(value, str)
    if kind == "vertex_id":
        return (isinstance(value, str) and bool(value)) or (
            isinstance(value, int)
            and not isinstance(value, bool)
            and -(2**63) <= value < 2**63
        )
    return False


class PlanValidator:
    """Normalizes LLM/user plans against the allowlisted program contract."""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def validate(
        self,
        plan: ExecutionPlan,
        *,
        compiled_backends: set[str] | None = None,
        for_execution: bool = False,
    ) -> ExecutionPlan:
        errors: list[str] = []
        errors.extend(
            application_capability_errors(
                plan.application_intent,
                plan.operation_id,
                require_complete_pattern=True,
            )
        )
        try:
            operation = self.catalog.operation(plan.operation_id)
        except Exception as error:
            raise PlanValidationError([str(error)]) from error

        if plan.problem_id != operation.problem_id:
            errors.append(
                f"operation {operation.id} belongs to {operation.problem_id}, "
                f"not {plan.problem_id}"
            )
        support = self.catalog.problem(plan.problem_id)["library_support"]
        if support["status"] != "validated":
            errors.append(f"problem {plan.problem_id} has no validated backend")
        if operation.id not in support["operation_ids"]:
            errors.append(
                f"operation {operation.id} is not registered for {plan.problem_id}"
            )

        if plan.backend_id not in operation.allowed_backends:
            errors.append(
                f"backend {plan.backend_id!r} is not allowed for {operation.id}; "
                f"choose one of {', '.join(operation.allowed_backends)}"
            )
        explicit_backend = plan.backend_id != "auto"
        effective_backend = plan.backend_id if explicit_backend else None
        if compiled_backends is not None:
            if explicit_backend and effective_backend not in compiled_backends:
                errors.append(
                    f"backend {effective_backend} is not compiled on this server"
                )
            elif not explicit_backend and not set(operation.backends).intersection(
                compiled_backends
            ):
                errors.append(
                    f"no compiled backend is available for operation {operation.id}"
                )

        parameter_specs = operation.instruction["parameters"]
        unknown_parameters = set(plan.parameters) - set(parameter_specs)
        if unknown_parameters:
            errors.append(
                f"unknown parameters for {operation.id}: {sorted(unknown_parameters)}"
            )

        normalized_parameters = dict(plan.parameters)
        # JSON naturally represents an unset optional value as null, while the
        # CLI represents it by omitting the corresponding flag. Normalize that
        # boundary before type checks; a required null remains a missing input.
        for name in parameter_specs:
            if normalized_parameters.get(name) is None:
                normalized_parameters.pop(name, None)
        missing_inputs: list[str] = []
        for name, specification in parameter_specs.items():
            if name not in normalized_parameters:
                if specification.get("required"):
                    missing_inputs.append(name)
                elif "default" in specification and (
                    not specification.get("backend")
                    or plan.backend_id == specification["backend"]
                ):
                    normalized_parameters[name] = specification["default"]
                continue
            value = normalized_parameters[name]
            if not _value_matches(value, specification):
                errors.append(f"parameter {name} must be {specification['type']}")
                continue
            if "minimum" in specification and value < specification["minimum"]:
                errors.append(
                    f"parameter {name} must be at least {specification['minimum']}"
                )
            if "maximum" in specification and value > specification["maximum"]:
                errors.append(
                    f"parameter {name} must be at most {specification['maximum']}"
                )
            if "choices" in specification and value not in specification["choices"]:
                errors.append(
                    f"parameter {name} must be one of {specification['choices']}"
                )
            required_output = specification.get("requires_output")
            if required_output and required_output not in plan.optional_outputs:
                errors.append(f"parameter {name} requires output {required_output}")
            required_outputs = specification.get("requires_any_output")
            if required_outputs and not set(required_outputs).intersection(
                plan.optional_outputs
            ):
                errors.append(
                    f"parameter {name} requires one of outputs {required_outputs}"
                )
            backend = specification.get("backend")
            if name in plan.parameters and backend and plan.backend_id != backend:
                errors.append(f"parameter {name} is only valid for backend {backend}")

        output_specs = operation.instruction["optional_outputs"]
        unknown_outputs = set(plan.optional_outputs) - set(output_specs)
        if unknown_outputs:
            errors.append(
                f"unknown optional outputs for {operation.id}: {sorted(unknown_outputs)}"
            )
        for output_name, constraint in operation.instruction.get(
            "output_constraints", {}
        ).items():
            if output_name in plan.optional_outputs:
                required_parameter = constraint.get("requires_parameter")
                if (
                    required_parameter
                    and required_parameter not in normalized_parameters
                ):
                    errors.append(
                        f"output {output_name} requires parameter {required_parameter}"
                    )

        auxiliary_specs = operation.instruction["auxiliary_inputs"]
        unknown_auxiliary = set(plan.auxiliary_inputs) - set(auxiliary_specs)
        if unknown_auxiliary:
            errors.append(
                f"unknown auxiliary inputs for {operation.id}: {sorted(unknown_auxiliary)}"
            )
        for name, specification in auxiliary_specs.items():
            values = plan.auxiliary_inputs.get(name, [])
            if (
                specification.get("required")
                and not values
                and name not in missing_inputs
            ):
                missing_inputs.append(name)
            if not specification.get("multiple") and len(values) > 1:
                errors.append(f"auxiliary input {name} accepts exactly one file")

        # The native CLI owns the operation-specific `auto` choice.  Applying the
        # correctness constraints of one nominal default here would reject valid
        # plans (for example, induced graph motifs select a different backend).
        # Explicit choices remain fully constrained.
        constraint = (
            operation.instruction.get("backend_constraints", {}).get(
                effective_backend, {}
            )
            if explicit_backend
            else {}
        )
        for name in constraint.get("forbids_true", []):
            if normalized_parameters.get(name) is True:
                errors.append(
                    f"backend {effective_backend} does not support {name}=true"
                )
        for name, maximum in constraint.get("parameter_maximum", {}).items():
            if normalized_parameters.get(name, -math.inf) > maximum:
                errors.append(
                    f"backend {effective_backend} supports {name} only up to {maximum}"
                )
        for name, expected in constraint.get("parameter_equals", {}).items():
            if normalized_parameters.get(name) != expected:
                errors.append(
                    f"backend {effective_backend} requires {name}={expected!r}"
                )

        if operation.instruction.get("validated_profile") and operation.id in {
            "connected-components",
            "max-flow-min-cut",
            "linear-assignment",
            "transitive-closure",
            "butterfly-counting",
        }:
            if plan.allow_directed_projection:
                errors.append(
                    "This profile does not accept directed projection; use the graph's declared direction."
                )
            if (
                operation.id == "connected-components"
                and plan.application_intent
                and plan.application_intent.requires_direction
                and normalized_parameters.get("connectivity_mode") == "weakly_connected"
            ):
                errors.append(
                    "Weak connectivity ignores direction; a request requiring directed connectivity cannot use that mode."
                )
            if operation.id == "max-flow-min-cut":
                if (
                    "source" in normalized_parameters
                    and "sink" in normalized_parameters
                    and normalized_parameters["source"] == normalized_parameters["sink"]
                ):
                    errors.append("Flow source and sink must be different vertices.")
                intent = plan.application_intent
                if (
                    normalized_parameters.get("unit_capacity")
                    and intent
                    and (
                        intent.requires_edge_weights
                        or intent.weight_attribute
                        or intent.weight_usage
                    )
                ):
                    errors.append(
                        "Unit capacity cannot replace explicitly requested edge capacities."
                    )

        if for_execution and missing_inputs:
            errors.append(
                f"execution plan has missing inputs: {sorted(missing_inputs)}"
            )
        if errors:
            raise PlanValidationError(errors)
        return plan.model_copy(
            update={
                "parameters": normalized_parameters,
                "missing_inputs": sorted(set(missing_inputs)),
            }
        )

    def performance_parameters(self, operation: OperationContract) -> set[str]:
        return {
            name
            for name, spec in operation.instruction["parameters"].items()
            if spec.get("performance_only")
        }


def bind_unique_required_auxiliary_inputs(
    plan: ExecutionPlan,
    operation: OperationContract,
    available_files: list[dict[str, Any]],
    *,
    protected_names: set[str] | None = None,
) -> ExecutionPlan:
    """Bind an omitted required input only when its uploaded role is unique.

    Explicit API selections, including an explicit empty selection, remain
    authoritative. Optional inputs and ambiguous roles are never inferred.
    """

    protected = protected_names or set()
    auxiliary = {name: list(values) for name, values in plan.auxiliary_inputs.items()}
    for name, specification in operation.instruction["auxiliary_inputs"].items():
        if (
            not specification.get("required")
            or name in protected
            or auxiliary.get(name)
        ):
            continue
        candidates = [
            str(item["id"])
            for item in available_files
            if item.get("id") and item.get("role") == specification.get("role")
        ]
        if len(candidates) == 1:
            auxiliary[name] = candidates
    return plan.model_copy(update={"auxiliary_inputs": auxiliary})
