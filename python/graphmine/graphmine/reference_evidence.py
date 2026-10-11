"""Check local correctness evidence before advertising application capabilities."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .backends.cugraph import OPERATIONS
from .exceptions import GraphMineError
from .reference import implementation_hash
from .registry import reference_algorithms as algorithms
from .registry import reference_families as families


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Evidence file is missing or outside the repository")
    return path


def verify_report(root, report):
    """Re-read source, dependency, metadata and JUnit evidence; never trust status."""
    try:
        xml = _path(root, report["report"])
        metadata_path = _path(root, report["metadata"])
        if (
            _sha(xml) != report["report_sha256"]
            or _sha(metadata_path) != report["metadata_sha256"]
        ):
            raise ValueError("Evidence artifact hash mismatch")
        metadata = json.loads(metadata_path.read_text())
        if (
            not metadata["sources_unchanged_during_run"]
            or not metadata["contracts_unchanged_during_run"]
        ):
            raise ValueError("Sources or contracts changed during verification")
        library = root / "python/graphmine"
        sources = metadata["source_files"]
        if set(sources) != {str(p.relative_to(library)) for p in library.rglob("*.py")}:
            raise ValueError("Source file inventory changed")
        for name, expected in sources.items():
            if _sha(_path(library.resolve(), name)) != expected:
                raise ValueError(f"Source changed: {name}")
        contracts = metadata["contracts"]
        current_contracts = {
            str(p.relative_to(root))
            for p in (root / "problems").glob("[0-9][0-9]_*/problem.json")
        }
        current_contracts.update(
            str(p.relative_to(root))
            for p in (root / "problems").glob("*_input.schema.json")
        )
        current_contracts.add("python/graphmine/pyproject.toml")
        if set(contracts) != current_contracts:
            raise ValueError("Contract file inventory changed")
        for name, expected in contracts.items():
            if _sha(_path(root, name)) != expected:
                raise ValueError(f"Contract changed: {name}")
        if metadata["python"] != sys.version:
            raise ValueError("Python runtime changed")
        for package, expected in metadata["packages"].items():
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                version = None
            if version != expected:
                raise ValueError(f"Dependency changed: {package}")
        suites = ET.parse(xml).getroot().findall("testsuite")
        counts = {
            key: sum(int(s.attrib[key]) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        if not counts["tests"] or any(
            counts[k] for k in ("failures", "errors", "skipped")
        ):
            raise ValueError("Report is empty or contains failures, errors or skips")
        if counts["tests"] != metadata["collected_test_count"]:
            raise ValueError("Report and collected test count disagree")
        if metadata["device"] == "cpu":
            expected_modules = {
                str(p.relative_to(library))
                for p in (library / "tests").glob("test_*.py")
            }
            if (
                set(metadata["test_modules"]) != expected_modules
                or metadata["cuda_visible_devices"] != ""
            ):
                raise ValueError(
                    "CPU evidence must cover the full suite with GPUs hidden"
                )
        elif metadata["device"] != "gpu":
            raise ValueError("Unknown test device")
        return {
            "id": report["id"],
            "status": "passed",
            "device": metadata["device"],
            "case_shard": metadata.get("case_shard"),
            "tests": counts["tests"],
            "report": report["report"],
        }
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        return {
            "id": report.get("id", "unknown"),
            "status": "unverified",
            "reason": str(exc),
        }


def capabilities(repository_root):
    root = Path(repository_root).resolve()
    try:
        inventory = json.loads(
            (root / "catalog/python_analytics_coverage.json").read_text()
        )
    except (OSError, ValueError):
        inventory = {}
    reports = [verify_report(root, report) for report in inventory.get("reports", [])]
    cpu = any(r["status"] == "passed" and r["device"] == "cpu" for r in reports)
    gpu_shards = {
        r.get("case_shard")
        for r in reports
        if r["status"] == "passed" and r["device"] == "gpu"
    }
    gpu = {"0/2", "1/2"} <= gpu_shards
    recorded = {card["id"]: card for card in inventory.get("operations", [])}
    cards = algorithms()
    for card in cards:
        profile = hashlib.sha256(json.dumps(card, sort_keys=True).encode()).hexdigest()
        matches = recorded.get(card["id"], {}).get("profile_sha256") == profile
        card["profile_sha256"] = profile
        card["execution"] = {
            "cpu": bool(cpu and matches),
            "gpu": bool(gpu and matches and card["id"] in OPERATIONS),
        }
        card["evidence_state"] = (
            "verified_profile" if card["execution"]["cpu"] else "verification_required"
        )
    return {
        "schema_version": "2.0.0",
        "implementation_sha256": implementation_hash(),
        "families": families(),
        "operations": cards,
        "reports": reports,
        "scope": inventory.get("scope", "Local tested profiles only"),
    }


def require_workflow_evidence(checked, caps):
    cards = {card["id"]: card for card in caps["operations"]}
    for step in checked["plan"]["steps"]:
        card = cards[step["operation"]]
        device = "gpu" if step["device"] == "gpu" else "cpu"
        if not card["execution"][device]:
            raise GraphMineError(
                f"Current {device} correctness evidence is missing or stale for {step['operation']}"
            )
