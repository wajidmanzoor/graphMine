"""Independent exhaustive checks for optimization and structural integrations.

Production uses flow, VF2, clique reduction, matching and HiGHS. These oracles
enumerate vertex subsets, permutations, partitions or sign assignments instead.
NetworkX is used only to obtain the input graph atlas.
"""

import math
import random
from collections import Counter, defaultdict
from fractions import Fraction
from functools import cache
from itertools import combinations, permutations, product

import networkx as nx
import pytest
from graphmine import Budget, Graph, run
from graphmine.exceptions import GraphMineError, ResourceLimit

ATLAS = [
    (i, len(g), tuple(g.edges))
    for i, g in enumerate(nx.graph_atlas_g())
    if 1 <= len(g) <= 6
]


def subsets(n, minimum=0, maximum=None):
    return [
        frozenset(s)
        for size in range(minimum, min(n, maximum if maximum is not None else n) + 1)
        for s in combinations(range(n), size)
    ]


def adjacency(n, edges, directed=False):
    adj = [set() for _ in range(n)]
    for u, v, *_ in edges:
        adj[u].add(v)
        if not directed:
            adj[v].add(u)
    return adj


def execute(op, graph, **args):
    envelope = run(
        op, graph, parameters=args, device="cpu", budget=Budget(timeout_seconds=90)
    )
    assert envelope["backend"]["device"] == "cpu"
    return envelope


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("clique_order", [2, 3, 4, 8])
def test_clique_density_against_subset_objectives(case, clique_order):
    _, n, edges = case
    adjacent = adjacency(n, edges)
    cliques = [
        s
        for s in subsets(n, clique_order, clique_order)
        if all(v in adjacent[u] for u, v in combinations(s, 2))
    ]
    feasible = subsets(n, 1)
    objective = lambda s: Fraction(sum(c <= s for c in cliques), len(s))
    envelope = execute(
        "densest-subgraph",
        Graph.from_edges(edges, vertices=range(n)),
        clique_order=clique_order,
    )
    result = envelope["result"]
    chosen = frozenset(result["vertices"])
    optimum = max(map(objective, feasible))
    assert chosen and objective(chosen) == optimum
    assert result["density"] == pytest.approx(float(optimum))
    assert result["clique_count"] == sum(c <= chosen for c in cliques)
    assert result["induced_edge_value"] == sum(
        u in chosen and v in chosen for u, v in edges
    )
    assert envelope["quality"] == "exact" and result["optimal"]


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
def test_fixed_and_minimum_cardinality_density(case):
    _, n, edges = case
    graph = Graph.from_edges(edges, vertices=range(n))
    score = lambda s: sum(u in s and v in s for u, v in edges)
    for k in sorted({1, max(1, n // 2), n}):
        result = execute("densest-k-subgraph", graph, k=k)["result"]
        chosen = frozenset(result["vertices"])
        assert len(chosen) == k
        assert (
            result["induced_edge_value"]
            == score(chosen)
            == max(map(score, subsets(n, k, k)))
        )
    minimum = max(1, n // 2)
    result = execute("densest-subgraph", graph, minimum_vertices=minimum)["result"]
    chosen = frozenset(result["vertices"])
    assert len(chosen) >= minimum
    assert Fraction(score(chosen), len(chosen)) == max(
        Fraction(score(s), len(s)) for s in subsets(n, minimum)
    )


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("gamma", [0.5, 0.8, 1.0])
def test_quasi_cliques_maximality_against_all_subsets(case, gamma):
    _, n, edges = case
    adjacent = adjacency(n, edges)
    candidates = [
        s
        for s in subsets(n, 2)
        if all(
            len(adjacent[v] & s) >= math.ceil(Fraction(str(gamma)) * (len(s) - 1))
            for v in s
        )
    ]
    expected = {s for s in candidates if not any(s < other for other in candidates)}
    result = execute(
        "quasi-cliques",
        Graph.from_edges(edges, vertices=range(n)),
        gamma=gamma,
        minimum_size=2,
    )["result"]
    assert {frozenset(row["vertices"]) for row in result["quasi_cliques"]} == expected
    assert result["count"] == len(expected) and result["complete"]
    for row in result["quasi_cliques"]:
        selected = set(row["vertices"])
        assert row["minimum_internal_degree"] == min(
            len(adjacent[v] & selected) for v in selected
        )
        assert row["induced_edge_count"] == sum(
            u in selected and v in selected for u, v in edges
        )


def embeddings(n, edges, size, query_edges, induced=False, directed=False):
    actual = set(edges) if directed else {tuple(sorted(e)) for e in edges}
    query = set(query_edges) if directed else {tuple(sorted(e)) for e in query_edges}
    pairs = (
        list(product(range(size), repeat=2))
        if directed
        else list(combinations(range(size), 2))
    )
    result = set()
    for mapping in permutations(range(n), size):
        valid = True
        for u, v in pairs:
            data_edge = (
                (mapping[u], mapping[v])
                if directed
                else tuple(sorted((mapping[u], mapping[v])))
            )
            present = data_edge in actual
            required = (u, v) in query
            if (required and not present) or (induced and required != present):
                valid = False
                break
        if valid:
            result.add(mapping)
    return result


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize(
    "query_edges", [((0, 1),), ((0, 1), (1, 2)), ((0, 1), (1, 2), (0, 2))]
)
@pytest.mark.parametrize("induced", [False, True])
def test_pattern_embeddings_and_automorphism_classes(case, query_edges, induced):
    _, n, edges = case
    size = max(v for e in query_edges for v in e) + 1
    graph, query = (
        Graph.from_edges(edges, vertices=range(n)),
        Graph.from_edges(query_edges),
    )
    expected = embeddings(n, edges, size, query_edges, induced)
    result = execute(
        "subgraph-isomorphism", graph, query_graph=query.to_canonical(), induced=induced
    )["result"]
    actual = {
        tuple(row["data_vertex"] for row in mapping) for mapping in result["matches"]
    }
    assert actual == expected and result["returned_count"] == len(expected)
    automorphisms = len(embeddings(size, query_edges, size, query_edges, True))
    for identity, divisor in (
        ("all_embeddings", 1),
        ("unique_vertex_set_and_mapping_class", automorphisms),
    ):
        result = execute(
            "motif-counting",
            graph,
            motifs=[query.to_canonical()],
            induced=induced,
            occurrence_identity=identity,
        )["result"]
        assert result["count_by_motif"]["graph"] == len(expected) // divisor


def connected(vertices, edges):
    reached = {min(vertices)}
    while True:
        before = set(reached)
        for u, v in edges:
            if u in vertices and v in vertices:
                if u in reached:
                    reached.add(v)
                if v in reached:
                    reached.add(u)
        if reached == before:
            return reached == set(vertices)


@cache
def graph_code(n, edges):
    edge_set = set(edges)
    return min(
        tuple(
            int(tuple(sorted((p[u], p[v]))) in edge_set)
            for u, v in combinations(range(n), 2)
        )
        for p in permutations(range(n))
    )


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
def test_graphlet_classes_and_orbit_participation(case):
    _, n, edges = case
    result = execute(
        "graphlet-counting",
        Graph.from_edges(edges, vertices=range(n)),
        graphlet_sizes=[2, 3, 4],
        include_orbit_counts=True,
        list_instances=True,
    )["result"]
    patterns, by_code = {}, {}
    for key, record in result["graphlet_dictionary"].items():
        pattern_edges = tuple(
            sorted(tuple(sorted((e["source"], e["target"]))) for e in record["edges"])
        )
        size = len(record["vertices"])
        code = (size, graph_code(size, pattern_edges))
        assert code not in by_code
        by_code[code] = key
        patterns[key] = (size, pattern_edges)
    assert Counter(size for size, _ in patterns.values()) == {2: 1, 3: 2, 4: 6}
    orbits = {}
    for key, (size, pattern_edges) in patterns.items():
        autos = embeddings(size, pattern_edges, size, pattern_edges, True)
        expected_orbits = {frozenset(p[v] for p in autos) for v in range(size)}
        definitions = {
            orbit: frozenset(d["pattern_vertices"])
            for orbit, d in result["orbit_dictionary"].items()
            if d["graphlet"] == key
        }
        assert set(definitions.values()) == expected_orbits
        orbits[key] = {
            v: orbit for orbit, vertices in definitions.items() for v in vertices
        }
    counts, roles, instances = Counter(), defaultdict(Counter), defaultdict(set)
    for chosen in subsets(n, 2, 4):
        if not connected(chosen, edges):
            continue
        vertices = sorted(chosen)
        induced = tuple(
            sorted(
                (vertices.index(u), vertices.index(v))
                for u, v in edges
                if u in chosen and v in chosen
            )
        )
        key = by_code[len(vertices), graph_code(len(vertices), induced)]
        counts[key] += 1
        instances[key].add(chosen)
        size, pattern_edges = patterns[key]
        mapping = next(iter(embeddings(size, induced, size, pattern_edges, True)))
        for p, local in enumerate(mapping):
            roles[vertices[local]][orbits[key][p]] += 1
    assert {k: counts[k] for k in patterns} == result["count_by_graphlet"]
    assert {r["vertex"]: r["counts"] for r in result["orbit_counts_by_vertex"]} == {
        v: dict(roles[v]) for v in range(n)
    }
    assert {
        k: set(map(frozenset, rows))
        for k, rows in result["instances_by_graphlet"].items()
    } == {k: instances[k] for k in patterns}


@cache
def partitions(n):
    if n == 0:
        return ((),)
    out = []
    for assignment in partitions(n - 1):
        for p in range(max(assignment, default=-1) + 2):
            out.append((*assignment, p))
    return tuple(out)


def partition_quality(assignment, edges, resolution, cpm=False):
    groups = [
        {v for v, group in enumerate(assignment) if group == p} for p in set(assignment)
    ]
    weights = {(u, v): w for u, v, w in edges}
    m = sum(weights.values())
    degree = [
        sum(w for (u, v), w in weights.items() if x in (u, v))
        for x in range(len(assignment))
    ]
    score = 0.0
    for group in groups:
        internal = sum(w for (u, v), w in weights.items() if u in group and v in group)
        if cpm:
            score += internal - resolution * len(group) * (len(group) - 1) / 2
        elif m:
            score += (
                internal / m
                - resolution * (sum(degree[v] for v in group) / (2 * m)) ** 2
            )
    return score


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize(
    "quality_function,resolution",
    [("modularity", 1.0), ("modularity", 2.0), ("constant_potts_model", 0.4)],
)
def test_community_optimum_against_every_set_partition(
    case, quality_function, resolution
):
    _, n, edges = case
    weighted_edges = [(u, v, 1) for u, v in edges]
    result = execute(
        "community-detection",
        Graph.from_edges(edges, vertices=range(n)),
        quality_function=quality_function,
        resolution=resolution,
        solution_quality="exact",
    )["result"]
    actual = tuple(r["part"] for r in result["partition_assignment"])
    objective = lambda a: partition_quality(
        a, weighted_edges, resolution, quality_function == "constant_potts_model"
    )
    assert result["optimal"]
    assert result["quality_score"] == pytest.approx(objective(actual), abs=1e-8)
    assert result["quality_score"] == pytest.approx(
        max(map(objective, partitions(n))), abs=1e-8
    )


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("objective", ["edge_cut", "normalized_cut"])
@pytest.mark.parametrize("tolerance", [0, 0.5])
def test_balance_constraints_and_cut_objective(case, objective, tolerance):
    _, n, edges = case
    if n < 2:
        with pytest.raises(GraphMineError):
            execute(
                "balanced-partitioning",
                Graph.from_edges(edges, vertices=range(n)),
                num_parts=2,
            )
        return
    k = 3 if n >= 4 else 2
    low, high = (1 - tolerance) * n / k, (1 + tolerance) * n / k
    feasible = [
        a
        for a in partitions(n)
        if len(set(a)) == k and all(low <= a.count(p) <= high for p in range(k))
    ]

    def score(a):
        if objective == "edge_cut":
            return sum(a[u] != a[v] for u, v in edges)
        return sum(
            sum((a[u] == p) != (a[v] == p) for u, v in edges) / a.count(p)
            for p in range(k)
        )

    result = execute(
        "balanced-partitioning",
        Graph.from_edges(edges, vertices=range(n)),
        num_parts=k,
        imbalance_tolerance=tolerance,
        objective=objective,
    )["result"]
    if not feasible:
        assert (
            not result["feasible"]
            and not result["balanced"]
            and result["infeasibility_certified"]
        )
        assert result["partition_assignment"] == []
        return
    assignment = tuple(r["part"] for r in result["partition_assignment"])
    assert len(set(assignment)) == k
    assert all(low <= assignment.count(p) <= high for p in range(k))
    assert result["balanced"] and result["feasible"] and result["optimal"]
    assert result["objective_value"] == pytest.approx(min(map(score, feasible)))
    assert result["objective_value"] == pytest.approx(score(assignment))


def bipartite_graph(mask, left_count=3, right_count=3, weighted=False):
    pairs = list(
        product(range(left_count), range(left_count, left_count + right_count))
    )
    edges = [
        (u, v, (i * 7 % 11) - 5) if weighted else (u, v)
        for i, (u, v) in enumerate(pairs)
        if mask >> i & 1
    ]
    data = Graph.from_edges(
        edges, vertices=range(left_count + right_count)
    ).to_canonical()
    for v in data["vertices"]:
        v["attributes"] = {"side": "left" if v["id"] < left_count else "right"}
    return Graph(data), edges


@pytest.mark.parametrize("mask", range(512))
def test_all_bipartite_three_by_three_counts_bicliques_and_matching(mask):
    graph, edges = bipartite_graph(mask)
    edge_set = set(edges)
    butterflies = [
        frozenset((*l, *r))
        for l in combinations(range(3), 2)
        for r in combinations(range(3, 6), 2)
        if all((u, v) in edge_set for u in l for v in r)
    ]
    for mode in ("per_vertex", "per_edge"):
        result = execute("butterfly-counting", graph, mode=mode)["result"]
        assert result["butterfly_count"] == len(butterflies)
        if mode == "per_vertex":
            assert [r["count"] for r in result["vertices"]] == [
                sum(v in b for b in butterflies) for v in range(6)
            ]
        else:
            for row in result["edges"]:
                assert row["count"] == sum(
                    {row["source"], row["target"]} <= b for b in butterflies
                )
    bicliques = [
        (l, frozenset(v + 3 for v in r))
        for l in subsets(3, 1)
        for r in subsets(3, 1)
        if all((u, v + 3) in edge_set for u in l for v in r)
    ]
    maximal = {
        (l, r)
        for l, r in bicliques
        if not any(l <= a and r <= b and (l, r) != (a, b) for a, b in bicliques)
    }
    result = execute(
        "maximal-bicliques", graph, left_partition=[0, 1, 2], right_partition=[3, 4, 5]
    )["result"]
    assert {
        (frozenset(r["left_vertices"]), frozenset(r["right_vertices"]))
        for r in result["bicliques"]
    } == maximal
    graph, weighted = bipartite_graph(mask, weighted=True)
    matchings = [
        indices
        for size in range(4)
        for indices in combinations(range(len(weighted)), size)
        if len({v for i in indices for v in weighted[i][:2]}) == 2 * size
    ]
    for objective in ("maximum_cardinality", "maximum_weight", "minimum_cost"):
        for perfect in (False, True):
            feasible = [m for m in matchings if not perfect or len(m) == 3]
            result = execute(
                "bipartite-matching",
                graph,
                objective=objective,
                weight_mode="edge_weight",
                perfect_matching_required=perfect,
            )["result"]
            if not feasible:
                assert not result["feasible"] and result["infeasibility_certified"]
                continue
            values = [
                len(m)
                if objective == "maximum_cardinality"
                else sum(weighted[i][2] for i in m)
                for m in feasible
            ]
            optimum = min(values) if objective == "minimum_cost" else max(values)
            assert result["feasible"] and result["optimal"]
            assert result["objective_value"] == optimum
            indices = result["matching_edges"]
            assert len(indices) == result["matching_size"]
            assert len({v for i in indices for v in weighted[i][:2]}) == 2 * len(
                indices
            )
            assert not perfect or len(indices) == 3


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("measure", ["degree", "butterfly_participation"])
def test_alpha_beta_cores_are_largest_feasible_vertex_sets(mask, measure):
    graph, edges = bipartite_graph(mask, 2, 3)
    adjacent = adjacency(5, edges)
    edge_set = set(edges)
    butterflies = [
        frozenset((0, 1, a, b))
        for a, b in combinations(range(2, 5), 2)
        if all((u, v) in edge_set for u in (0, 1) for v in (a, b))
    ]
    for alpha, beta in ((1, 1), (2, 1), (1, 2), (3, 3)):
        feasible = []
        for chosen in subsets(5):
            valid = all(
                (
                    len(adjacent[v] & chosen)
                    if measure == "degree"
                    else sum(v in b and b <= chosen for b in butterflies)
                )
                >= (alpha if v < 2 else beta)
                for v in chosen
            )
            if valid:
                feasible.append(chosen)
        expected = frozenset().union(*feasible)
        result = execute(
            "butterfly-counting",
            graph,
            mode="alpha_beta_core",
            alpha=alpha,
            beta=beta,
            core_measure=measure,
        )["result"]
        assert result["core_measure"] == measure
        assert frozenset(result["cores"][0]["vertices"]) == expected


@pytest.mark.parametrize("code", range(3**6))
def test_all_four_vertex_signed_graphs(code):
    edges, signs = [], []
    for u, v in combinations(range(4), 2):
        value, code = code % 3, code // 3
        if value:
            edges.append((u, v, 0 if len(edges) == 0 else len(edges)))
            signs.append(value == 2)
    data = Graph.from_edges(edges, vertices=range(4)).to_canonical()
    for edge, negative in zip(data["edges"], signs, strict=True):
        edge["type"] = "negative" if negative else "positive"
    graph = Graph(data)
    assignments = list(product((0, 1), repeat=4))

    def objective(a, weighted):
        return sum(
            (w if weighted else 1)
            for (u, v, w), negative in zip(edges, signs, strict=True)
            if (a[u] != a[v]) != negative
        )

    balanced = min(objective(a, False) for a in assignments) == 0
    for task, weighted in (
        ("balance_check", False),
        ("frustration_minimization", False),
        ("frustration_minimization", True),
    ):
        result = execute(
            "signed-balance",
            graph,
            task=task,
            weight_mode="edge_weight" if weighted else "unweighted",
        )["result"]
        assignment = tuple(
            int(r["faction"] == "B") for r in result["faction_assignment"]
        )
        assert result["balanced"] == balanced
        assert result["frustrated_weight"] == objective(assignment, weighted)
        if task == "frustration_minimization":
            assert result["frustration_optimal"]
            assert result["frustrated_weight"] == min(
                objective(a, weighted) for a in assignments
            )
        elif not balanced:
            assert not result["frustration_optimal"]


@pytest.mark.parametrize("seed", range(32))
def test_weighted_optimization_and_typed_ids(seed):
    rng = random.Random(seed)
    n = 5
    ids = [0, "0", 2**62 + 1, "z", -2]
    edges = [
        (u, v, rng.randrange(9) / 4)
        for u, v in combinations(range(n), 2)
        if rng.random() < 0.6
    ]
    graph = Graph.from_edges([(ids[u], ids[v], w) for u, v, w in edges], vertices=ids)
    subsets_ = subsets(n, 1)
    cost = lambda s: sum(w for u, v, w in edges if u in s and v in s)
    for minimum in (1, 3):
        result = execute(
            "densest-subgraph",
            graph,
            minimum_vertices=minimum,
            weight_mode="edge_weight",
        )["result"]
        chosen = {ids.index(v) for v in result["vertices"]}
        assert len(chosen) >= minimum
        assert result["density"] == pytest.approx(
            max(cost(s) / len(s) for s in subsets_ if len(s) >= minimum)
        )
    for k in (2, 3):
        result = execute("densest-k-subgraph", graph, k=k, weight_mode="edge_weight")[
            "result"
        ]
        assert result["induced_edge_value"] == max(
            cost(s) for s in subsets_ if len(s) == k
        )
    for criterion in ("modularity", "constant_potts_model"):
        result = execute(
            "community-detection",
            graph,
            solution_quality="exact",
            quality_function=criterion,
            resolution=0.75,
            weight_mode="edge_weight",
        )["result"]
        assert result["quality_score"] == pytest.approx(
            max(
                partition_quality(a, edges, 0.75, criterion == "constant_potts_model")
                for a in partitions(n)
            ),
            abs=1e-8,
        )
    weights = [rng.randrange(5) for _ in range(n)]
    for objective in ("edge_cut", "normalized_cut"):
        feasible = [
            a
            for a in partitions(n)
            if len(set(a)) == 2
            and all(
                0.5 * sum(weights) / 2
                <= sum(weights[v] for v in range(n) if a[v] == p)
                <= 1.5 * sum(weights) / 2
                for p in range(2)
            )
            and (
                objective == "edge_cut"
                or all(
                    sum(weights[v] for v in range(n) if a[v] == p) > 0 for p in range(2)
                )
            )
        ]
        result = execute(
            "balanced-partitioning",
            graph,
            num_parts=2,
            balance_mode="vertex_weight",
            vertex_weights=[
                {"vertex": v, "value": w} for v, w in zip(ids, weights, strict=True)
            ],
            imbalance_tolerance=0.5,
            edge_weight_mode="edge_weight",
            objective=objective,
        )["result"]
        if not feasible:
            assert not result["feasible"]
            continue

        def value(a, objective=objective):
            if objective == "edge_cut":
                return sum(w for u, v, w in edges if a[u] != a[v])
            return sum(
                sum(w for u, v, w in edges if (a[u] == p) != (a[v] == p))
                / sum(weights[v] for v in range(n) if a[v] == p)
                for p in range(2)
            )

        assert result["feasible"]
        assert result["objective_value"] == pytest.approx(min(map(value, feasible)))


def test_resource_failure_never_becomes_a_completed_optimum():
    graph = Graph.from_edges(combinations(range(8), 2), vertices=range(8))
    for op, args in (
        ("quasi-cliques", {"gamma": 0.5, "minimum_size": 2}),
        ("densest-k-subgraph", {"k": 4}),
        ("community-detection", {"solution_quality": "exact"}),
        ("balanced-partitioning", {"num_parts": 2}),
    ):
        with pytest.raises(ResourceLimit):
            run(
                op,
                graph,
                parameters=args,
                device="cpu",
                budget=Budget(max_candidates=1),
            )
