#!/usr/bin/env python3
"""Build the documentation's family/problem/algorithm catalog from native data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str):
    return json.loads((ROOT / path).read_text())


def build(binary: Path) -> dict:
    result = subprocess.run(
        [str(binary.resolve()), "catalog"], capture_output=True, text=True, check=True
    )
    native = json.loads(result.stdout)
    taxonomy = read_json("library/manifests/problem_families.json")
    research = read_json("catalog/artifact_sources.json")["artifacts"]
    families = {row["id"]: row for row in taxonomy["families"]}
    problems = {row["id"]: row for row in taxonomy["problems"]}
    assert len(families) == len(taxonomy["families"]), "Duplicate family"
    assert len(problems) == len(taxonomy["problems"]), "Duplicate problem"
    assert {p["id"]: p.get("contract") for p in native["problems"]} == {
        p["id"]: p.get("contract") for p in problems.values()
    }, "Rebuild the native runtime: its problem taxonomy is stale"
    assert {f["id"] for f in native["families"]} == set(families)
    operations = sorted(native["operations"], key=lambda row: row["id"])
    assert len({op["id"] for op in operations}) == len(operations)
    for row in [*families.values(), *problems.values(), *operations]:
        assert re.fullmatch(r"[a-z0-9_-]+", row["id"]), row["id"]
    for op in operations:
        assert op["problem_id"] in problems, op["id"]
        assert op["family"] == problems[op["problem_id"]]["family"], op["id"]
    assert all(a["problem_id"] in problems for a in research)

    documents = []
    sources = [
        "library/manifests/problem_families.json",
        "catalog/artifact_sources.json",
    ]
    for problem in problems.values():
        assert problem["family"] in families
        contract = problem.get("contract")
        spec = (
            read_json(contract)
            if contract
            else {
                "name": problem["name"],
                "problem_statement": "Look up, filter and summarize canonical vertex and edge records. These workflow utilities are listed separately from the formal research problem contracts.",
            }
        )
        if contract:
            assert spec["problem_id"] == problem["id"]
            sources.append(contract)
        algorithms = [
            {
                key: artifact.get(key)
                for key in (
                    "paper_id",
                    "title",
                    "year",
                    "venue",
                    "publication_url",
                    "code_url",
                    "collection_metadata",
                )
            }
            for artifact in research
            if artifact["problem_id"] == problem["id"]
        ]
        documents.append(
            {
                **problem,
                "spec": spec,
                "operation_ids": [
                    op["id"] for op in operations if op["problem_id"] == problem["id"]
                ],
                "research_algorithms": algorithms,
            }
        )
    return {
        "schema_version": "graphmine-docs-catalog-v1",
        "scope": "Native operation profiles and research references, organized by the authoritative problem taxonomy. Compiled backends describe the documentation build; execution also requires compatible inputs, hardware and matching validation evidence.",
        "native_implementation_sha256": native["implementation_sha256"],
        "source_sha256": {
            source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
            for source in sorted(sources)
        },
        "counts": {
            "families": len(families),
            "formal_problems": sum(bool(p.get("contract")) for p in documents),
            "utility_problems": sum(not p.get("contract") for p in documents),
            "operations": len(operations),
            "research_algorithms": len(research),
        },
        "families": sorted(families.values(), key=lambda row: row["title"]),
        "problems": documents,
        "operations": operations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary", type=Path, default=ROOT / "library/build/runtime/graphmine-native"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the published catalog needs regeneration",
    )
    args = parser.parse_args()
    document = build(args.binary)
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    output = ROOT / "docs/catalog.json"
    if args.check:
        if not output.is_file() or output.read_text() != encoded:
            raise SystemExit(
                "docs/catalog.json is stale; run tools/build_site_catalog.py"
            )
    else:
        output.write_text(encoded)
    print(json.dumps(document["counts"]))


if __name__ == "__main__":
    main()
