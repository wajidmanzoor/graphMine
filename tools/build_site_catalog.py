#!/usr/bin/env python3
"""Build the documentation's family/topic/algorithm catalog from native data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from family_catalog import problem_metadata, taxonomy as load_taxonomy
from site_catalog_pages import generated_pages

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str):
    return json.loads((ROOT / path).read_text())


SNAPSHOT = ROOT / "catalog/site_runtime_snapshot.json"


def runtime_sources():
    """Bind the documented build to the checked-in native implementation."""
    paths = subprocess.check_output([
        "git", "ls-files", "library/runtime", "library/include", "library/src",
        "library/manifests", "library/cmake", "library/CMakeLists.txt",
    ], cwd=ROOT, text=True).splitlines()
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in paths if (ROOT / p).is_file()}


def native_catalog(binary: Path | None, check: bool):
    if binary:
        result = subprocess.run([str(binary.resolve()), "catalog"],
                                capture_output=True, text=True, check=True)
        snapshot = {"source_sha256": runtime_sources(), "catalog": json.loads(result.stdout)}
        encoded = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        if check:
            if SNAPSHOT.read_text() != encoded:
                raise SystemExit("Native documentation snapshot is stale; refresh with --binary")
        else:
            SNAPSHOT.write_text(encoded)
    else:
        snapshot = json.loads(SNAPSHOT.read_text())
        if snapshot["source_sha256"] != runtime_sources():
            raise SystemExit("Native sources changed; rebuild and refresh with --binary PATH")
    return snapshot["catalog"]


def build(native: dict) -> dict:
    taxonomy = load_taxonomy(ROOT)
    metadata = problem_metadata(ROOT)
    research = read_json("catalog/artifact_sources.json")["artifacts"]
    public_links = read_json("catalog/site_reference_links.json")
    research = [{**a, **public_links.get(a["paper_id"], {})} for a in research]
    families = {row["id"]: row for row in taxonomy["families"]}
    topics = {row["id"]: row for row in metadata["topics"]}
    problem_families = {
        problem: family["id"]
        for family in taxonomy["families"]
        for problem in family["problems"]
    }
    assert len(families) == len(taxonomy["families"]), "Duplicate family"
    assert len(topics) == len(metadata["topics"]), "Duplicate topic"
    assert {p["id"]: p.get("contract") for p in native["topics"]} == {
        p["id"]: p.get("contract") for p in topics.values()
    }, "Rebuild the native runtime: its topic taxonomy is stale"
    assert native["families"] == taxonomy["families"], "Rebuild the native runtime: its family taxonomy is stale"
    problems = sorted(native["problems"], key=lambda row: row["id"])
    assert len({op["id"] for op in problems}) == len(problems)
    for row in [*families.values(), *topics.values(), *problems]:
        assert re.fullmatch(r"[a-z0-9_-]+", row["id"]), row["id"]
    for op in problems:
        assert op["topic_id"] in topics, op["id"]
        assert op["family"] == problem_families[op["id"]], op["id"]
        topic = topics[op["topic_id"]]
        assert topic.get("family", op["family"]) == op["family"], op["id"]
        topic["family"] = op["family"]
    assert all(a["topic_id"] in topics for a in research)

    documents = []
    sources = [
        "catalog/family.json",
        "catalog/problems.json",
        "catalog/algo.json",
        "catalog/artifact_sources.json",
        "catalog/site_reference_links.json",
    ]
    for topic in topics.values():
        assert topic["family"] in families
        contract = topic.get("contract")
        spec = (
            read_json(contract)
            if contract
            else {
                "name": topic["name"],
                "problem_statement": "Look up, filter and summarize canonical vertex and edge records. These workflow utilities are listed separately from the formal research topic contracts.",
            }
        )
        if contract:
            assert spec["topic_id"] == topic["id"]
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
                    "note",
                )
            }
            for artifact in research
            if artifact["topic_id"] == topic["id"]
        ]
        documents.append(
            {
                **topic,
                "spec": spec,
                "problem_ids": [
                    op["id"] for op in problems if op["topic_id"] == topic["id"]
                ],
                "research_algorithms": algorithms,
            }
        )
    return {
        "schema_version": "graphmine-docs-catalog-v1",
        "scope": "Native problem profiles and research references, organized by the authoritative topic taxonomy. Compiled backends describe the documentation build; execution also requires compatible inputs, hardware and matching validation evidence.",
        "native_implementation_sha256": native["implementation_sha256"],
        "source_sha256": {
            source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
            for source in sorted(sources)
        },
        "counts": {
            "families": len(families),
            "formal_problems": sum(bool(p.get("contract")) for p in documents),
            "utility_problems": sum(not p.get("contract") for p in documents),
            "problems": len(problems),
            "research_algorithms": len(research),
        },
        "families": list(families.values()),
        "topics": documents,
        "problems": problems,
    }


def vague_term_families():
    path = ROOT / "catalog/vague_terms.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text())
    families = load_taxonomy(ROOT)["families"]
    for term in document["terms"]:
        problems = {row["problem"] for row in term["interpretations"]}
        term["families"] = [family["id"] for family in families if problems & set(family["problems"])]
    return {path: json.dumps(document, ensure_ascii=False, indent=2) + "\n"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary", type=Path, help="Refresh from a built runtime; otherwise verify the committed source-bound snapshot"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the published catalog needs regeneration",
    )
    args = parser.parse_args()
    document = build(native_catalog(args.binary, args.check))
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    outputs = {ROOT / "docs-src/catalog.json": encoded}
    outputs.update({ROOT / "docs-src" / path: content for path, content in generated_pages(document).items()})
    outputs.update(vague_term_families())
    for output, content in outputs.items():
        if args.check:
            if not output.is_file() or output.read_text() != content:
                raise SystemExit(f"{output.relative_to(ROOT)} is stale; run tools/build_site_catalog.py")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content)
    print(json.dumps(document["counts"]))


if __name__ == "__main__":
    main()
