#!/usr/bin/env python3
"""Independent public-CLI oracle checks for the nine promoted GPU repairs."""

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import random
import re
import subprocess
from pathlib import Path

import networkx as nx
import numpy as np

HERE = Path(__file__).resolve().parent


def graph(n, edges, directed=False, left=None, weighted=False):
    ids = [
        i * 7 - 3 if i % 2 == 0 else ("0" if i == 1 else f"vertex {i}")
        for i in range(n)
    ]
    data = {
        "graph": {
            "id": "integration",
            "directed": directed,
            "allows_self_loops": True,
            "allows_parallel_edges": True,
        },
        "vertices": [{"id": v} for v in ids],
        "edges": [],
    }
    if left is not None:
        for i, v in enumerate(data["vertices"]):
            v["attributes"] = {"side": "left" if i < left else "right"}
    for i, edge in enumerate(edges):
        u, v = edge[:2]
        row = {
            "id": i if i % 2 == 0 else f"edge {i}",
            "source": ids[u],
            "target": ids[v],
        }
        if weighted:
            row["weight"] = edge[2]
        data["edges"].append(row)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument(
        "--suite", choices=["quick", "full", "sanitizer"], default="full"
    )
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "1", "OPENBLAS_NUM_THREADS": "1"}
    results = []

    def run(name, operation, data, options=(), reject=False, verify=None):
        path = work / (name + ".json")
        path.write_text(json.dumps(data) + "\n")
        command = [
            str(binary),
            "run",
            operation,
            "--graph",
            str(path),
            *map(str, options),
        ]
        if args.suite == "sanitizer" and not reject:
            command = [
                "compute-sanitizer",
                "--tool",
                "memcheck",
                "--target-processes",
                "all",
                "--error-exitcode",
                "97",
                "--log-file",
                str(work / (name + "-memcheck.log")),
                *command,
            ]
        record = {
            "name": name,
            "operation": operation,
            "kind": "rejection" if reject else "correctness",
            "command": command,
        }
        try:
            process = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            (work / (name + ".log")).write_text(process.stdout + process.stderr)
            try:
                payload = json.loads(process.stdout)
            except json.JSONDecodeError:
                # CLI syntax/semantic option errors use the established stderr
                # usage-error contract; native execution failures return JSON.
                assert reject and process.returncode != 0 and process.stderr.strip(), (
                    process.stdout
                )
                payload = {"ok": False, "error": {"message": process.stderr.strip()}}
            record.update(exit=process.returncode, result=payload)
            if reject:
                assert process.returncode != 0 and payload["ok"] is False, payload
            else:
                assert process.returncode == 0 and payload["ok"] is True, payload
                if verify:
                    verify(payload["output"])
                if args.suite == "sanitizer":
                    text = (work / (name + "-memcheck.log")).read_text()
                    assert "ERROR SUMMARY: 0 errors" in text and not re.search(
                        r"ERROR SUMMARY: [1-9]", text
                    ), text
            record["passed"] = True
        except Exception as error:  # noqa: BLE001 - retain each failed oracle result
            record.update(passed=False, error=str(error))
        results.append(record)
        (work / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        if not record["passed"]:
            print("FAIL", name, record["error"][:600], flush=True)

    def eq(condition, detail="oracle mismatch"):
        assert condition, detail

    def plain_case(name, n, edges):
        data = graph(n, edges)
        ids = [v["id"] for v in data["vertices"]]
        g = nx.Graph()
        g.add_nodes_from(range(n))
        g.add_edges_from((u, v) for u, v in edges if u != v)
        expected = {}
        for k in range(2, n + 1):
            for u, v in nx.k_truss(g, k).edges():
                expected[tuple(sorted((u, v)))] = k
        representatives = {}
        for e, (u, v) in zip(data["edges"], edges):
            if u == v:
                continue
            key = tuple(sorted((u, v)))
            if key not in representatives:
                representatives[key] = e["id"]
        truss = {
            (type(representatives[e]).__name__, str(representatives[e])): k
            for e, k in expected.items()
        }

        def check_truss(out):
            actual = {
                (type(e["edge"]).__name__, str(e["edge"])): e["truss_number"]
                for e in out["truss_number_by_edge"]
            }
            eq(
                actual == truss and len(out["truss_number_by_edge"]) == len(truss),
                (actual, truss),
            )
            eq(out["maximum_truss_number"] == max(expected.values(), default=0))

        run(name + "-truss", "k-truss", data, verify=check_truss)
        if n:
            subsets = [
                [i for i in range(n) if mask >> i & 1] for mask in range(1, 1 << n)
            ]
            best = max(len(g.subgraph(s).edges()) / len(s) for s in subsets)

            def check_density(out):
                chosen = [ids.index(v) for v in out["vertices"]]
                eq(len(chosen) == len(set(chosen)) > 0)
                count = len(g.subgraph(chosen).edges())
                eq(
                    out["induced_edge_value"] == count
                    and out["density"] == count / len(chosen)
                )
                eq(out["density"] == best and out["optimal"])

            run(name + "-density", "densest-subgraph", data, verify=check_density)
        optimum = max(map(len, nx.find_cliques(g)), default=0)

        def check_clique(out):
            eq(out["maximum_size"] == optimum and out["optimal"], out)
            for c in out["cliques"]:
                chosen = [ids.index(v) for v in c]
                eq(len(chosen) == len(set(chosen)) == optimum)
                eq(all(g.has_edge(u, v) for u, v in itertools.combinations(chosen, 2)))

        for backend in ["cuda-ms", "maximum-clique-on-gpu"]:
            run(
                name + "-" + backend,
                "maximum-clique",
                data,
                ["--backend", backend],
                verify=check_clique,
            )

    if args.suite == "full":
        pairs = list(itertools.combinations(range(4), 2))
        for mask in range(64):
            plain_case(
                "simple4-" + str(mask),
                4,
                [e for i, e in enumerate(pairs) if mask >> i & 1],
            )
        rng = random.Random(20261005)
        for i in range(16):
            n = 5 + i % 4
            plain_case(
                "random-" + str(i),
                n,
                [
                    e
                    for e in itertools.combinations(range(n), 2)
                    if rng.random() < (i + 1) / 18
                ],
            )
        plain_case("empty", 0, [])
        plain_case("duplicates-loops", 5, [(0, 1), (0, 1), (1, 2), (2, 0), (4, 4)])
    else:
        plain_case("triangle-isolate", 4, [(0, 1), (1, 2), (2, 0)])

    for i, (left, right, pairs) in enumerate(
        [
            (3, 3, []),
            (2, 3, [(0, 2)]),
            (2, 2, [(u, v) for u in range(2) for v in range(2, 4)]),
            (4, 4, [(u, v) for u in range(4) for v in range(4, 8) if u != v - 4]),
            (3, 4, [(u, v) for u in range(3) for v in range(3, 7)]),
        ]
    ):
        if args.suite == "sanitizer" and i != 2:
            continue
        data = graph(left + right, pairs, left=left)
        neighborhoods = [
            {u for u, v in pairs if v == r} for r in range(left, left + right)
        ]
        closed = set()
        for row in neighborhoods:
            closed |= {frozenset(row)} | {
                frozenset(row & previous) for previous in closed
            }
            closed.discard(frozenset())
        butterflies = sum(
            math.comb(len(a & b), 2)
            for a, b in itertools.combinations(neighborhoods, 2)
        )
        run(
            f"bipartite-{i}-mbe",
            "maximal-biclique-counting",
            data,
            verify=lambda out, expected=closed: eq(
                out["total_count"] == len(expected) and out["complete"], out
            ),
        )
        run(
            f"bipartite-{i}-gamma",
            "butterfly-counting",
            data,
            ["--backend", "gamma-butterfly"],
            verify=lambda out, count=butterflies: eq(
                out["butterfly_count"] == count and out["complete"], out
            ),
        )

    ppr_cases = [
        (1, []),
        (4, []),
        (5, [(i, (i + 1) % 5) for i in range(5)]),
        (5, [(0, 1), (0, 1), (1, 1), (1, 2), (3, 4)]),
        (7, [(i, i + 1) for i in range(6)]),
    ]
    for i, (n, edges) in enumerate(ppr_cases):
        if args.suite == "sanitizer" and i != 4:
            continue
        data = graph(n, edges, directed=True)
        ids = [v["id"] for v in data["vertices"]]
        seed = 0
        matrix = np.zeros((n, n))
        for u, v in edges:
            matrix[u, v] += 1
        for u in range(n):
            if matrix[u].sum():
                matrix[u] /= matrix[u].sum()
            else:
                matrix[u, seed] = 1
        restart = np.zeros(n)
        restart[seed] = 0.2
        expected = np.linalg.solve(np.eye(n) - 0.8 * matrix.T, restart)

        def check_ppr(out, expected=expected, ids=ids):
            rows = out["ranked_vertices"]
            eq(len(rows) == len(ids) and out["complete"])
            eq(
                out["restart_probability_used"] == 0.2
                and out["approximate"]
                and not out["error_bound_certified"]
            )
            for row in rows:
                actual = expected[ids.index(row["vertex"])]
                eq(
                    abs(actual - row["score"])
                    <= 0.01 * max(actual, 1 / len(ids)) + 2e-10,
                    (actual, row),
                )
            eq(all(a["score"] >= b["score"] for a, b in itertools.pairwise(rows)))

        run(
            f"ppr-{i}",
            "personalized-pagerank",
            data,
            [
                "--seed-vertex",
                json.dumps(ids[seed]),
                "--top-k",
                n,
                "--restart-probability",
                ".2",
            ],
            verify=check_ppr,
        )

    for i, (n, edges, groups) in enumerate(
        [
            (4, [(0, 1, 2), (1, 2, 3), (2, 3, 4), (0, 3, 20)], [[0], [3]]),
            (4, [(0, 1, 0), (1, 2, 0), (2, 3, 8)], [[0, 1], [1, 3]]),
            (4, [(0, 1, 1)], [[0], [3]]),
            (3, [(0, 1, 2**31), (1, 2, 17)], [[0], [2]]),
            (3, [(0, 1, 8), (0, 1, 2), (1, 2, 1)], [[0], [2], [1, 2]]),
        ]
    ):
        if args.suite == "sanitizer" and i != 0:
            continue
        data = graph(n, edges, weighted=True)
        ids = [v["id"] for v in data["vertices"]]
        g = nx.Graph()
        g.add_nodes_from(range(n))
        for u, v, w in edges:
            g.add_edge(u, v, weight=min(w, g.get_edge_data(u, v, {}).get("weight", w)))
        optimum = None
        for mask in range(1, 1 << n):
            selected = {v for v in range(n) if mask >> v & 1}
            if all(
                selected.intersection(group) for group in groups
            ) and nx.is_connected(g.subgraph(selected)):
                cost = sum(
                    e[2]["weight"]
                    for e in nx.minimum_spanning_tree(g.subgraph(selected)).edges(
                        data=True
                    )
                )
                optimum = cost if optimum is None else min(cost, optimum)

        def check_tree(out, expected=optimum, data=data, groups=groups, ids=ids):
            eq(out["optimal"] and out["feasible"] == (expected is not None), out)
            if expected is None:
                eq(out["tree_edges"] == [] and out["selected_vertices"] == [])
                return
            eq(out["tree_weight"] == expected, out)
            chosen = {ids.index(v) for v in out["selected_vertices"]}
            eq(all(chosen.intersection(group) for group in groups))
            selected_edges = [e for e in data["edges"] if e["id"] in out["tree_edges"]]
            tree = nx.Graph()
            tree.add_nodes_from(chosen)
            tree.add_edges_from(
                (ids.index(e["source"]), ids.index(e["target"])) for e in selected_edges
            )
            eq(
                nx.is_tree(tree)
                and sum(e["weight"] for e in selected_edges) == expected
            )

        run(
            f"gst-{i}",
            "group-steiner-tree",
            data,
            ["--groups", json.dumps([[ids[v] for v in group] for group in groups])],
            verify=check_tree,
        )

    spec = importlib.util.spec_from_file_location(
        "superfuser_oracle", HERE.parent / "algorithm_repairs/superfuser/validate.py"
    )
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    for i, (n, edges, k) in enumerate(
        [
            (8, [(v, v + 1, 1) for v in range(7)], 1),
            (4, [], 4),
            (4, [(0, 1, 0.5), (1, 2, 0.5), (0, 2, 0.25), (2, 3, 0.75)], 2),
            (3, [(0, 1, 0.5), (0, 1, 0.5), (1, 2, 1), (0, 0, 1)], 1),
        ]
    ):
        if args.suite == "sanitizer" and i != 2:
            continue
        data = graph(n, edges, directed=True, weighted=True)
        ids = [v["id"] for v in data["vertices"]]

        def check_influence(out, n=n, edges=edges, k=k, ids=ids):
            seeds = [ids.index(v) for v in out["seed_set"]]
            eq(len(seeds) == len(set(seeds)) == k and not out["guarantee_met"])
            expected = oracle.prefix_spread(
                oracle.ensemble(n, edges, 256, oracle.mix(42 ^ oracle.EVAL_KEY)), seeds
            )
            eq(
                out["prefix_spread"] == expected
                and out["expected_spread"] == expected[-1],
                (out, expected),
            )

        run(
            f"influence-{i}",
            "influence-maximization",
            data,
            ["--diffusion-model", "independent_cascade", "--seed-set-size", k],
            verify=check_influence,
        )

    if args.suite != "sanitizer":
        plain = graph(3, [(0, 1), (1, 2)])
        weighted = graph(3, [(0, 1, 0.5), (1, 2, 1)], directed=True, weighted=True)
        for operation in ["k-truss", "densest-subgraph", "maximal-biclique-counting"]:
            run(
                "reject-direction-" + operation,
                operation,
                graph(3, [(0, 1)], directed=True),
                reject=True,
            )
        run(
            "reject-gamma-sides",
            "butterfly-counting",
            plain,
            ["--backend", "gamma-butterfly"],
            reject=True,
        )
        run("reject-biclique-sides", "maximal-biclique-counting", plain, reject=True)
        run("reject-empty-density", "densest-subgraph", graph(0, []), reject=True)
        for name, options in [
            ("alpha", ["--restart-probability", ".15"]),
            (
                "quality",
                [
                    "--restart-probability",
                    ".2",
                    "--solution-quality",
                    "exact_or_converged",
                ],
            ),
            ("epsilon", ["--restart-probability", ".2", "--epsilon", "nan"]),
        ]:
            run(
                "reject-ppr-" + name,
                "personalized-pagerank",
                graph(3, [(0, 1)], directed=True),
                ["--seed-vertex", "-3", "--top-k", "2", *options],
                reject=True,
            )
        for name, groups in [
            ("empty", []),
            ("empty-group", [[]]),
            ("missing", [["absent"]]),
            ("too-many", [[-3]] * 17),
            ("bool", [[True]]),
        ]:
            run(
                "reject-groups-" + name,
                "group-steiner-tree",
                graph(3, [(0, 1, 2)], weighted=True),
                ["--groups", json.dumps(groups)],
                reject=True,
            )
        for name, probability in [("negative", -0.1), ("large", 1.1)]:
            run(
                "reject-probability-" + name,
                "influence-maximization",
                graph(2, [(0, 1, probability)], directed=True, weighted=True),
                ["--diffusion-model", "independent_cascade", "--seed-set-size", 1],
                reject=True,
            )
        for name, extra in [
            ("guarantee", ["--require-guarantee"]),
            ("samples", ["--sample-count", "33"]),
            ("overflow", ["--seed-set-size", "9"]),
            ("linear-threshold", ["--diffusion-model", "linear_threshold"]),
        ]:
            options = [
                "--diffusion-model",
                "independent_cascade",
                "--seed-set-size",
                "1",
            ]
            if extra[0] in options:
                options[options.index(extra[0]) + 1] = extra[1]
            else:
                options += extra
            run(
                "reject-influence-" + name,
                "influence-maximization",
                weighted,
                options,
                reject=True,
            )
        run(
            "reject-worker-directory",
            "k-truss",
            plain,
            ["--worker-directory", str(work / "missing-workers")],
            reject=True,
        )

    summary = {
        "status": "passed" if all(r["passed"] for r in results) else "failed",
        "checks": len(results),
        "passed": sum(r["passed"] for r in results),
        "failures": sum(not r["passed"] for r in results),
        "rejection_checks": sum(r["kind"] == "rejection" for r in results),
        "suite": args.suite,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    raise SystemExit(bool(summary["failures"]))


if __name__ == "__main__":
    main()
