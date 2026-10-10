from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .exceptions import GraphMineError, ResourceLimit


@dataclass(frozen=True)
class Parameter:
    kind: str
    default: Any = None
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] = ()
    nullable: bool = False
    description: str = ""

    def validate(self, name: str, value: Any) -> Any:
        if value is None and self.nullable:
            return None
        types = {
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
            "string": (str,),
            "array": (list,),
            "object": (dict,),
            "vertex_id": (str, int),
        }
        if self.kind in types and type(value) not in types[self.kind]:
            raise GraphMineError(f"{name} must have type {self.kind}")
        if type(value) is float and not math.isfinite(value):
            raise GraphMineError(f"{name} must be finite")
        if self.minimum is not None and value < self.minimum:
            raise GraphMineError(f"{name} must be >= {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise GraphMineError(f"{name} must be <= {self.maximum}")
        if self.choices and value not in self.choices:
            raise GraphMineError(f"{name} must be one of {self.choices}")
        return value

    def schema(self) -> dict:
        result = {
            "kind": self.kind,
            "required": self.required,
            "description": self.description,
        }
        for key in ("minimum", "maximum"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if not self.required:
            result["default"] = self.default
        if self.choices:
            result["choices"] = list(self.choices)
        result["nullable"] = self.nullable
        return result


@dataclass(frozen=True)
class Budget:
    max_output_items: int = 100_000
    max_candidates: int = 2_000_000
    timeout_seconds: float = 60.0

    def __post_init__(self):
        if type(self.max_output_items) is not int or self.max_output_items < 1:
            raise GraphMineError("max_output_items must be a positive integer")
        if type(self.max_candidates) is not int or self.max_candidates < 1:
            raise GraphMineError("max_candidates must be a positive integer")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise GraphMineError("timeout_seconds must be positive and finite")


class WorkCounter:
    def __init__(self, budget: Budget):
        self.budget = budget
        self.started = time.monotonic()
        self.candidates = 0

    def tick(self, amount=1):
        self.candidates += amount
        if self.candidates > self.budget.max_candidates:
            raise ResourceLimit(
                "Candidate budget exceeded; no exhaustive result was produced"
            )
        if time.monotonic() - self.started > self.budget.timeout_seconds:
            raise ResourceLimit(
                "Computation budget exceeded; no completed result was produced"
            )

    def output(self, count: int):
        self.tick(0)
        if count > self.budget.max_output_items:
            raise ResourceLimit(
                "Output budget exceeded; request an explicit result limit or a count"
            )


@dataclass
class AlgorithmOutput:
    data: dict[str, Any]
    ports: dict[str, dict[str, Any]] = field(default_factory=dict)
    complete: bool = True
    quality: str = "exact"
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Algorithm:
    id: str
    problem_id: str
    family: str
    title: str
    description: str
    parameters: dict[str, Parameter]
    function: Callable
    library: str = "networkx"
    quality: str = "exact"
    references: tuple[str, ...] = ()
    input_kind: str = "graph"

    def arguments(self, supplied: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(supplied, dict):
            raise GraphMineError("parameters must be an object")
        unknown = set(supplied) - set(self.parameters)
        if unknown:
            raise GraphMineError(
                f"Unsupported parameters for {self.id}: {sorted(unknown)}"
            )
        values = {}
        for name, spec in self.parameters.items():
            if name not in supplied and spec.required:
                raise GraphMineError(f"Required parameter missing: {name}")
            values[name] = spec.validate(name, supplied.get(name, spec.default))
        return values

    def card(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "problem_id": self.problem_id,
            "family": self.family,
            "title": self.title,
            "description": self.description,
            "parameters": {k: v.schema() for k, v in self.parameters.items()},
            "library": self.library,
            "quality": self.quality,
            "references": list(self.references),
            "input_kind": self.input_kind,
        }
