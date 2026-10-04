from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import Catalog, CatalogError
from .models import ExecutionPlan, GraphMetadata
from .planning import PlanValidationError, PlanValidator


class BackendPolicyError(RuntimeError):
    """Raised when a benchmark-derived backend policy is malformed."""


# Correctness exclusions override benchmark rankings, including stale/custom
# policies. Keep these until an independent audit establishes a safe contract.
# synthetic-v1/random-01-q01: CUDA-MS returned 3 and certified optimality when
# exhaustive enumeration and both exact GPU backends found a four-clique.
CORRECTNESS_EXCLUSIONS = {
    "maximum-clique": {
        "cuda-ms": "CUDA-MS cannot reliably certify the global maximum; use an exact maximum-clique backend",
        "maximum-clique-on-gpu": "Maximum-Clique-on-GPU aborts on the seeded cycle_chords-01 regression; quarantined pending adapter repair",
    },
}


def feature_bucket(metadata: GraphMetadata | dict[str, Any] | None) -> str:
    """Return a stable, deliberately coarse graph bucket for v1 policies."""

    if isinstance(metadata, GraphMetadata):
        value = metadata.model_dump(mode="json")
    elif isinstance(metadata, dict):
        value = metadata
    else:
        value = {}
    vertices = int(value.get("vertex_count") or 0)
    density = float(value.get("density") or 0.0)
    if vertices <= 10_000:
        scale = "tiny"
    elif vertices <= 100_000:
        scale = "small"
    elif vertices <= 1_000_000:
        scale = "medium"
    else:
        scale = "large"
    if density < 0.001:
        density_class = "sparse"
    elif density < 0.05:
        density_class = "moderate"
    else:
        density_class = "dense"
    direction = "directed" if value.get("directed") else "undirected"
    temporal = "temporal" if value.get("has_timestamps") else "static"
    return f"{scale}:{density_class}:{direction}:{temporal}"


class BackendSelector:
    """Select only validated, compiled, plan-compatible benchmark winners."""

    def __init__(self, path: Path, catalog: Catalog, validator: PlanValidator) -> None:
        self.path = path
        self.catalog = catalog
        self.validator = validator
        self.policy: dict[str, Any] | None = None
        self.error: str | None = None
        self._load()

    @property
    def loaded(self) -> bool:
        return self.policy is not None

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise BackendPolicyError("policy root must be an object")
            if value.get("schema_version") != "1.0.0":
                raise BackendPolicyError("unsupported backend policy schema")
            operations = value.get("operations")
            if not isinstance(operations, dict):
                raise BackendPolicyError("policy operations must be an object")
            for operation_id, policy in operations.items():
                if not isinstance(operation_id, str) or not operation_id:
                    raise BackendPolicyError("policy operation IDs must be strings")
                operation = self.catalog.operation(operation_id)
                if not isinstance(policy, dict):
                    raise BackendPolicyError(
                        f"policy for {operation_id} must be an object"
                    )
                global_ranked = policy.get("global_ranked_backends", [])
                if not isinstance(global_ranked, list) or not all(
                    isinstance(item, str) and item for item in global_ranked
                ):
                    raise BackendPolicyError(
                        f"global ranking for {operation_id} must be backend IDs"
                    )
                buckets = policy.get("buckets", {})
                if not isinstance(buckets, dict):
                    raise BackendPolicyError(
                        f"buckets for {operation_id} must be an object"
                    )
                candidates: list[Any] = list(global_ranked)
                for bucket in buckets.values():
                    if not isinstance(bucket, dict):
                        raise BackendPolicyError(
                            f"bucket for {operation_id} must be an object"
                        )
                    ranked = bucket.get("ranked_backends", [])
                    if not isinstance(ranked, list) or not all(
                        isinstance(item, str) and item for item in ranked
                    ):
                        raise BackendPolicyError(
                            f"bucket ranking for {operation_id} must be backend IDs"
                        )
                    candidates.extend(ranked)
                unknown = set(candidates) - set(operation.backends)
                if unknown:
                    raise BackendPolicyError(
                        f"policy for {operation_id} has unknown backends: "
                        f"{sorted(unknown)}"
                    )
            self.policy = value
        except (
            OSError,
            json.JSONDecodeError,
            BackendPolicyError,
            CatalogError,
            KeyError,
        ) as error:
            self.policy = None
            self.error = str(error)

    def ranked_backends(
        self,
        operation_id: str,
        metadata: GraphMetadata | dict[str, Any] | None,
    ) -> list[str]:
        operation_policy = (
            (self.policy or {}).get("operations", {}).get(operation_id, {})
        )
        bucket = feature_bucket(metadata)
        ranked = list(
            operation_policy.get("buckets", {})
            .get(bucket, {})
            .get("ranked_backends", [])
        )
        ranked.extend(operation_policy.get("global_ranked_backends", []))
        operation = self.catalog.operation(operation_id)
        ranked.append(operation.default_backend)
        ranked.extend(operation.backends)
        excluded = CORRECTNESS_EXCLUSIONS.get(operation_id, {})
        return [
            item
            for item in dict.fromkeys(str(item) for item in ranked)
            if item not in excluded
        ]

    def select(
        self,
        plan: ExecutionPlan,
        metadata: GraphMetadata | dict[str, Any] | None,
        compiled_backends: set[str],
    ) -> ExecutionPlan:
        excluded = CORRECTNESS_EXCLUSIONS.get(plan.operation_id, {})
        if plan.backend_id in excluded:
            raise PlanValidationError([excluded[plan.backend_id]])
        if plan.backend_id != "auto" or (self.policy is None and not excluded):
            return plan
        for backend in self.ranked_backends(plan.operation_id, metadata):
            if backend not in compiled_backends:
                continue
            candidate = plan.model_copy(update={"backend_id": backend})
            try:
                return self.validator.validate(
                    candidate,
                    compiled_backends=compiled_backends,
                    for_execution=True,
                )
            except PlanValidationError:
                continue
        if excluded:
            raise PlanValidationError(
                [
                    "No compiled, compatible, correctness-approved backend is available for this analysis"
                ]
            )
        return plan
