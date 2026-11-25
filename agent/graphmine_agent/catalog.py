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
class ProblemContract:
    id: str
    topic_id: str
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
    """Loads and cross-validates topic, runtime, domain, and tool contracts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.global_catalog = _read_json(settings.catalog_path)
        self.manifest = _read_json(settings.manifest_path)
        self.program_instructions = _read_json(settings.program_instructions_path)
        self.domain_catalog = _read_json(
            settings.repository_root / "agent" / "domain_profiles.json"
        )

        self.topics = {
            item["spec"]["topic_id"]: item
            for item in self.global_catalog.get("topics", [])
        }
        self.manifest_problems = {
            item["id"]: item for item in self.manifest.get("problems", [])
        }
        self.catalog_problems = {
            item["id"]: item for item in self.global_catalog.get("problems", [])
        }
        self.instructions = {
            item["id"]: item for item in self.program_instructions.get("problems", [])
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
        scope = self.global_catalog.get("scope", {})
        collections = (
            ("topics", self.topics, self.global_catalog.get("topics", [])),
            (
                "manifest problems",
                self.manifest_problems,
                self.manifest.get("problems", []),
            ),
            (
                "catalog problems",
                self.catalog_problems,
                self.global_catalog.get("problems", []),
            ),
            (
                "instructions",
                self.instructions,
                self.program_instructions.get("problems", []),
            ),
        )
        for label, indexed, records in collections:
            if not indexed or len(indexed) != len(records):
                raise CatalogError(f"{label} must contain nonempty, unique IDs")
        if len(self.topics) != scope.get("catalog_topic_count"):
            raise CatalogError("topic count differs from the declared catalog scope")

        problem_sets = {
            "manifest": set(self.manifest_problems),
            "catalog": set(self.catalog_problems),
            "program instructions": set(self.instructions),
        }
        expected = next(iter(problem_sets.values()))
        for label, values in problem_sets.items():
            if values != expected:
                missing = sorted(expected - values)
                extra = sorted(values - expected)
                raise CatalogError(
                    f"{label} problem set differs; missing={missing}, extra={extra}"
                )
        if len(expected) != scope.get("runnable_problem_count") or len(
            expected
        ) != self.manifest.get("scope", {}).get("runnable_problem_count"):
            raise CatalogError(
                "problem count differs from the declared catalog scope"
            )

        for problem_id in sorted(expected):
            manifest = self.manifest_problems[problem_id]
            catalog = self.catalog_problems[problem_id]
            instruction = self.instructions[problem_id]
            topic_ids = {
                manifest["topic_id"],
                catalog["topic_id"],
                instruction["topic_id"],
            }
            if len(topic_ids) != 1:
                raise CatalogError(
                    f"topic mismatch for {problem_id}: {sorted(topic_ids)}"
                )
            topic_id = next(iter(topic_ids))
            if topic_id not in self.topics:
                raise CatalogError(f"unknown topic {topic_id} for {problem_id}")
            support = self.topics[topic_id]["library_support"]
            if not support["available"] or problem_id not in support["problem_ids"]:
                raise CatalogError(f"missing topic support for {problem_id}")
            manifest_backends = set(manifest["backends"])
            catalog_backends = set(catalog["backends"])
            if manifest_backends != catalog_backends:
                raise CatalogError(f"backend mismatch for {problem_id}")
            if instruction["default_backend"] not in manifest_backends:
                raise CatalogError(
                    f"default backend for {problem_id} is not registered"
                )
            if (
                set(instruction["required_outputs"])
                != set(manifest["required_outputs"])
                and problem_id != "graph-motifs"
            ):
                # Nested path notation differs for graph motifs; its top-level
                # output is intentionally represented as the motifs array.
                raise CatalogError(f"required output mismatch for {problem_id}")

        backend_count = sum(
            len(item["backends"]) for item in self.manifest_problems.values()
        )
        if backend_count != scope.get(
            "validated_backend_count"
        ) or backend_count != self.manifest["scope"].get("validated_backend_count"):
            raise CatalogError("backend count differs from the declared catalog scope")
        for topic_id, record in self.topics.items():
            actual = {
                op_id
                for op_id, op in self.manifest_problems.items()
                if op["topic_id"] == topic_id
            }
            support = record["library_support"]
            if (
                set(support["problem_ids"]) != actual
                or bool(actual) != support["available"]
            ):
                raise CatalogError(f"inconsistent problem support for {topic_id}")
        supported_ids = {
            topic_id
            for topic_id, record in self.topics.items()
            if record["library_support"]["available"]
        }
        if (
            len(supported_ids) != scope.get("library_supported_topic_count")
            or len(self.topics) - len(supported_ids)
            != scope.get("library_unsupported_topic_count")
            or len(supported_ids)
            != self.manifest["scope"].get("topic_count")
        ):
            raise CatalogError(
                "supported topic count differs from the declared scope"
            )
        embedded = self.manifest.get("included_topic_specs", [])
        if (
            len(embedded) != len(supported_ids)
            or {entry["spec"]["topic_id"] for entry in embedded} != supported_ids
        ):
            raise CatalogError(
                "manifest must embed every supported topic exactly once"
            )
        for entry in embedded:
            if entry["spec"] != self.topics[entry["spec"]["topic_id"]]["spec"]:
                raise CatalogError("manifest and catalog topic specifications differ")

        if "general" not in self.domains:
            raise CatalogError("domain profiles require a general fallback")
        for domain in self.domains.values():
            unknown = set(domain.relevant_topic_ids) - set(self.topics)
            if unknown:
                raise CatalogError(
                    f"domain {domain.id} refers to unknown topics: {sorted(unknown)}"
                )

    def problem(self, problem_id: str) -> ProblemContract:
        try:
            manifest = self.manifest_problems[problem_id]
            catalog = self.catalog_problems[problem_id]
            instruction = self.instructions[problem_id]
        except KeyError as error:
            raise CatalogError(f"unknown problem: {problem_id}") from error
        return ProblemContract(
            id=problem_id,
            topic_id=instruction["topic_id"],
            manifest=manifest,
            catalog=catalog,
            instruction=instruction,
        )

    def topic(self, topic_id: str) -> dict[str, Any]:
        try:
            return self.topics[topic_id]
        except KeyError as error:
            raise CatalogError(f"unknown topic: {topic_id}") from error

    def domain(self, domain_id: str) -> DomainProfile:
        try:
            return self.domains[domain_id]
        except KeyError as error:
            raise CatalogError(f"unknown domain: {domain_id}") from error

    def routing_context(self, domain_id: str) -> dict[str, Any]:
        domain = self.domain(domain_id)
        topics = []
        for topic_id, record in self.topics.items():
            spec = record["spec"]
            topics.append(
                {
                    "topic_id": topic_id,
                    "name": spec["name"],
                    "problem_statement": spec["problem_statement"],
                    "intent_signals": record.get("intent_signals", []),
                    "library_support": record["library_support"],
                    "domain_relevant": topic_id in domain.relevant_topic_ids,
                }
            )
        return {
            "contract_version": self.global_catalog.get("routing", {}).get(
                "contract_version", "legacy-20"
            ),
            "domain": domain.model_dump(mode="json"),
            "topics": topics,
        }

    def problem_context(self, problem_id: str) -> dict[str, Any]:
        problem = self.problem(problem_id)
        spec = self.topic(problem.topic_id)["spec"]
        return {
            # Keep semantic meaning without exposing the broader research
            # topic's parameter/output names. The validated adapter below is
            # the sole executable allowlist and sometimes exposes a narrower
            # profile under different names.
            "problem_semantics": {
                "topic_id": spec["topic_id"],
                "name": spec["name"],
                "problem_statement": spec["problem_statement"],
                "graph_input": spec["graph_input"],
                "solution_semantics": spec["solution_semantics"],
            },
            "problem": problem.catalog,
            "program_instruction": problem.instruction,
        }
