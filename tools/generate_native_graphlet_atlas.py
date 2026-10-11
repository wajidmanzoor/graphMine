#!/usr/bin/env python3
"""Freeze mathematical graph-atlas data; never invoked by the native runtime."""

import hashlib
import inspect
import json
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]


def main():
    patterns = []
    for index, graph in enumerate(nx.graph_atlas_g()):
        if len(graph) < 2 or not nx.is_connected(graph):
            continue
        union = nx.utils.UnionFind(graph)
        for mapping in nx.algorithms.isomorphism.GraphMatcher(
            graph, graph
        ).isomorphisms_iter():
            for vertex, image in mapping.items():
                union.union(vertex, image)
        orbits = sorted(
            (sorted(group) for group in union.to_sets()), key=lambda group: group[0]
        )
        patterns.append(
            {
                "id": f"atlas-{index}",
                "vertices": len(graph),
                "edges": sorted([sorted(edge) for edge in graph.edges]),
                "orbits": orbits,
            }
        )
    source = Path(inspect.getfile(nx.generators.atlas))
    result = {
        "schema_version": 1,
        "description": "Complete connected simple undirected graph atlas for orders 2 through 7, with exact automorphism orbits. Static mathematical data only; native C++ performs classification and counting.",
        "source": "NetworkX graph_atlas_g; https://networkx.org/documentation/stable/reference/generated/networkx.generators.atlas.graph_atlas_g.html",
        "networkx_version": nx.__version__,
        "generator_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "generator_script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "patterns": patterns,
    }
    path = ROOT / "library/manifests/graphlet_atlas.json"
    path.write_text(json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n")
    print(f"Wrote {len(patterns)} connected graph classes to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
