#!/usr/bin/env python3
"""Reconcile formal problems with executable Python profiles and test evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from graphmine import list_algorithms
from graphmine.backends.cugraph import OPERATIONS

ROOT = Path(__file__).resolve().parents[1]


def audit():
    library = ROOT / "python/graphmine"
    reports = []
    for name in ("cpu-workspace", "gpu-0-workspace", "gpu-1-workspace"):
        xml = ROOT / "validation/python_analytics" / f"{name}.xml"
        metadata_path = xml.with_name(xml.name + ".metadata.json")
        if not xml.exists() or not metadata_path.exists():
            reports.append({"id": name, "status": "missing"})
            continue
        metadata = json.loads(metadata_path.read_text())
        changed = [
            name
            for name, expected in metadata["source_files"].items()
            if not (library / name).is_file()
            or hashlib.sha256((library / name).read_bytes()).hexdigest() != expected
        ]
        current_files = {str(p.relative_to(library)) for p in library.rglob("*.py")}
        changed.extend(sorted(current_files - set(metadata["source_files"])))
        for contract, expected in metadata.get("contracts", {}).items():
            path = ROOT / contract
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                changed.append(contract)
        changed_dependencies = []
        for package, expected in metadata["packages"].items():
            try:
                current = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                current = None
            if current != expected:
                changed_dependencies.append(
                    {"package": package, "tested": expected, "current": current}
                )
        suite = ET.parse(xml).getroot().find("testsuite")
        failures = int(suite.attrib["failures"]) + int(suite.attrib["errors"])
        reports.append(
            {
                "id": name,
                "status": "stale"
                if changed
                or changed_dependencies
                or not metadata["sources_unchanged_during_run"]
                or not metadata.get("contracts_unchanged_during_run", False)
                else "failed"
                if failures
                else "passed",
                "tests": int(suite.attrib["tests"]),
                "failures": failures,
                "skipped": int(suite.attrib["skipped"]),
                "changed_sources": changed,
                "changed_dependencies": changed_dependencies,
                "test_modules": metadata.get("test_modules", []),
                "report": str(xml.relative_to(ROOT)),
                "report_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                "metadata": str(metadata_path.relative_to(ROOT)),
                "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                "packages": metadata["packages"],
            }
        )
    cards = list_algorithms()
    for card in cards:
        card["profile_sha256"] = hashlib.sha256(
            json.dumps(card, sort_keys=True).encode()
        ).hexdigest()
    problems = []
    for path in sorted((ROOT / "problems").glob("[0-9][0-9]_*/problem.json")):
        spec = json.loads(path.read_text())
        operations = [
            card for card in cards if card["problem_id"] == spec["problem_id"]
        ]
        problems.append(
            {
                "problem_id": spec["problem_id"],
                "name": spec["name"],
                "contract": str(path.relative_to(ROOT)),
                "contract_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "cpu_operations": [card["id"] for card in operations],
                "cugraph_operations": [
                    card["id"] for card in operations if card["id"] in OPERATIONS
                ],
                "status": "has_executable_profile"
                if operations
                else "integration_required",
                "full_formal_parameter_coverage_claimed": False,
            }
        )
    return {
        "schema_version": "1.0.0",
        "problem_count": len(problems),
        "cpu_operation_count": len(cards),
        "problems_with_cpu_profile": sum(bool(p["cpu_operations"]) for p in problems),
        "cugraph_operation_count": len(OPERATIONS),
        "reports": reports,
        "scope": "Executable profiles and the specific independent oracle fixtures recorded in each report. Native backends and outer-folder diagnostics are separate; no universal correctness or full parameter coverage claim.",
        "problems": problems,
        "operations": cards,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = audit()
    if args.write:
        path = ROOT / "catalog/python_analytics_coverage.json"
        path.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "problem_count",
                    "cpu_operation_count",
                    "problems_with_cpu_profile",
                    "cugraph_operation_count",
                    "reports",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
