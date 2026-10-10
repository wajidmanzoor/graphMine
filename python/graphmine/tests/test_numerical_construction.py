"""Equation, path-enumeration and finite-field oracles for new CPU profiles."""

import math
import random
from itertools import combinations, product

import networkx as nx
import numpy as np
import pytest
from graphmine import FeatureVectors, Graph, Hypergraph, run
from graphmine.exceptions import GraphMineError

ATLAS = [
    (i, len(g), tuple(g.edges))
    for i, g in enumerate(nx.graph_atlas_g())
    if 1 <= len(g) <= 6
]


def execute(operation, graph, **arguments):
    result = run(operation, graph, device="cpu", parameters=arguments)
    assert result["backend"]["device"] == "cpu"
    return result


def laplacian(n, edges, normalized=False):
    result = np.zeros((n, n))
    degree = np.zeros(n)
    for u, v, w in edges:
        result[u, v] -= w
        result[v, u] -= w
        degree[u] += w
        degree[v] += w
    for i in range(n):
        result[i, i] = degree[i]
    if normalized:
        for i in range(n):
            for j in range(n):
                result[i, j] = (
                    result[i, j] / math.sqrt(degree[i] * degree[j])
                    if degree[i] * degree[j]
                    else 0
                )
    return result


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("normalized", [False, True])
def test_laplacian_equations_selection_and_isolates(case, normalized):
    _, n, pairs = case
    edges = [(u, v, (u + v) % 4) for u, v in pairs]
    matrix = laplacian(n, edges, normalized)
    expected = np.linalg.eigvalsh(matrix)
    graph = Graph.from_edges(edges, vertices=range(n))
    for selection in ("smallest", "largest"):
        k = max(1, n // 2)
        result = execute(
            "laplacian-eigenpairs",
            graph,
            num_eigenpairs=k,
            laplacian="symmetric_normalized" if normalized else "combinatorial",
            selection=selection,
        )["result"]
        values, vectors = (
            np.array(result["eigenvalues"]),
            np.array(result["eigenvectors"]),
        )
        assert np.allclose(
            values,
            expected[:k] if selection == "smallest" else expected[-k:],
            atol=1e-10,
        )
        assert np.allclose(matrix @ vectors, vectors * values, atol=1e-9)
        assert np.allclose(vectors.T @ vectors, np.eye(k), atol=1e-10)
        assert np.allclose(
            result["residual_norms"],
            np.linalg.norm(matrix @ vectors - vectors * values, axis=0),
        )
    if n > 1:
        unweighted_complete = Graph.from_edges(combinations(range(n), 2))
        result = execute(
            "laplacian-eigenpairs",
            unweighted_complete,
            num_eigenpairs=n,
            laplacian="symmetric_normalized" if normalized else "combinatorial",
        )["result"]
        assert result["eigenvalues"] == pytest.approx(
            [0] + [n / (n - 1) if normalized else n] * (n - 1), abs=1e-10
        )


def l1_oracle(y, difference, strength):
    """Minimize each affine-sign region, including every boundary face."""
    best = math.inf
    for signs in product((-1, 0, 1), repeat=difference.shape[0]):
        signs = np.asarray(signs)
        shifted = y - strength * difference.T @ signs
        zero = difference[signs == 0]
        candidate = (
            shifted - np.linalg.pinv(zero) @ (zero @ shifted) if len(zero) else shifted
        )
        differences = difference @ candidate
        if any(s and s * v < -1e-8 for s, v in zip(signs, differences, strict=True)):
            continue
        objective = (
            0.5 * np.sum((candidate - y) ** 2) + strength * np.abs(differences).sum()
        )
        best = min(best, objective)
    return best


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize(
    "regularizer,order",
    [
        ("total_variation", 0),
        ("trend_filtering", 0),
        ("trend_filtering", 1),
        ("trend_filtering", 2),
        ("laplacian_quadratic", 0),
    ],
)
def test_denoising_against_independent_piecewise_quadratic_optima(
    mask, regularizer, order
):
    pairs = list(combinations(range(4), 2))
    edges = [(u, v, (i % 3 + 1) / 2) for i, (u, v) in enumerate(pairs) if mask >> i & 1]
    graph = Graph.from_edges(edges, vertices=range(4))
    y, strength = np.array([0.0, 1.0, -2.0, 4.0]), 0.4
    result = execute(
        "graph-signal-denoising",
        graph,
        observed_signal=[{"vertex": i, "value": float(v)} for i, v in enumerate(y)],
        regularizer=regularizer,
        difference_order=order,
        regularization_strength=strength,
        tolerance=1e-6,
    )
    matrix = laplacian(4, edges)
    x = np.array([row["value"] for row in result["result"]["estimated_signal"]])
    if regularizer == "laplacian_quadratic":
        expected = np.linalg.inv(np.eye(4) + strength * matrix) @ y
        assert np.allclose(x, expected, atol=1e-8)
        objective = 0.5 * np.sum((x - y) ** 2) + 0.5 * strength * x @ matrix @ x
    else:
        difference = np.zeros((len(edges), 4))
        for i, (u, v, w) in enumerate(edges):
            factor = w if regularizer == "total_variation" else math.sqrt(w)
            difference[i, u], difference[i, v] = factor, -factor
        if regularizer == "trend_filtering":
            difference = (
                difference @ np.linalg.matrix_power(matrix, order // 2)
                if order % 2 == 0
                else np.linalg.matrix_power(matrix, (order + 1) // 2)
            )
        objective = 0.5 * np.sum((x - y) ** 2) + strength * np.abs(difference @ x).sum()
        assert objective == pytest.approx(l1_oracle(y, difference, strength), abs=2e-6)
    assert result["result"]["objective_value"] == pytest.approx(objective, abs=1e-9)
    assert result["diagnostics"]["objective_gap_bound"] <= 1e-6
    assert result["result"]["converged"]


@pytest.mark.parametrize("seed", range(64))
@pytest.mark.parametrize("metric", ["euclidean", "squared_euclidean", "cosine"])
@pytest.mark.parametrize("mode", ["directed", "union", "mutual"])
def test_feature_graph_neighbors_distances_and_symmetrization(seed, metric, mode):
    rng = random.Random(seed)
    ids = [0, "0", 2**62 + 1, -2, "last"]
    values = [[rng.randint(1, 4) for _ in range(3)] for _ in ids]
    vectors = FeatureVectors(
        {
            "dataset_id": "features",
            "dimension": 3,
            "vectors": [
                {"id": v, "values": x} for v, x in zip(ids, values, strict=True)
            ],
        }
    )
    k = seed % len(ids)
    distances = [[0.0] * len(ids) for _ in ids]
    for i, x in enumerate(values):
        for j, y in enumerate(values):
            squared = sum((a - b) ** 2 for a, b in zip(x, y, strict=True))
            distances[i][j] = (
                math.sqrt(squared)
                if metric == "euclidean"
                else squared
                if metric == "squared_euclidean"
                else 1
                - sum(a * b for a, b in zip(x, y, strict=True))
                / math.sqrt(sum(a * a for a in x) * sum(b * b for b in y))
            )
    result = execute("knn-graph", vectors, k=k, distance=metric, symmetrization=mode)
    neighbors = result["result"]["neighbor_lists"]
    arcs = set()
    for i, row in enumerate(neighbors):
        indices = [ids.index(v) for v in row["neighbors"]]
        assert len(indices) == len(set(indices)) == k and i not in indices
        assert all(
            distances[i][j]
            <= min(
                (
                    distances[i][other]
                    for other in range(len(ids))
                    if other != i and other not in indices
                ),
                default=math.inf,
            )
            + 1e-12
            for j in indices
        )
        assert row["distances"] == pytest.approx(
            [distances[i][j] for j in indices], abs=1e-12
        )
        arcs.update((i, j) for j in indices)
    expected = (
        arcs
        if mode == "directed"
        else {
            tuple(sorted((i, j))) for i, j in arcs if mode == "union" or (j, i) in arcs
        }
    )
    edges = result["result"]["graph"]["edges"]
    assert {(ids.index(e["source"]), ids.index(e["target"])) for e in edges} == expected
    assert (
        result["input_kind"] == "feature_vectors" and "graph_fingerprint" not in result
    )
    assert (
        result["ports"]["graph"]["graph_fingerprint"]
        == Graph(result["result"]["graph"]).fingerprint
    )
    assert result["ports"]["graph"]["source_input_fingerprint"] == vectors.fingerprint


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("loop_policy", ["keep", "drop"])
def test_quotient_aggregation_and_matching_coarsening(case, loop_policy):
    _, n, pairs = case
    edges = [(u, v, u + v + 1) for u, v in pairs]
    data = Graph.from_edges(edges, vertices=range(n)).to_canonical()
    for v in data["vertices"]:
        v["attributes"] = {"features": [v["id"], 2]}
    graph = Graph(data)
    for supplied in (True, False):
        arguments = (
            {
                "cluster_assignment": [
                    {"vertex": v, "value": -1 if v % 2 else 12} for v in range(n)
                ]
            }
            if supplied
            else {}
        )
        result = execute(
            "graph-coarsening",
            graph,
            self_loop_policy=loop_policy,
            feature_reduction="mean",
            **arguments,
        )
        assignments = {
            r["vertex"]: r["cluster"] for r in result["result"]["fine_to_coarse"]
        }
        expected = {}
        for u, v, weight in edges:
            pair = tuple(sorted((assignments[u], assignments[v])))
            if pair[0] == pair[1] and loop_policy == "drop":
                continue
            expected[pair] = expected.get(pair, 0) + weight
        coarse = result["result"]["coarse_graph"]
        assert {
            (e["source"], e["target"]): e["weight"] for e in coarse["edges"]
        } == expected
        for v in coarse["vertices"]:
            members = [u for u, group in assignments.items() if group == v["id"]]
            assert v["attributes"]["features"] == pytest.approx(
                [sum(members) / len(members), 2]
            )
            assert v["attributes"]["cluster_size"] == len(members)
            if not supplied and len(members) == 2:
                assert tuple(sorted(members)) in pairs
            assert supplied or len(members) <= 2
        assert result["ports"]["graph"]["source_graph_fingerprint"] == graph.fingerprint


@pytest.mark.parametrize("mask", range(128))
@pytest.mark.parametrize("objective", ["cut_net", "connectivity_minus_one"])
def test_all_three_vertex_hypergraphs_against_part_assignments(mask, objective):
    candidates = [s for size in range(1, 4) for s in combinations(range(3), size)]
    edges = [(s, i % 3) for i, s in enumerate(candidates) if mask >> i & 1]
    graph = Hypergraph(
        {
            "graph": {"id": "h"},
            "vertices": [{"id": v} for v in range(3)],
            "hyperedges": [
                {"id": i, "vertices": list(v), "weight": w}
                for i, (v, w) in enumerate(edges)
            ],
        }
    )
    result = execute(
        "hypergraph-partitioning",
        graph,
        num_parts=2,
        imbalance_tolerance=1 / 3,
        objective=objective,
    )["result"]
    # Decimal 0.3333333333333333 is strictly smaller than 1/3, so size 2
    # is genuinely outside the requested bound. Never round balance upward.
    assert not result["feasible"]
    result = execute(
        "hypergraph-partitioning",
        graph,
        num_parts=2,
        imbalance_tolerance=0.34,
        objective=objective,
    )["result"]

    def score(a):
        return sum(
            w
            * (
                (len({a[v] for v in s}) > 1)
                if objective == "cut_net"
                else len({a[v] for v in s}) - 1
            )
            for s, w in edges
        )

    feasible = [a for a in product(range(2), repeat=3) if len(set(a)) == 2]
    assert result["feasible"] and result["optimal"]
    actual = tuple(row["part"] for row in result["partition"])
    assert result["objective_value"] == score(actual) == min(map(score, feasible))


@pytest.mark.parametrize("seed", range(64))
def test_weighted_hypergraphs_and_both_hyperedge_objectives(seed):
    rng = random.Random(seed)
    n, k = 5, 3
    weights = [rng.randrange(4) for _ in range(n)]
    edges = [
        (tuple(rng.sample(range(n), rng.randrange(1, n + 1))), rng.randrange(4))
        for _ in range(5)
    ]
    graph = Hypergraph(
        {
            "graph": {"id": "h"},
            "vertices": [{"id": v, "weight": w} for v, w in enumerate(weights)],
            "hyperedges": [
                {"id": i, "vertices": list(s), "weight": w}
                for i, (s, w) in enumerate(edges)
            ],
        }
    )
    feasible = [
        a
        for a in product(range(k), repeat=n)
        if len(set(a)) == k
        and all(
            sum(weights[v] for v in range(n) if a[v] == p) <= sum(weights) / k * 1.5
            for p in range(k)
        )
    ]
    for objective in ("cut_net", "connectivity_minus_one"):
        result = execute(
            "hypergraph-partitioning",
            graph,
            num_parts=k,
            imbalance_tolerance=0.5,
            objective=objective,
        )["result"]
        if not feasible:
            assert not result["feasible"]
            continue

        def cost(a, objective=objective):
            return sum(
                w
                * (
                    (len({a[v] for v in s}) > 1)
                    if objective == "cut_net"
                    else len({a[v] for v in s}) - 1
                )
                for s, w in edges
            )

        assert result["feasible"]
        assert result["objective_value"] == min(map(cost, feasible))


def simrank_equations(n, edges, decay, directed):
    incoming = [set() for _ in range(n)]
    for u, v in edges:
        incoming[v].add(u)
        if not directed:
            incoming[u].add(v)
    matrix, rhs = np.eye(n * n), np.zeros(n * n)
    for u in range(n):
        for v in range(n):
            row = u * n + v
            if u == v:
                rhs[row] = 1
            elif incoming[u] and incoming[v]:
                for a in incoming[u]:
                    for b in incoming[v]:
                        matrix[row, a * n + b] -= decay / (
                            len(incoming[u]) * len(incoming[v])
                        )
    return np.linalg.solve(matrix, rhs).reshape(n, n)


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
def test_simrank_against_explicit_equation_system(case):
    _, n, edges = case
    graph = Graph.from_edges(edges, vertices=range(n))
    expected = simrank_equations(n, edges, 0.8, False)
    result = execute(
        "simrank", graph, query_mode="top_k_pairs", convergence_tolerance=1e-8
    )
    assert result["result"]["scored_pair_count"] == n * (n - 1) // 2
    for row in result["result"]["similarity_scores"]:
        assert abs(row["similarity"] - expected[row["source"], row["target"]]) <= 1e-8
    assert result["diagnostics"]["absolute_error_bound"] <= 1e-8


@pytest.mark.parametrize("mask", range(64))
def test_directed_simrank_projection_and_pair_scope(mask):
    possible = [(u, v) for u in range(3) for v in range(3) if u != v]
    edges = [e for i, e in enumerate(possible) if mask >> i & 1]
    graph = Graph.from_edges(edges, vertices=range(3), directed=True)
    for projection in (False, True):
        expected = simrank_equations(3, edges, 0.9, not projection)
        for mode in ("single_pair", "single_source_all"):
            args = {
                "query_mode": mode,
                "source_vertex": 0,
                "decay_factor": 0.9,
                "direction_mode": "undirected_projection" if projection else "incoming",
                "convergence_tolerance": 1e-9,
            }
            args.update({"target_vertex": 2} if mode == "single_pair" else {"top_k": 1})
            result = execute("simrank", graph, **args)
            for row in result["result"]["similarity_scores"]:
                assert row["similarity"] == pytest.approx(
                    expected[0, row["target"]], abs=1e-9
                )
            if mode == "single_source_all":
                assert not result["ports"]["pairs"]["complete"]
                assert result["result"]["similarity_scores"][0][
                    "similarity"
                ] == pytest.approx(max(expected[0, 1:]))


@pytest.mark.parametrize("seed", range(128))
@pytest.mark.parametrize("directed", [False, True])
def test_widest_paths_against_max_min_floyd_warshall(seed, directed):
    rng = random.Random(seed)
    n = 6
    edges = [
        (u, v, rng.choice([0, 1, 3, 2**60 + 1]))
        for u in range(n)
        for v in range(n)
        if u != v and (directed or u < v) and rng.random() < 0.3
    ]
    graph = Graph.from_edges(edges, vertices=range(n), directed=directed)
    capacities = [[math.inf if u == v else None for v in range(n)] for u in range(n)]
    edge_weights = {}
    for u, v, w in edges:
        capacities[u][v] = w
        edge_weights[u, v] = w
        if not directed:
            capacities[v][u] = w
            edge_weights[v, u] = w
    for k in range(n):
        for u in range(n):
            for v in range(n):
                if capacities[u][k] is not None and capacities[k][v] is not None:
                    candidate = min(capacities[u][k], capacities[k][v])
                    capacities[u][v] = (
                        candidate
                        if capacities[u][v] is None
                        else max(capacities[u][v], candidate)
                    )
    source = seed % n
    rows = execute("widest-paths", graph, source_vertex=source)["result"]["vertices"]
    for v, row in enumerate(rows):
        assert row["is_source"] == (v == source)
        assert row["reachable"] == (capacities[source][v] is not None)
        assert row["bottleneck_capacity"] == (
            None if v == source else capacities[source][v]
        )
        if row["reachable"] and v != source:
            visited, values, current = set(), [], v
            while current != source:
                assert current not in visited
                visited.add(current)
                previous = rows[current]["predecessor"]
                values.append(edge_weights[previous, current])
                current = previous
            assert min(values) == capacities[source][v]


@pytest.mark.parametrize("seed", range(128))
def test_critical_paths_against_complete_edge_sequence_enumeration(seed):
    rng = random.Random(seed)
    n = 6
    records = []
    for u, v in combinations(range(n), 2):
        for _ in range(rng.randrange(3)):
            records.append(
                {
                    "id": len(records),
                    "source": u,
                    "target": v,
                    "weight": rng.choice([-(2**60), -3, 0, 2, 2**60 + 1]),
                }
            )
    data = Graph.from_edges([], vertices=range(n), directed=True).to_canonical()
    data["graph"]["allows_parallel_edges"] = True
    data["edges"] = records
    graph = Graph(data)
    sources = [v for v in range(n) if not any(e["target"] == v for e in records)]
    sinks = {v for v in range(n) if not any(e["source"] == v for e in records)}
    expected = {}
    stack = [(v, (), (v,)) for v in sources]
    while stack:
        v, path, vertices = stack.pop()
        if v in sinks:
            expected[path, vertices] = sum(records[i]["weight"] for i in path)
        stack.extend(
            (e["target"], (*path, e["id"]), (*vertices, e["target"]))
            for e in records
            if e["source"] == v
        )
    for k in (1, 3, len(expected) + 1):
        result = execute("top-k-critical-paths", graph, k=k)
        paths = result["result"]["paths"]
        assert [row["total_weight"] for row in paths] == sorted(
            expected.values(), reverse=True
        )[:k]
        assert len({tuple(row["edges"]) for row in paths if row["edges"]}) == sum(
            bool(row["edges"]) for row in paths
        )
        for row in paths:
            assert (
                row["total_weight"]
                == expected[tuple(row["edges"]), tuple(row["vertices"])]
            )
        assert result["complete"] and result["result"]["complete"]


def rank_mod(matrix, p):
    matrix = np.asarray(matrix, dtype=int).copy() % p
    pivot_row = 0
    for column in range(matrix.shape[1]):
        pivot = next(
            (r for r in range(pivot_row, matrix.shape[0]) if matrix[r, column]), None
        )
        if pivot is None:
            continue
        matrix[[pivot_row, pivot]] = matrix[[pivot, pivot_row]]
        matrix[pivot_row] = (
            matrix[pivot_row] * pow(int(matrix[pivot_row, column]), -1, p) % p
        )
        for row in range(matrix.shape[0]):
            if row != pivot_row:
                matrix[row] = (
                    matrix[row] - matrix[row, column] * matrix[pivot_row]
                ) % p
        pivot_row += 1
        if pivot_row == matrix.shape[0]:
            break
    return pivot_row, matrix


def kernel_mod(matrix, p):
    rank, reduced = rank_mod(matrix, p)
    pivots = [
        next(c for c in range(matrix.shape[1]) if reduced[r, c]) for r in range(rank)
    ]
    free = [c for c in range(matrix.shape[1]) if c not in pivots]
    basis = np.zeros((matrix.shape[1], len(free)), dtype=int)
    for j, column in enumerate(free):
        basis[column, j] = 1
        for row, pivot in enumerate(pivots):
            basis[pivot, j] = -reduced[row, column] % p
    return basis


def complex_at(n, edges, threshold, maximum):
    active = {tuple(sorted((u, v))) for u, v, w in edges if w <= threshold}
    return {
        d: [
            s
            for s in combinations(range(n), d + 1)
            if all(e in active for e in combinations(s, 2))
        ]
        for d in range(maximum + 2)
    }


def boundary(complex_, dimension):
    columns = complex_[dimension]
    rows = complex_.get(dimension - 1, [])
    matrix = np.zeros((len(rows), len(columns)), dtype=int)
    if dimension:
        lookup = {s: i for i, s in enumerate(rows)}
        for j, simplex in enumerate(columns):
            for omit in range(len(simplex)):
                face = simplex[:omit] + simplex[omit + 1 :]
                matrix[lookup[face], j] = (-1) ** omit
    return matrix


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("field", [2, 3])
def test_persistence_against_independent_homology_rank_invariants(case, field):
    index, n, pairs = case
    edges = [(u, v, (i + index) % 4) for i, (u, v) in enumerate(pairs)]
    graph = Graph.from_edges(edges, vertices=range(n))
    for cutoff in (None, 1):
        result = execute(
            "persistent-homology",
            graph,
            max_homology_dimension=2,
            max_filtration=cutoff,
            field_prime=field,
        )["result"]
        times = sorted({0, *(w for _, _, w in edges if cutoff is None or w <= cutoff)})
        complexes = {t: complex_at(n, edges, t, 2) for t in times}
        for d in range(3):
            for a in times:
                first = complexes[a]
                cycles = kernel_mod(boundary(first, d), field)
                for b in times:
                    if b < a:
                        continue
                    second = complexes[b]
                    boundaries = boundary(second, d + 1)
                    embedded = np.zeros((len(second[d]), cycles.shape[1]), dtype=int)
                    for i, simplex in enumerate(first[d]):
                        embedded[second[d].index(simplex)] = cycles[i]
                    rank = (
                        rank_mod(np.concatenate([boundaries, embedded], axis=1), field)[
                            0
                        ]
                        - rank_mod(boundaries, field)[0]
                    )
                    reported = sum(
                        row["dimension"] == d
                        and row["birth"] <= a
                        and (row["death"] is None or row["death"] > b)
                        for row in result["intervals"]
                    )
                    assert rank == reported, (d, a, b, result)
        assert result["coefficient_field"] == field
        assert ("right_censored" in result["essential_interval_convention"]) == (
            cutoff is not None
        )


def test_inputs_empty_cases_and_unused_parameters_are_rejected():
    with pytest.raises(GraphMineError):
        FeatureVectors(
            {"dataset_id": "x", "dimension": 2, "vectors": [{"id": 0, "values": [1]}]}
        )
    with pytest.raises(GraphMineError):
        Hypergraph(
            {
                "graph": {"id": "x"},
                "vertices": [{"id": 0}],
                "hyperedges": [{"id": 0, "vertices": [0, 0]}],
            }
        )
    empty = Graph.from_edges([], vertices=[])
    assert execute("persistent-homology", empty)["result"]["intervals"] == []
    assert (
        execute("graph-coarsening", empty)["result"]["coarse_graph"]["vertices"] == []
    )
    assert (
        execute("simrank", empty, query_mode="top_k_pairs")["result"][
            "similarity_scores"
        ]
        == []
    )
    assert (
        execute(
            "graph-signal-denoising",
            empty,
            observed_signal=[],
            regularization_strength=1,
        )["result"]["estimated_signal"]
        == []
    )
    with pytest.raises(GraphMineError, match="Unsupported parameters"):
        execute(
            "laplacian-eigenpairs",
            Graph.from_edges([], vertices=[0]),
            num_eigenpairs=1,
            max_iterations=10,
        )
    with pytest.raises(GraphMineError):
        execute("persistent-homology", empty, field_prime=4)


def test_numerical_boundaries_vectors_and_negative_dag_weights():
    ids = [0, "0", 2**62 + 1]
    graph = Graph.from_edges([(ids[0], ids[1], 2)], vertices=ids)
    signal = [{"vertex": v, "value": [float(i), float(-i)]} for i, v in enumerate(ids)]
    result = execute(
        "graph-signal-denoising",
        graph,
        observed_signal=signal,
        regularization_strength=0.25,
        tolerance=1e-10,
    )["result"]
    assert np.allclose(
        [row["value"] for row in result["estimated_signal"]],
        [[0.5, -0.5], [0.5, -0.5], [2, -2]],
        atol=2e-5,
    )
    vectors = FeatureVectors(
        {
            "dataset_id": "zero",
            "dimension": 1,
            "vectors": [{"id": v, "values": [0]} for v in ids],
        }
    )
    with pytest.raises(GraphMineError, match="zero vector"):
        execute("knn-graph", vectors, k=1, distance="cosine")
    with pytest.raises(GraphMineError):
        execute("laplacian-eigenpairs", vectors, num_eigenpairs=1)
    with pytest.raises(GraphMineError, match="Unsupported parameters"):
        execute("knn-graph", vectors, k=1, seed=2)
    with pytest.raises(GraphMineError, match="Unsupported parameters"):
        execute("graph-coarsening", graph, seed=2)
    # A complete filtration must retain the essential component as well as
    # finite H0 intervals; cutoff intervals explicitly remain right-censored.
    persistence = execute("persistent-homology", graph, max_homology_dimension=10)[
        "result"
    ]
    assert persistence["intervals"] == [
        {"dimension": 0, "birth": 0, "death": 2},
        {"dimension": 0, "birth": 0, "death": None},
        {"dimension": 0, "birth": 0, "death": None},
    ]
    directed = Graph.from_edges(
        [(0, 1, -0.25), (1, 2, -0.5), (0, 2, -0.875)], vertices=range(3), directed=True
    )
    result = execute("top-k-critical-paths", directed, k=1)["result"]
    assert result["paths"][0]["edges"] == [0, 1]
    assert result["paths"][0]["weight_fraction"] == {"numerator": -3, "denominator": 4}


def test_balance_bound_just_below_a_whole_vertex_is_not_rounded_outward():
    graph = Graph.from_edges([], vertices=range(3))
    result = execute(
        "balanced-partitioning", graph, num_parts=2, imbalance_tolerance=1 / 3
    )["result"]
    assert not result["feasible"] and result["infeasibility_certified"]
    result = execute(
        "balanced-partitioning", graph, num_parts=2, imbalance_tolerance=0.34
    )["result"]
    assert result["feasible"] and result["balanced"]
