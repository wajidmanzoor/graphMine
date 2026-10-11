import math
import os
import random
from itertools import combinations

import numpy as np
import pytest
from graphmine.reference import Graph, run
from graphmine.exceptions import GraphMineError, UnsupportedOperation

DEVICE = os.environ.get("GRAPHMINE_TEST_DEVICE", "cpu")


def floyd(n, edges, directed):
    d = [[0 if u == v else math.inf for v in range(n)] for u in range(n)]
    for u, v, weight in edges:
        d[u][v] = min(d[u][v], weight)
        if not directed:
            d[v][u] = min(d[v][u], weight)
    for k in range(n):
        for u in range(n):
            for v in range(n):
                d[u][v] = min(d[u][v], d[u][k] + d[k][v])
    return d


@pytest.mark.parametrize("seed", range(64))
def test_weighted_shortest_paths(seed):
    rng = random.Random(seed)
    n = 2 + seed % 5
    directed = seed % 2 == 0
    edges = [
        (u, v, rng.randint(1, 17) / 4)
        for u in range(n)
        for v in range(n)
        if u != v and (directed or u < v) and rng.random() < 0.4
    ]
    ids = [0, "0", 2**62 + 1, "3", 4, "last"][:n]
    graph = Graph.from_edges(
        [(ids[u], ids[v], w) for u, v, w in edges], vertices=ids, directed=directed
    )
    expected = floyd(n, edges, directed)
    for source in range(n):
        result = run(
            "single-source-shortest-paths",
            graph,
            parameters={"source": ids[source]},
            device=DEVICE,
        )
        assert result["backend"]["device"] == DEVICE
        for target, row in enumerate(result["result"]["distances"]):
            assert row["vertex"] == ids[target]
            distance = expected[source][target]
            assert row["distance"] == (distance if math.isfinite(distance) else None)
            if row["predecessor"] is not None:
                predecessor = ids.index(row["predecessor"])
                weights = [
                    w
                    for u, v, w in edges
                    if (u, v) == (predecessor, target)
                    or (not directed and (v, u) == (predecessor, target))
                ]
                assert weights
                assert expected[source][predecessor] + min(weights) == distance


@pytest.mark.parametrize("mask", range(64))
def test_directed_weighted_pagerank_and_topological_sort(mask):
    arcs = [(u, v) for u in range(3) for v in range(3) if u != v]
    edges = [(u, v, (i % 3) + 1) for i, (u, v) in enumerate(arcs) if mask >> i & 1]
    graph = Graph.from_edges(edges, vertices=[0, 1, 2], directed=True)
    for personalized in (False, True):
        p = np.array([1.0, 0, 0]) if personalized else np.full(3, 1 / 3)
        transition = np.zeros((3, 3))
        for u in range(3):
            outgoing = [(v, w) for source, v, w in edges if source == u]
            if outgoing:
                for v, w in outgoing:
                    transition[u, v] = w / sum(w for _, w in outgoing)
            else:
                transition[u] = p
        expected = np.linalg.solve(np.eye(3) - 0.85 * transition.T, 0.15 * p)
        parameters = {"weight_mode": "edge_weight"}
        if personalized:
            parameters["seed_vertices"] = [0]
        result = run(
            "personalized-pagerank" if personalized else "pagerank",
            graph,
            parameters=parameters,
            device=DEVICE,
        )
        np.testing.assert_allclose(
            [r["score"] for r in result["result"]["vertices"]],
            expected,
            rtol=1e-8,
            atol=1e-8,
        )
    if DEVICE == "cpu":
        reach = floyd(3, edges, True)
        cyclic = any(math.isfinite(reach[v][u]) for u, v, _ in edges)
        if cyclic:
            with pytest.raises(GraphMineError, match="cycle"):
                run("topological-sort", graph, device="cpu")
        else:
            order = run("topological-sort", graph, device="cpu")["result"]["order"]
            assert set(order) == {0, 1, 2}
            assert all(order.index(u) < order.index(v) for u, v, _ in edges)


def forest_components(n, edges):
    parent = list(range(n))

    def root(u):
        while u != parent[u]:
            u = parent[u]
        return u

    cycle = False
    for u, v, _ in edges:
        u, v = root(u), root(v)
        if u == v:
            cycle = True
        parent[u] = v
    return {
        frozenset(v for v in range(n) if root(v) == r)
        for r in {root(v) for v in range(n)}
    }, cycle


@pytest.mark.parametrize("seed", range(64))
def test_minimum_and_maximum_weighted_forests(seed):
    rng = random.Random(seed)
    n = 2 + seed % 4
    edges = [
        (u, v, rng.randint(-5, 12) / 2)
        for u, v in combinations(range(n), 2)
        if rng.random() < 0.65
    ]
    graph = Graph.from_edges(edges, vertices=list(range(n)))
    components, _ = forest_components(n, edges)
    valid = [
        candidate
        for candidate in combinations(edges, n - len(components))
        if forest_components(n, candidate) == (components, False)
    ]
    totals = [sum(w for _, _, w in tree) for tree in valid]
    for objective, expected in [("minimum", min(totals)), ("maximum", max(totals))]:
        envelope = run(
            "spanning-tree-forest",
            graph,
            parameters={"objective": objective},
            device=DEVICE,
        )
        assert envelope["backend"]["device"] == DEVICE
        result = envelope["result"]
        assert result["vertices"] == list(range(n))
        assert result["total_weight"] == expected
        selected = [(e["source"], e["target"], e["weight"]) for e in result["edges"]]
        assert forest_components(n, selected) == (components, False)


def test_precision_limit_preserves_exact_cpu_integer_distances():
    graph = Graph.from_edges([(0, 1, 2**53 + 1)], vertices=[0, 1], directed=True)
    cpu = run(
        "single-source-shortest-paths", graph, parameters={"source": 0}, device="cpu"
    )
    assert cpu["result"]["distances"][1]["distance"] == 2**53 + 1
    with pytest.raises(UnsupportedOperation, match="float64"):
        run(
            "single-source-shortest-paths",
            graph,
            parameters={"source": 0},
            device="gpu",
        )


def test_zero_weight_edges_are_not_removed():
    graph = Graph.from_edges(
        [(0, 1, 0), (1, 2, 0), (0, 2, 3)], vertices=[0, 1, 2], directed=True
    )
    result = run(
        "single-source-shortest-paths", graph, parameters={"source": 0}, device=DEVICE
    )
    assert [r["distance"] for r in result["result"]["distances"]] == [0, 0, 0]
