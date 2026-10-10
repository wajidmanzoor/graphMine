"""Independent combinatorial/linear-algebra oracles, not CPU/GPU agreement.

NetworkX supplies only the graph atlas fixtures; expected outputs below do not
call its graph algorithms. Run with GRAPHMINE_TEST_DEVICE=gpu for CUDA checks.
GRAPHMINE_CASE_SHARD=0/2 and 1/2 partition fixtures across physical GPUs.
"""

import math
import os
from itertools import combinations

import networkx as nx
import numpy as np
import pytest
from graphmine import Graph, run

DEVICE = os.environ.get("GRAPHMINE_TEST_DEVICE", "cpu")
ALL_CASES = [
    (i, len(g), list(g.edges))
    for i, g in enumerate(nx.graph_atlas_g())
    if 1 <= len(g) <= 6
]
if os.environ.get("GRAPHMINE_CASE_SHARD"):
    part, count = map(int, os.environ["GRAPHMINE_CASE_SHARD"].split("/"))
    CASES = [case for i, case in enumerate(ALL_CASES) if i % count == part]
else:
    CASES = ALL_CASES

OPERATIONS = [
    "connected-components",
    "triangle-counting",
    "k-core",
    "k-truss",
    "breadth-first-search",
    "single-source-shortest-paths",
    "many-source-shortest-paths",
    "pagerank",
    "personalized-pagerank",
    "link-prediction",
    "induced-subgraph",
    "betweenness-centrality",
    "spanning-tree-forest",
]
if DEVICE == "cpu":
    OPERATIONS += [
        "k-cliques",
        "maximal-cliques",
        "maximum-clique",
        "maximum-independent-set",
        "minimum-vertex-cover",
        "maximal-independent-set",
        "vertex-coloring",
        "degree-centrality",
        "transitive-closure",
        "weighted-matching",
        "max-flow-min-cut",
        "biconnected-components",
        "overlapping-communities",
    ]


def subsets(n):
    return [frozenset(i for i in range(n) if mask >> i & 1) for mask in range(1 << n)]


def adjacency(n, edges):
    result = [set() for _ in range(n)]
    for u, v in edges:
        result[u].add(v)
        result[v].add(u)
    return result


def distances(n, edges):
    matrix = [[0 if u == v else math.inf for v in range(n)] for u in range(n)]
    for u, v in edges:
        matrix[u][v] = matrix[v][u] = 1
    for k in range(n):
        for i in range(n):
            for j in range(n):
                matrix[i][j] = min(matrix[i][j], matrix[i][k] + matrix[k][j])
    return matrix


def page_rank(n, adjacent, seed=None):
    p = np.full(n, 1 / n) if seed is None else np.eye(n)[seed]
    transition = np.zeros((n, n))
    for u in range(n):
        if adjacent[u]:
            for v in adjacent[u]:
                transition[u, v] = 1 / len(adjacent[u])
        else:
            transition[u] = p
    return np.linalg.solve(np.eye(n) - 0.85 * transition.T, 0.15 * p)


def all_simple_paths(adjacent, source, target):
    stack = [[source]]
    found = []
    while stack:
        path = stack.pop()
        if path[-1] == target:
            found.append(path)
        else:
            stack.extend([*path, v] for v in adjacent[path[-1]] if v not in path)
    return found


def component_sets(n, adjacent, removed=frozenset(), removed_edge=None):
    remaining = set(range(n)) - set(removed)
    result = set()
    while remaining:
        reached, frontier = set(), [min(remaining)]
        while frontier:
            u = frontier.pop()
            if u in reached or u in removed:
                continue
            reached.add(u)
            frontier.extend(
                v
                for v in adjacent[u]
                if frozenset((u, v)) != removed_edge and v not in removed
            )
        result.add(frozenset(reached))
        remaining -= reached
    return result


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("case", CASES, ids=lambda case: f"atlas-{case[0]}")
def test_against_independent_small_graph_oracle(operation, case):
    _, n, edges = case
    graph = Graph.from_edges(edges, vertices=list(range(n)))
    adjacent = adjacency(n, edges)
    arguments = {
        "breadth-first-search": {
            "sources": [0, n - 1],
            "source_mode": "nearest_source",
        },
        "single-source-shortest-paths": {"source": 0},
        "personalized-pagerank": {"seed_vertices": [0]},
        "k-cliques": {"k": 3, "mode": "enumerate"},
        "induced-subgraph": {"mode": "ego", "vertices_or_seeds": [0], "radius": 2},
        "max-flow-min-cut": {"source": 0, "sink": n - 1},
        "overlapping-communities": {"k": 3},
    }.get(operation, {})
    if operation == "max-flow-min-cut" and n == 1:
        from graphmine.exceptions import GraphMineError

        with pytest.raises(GraphMineError):
            run(operation, graph, parameters=arguments, device=DEVICE)
        return
    envelope = run(operation, graph, parameters=arguments, device=DEVICE)
    assert envelope["backend"]["device"] == DEVICE
    assert envelope["complete"]
    result = envelope["result"]
    if operation == "connected-components":
        assert {
            frozenset(row["vertices"]) for row in result["groups"]
        } == component_sets(n, adjacent)
    elif operation in {
        "triangle-counting",
        "k-cliques",
        "maximal-cliques",
        "maximum-clique",
    }:
        cliques = [
            s
            for s in subsets(n)
            if s and all(v in adjacent[u] for u, v in combinations(s, 2))
        ]
        if operation in {"triangle-counting", "k-cliques"}:
            expected = {s for s in cliques if len(s) == 3}
            assert result["count"] == len(expected)
            if operation == "k-cliques":
                assert {frozenset(g["vertices"]) for g in result["groups"]} == expected
        elif operation == "maximal-cliques":
            assert {frozenset(g["vertices"]) for g in result["groups"]} == {
                s for s in cliques if not any(s < t for t in cliques)
            }
        else:
            assert result["maximum_size"] == max(map(len, cliques))
    elif operation == "k-core":
        expected = [0] * n
        for s in subsets(n):
            if s:
                degree = min(len(adjacent[v] & s) for v in s)
                for v in s:
                    expected[v] = max(expected[v], degree)
        assert [row["core_number"] for row in result["vertices"]] == expected
    elif operation == "k-truss":
        expected = {frozenset(e): 2 for e in edges}
        for k in range(3, n + 1):
            active = set(expected)
            while True:
                remove = {
                    edge
                    for edge in active
                    for u, v in [tuple(edge)]
                    if sum(
                        frozenset((u, w)) in active and frozenset((v, w)) in active
                        for w in range(n)
                    )
                    < k - 2
                }
                if not remove:
                    break
                active -= remove
            for edge in active:
                expected[edge] = k
        assert {
            frozenset((e["source"], e["target"])): e["truss_number"]
            for e in result["edges"]
        } == expected
    elif operation in {
        "breadth-first-search",
        "single-source-shortest-paths",
        "many-source-shortest-paths",
        "transitive-closure",
        "induced-subgraph",
    }:
        matrix = distances(n, edges)
        if operation == "transitive-closure":
            assert result["count"] == sum(
                math.isfinite(d) for row in matrix for d in row
            )
        elif operation == "induced-subgraph":
            selected = {v for v in range(n) if matrix[0][v] <= 2}
            assert {v["id"] for v in result["graph"]["vertices"]} == selected
            assert {
                frozenset((e["source"], e["target"])) for e in result["graph"]["edges"]
            } == {frozenset(e) for e in edges if set(e) <= selected}
        else:
            for row in result["distances"]:
                target = row.get("vertex", row.get("target"))
                expected = (
                    min(matrix[0][target], matrix[n - 1][target])
                    if operation == "breadth-first-search"
                    else matrix[row.get("source", 0)][target]
                )
                assert row["distance"] == (
                    expected if math.isfinite(expected) else None
                )
                predecessor = row.get("predecessor")
                if predecessor is not None:
                    assert predecessor in adjacent[target]
    elif operation in {"pagerank", "personalized-pagerank"}:
        expected = page_rank(
            n, adjacent, 0 if operation == "personalized-pagerank" else None
        )
        np.testing.assert_allclose(
            [row["score"] for row in result["vertices"]], expected, atol=1e-8, rtol=1e-8
        )
    elif operation == "betweenness-centrality":
        expected = [0.0] * n
        for u, v in combinations(range(n), 2):
            paths = all_simple_paths(adjacent, u, v)
            if paths:
                shortest = [p for p in paths if len(p) == min(map(len, paths))]
                for w in range(n):
                    expected[w] += sum(w in p[1:-1] for p in shortest) / len(shortest)
        if n > 2:
            expected = [v * 2 / ((n - 1) * (n - 2)) for v in expected]
        np.testing.assert_allclose(
            [row["score"] for row in result["vertices"]], expected, atol=1e-7, rtol=1e-6
        )
    elif operation == "link-prediction":
        expected = {
            (u, v): len(adjacent[u] & adjacent[v]) / len(adjacent[u] | adjacent[v])
            if adjacent[u] | adjacent[v]
            else 0.0
            for u, v in combinations(range(n), 2)
            if v not in adjacent[u]
        }
        assert {(r["source"], r["target"]) for r in result["pairs"]} == set(expected)
        for row in result["pairs"]:
            assert row["score"] == pytest.approx(
                expected[row["source"], row["target"]], abs=1e-7
            )
    elif operation in {
        "maximum-independent-set",
        "minimum-vertex-cover",
        "maximal-independent-set",
    }:
        independent = [
            s
            for s in subsets(n)
            if not any(v in adjacent[u] for u, v in combinations(s, 2))
        ]
        chosen = frozenset(result["vertices"])
        if operation == "minimum-vertex-cover":
            assert len(chosen) == n - max(map(len, independent))
            assert all(chosen & set(e) for e in edges)
        else:
            assert chosen in independent
            if operation == "maximum-independent-set":
                assert len(chosen) == max(map(len, independent))
            else:
                assert not any(chosen < s for s in independent)
    elif operation == "vertex-coloring":
        colors = {r["vertex"]: r["color"] for r in result["vertices"]}
        assert set(colors) == set(range(n))
        assert all(colors[u] != colors[v] for u, v in edges)
    elif operation == "degree-centrality":
        assert [r["score"] for r in result["vertices"]] == [
            len(adjacent[v]) / max(1, n - 1) for v in range(n)
        ]
    elif operation == "spanning-tree-forest":
        assert len(result["edges"]) == n - len(component_sets(n, adjacent))
        tree = adjacency(n, [(e["source"], e["target"]) for e in result["edges"]])
        assert component_sets(n, tree) == component_sets(n, adjacent)
        assert all(e["target"] in adjacent[e["source"]] for e in result["edges"])
    elif operation == "weighted-matching":
        # Unit-weight optimum by exhaustive edge-subset enumeration.
        optimum = 0
        for size in range(n // 2 + 1):
            if any(
                len({v for e in candidate for v in e}) == size * 2
                for candidate in combinations(edges, size)
            ):
                optimum = size
        assert result["total_weight"] == optimum
        assert (
            len({v for e in result["edges"] for v in (e["source"], e["target"])})
            == len(result["edges"]) * 2
        )
    elif operation == "max-flow-min-cut":
        cuts = [
            sum((u in s) != (v in s) for u, v in edges)
            for s in subsets(n)
            if 0 in s and n - 1 not in s
        ]
        assert result["flow_value"] == result["cut_capacity"] == min(cuts)
    elif operation == "biconnected-components":
        count = len(component_sets(n, adjacent))
        expected_points = {
            v for v in range(n) if len(component_sets(n, adjacent, removed={v})) > count
        }
        expected_bridges = {
            frozenset(e)
            for e in edges
            if len(component_sets(n, adjacent, removed_edge=frozenset(e))) > count
        }
        assert set(result["articulation_points"]) == expected_points
        assert {
            frozenset((e["source"], e["target"])) for e in result["bridges"]
        } == expected_bridges
    elif operation == "overlapping-communities":
        triangles = {
            s
            for s in subsets(n)
            if len(s) == 3 and all(v in adjacent[u] for u, v in combinations(s, 2))
        }
        expected = set()
        while triangles:
            frontier = [triangles.pop()]
            members = set()
            while frontier:
                item = frontier.pop()
                members.update(item)
                neighbors = {t for t in triangles if len(item & t) >= 2}
                triangles -= neighbors
                frontier.extend(neighbors)
            expected.add(frozenset(members))
        assert {frozenset(row["vertices"]) for row in result["groups"]} == expected
