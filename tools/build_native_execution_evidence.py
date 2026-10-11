#!/usr/bin/env python3
"""Build the application's native evidence gate from completed oracle reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python/graphmine"))
from graphmine.evidence import profile_hash, sha, verify_report

SUITES = {
    "runtime": {"bfs": ["breadth-first-search"], "triangles": ["triangle-counting"]},
    "reference": {
        "paths": ["single-source-shortest-paths", "many-source-shortest-paths"],
        "forests": ["spanning-tree-forest"],
        "connectivity": ["connected-components", "topological-sort"],
        "rank": ["pagerank", "personalized-pagerank"],
        "similarity": ["link-prediction"],
    },
    "structure": {"truss": ["k-truss"], "blocks": ["biconnected-components"]},
    "centrality": {
        "degree": ["degree-centrality"],
        "betweenness": ["betweenness-centrality"],
        "weighted": ["betweenness-centrality"],
    },
    "matching": {
        "general": ["weighted-matching"],
        "bipartite": ["bipartite-matching"],
        "assignment": ["bipartite-matching"],
    },
    "flow": {
        "edges": ["max-flow-min-cut"],
        "vertices": ["max-flow-min-cut"],
        "structures": ["max-flow-min-cut"],
        "structure": ["max-flow-min-cut"],
    },
    "mining": {
        "maximal": ["maximal-cliques"],
        "maximum": ["maximum-clique"],
        "fixed": ["k-cliques"],
        "core": ["k-core"],
        "optimization": ["maximum-independent-set", "minimum-vertex-cover"],
    },
    "selection": {
        "independent": ["maximal-independent-set"],
        "coloring": ["vertex-coloring"],
        "subgraphs": ["induced-subgraph"],
        "walks": ["random-walks"],
        "sampling": ["neighborhood-sampling"],
    },
}


def record(path, metadata, kind):
    meta = json.loads(metadata.read_text())
    if kind == "junit":
        document = ET.parse(path).getroot()
        suites = (
            [document] if document.tag == "testsuite" else document.findall("testsuite")
        )
        passed = sum(int(s.attrib["tests"]) for s in suites)
    else:
        passed = sum(row["passed_requests"] for row in json.loads(path.read_text()))
    return {
        "id": str(path.relative_to(ROOT)),
        "report": str(path.relative_to(ROOT)),
        "metadata": str(metadata.relative_to(ROOT)),
        "format": kind,
        "passed": passed,
        "device": meta["device"],
        "artifacts": {str(p.relative_to(ROOT)): sha(p) for p in (path, metadata)},
    }


def build_record(build, source_root, directory, junit):
    catalog = json.loads(
        subprocess.check_output([build / "graphmine-native", "catalog"])
    )
    library = build / "libgraphmine_runtime.so"
    inventory = (build / "native-source-hashes.txt").read_text()
    assert (
        hashlib.sha256(inventory.encode()).hexdigest()
        == catalog["implementation_sha256"]
    )
    sources, isolated = {}, {}
    for line in inventory.splitlines():
        name, digest = line.rsplit(":", 1)
        compiled = (source_root / "library" / name).resolve()
        assert sha(compiled) == digest, compiled
        relative = str(compiled.relative_to(source_root))
        current = ROOT / relative
        working = sha(current)
        if working != digest:
            assert relative == "library/CMakeLists.txt", (
                f"Compiled source differs from checkout: {relative}"
            )
            # Preserve the exact isolated recipe alongside the evidence rather
            # than discarding unrelated build-system changes in the workspace.
            recipe = directory / "isolated-library-CMakeLists.txt"
            recipe.write_bytes(compiled.read_bytes())
            isolated[relative] = {
                "compiled_sha256": digest,
                "working_sha256": working,
                "recipe": str(recipe.relative_to(ROOT)),
            }
            sources[str(recipe.relative_to(ROOT))] = digest
        sources[relative] = working
    linkage = subprocess.check_output(["ldd", library], text=True)
    assert "not found" not in linkage
    dependencies = {
        str(Path(name).resolve()): sha(Path(name).resolve())
        for name in re.findall(r"=> (/\S+)", linkage)
    }
    reports, observed = [], {}
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".metadata.json"):
            continue
        metadata = path.with_suffix(".json.metadata.json")
        if not metadata.is_file():
            continue
        report = record(path, metadata, "native_suites")
        checked = verify_report(
            ROOT, report, catalog["implementation_sha256"], sha(library)
        )
        assert checked["status"] == "passed", checked
        reports.append(report)
        group = path.stem.split("-")[0]
        if group in {"cpu", "gpu"}:
            group = "runtime"
        assert group in SUITES, group
        for row in json.loads(path.read_text()):
            backend = (
                "cpp"
                if report["device"] == "cpu"
                else ("libcugraph" if row["backend"] == "gpu" else row["backend"])
            )
            for operation in SUITES[group].get(row["suite"], []):
                observed.setdefault(operation, {}).setdefault(backend, set()).add(
                    report["id"]
                )
    for path in junit:
        metadata = Path(str(path) + ".native.metadata.json")
        report = record(path, metadata, "junit")
        checked = verify_report(
            ROOT, report, catalog["implementation_sha256"], sha(library)
        )
        assert checked["status"] == "passed", checked
        reports.append(report)
        for key, count in json.loads(metadata.read_text())[
            "observed_operations"
        ].items():
            operation, backend = key.rsplit(":", 1)
            assert count > 0
            observed.setdefault(operation, {}).setdefault(backend, set()).add(
                report["id"]
            )
    profiles = {}
    for card in catalog["operations"]:
        profiles[card["id"]] = {
            "profile_sha256": profile_hash(card),
            "backends": {
                backend["id"]: sorted(
                    observed.get(card["id"], {}).get(backend["id"], set())
                )
                for backend in card["backends"]
                if backend["compiled"]
            },
        }
        assert profiles[card["id"]]["backends"]["cpp"], (
            f"No CPU oracle evidence: {card['id']}"
        )
    return {
        "id": build.name,
        "implementation_sha256": catalog["implementation_sha256"],
        "binary_sha256": sha(library),
        "native_library": str(library),
        "sources": sources,
        "isolated_build_recipes": isolated,
        "dependencies": dependencies,
        "workers": {
            str(p): sha(p)
            for p in (build / "optimization-workers").glob("graphmine-worker-*")
        },
        "profiles": profiles,
        "reports": reports,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--junit", type=Path, action="append", required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "catalog/native_execution_evidence.json"
    )
    args = parser.parse_args()
    entry = build_record(
        args.build.resolve(),
        args.source_root.resolve(),
        args.reports.resolve(),
        [p.resolve() for p in args.junit],
    )
    data = (
        json.loads(args.output.read_text())
        if args.output.is_file()
        else {
            "schema_version": 1,
            "scope": "Independent native evidence for executable application profiles",
            "builds": [],
            "known_failures": [],
        }
    )
    data["builds"] = [
        build
        for build in data["builds"]
        if build["implementation_sha256"] != entry["implementation_sha256"]
    ] + [entry]
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print(
        json.dumps(
            {
                "native_profiles": len(entry["profiles"]),
                "build": entry["id"],
                "reports": len(entry["reports"]),
            }
        )
    )


if __name__ == "__main__":
    main()
