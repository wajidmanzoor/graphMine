"""Deterministic preflight for bounded native profiles, after graph filtering."""

from __future__ import annotations

import copy
import math
from typing import Any

from .graph_context import field_value, identity
from .models import ExecutionPlan

EXPANSION_OPERATIONS = frozenset(
    {
        "connected-components",
        "max-flow-min-cut",
        "linear-assignment",
        "transitive-closure",
        "butterfly-counting",
    }
)
DIRECTION_PRESERVING_OPERATIONS = frozenset(
    {
        "temporal-motif-mining",
        "connected-components",
        "max-flow-min-cut",
        "transitive-closure",
    }
)


class ProfileInputError(ValueError):
    def __init__(self, message: str, status: str = "unsupported"):
        self.status = status
        super().__init__(message)


def prepare_operation_graph(
    graph: dict[str, Any], plan: ExecutionPlan
) -> dict[str, Any]:
    """Return a copy with explicitly selected capacities/costs in native weight.

    Never infer capacities, round values, infer bipartite sides, drop edges to
    fit a profile, or mutate the uploaded graph. Native checks remain authoritative.
    """
    operation = plan.operation_id
    if operation not in EXPANSION_OPERATIONS:
        return graph
    vertices, edges = graph["vertices"], graph["edges"]
    directed = graph["graph"]["directed"]
    if len(vertices) > 1_000_000 or len(edges) > 10_000_000:
        raise ProfileInputError(
            "This profile accepts at most 1,000,000 entities and 10,000,000 relationships."
        )
    if operation in {"max-flow-min-cut", "transitive-closure"} and not directed:
        raise ProfileInputError(
            "This calculation requires directed relationships; an undirected input cannot be interpreted as directed automatically."
        )
    if operation in {"linear-assignment", "butterfly-counting"} and directed:
        raise ProfileInputError("This bipartite profile requires an undirected graph.")
    if operation == "transitive-closure" and len(vertices) > 1024:
        raise ProfileInputError(
            "Full reachability currently supports at most 1,024 entities; a reusable index is not available."
        )
    if operation == "max-flow-min-cut":
        ids = {identity(row["id"]) for row in vertices}
        for name in ("source", "sink"):
            if name in plan.parameters and identity(plan.parameters[name]) not in ids:
                raise ProfileInputError(
                    f"The selected {name} is not present after filtering. Select an entity in this scope.",
                    "needs_information",
                )

    prepared = graph
    weighted = operation in {
        "max-flow-min-cut",
        "linear-assignment",
    } and not plan.parameters.get("unit_capacity", False)
    if weighted:
        intent = plan.application_intent
        field = (
            intent.weight_attribute if intent and intent.weight_attribute else "weight"
        )
        label = "capacity" if operation == "max-flow-min-cut" else "assignment cost"
        maximum = 1_000_000_000 if operation == "max-flow-min-cut" else 999
        prepared = copy.deepcopy(graph)
        for edge in prepared["edges"]:
            try:
                value = field_value(edge, field)
            except KeyError as error:
                raise ProfileInputError(
                    f"Every relationship needs a {label} in {field}; that field is missing on at least one selected relationship.",
                    "needs_information",
                ) from error
            if value is None:
                raise ProfileInputError(
                    f"Every relationship needs a {label} in {field}; missing values cannot be guessed.",
                    "needs_information",
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= maximum
                or not math.isfinite(value)
                or int(value) != value
            ):
                raise ProfileInputError(
                    f"This profile requires integer {label} values from 0 to {maximum}; values cannot be rounded or rescaled automatically."
                )
            edge["weight"] = int(value)
    if operation == "max-flow-min-cut":
        total = sum(
            1 if plan.parameters.get("unit_capacity") else edge["weight"]
            for edge in prepared["edges"]
            if identity(edge["source"]) != identity(edge["target"])
        )
        if total > 1_000_000_000:
            raise ProfileInputError(
                "Total edge capacity must not exceed 1,000,000,000 in this profile."
            )
    if operation in {"linear-assignment", "butterfly-counting"}:
        sides = {
            identity(row["id"]): row.get("attributes", {}).get("side")
            for row in vertices
        }
        if any(side not in ("left", "right") for side in sides.values()):
            raise ProfileInputError(
                "Label every entity's attributes.side as left or right to identify the two groups.",
                "needs_information",
            )
        pairs = set()
        for edge in edges:
            source, target = identity(edge["source"]), identity(edge["target"])
            if sides[source] == sides[target]:
                raise ProfileInputError(
                    "Every relationship must join opposite groups; loops and same-side relationships are not supported."
                )
            pairs.add((source, target) if sides[source] == "left" else (target, source))
        if operation == "linear-assignment":
            left = sum(side == "left" for side in sides.values())
            right = len(sides) - left
            if left != right or left > 64:
                raise ProfileInputError(
                    "Minimum-cost perfect assignment requires equal-sized groups with at most 64 entities on each side."
                )
            if len(pairs) != left * right:
                raise ProfileInputError(
                    "Minimum-cost perfect assignment requires a cost for every possible pair across the two groups; sparse matching is not supported."
                )
    return prepared
