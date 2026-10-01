from __future__ import annotations

import math
from typing import Any

from .catalog import Catalog, OperationContract
from .models import ExecutionPlan, RouteDecision


class PlanValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def normalize_route(catalog: Catalog, decision: RouteDecision) -> RouteDecision:
    """Validate model-selected identity and derive support from the catalog."""

    if not decision.problem_id:
        return decision.model_copy(update={"supported": False, "operation_id": None})
    try:
        problem = catalog.problem(decision.problem_id)
    except Exception as error:
        raise PlanValidationError([str(error)]) from error
    expected_support = problem["library_support"]["status"] == "validated"
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
