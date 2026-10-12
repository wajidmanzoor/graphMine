#!/usr/bin/env python3
"""Freeze fresh variations and verify independent answers before model exposure."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from evaluate_analytics_holdout import check_value, digest


def graph(name, vertices, edges, *, directed=False):
    return {
        "graph": {
            "id": name,
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": v} for v in vertices],
        "edges": [
            {"id": f"e{i}", "source": u, "target": v, "weight": w}
            for i, (u, v, w) in enumerate(edges)
        ],
    }


def build():
    cases = []

    def add(name, question, data, requests, checks, *, dependency=None, required=None):
        cases.append(
            {
                "id": name,
                "question": question,
                "input": data,
                "operations": [r["operation"] for r in requests],
                "expected_status": "ready",
                "checks": checks,
                "required_parameters": required or {},
                "required_graph_dependency": dependency or {},
                "oracle_requests": requests,
            }
        )

    def check(operation, port, kind, value):
        return {"operation": operation, "port": port, "kind": kind, "value": value}

    for i, pairs in enumerate(
        [
            [(0, 1), (1, 2), (2, 3)],
            [(0, 1), (0, 2), (0, 3), (0, 4)],
            [(0, 1), (1, 2), (2, 0), (3, 4)],
        ]
    ):
        vertices = [f"site-{i}-{c}" for c in "ABCDEF"]
        data = graph(
            f"fresh-cover-{i}",
            vertices,
            [(vertices[u], vertices[v], 1) for u, v in pairs],
        )
        covers = []
        for size in range(len(vertices) + 1):
            covers = [
                list(s)
                for s in itertools.combinations(vertices, size)
                if all(vertices[u] in s or vertices[v] in s for u, v in pairs)
            ]
            if covers:
                break
        wording = [
            "Choose the fewest sites so that each connection has at least one chosen endpoint. I need a global optimum with no size bound.",
            "Place inspectors at the smallest possible set of sites that touches every link. Solve this exactly, with no limit k.",
            "Return one exact minimum vertex cover, including all disconnected parts of the network in the optimization.",
        ][i]
        add(
            f"fresh_cover_{i}",
            wording,
            data,
            [{"operation": "minimum-vertex-cover", "parameters": {}}],
            [check("minimum-vertex-cover", "vertices", "one_of_sets", covers)],
        )

    for i, directed in enumerate([True, False, True]):
        vertices = [f"depot-{i}-{c}" for c in "PQRSZ"]
        pairs = [
            (0, 1, 7),
            (0, 2, 1.5),
            (2, 1, 0.5),
            (1, 3, 0 if i == 2 else 2),
            (2, 3, 9),
        ]
        data = graph(
            f"fresh-costs-{i}",
            vertices,
            [(vertices[u], vertices[v], w) for u, v, w in pairs],
            directed=directed,
        )
        source = vertices[0] if i != 1 else vertices[3]
        distances = {v: math.inf for v in vertices}
        distances[source] = 0
        for _ in vertices:
            for e in data["edges"]:
                u, v, w = e["source"], e["target"], e["weight"]
                distances[v] = min(distances[v], distances[u] + w)
                if not directed:
                    distances[u] = min(distances[u], distances[v] + w)
        expected = {v: None if math.isinf(d) else d for v, d in distances.items()}
        add(
            f"fresh_costs_{i}",
            f"For every depot, compute the lowest total travel cost from {source}. Edge weights are costs, not hop counts. Respect the graph direction and do not apply a cutoff.",
            data,
            [
                {
                    "operation": "single-source-shortest-paths",
                    "parameters": {"source": source},
                }
            ],
            [check("single-source-shortest-paths", "distances", "scores", expected)],
            required={"single-source-shortest-paths": {"source": source}},
        )

    for i, direction in enumerate(["in", "out", "both"]):
        vertices = [f"member-{i}-{c}" for c in "WXYZ"]
        pairs = [(0, 1), (2, 1), (1, 3)]
        directed = direction != "both"
        data = graph(
            f"fresh-neighbors-{i}",
            vertices,
            [(vertices[u], vertices[v], 1) for u, v in pairs],
            directed=directed,
        )
        entity = vertices[1]
        neighbors = sorted(
            {
                e["source"]
                for e in data["edges"]
                if e["target"] == entity and direction in {"in", "both"}
            }
            | {
                e["target"]
                for e in data["edges"]
                if e["source"] == entity and direction in {"out", "both"}
            }
        )
        wording = {
            "in": f"Which members have a direct edge pointing into {entity}? Return all incoming neighbors at one hop, excluding the member itself.",
            "out": f"List every member directly reached by following one outgoing edge from {entity}. Exclude the starting member.",
            "both": f"Show all immediate neighbors of {entity} in this undirected network; exclude the starting member.",
        }[direction]
        params = {
            "entity": entity,
            "hops": 1,
            "direction": direction,
            "include_seed": False,
        }
        add(
            f"fresh_neighbors_{i}",
            wording,
            data,
            [{"operation": "neighbors", "parameters": params}],
            [check("neighbors", "vertices", "set", neighbors)],
            required={"neighbors": params},
        )

    vertices = ["lab-A", "lab-B", "lab-C", "lab-D", "lab-E", "lab-F"]
    pairs = [(0, 1), (1, 2), (0, 2), (2, 3), (3, 4), (2, 4)]
    data = graph(
        "fresh-derived", vertices, [(vertices[u], vertices[v], 1) for u, v in pairs]
    )
    edges = {frozenset((vertices[u], vertices[v])) for u, v in pairs}
    for i, indices in enumerate([[0, 1, 3, 5], [0, 1, 2, 5], [2, 3, 4]]):
        selected = [vertices[j] for j in indices]
        triangles = sum(
            all(frozenset(pair) in edges for pair in itertools.combinations(triple, 2))
            for triple in itertools.combinations(selected, 3)
        )
        requests = [
            {
                "operation": "query-subgraph",
                "parameters": {"mode": "vertices", "vertices": selected},
            },
            {
                "operation": "triangle-counting",
                "parameters": {},
                "graph_from": "query-subgraph",
            },
        ]
        add(
            f"fresh_derived_{i}",
            f"First use query-subgraph in vertex mode to keep only {', '.join(selected)} and their connecting edges. Then return the triangle count for that extracted graph, not the original network.",
            data,
            requests,
            [
                check("query-subgraph", "vertices", "set", selected),
                check("triangle-counting", "count", "equal", triangles),
            ],
            dependency={"triangle-counting": "query-subgraph"},
        )
    selected = [vertices[j] for j in [0, 1, 3, 5]]
    all_triangles = sum(
        all(frozenset(pair) in edges for pair in itertools.combinations(triple, 2))
        for triple in itertools.combinations(vertices, 3)
    )
    add(
        "fresh_independent_scope",
        f"Give me two independent outputs: use query-subgraph in vertex mode to extract only {', '.join(selected)}; separately count all triangles in the original full network. The triangle calculation must not use the extracted graph.",
        data,
        [
            {
                "operation": "query-subgraph",
                "parameters": {"mode": "vertices", "vertices": selected},
            },
            {"operation": "triangle-counting", "parameters": {}},
        ],
        [
            check("query-subgraph", "vertices", "set", selected),
            check("triangle-counting", "count", "equal", all_triangles),
        ],
    )
    return {
        "version": "planner-recovery-fresh-20261011-v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Thirteen assistant-authored cases: twelve variations of four known failure categories and an independent-input scope control. Frozen and independently checked before model exposure. New data/wording; targeted local generalization check, not a public benchmark or human evaluation.",
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--oracles", type=Path, required=True)
    args = parser.parse_args()
    if args.suite.exists() or args.oracles.exists():
        raise ValueError("Refusing to overwrite a frozen suite or oracle report")
    suite = build()
    from graphmine.native import NativeLibrary

    library = NativeLibrary()
    evidence = []
    for case in suite["cases"]:
        results = {}
        for request in case["oracle_requests"]:
            data = (
                case["input"]
                if not request.get("graph_from")
                else results[request["graph_from"]]["ports"]["graph"]["value"]
            )
            results[request["operation"]] = library.run(
                request["operation"],
                data,
                parameters=request["parameters"],
                device="cpu",
            )
        checks = [
            check_value(c, results[c["operation"]]["ports"][c["port"]])
            for c in case["checks"]
        ]
        assert all(checks), case["id"]
        evidence.append({"id": case["id"], "checks": checks})
    args.suite.parent.mkdir(parents=True, exist_ok=True)
    args.suite.write_text(json.dumps(suite, indent=2, allow_nan=False) + "\n")
    args.oracles.write_text(
        json.dumps(
            {
                "suite_sha256": digest(suite),
                "generator_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "implementation_sha256": library.catalog()["implementation_sha256"],
                "passed": len(evidence),
                "cases": evidence,
            },
            indent=2,
        )
        + "\n"
    )
    print("Frozen and checked", len(evidence), "cases", digest(suite))


if __name__ == "__main__":
    main()
