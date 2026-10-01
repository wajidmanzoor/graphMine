from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .models import DomainProfile


class CatalogError(RuntimeError):
    """Raised when the checked-in contracts disagree with one another."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CatalogError(f"required catalog file is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise CatalogError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise CatalogError(f"catalog root must be an object: {path}")
    return value


@dataclass(frozen=True, slots=True)
class OperationContract:
    id: str
    problem_id: str
    manifest: dict[str, Any]
    catalog: dict[str, Any]
    instruction: dict[str, Any]

    @property
    def backends(self) -> tuple[str, ...]:
        return tuple(self.manifest["backends"])

    @property
    def allowed_backends(self) -> tuple[str, ...]:
        return ("auto", *self.backends)

    @property
    def default_backend(self) -> str:
        return str(self.instruction["default_backend"])


class Catalog:
    """Loads and cross-validates problem, runtime, domain, and tool contracts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.global_catalog = _read_json(settings.catalog_path)
        self.manifest = _read_json(settings.manifest_path)
        self.program_instructions = _read_json(settings.program_instructions_path)
        self.domain_catalog = _read_json(
            settings.repository_root / "agent" / "domain_profiles.json"
        )

        self.problems = {
            item["spec"]["problem_id"]: item
            for item in self.global_catalog.get("problems", [])
        }
        self.manifest_operations = {
            item["id"]: item for item in self.manifest.get("operations", [])
        }
        self.catalog_operations = {
            item["id"]: item for item in self.global_catalog.get("operations", [])
        }
        self.instructions = {
            item["id"]: item for item in self.program_instructions.get("operations", [])
        }
        self.domains = {
            item["id"]: DomainProfile.model_validate(item)
            for item in self.domain_catalog.get("domains", [])
        }
        self._validate()

    def _validate(self) -> None:
        if self.global_catalog.get("schema_version") != "2.0.0":
            raise CatalogError("unsupported graphmine_catalog.json schema")
        if self.manifest.get("schema_version") != "1.0.0":
            raise CatalogError("unsupported graphmine_manifest.json schema")
        if self.program_instructions.get("schema_version") != "1.0.0":
            raise CatalogError("unsupported program instruction schema")
        if self.domain_catalog.get("schema_version") != "1.0.0":
            raise CatalogError("unsupported domain profile schema")
        if len(self.problems) != 20:
            raise CatalogError(
                f"expected 20 problem definitions, found {len(self.problems)}"
            )

        operation_sets = {
            "manifest": set(self.manifest_operations),
            "catalog": set(self.catalog_operations),
            "program instructions": set(self.instructions),
        }
        expected = next(iter(operation_sets.values()))
        for label, values in operation_sets.items():
            if values != expected:
                missing = sorted(expected - values)
                extra = sorted(values - expected)
                raise CatalogError(
                    f"{label} operation set differs; missing={missing}, extra={extra}"
                )
        if len(expected) != 13:
            raise CatalogError(
                f"expected 13 runnable operations, found {len(expected)}"
            )

        for operation_id in sorted(expected):
            manifest = self.manifest_operations[operation_id]
            catalog = self.catalog_operations[operation_id]
            instruction = self.instructions[operation_id]
            problem_ids = {
                manifest["research_problem_id"],
                catalog["research_problem_id"],
                instruction["problem_id"],
            }
            if len(problem_ids) != 1:
                raise CatalogError(
                    f"problem mismatch for {operation_id}: {sorted(problem_ids)}"
                )
            problem_id = next(iter(problem_ids))
            if problem_id not in self.problems:
                raise CatalogError(f"unknown problem {problem_id} for {operation_id}")
            manifest_backends = set(manifest["backends"])
            catalog_backends = set(catalog["backends"])
            if manifest_backends != catalog_backends:
                raise CatalogError(f"backend mismatch for {operation_id}")
            if instruction["default_backend"] not in manifest_backends:
                raise CatalogError(
                    f"default backend for {operation_id} is not registered"
                )
            if (
                set(instruction["required_outputs"])
                != set(manifest["required_outputs"])
                and operation_id != "graph-motifs"
            ):
                # Nested path notation differs for graph motifs; its top-level
                # output is intentionally represented as the motifs array.
                raise CatalogError(f"required output mismatch for {operation_id}")

        if "general" not in self.domains:
            raise CatalogError("domain profiles require a general fallback")
        for domain in self.domains.values():
            unknown = set(domain.relevant_problem_ids) - set(self.problems)
            if unknown:
                raise CatalogError(
                    f"domain {domain.id} refers to unknown problems: {sorted(unknown)}"
                )

    def operation(self, operation_id: str) -> OperationContract:
        try:
            manifest = self.manifest_operations[operation_id]
            catalog = self.catalog_operations[operation_id]
            instruction = self.instructions[operation_id]
        except KeyError as error:
            raise CatalogError(f"unknown operation: {operation_id}") from error
        return OperationContract(
            id=operation_id,
            problem_id=instruction["problem_id"],
            manifest=manifest,
            catalog=catalog,
            instruction=instruction,
        )

    def problem(self, problem_id: str) -> dict[str, Any]:
        try:
            return self.problems[problem_id]
        except KeyError as error:
            raise CatalogError(f"unknown problem: {problem_id}") from error

    def domain(self, domain_id: str) -> DomainProfile:
        try:
            return self.domains[domain_id]
        except KeyError as error:
            raise CatalogError(f"unknown domain: {domain_id}") from error

    def routing_context(self, domain_id: str) -> dict[str, Any]:
        domain = self.domain(domain_id)
        problems = []
        for problem_id, record in self.problems.items():
            spec = record["spec"]
            problems.append(
                {
                    "problem_id": problem_id,
                    "name": spec["name"],
                    "problem_statement": spec["problem_statement"],
                    "intent_signals": record.get("intent_signals", []),
                    "library_support": record["library_support"],
                    "domain_relevant": problem_id in domain.relevant_problem_ids,
                }
            )
        return {"domain": domain.model_dump(mode="json"), "problems": problems}

    def operation_context(self, operation_id: str) -> dict[str, Any]:
        operation = self.operation(operation_id)
        spec = self.problem(operation.problem_id)["spec"]
        return {
            # Keep semantic meaning without exposing the broader research
            # problem's parameter/output names. The validated adapter below is
            # the sole executable allowlist and sometimes exposes a narrower
            # profile under different names.
            "problem_semantics": {
                "problem_id": spec["problem_id"],
                "name": spec["name"],
                "problem_statement": spec["problem_statement"],
                "graph_input": spec["graph_input"],
                "solution_semantics": spec["solution_semantics"],
            },
            "operation": operation.catalog,
            "program_instruction": operation.instruction,
        }
