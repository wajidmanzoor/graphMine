"""Tree subsets, injections, edit DP, set partitions and direct score formulas."""

import math
import random
import statistics
from fractions import Fraction
from itertools import combinations, permutations, product

import networkx as nx
import pytest
from graphmine import Graph, run
from graphmine.exceptions import GraphMineError

ATLAS = [
    (i, len(g), tuple(g.edges))
    for i, g in enumerate(nx.graph_atlas_g())
    if 1 <= len(g) <= 6
]


def execute(operation, graph, **parameters):
    result = run(operation, graph, device="cpu", parameters=parameters)
    assert result["backend"]["device"] == "cpu"
    return result


def connected_tree(n, edges):
    parent = list(range(n))

    def root(v):
        while parent[v] != v:
            v = parent[v]
        return v

    vertices = set()
    for u, v in edges:
        first, second = root(u), root(v)
        if first == second:
            return None
        parent[first] = second
        vertices |= {u, v}
    if len({root(v) for v in vertices}) != 1:
        return None
    return vertices


def steiner_oracle(n, edges, groups, required):
    best = math.inf
    for v in range(n):
        if all(v in group for group in groups) and required <= {v}:
            best = 0
    for size in range(1, min(n - 1, len(edges)) + 1):
        for chosen in combinations(edges, size):
            nodes = connected_tree(n, [(u, v) for u, v, _ in chosen])
            if (
                nodes is not None
                and required <= nodes
                and all(nodes & group for group in groups)
            ):
                best = min(best, sum(w for _, _, w in chosen))
    return best


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("group_case", ["terminals", "overlapping"])
def test_group_steiner_against_all_edge_subsets(case, group_case):
    _, n, pairs = case
    edges = [(u, v, (u * 3 + v) % 4) for u, v in pairs]
    groups = (
        [{0}, {n - 1}]
        if group_case == "terminals"
        else [set(range(0, n, 2)), {n - 1, n // 2}]
    )
    required = set() if group_case == "terminals" else {n // 2}
    expected = steiner_oracle(n, edges, groups, required)
    result = execute(
        "group-steiner-tree",
        Graph.from_edges(edges, vertices=range(n)),
        groups=[sorted(g) for g in groups],
        required_vertices=sorted(required),
    )
    data = result["result"]
    if math.isinf(expected):
        assert (
            not data["feasible"] and data["tree_weight"] is None and not data["optimal"]
        )
        assert result["diagnostics"]["status"] == "infeasible"
        return
    assert data["feasible"] and data["optimal"] and data["tree_weight"] == expected
    assert result["quality"] == "numerical_optimum"
    selected = set(data["selected_vertices"])
    chosen = [edges[i] for i in data["tree_edges"]]
    assert sum(w for _, _, w in chosen) == expected
    if chosen:
        assert connected_tree(n, [(u, v) for u, v, _ in chosen]) == selected
    else:
        assert len(selected) == 1
    assert required <= selected and all(group & selected for group in groups)
    assert all(
        row["vertex"] in groups[row["group"]] & selected
        for row in data["group_representatives"]
    )


def test_group_steiner_parallel_original_id_and_zero_cost_cycles():
    graph = Graph.from_edges([], vertices=[0, "0", 2**60]).to_canonical()
    graph["graph"].update(allows_parallel_edges=True, allows_self_loops=True)
    graph["edges"] = [
        {"id": "expensive", "source": 0, "target": "0", "weight": 8},
        {"id": "cheap", "source": 0, "target": "0", "weight": 0.125},
        {"id": "other", "source": "0", "target": 2**60, "weight": 0.25},
        {"id": "loop", "source": 0, "target": 0, "weight": 0},
    ]
    result = execute("group-steiner-tree", graph, groups=[[0], [2**60]])["result"]
    assert set(result["tree_edges"]) == {"cheap", "other"}
    assert result["tree_weight_fraction"] == "3/8"
    graph = Graph.from_edges([(u, v, 0) for u, v in combinations(range(5), 2)])
    result = execute("group-steiner-tree", graph, groups=[[v] for v in range(5)])[
        "result"
    ]
    assert result["tree_weight"] == 0 and len(result["tree_edges"]) == 4


def injections(na, nb):
    if na <= nb:
        yield from (dict(enumerate(p)) for p in permutations(range(nb), na))
    else:
        yield from (
            {a: b for b, a in enumerate(p)} for p in permutations(range(na), nb)
        )


def alignment_score(mapping, edges_a, edges_b, prior, alpha, weighted, directed):
    b = {(u, v) if directed else tuple(sorted((u, v))): w for u, v, w in edges_b}
    value = sum((Fraction(prior.get(pair, 0)) for pair in mapping.items()), Fraction())
    for u, v, w in edges_a:
        if u not in mapping or v not in mapping:
            continue
        pair = (
            (mapping[u], mapping[v])
            if directed
            else tuple(sorted((mapping[u], mapping[v])))
        )
        if pair in b:
            value += Fraction(alpha) * (min(w, b[pair]) if weighted else 1)
    return value


@pytest.mark.parametrize("directed", [False, True])
@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("other_case", range(6))
def test_global_alignment_against_every_injective_mapping(directed, mask, other_case):
    na, nb = (3, 3) if directed else (4, [0, 1, 2, 3, 4, 5][other_case])
    pairs_a = list(
        permutations(range(na), 2) if directed else combinations(range(na), 2)
    )
    pairs_b = list(
        permutations(range(nb), 2) if directed else combinations(range(nb), 2)
    )
    edges_a = [
        (u, v, (i + mask) % 4) for i, (u, v) in enumerate(pairs_a) if mask >> i & 1
    ]
    rng = random.Random(mask * 7 + other_case)
    edges_b = [
        (u, v, rng.randrange(4))
        for u, v in pairs_b
        if rng.random() < (other_case + 1) / 6
    ]
    prior = {
        (u, p): ((u * 5 + p * 7 + mask) % 7 - 3) / 2
        for u in range(na)
        for p in range(nb)
    }
    alpha, weighted = 0.5 if mask % 2 else 2, bool(mask % 2)
    expected = max(
        alignment_score(mapping, edges_a, edges_b, prior, alpha, weighted, directed)
        for mapping in injections(na, nb)
    )
    result = execute(
        "network-alignment",
        Graph.from_edges(edges_a, vertices=range(na), directed=directed),
        other_graph=Graph.from_edges(
            edges_b, vertices=range(nb), directed=directed
        ).to_canonical(),
        node_similarity_prior=[
            {"graph_a_vertex": u, "graph_b_vertex": p, "value": w}
            for (u, p), w in prior.items()
        ],
        topology_weight=alpha,
        weight_mode="edge_weight" if weighted else "unweighted",
    )
    data = result["result"]
    mapping = {
        row["graph_a_vertex"]: row["graph_b_vertex"] for row in data["vertex_mapping"]
    }
    assert data["objective_value"] == float(expected)
    assert Fraction(data["objective_fraction"]) == expected
    assert len(mapping) == min(na, nb) and len(set(mapping.values())) == len(mapping)
    assert (
        alignment_score(mapping, edges_a, edges_b, prior, alpha, weighted, directed)
        == expected
    )
    assert sum(row["score"] for row in data["vertex_mapping"]) == float(expected)
    assert data["complete"] and data["optimal"]


def test_alignment_parallel_weights_typed_ids_and_empty_graphs():
    a = Graph.from_edges([], vertices=[0, "0"]).to_canonical()
    a["graph"].update(allows_parallel_edges=True, allows_self_loops=True)
    a["edges"] = [
        {"id": "one", "source": 0, "target": "0", "weight": 2},
        {"id": "two", "source": 0, "target": "0", "weight": 3},
        {"id": "loop", "source": 0, "target": 0, "weight": 100},
    ]
    b = Graph.from_edges([(2**60, "large", 4)]).to_canonical()
    result = execute("network-alignment", a, other_graph=b, weight_mode="edge_weight")[
        "result"
    ]
    assert result["conserved_edge_value"] == 4 and result["edge_correctness"] == 1
    assert {row["graph_a_vertex"] for row in result["vertex_mapping"]} == {0, "0"}
    for a, b in [
        (Graph.from_edges([]), Graph.from_edges([])),
        (Graph.from_edges([]), Graph.from_edges([(0, 1)])),
    ]:
        result = execute("network-alignment", a, other_graph=b.to_canonical())["result"]
        assert result["vertex_mapping"] == [] and result["objective_value"] == 0


def records(values, ids=None):
    graph = Graph.from_edges(
        [], vertices=range(len(values)) if ids is None else ids
    ).to_canonical()
    for vertex, attributes in zip(graph["vertices"], values, strict=True):
        vertex["attributes"] = attributes
    return Graph(graph)


def edit_distance(a, b):
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        table[i][0] = i
    for j in range(len(b) + 1):
        table[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            table[i][j] = min(
                table[i - 1][j] + 1,
                table[i][j - 1] + 1,
                table[i - 1][j - 1] + (a[i - 1] != b[j - 1]),
            )
    return table[-1][-1]


@pytest.mark.parametrize("distance", [0, 1, 2, 3, 10**100])
def test_entity_blocking_edit_distance_against_dynamic_programming(distance):
    strings = [
        "".join(chars) for size in range(4) for chars in product("ab", repeat=size)
    ] + ["é", "e\u0301", "🙂"]
    graph = records([{"text": value} for value in strings])
    result = execute(
        "entity-resolution",
        graph,
        task="blocking",
        blocking_rules=[
            {
                "id": "edit",
                "all": [
                    {
                        "field": "text",
                        "operator": "edit_distance",
                        "max_distance": distance,
                    }
                ],
            }
        ],
    )["result"]
    expected = {
        (u, v)
        for u, v in combinations(range(len(strings)), 2)
        if edit_distance(strings[u], strings[v]) <= distance
    }
    assert {
        (row["source"], row["target"]) for row in result["candidate_pairs"]
    } == expected
    assert all(row["rule_ids"] == ["edit"] for row in result["candidate_pairs"])
    assert result["reduction_ratio"] == pytest.approx(
        1 - len(expected) / math.comb(len(strings), 2)
    )


def partitions(n):
    def visit(values):
        if len(values) == n:
            yield values
        else:
            for value in range(max(values, default=-1) + 2):
                yield from visit([*values, value])

    yield from visit([])


@pytest.mark.parametrize("state", list(product((-1, 0, 1), repeat=6)))
def test_entity_correlation_clustering_against_every_partition(state):
    pairs = list(combinations(range(4), 2))
    attrs = [{"block": [], "match": []} for _ in range(4)]
    for i, ((u, v), status) in enumerate(zip(pairs, state, strict=True)):
        for vertex in (u, v):
            if status != -1:
                attrs[vertex]["block"].append(f"b{i}")
            if status == 1:
                attrs[vertex]["match"].append(f"m{i}")
    graph = records([{k: " ".join(v) for k, v in row.items()} for row in attrs])
    result = execute(
        "entity-resolution",
        graph,
        task="resolution",
        blocking_rules=[
            {"id": "tokens", "all": [{"field": "block", "operator": "shared_token"}]}
        ],
        match_decision_rule={"all": [{"field": "match", "operator": "shared_token"}]},
        clustering_policy="correlation_clustering",
    )["result"]
    cluster = {row["vertex"]: row["cluster"] for row in result["resolved_entity_id"]}
    expected = min(
        sum(
            (labels[u] == labels[v]) != bool(status)
            for (u, v), status in zip(pairs, state, strict=True)
            if status != -1
        )
        for labels in partitions(4)
    )
    actual = sum(
        (cluster[u] == cluster[v]) != bool(status)
        for (u, v), status in zip(pairs, state, strict=True)
        if status != -1
    )
    assert result["candidate_pair_disagreements"] == expected == actual
    assert result["clustering_optimal"]
    assert {(row["source"], row["target"]) for row in result["candidate_pairs"]} == {
        pair for pair, status in zip(pairs, state, strict=True) if status != -1
    }
    for u in range(4):
        if not any(
            u in pair and status != -1
            for pair, status in zip(pairs, state, strict=True)
        ):
            assert sum(c == cluster[u] for c in cluster.values()) == 1


def test_entity_conjunction_disjunction_normalization_optional_fields_and_conflicts():
    graph = records(
        [
            {"name": "Ａlice", "age": 20, "group": "x"},
            {"name": "ALICE", "age": 21, "group": "x"},
            {"name": "Bob", "age": 22, "group": "x"},
            {"group": "y", "age": 40},
        ],
        ids=[0, "0", 2**60, "last"],
    )
    rules = [
        {
            "id": "name",
            "all": [
                {
                    "field": "name",
                    "operator": "eq",
                    "normalization": "nfkc_casefold",
                    "optional": True,
                }
            ],
        },
        {
            "id": "group",
            "all": [
                {"field": "group", "operator": "eq"},
                {"field": "age", "operator": "numeric_difference", "max_distance": 1},
            ],
        },
    ]
    result = execute(
        "entity-resolution",
        graph,
        task="resolution",
        blocking_rules=rules,
        match_decision_rule={
            "all": [
                {"field": "age", "operator": "numeric_difference", "max_distance": 1}
            ]
        },
    )["result"]
    assert result["candidate_pairs"] == [
        {"source": 0, "target": "0", "rule_ids": ["name", "group"]},
        {"source": "0", "target": 2**60, "rule_ids": ["group"]},
    ]
    cluster = {row["vertex"]: row["cluster"] for row in result["resolved_entity_id"]}
    assert cluster[0] == cluster["0"] == cluster[2**60] != cluster["last"]
    graph = records([{"group": "x", "value": v} for v in (0, 1, 2)])
    result = execute(
        "entity-resolution",
        graph,
        task="resolution",
        blocking_rules=[{"id": "all", "all": [{"field": "group", "operator": "eq"}]}],
        match_decision_rule={
            "all": [
                {"field": "value", "operator": "numeric_difference", "max_distance": 1}
            ]
        },
    )["result"]
    assert result["candidate_pair_disagreements"] == 1
    assert len({r["cluster"] for r in result["resolved_entity_id"]}) == 1


def anomaly_formula(values, reference, method, weights, floor):
    dimension = len(weights)
    mean = [statistics.mean(row[j] for row in reference) for j in range(dimension)]
    scale = [statistics.pstdev(row[j] for row in reference) for j in range(dimension)]
    contributions, scores = [], []
    for row in values:
        z = [
            (row[j] - mean[j]) / max(floor, scale[j]) if max(floor, scale[j]) else 0
            for j in range(dimension)
        ]
        c = [
            w * (x * x if method == "standardized_l2" else abs(x))
            for w, x in zip(weights, z, strict=True)
        ]
        score = (
            math.sqrt(sum(c))
            if method == "standardized_l2"
            else sum(c)
            if method == "standardized_l1"
            else max(c)
        )
        contributions.append(c)
        scores.append(score)
    return mean, scale, scores, contributions


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("method", ["standardized_l1", "standardized_l2", "max_abs_z"])
def test_vertex_anomaly_features_scores_and_reference_separation(case, method):
    _, n, edges = case
    adjacency = [
        {b if a == v else a for a, b in edges if v in (a, b)} for v in range(n)
    ]
    values = [
        [
            len(adjacency[v]),
            sum(a in adjacency[v] and b in adjacency[v] for a, b in edges),
            sum(a in adjacency[v] | {v} and b in adjacency[v] | {v} for a, b in edges),
        ]
        for v in range(n)
    ]
    reference_ids = list(range(max(1, n - 1)))
    weights = [1, 0.5, 2]
    mean, scale, scores, contributions = anomaly_formula(
        values, [values[v] for v in reference_ids], method, weights, 0.5
    )
    k = max(1, n // 2)
    result = execute(
        "graph-anomalies",
        Graph.from_edges(edges, vertices=range(n)),
        anomaly_target="vertex",
        feature_definitions=[
            {"name": "degree", "measure": "degree"},
            {"name": "triangles", "measure": "triangle_count"},
            {"name": "ego", "measure": "ego_edge_count"},
        ],
        normality_reference={"kind": "population", "entities": reference_ids},
        scoring_definition={
            "method": method,
            "feature_weights": weights,
            "minimum_scale": 0.5,
        },
        top_k=k,
    )
    data = result["result"]
    assert data["reference_statistics"]["location"] == pytest.approx(mean)
    assert data["reference_statistics"]["scale"] == pytest.approx(scale)
    expected = sorted(range(n), key=lambda v: (-scores[v], v))[:k]
    assert [row["entity"] for row in data["ranked_anomalies"]] == expected
    for row in data["ranked_anomalies"]:
        v = row["entity"]
        assert list(row["feature_values"].values()) == values[v]
        assert list(row["feature_contributions"].values()) == pytest.approx(
            contributions[v]
        )
        assert row["score"] == pytest.approx(scores[v])
    assert data["scored_entity_count"] == n and data["complete"]
    assert result["ports"]["ranking"]["complete"] == (k >= n)


@pytest.mark.parametrize("mask", range(64))
def test_edge_and_subgraph_anomaly_features(mask):
    pairs = list(permutations(range(3), 2))
    edges = [(u, v, i - 2) for i, (u, v) in enumerate(pairs) if mask >> i & 1]
    graph = Graph.from_edges(edges, vertices=range(3), directed=True)
    degrees = [sum(v in (u, w) for u, w, _ in edges) for v in range(3)]
    measures = ["edge_weight", "source_degree", "target_degree"]
    result = execute(
        "graph-anomalies",
        graph,
        anomaly_target="edge",
        feature_definitions=[{"name": m, "measure": m} for m in measures],
        normality_reference={
            "kind": "statistics",
            "location": [0, 0, 0],
            "scale": [1, 1, 1],
        },
        scoring_definition={"method": "standardized_l1"},
        top_k=100,
    )["result"]
    for row in result["ranked_anomalies"]:
        u, v, w = edges[row["entity"]]
        assert list(row["feature_values"].values()) == [w, degrees[u], degrees[v]]
        assert row["score"] == abs(w) + degrees[u] + degrees[v]
    subsets = [set(c) for size in range(4) for c in combinations(range(3), size)]
    measures = ["vertex_count", "edge_count", "weight_sum", "density"]
    result = execute(
        "graph-anomalies",
        graph,
        anomaly_target="subgraph",
        subgraphs=[
            {"id": i, "vertices": sorted(nodes)} for i, nodes in enumerate(subsets)
        ],
        feature_definitions=[{"name": m, "measure": m} for m in measures],
        normality_reference={"kind": "population"},
        scoring_definition={"method": "standardized_l2", "minimum_scale": 0.5},
        top_k=100,
    )["result"]
    for row in result["ranked_anomalies"]:
        nodes = subsets[row["entity"]]
        selected = [(u, v, w) for u, v, w in edges if u in nodes and v in nodes]
        assert list(row["feature_values"].values()) == [
            len(nodes),
            len(selected),
            sum(w for _, _, w in selected),
            len(selected) / (len(nodes) * (len(nodes) - 1)) if len(nodes) > 1 else 0,
        ]


def test_anomaly_parallel_events_loops_external_reference_and_constant_columns():
    graph = Graph.from_edges([], vertices=[0, "0"]).to_canonical()
    graph["graph"].update(allows_self_loops=True, allows_parallel_edges=True)
    graph["edges"] = [
        {"id": i, "source": u, "target": v, "weight": w}
        for i, (u, v, w) in enumerate([(0, "0", 2), (0, "0", 3), (0, 0, 4)])
    ]
    measures = ["degree", "strength", "event_count"]
    result = execute(
        "graph-anomalies",
        graph,
        anomaly_target="vertex",
        feature_definitions=[{"name": m, "measure": m} for m in measures],
        normality_reference={
            "kind": "statistics",
            "location": [0] * 3,
            "scale": [1] * 3,
        },
        scoring_definition={"method": "standardized_l1"},
        top_k=2,
    )["result"]
    by_id = {
        r["entity"]: list(r["feature_values"].values())
        for r in result["ranked_anomalies"]
    }
    assert by_id == {0: [3, 13, 3], "0": [1, 5, 2]}
    graph = records([{"value": v} for v in (10, 12, 14)], ids=["z", 0, "0"])
    reference = records([{"value": v} for v in (0, 2)])
    args = {
        "anomaly_target": "vertex",
        "feature_definitions": [
            {"name": "value", "measure": "numeric_attribute", "field": "value"}
        ],
        "normality_reference": {
            "kind": "population",
            "graph": reference.to_canonical(),
        },
        "scoring_definition": {"method": "standardized_l1"},
        "candidate_entities": ["z"],
        "top_k": 2,
    }
    result = execute("graph-anomalies", graph, **args)["result"]
    assert result["ranked_anomalies"][0]["score"] == 9
    assert result["reference_statistics"]["location"] == [1]
    args.pop("candidate_entities")
    args["normality_reference"] = {"kind": "population"}
    constant = records([{"value": 0.1} for _ in range(7)])
    result = execute("graph-anomalies", constant, **args)["result"]
    assert result["reference_statistics"]["scale"] == [0]
    assert all(row["score"] == 0 for row in result["ranked_anomalies"])
    args["normality_reference"] = {"kind": "statistics", "location": [0], "scale": [0]}
    with pytest.raises(GraphMineError, match="zero-variance"):
        execute("graph-anomalies", constant, **args)
    args["scoring_definition"]["feature_weights"] = [0]
    assert (
        execute("graph-anomalies", constant, **args)["result"]["ranked_anomalies"][0][
            "score"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("group-steiner-tree", {"groups": []}),
        ("group-steiner-tree", {"groups": [[]]}),
        (
            "network-alignment",
            {
                "other_graph": Graph.from_edges([]).to_canonical(),
                "alignment_mode": "local_many_to_one",
            },
        ),
        (
            "network-alignment",
            {"other_graph": Graph.from_edges([]).to_canonical(), "top_k": 1},
        ),
        ("entity-resolution", {"task": "blocking", "blocking_rules": []}),
        (
            "entity-resolution",
            {
                "task": "blocking",
                "blocking_rules": [
                    {"id": "x", "all": [{"field": "missing", "operator": "eq"}]}
                ],
            },
        ),
        (
            "entity-resolution",
            {
                "task": "blocking",
                "blocking_rules": [
                    {
                        "id": "x",
                        "all": [{"field": "x", "operator": "eval", "code": "1+1"}],
                    }
                ],
            },
        ),
        (
            "graph-anomalies",
            {
                "anomaly_target": "vertex",
                "feature_definitions": [],
                "normality_reference": {"kind": "population"},
                "scoring_definition": {"method": "standardized_l1"},
                "top_k": 1,
            },
        ),
    ],
)
def test_new_data_profiles_reject_invalid_or_unimplemented_parameters(
    operation, parameters
):
    with pytest.raises(GraphMineError):
        execute(operation, Graph.from_edges([(0, 1, 1)]), **parameters)


@pytest.mark.parametrize("scale", [1, 1e-3, 1e-6, 1e-9, 1e-12, 1e-15, 1e-200])
def test_optimization_objectives_preserve_small_weight_ordering(scale):
    graph = Graph.from_edges([(0, 2, 4 * scale), (0, 1, scale), (1, 2, scale)])
    result = execute("group-steiner-tree", graph, groups=[[0], [2]])
    assert result["result"]["tree_weight"] == 2 * scale
    assert result["diagnostics"]["objective_scaling"] == "exact_rational_grid"
    a = Graph.from_edges([], vertices=[0])
    b = Graph.from_edges([], vertices=[0, 1])
    result = execute(
        "network-alignment",
        a,
        other_graph=b.to_canonical(),
        node_similarity_prior=[
            {"graph_a_vertex": 0, "graph_b_vertex": 0, "value": scale},
            {"graph_a_vertex": 0, "graph_b_vertex": 1, "value": 2 * scale},
        ],
    )
    assert result["result"]["objective_value"] == 2 * scale
    assert result["result"]["vertex_mapping"][0]["graph_b_vertex"] == 1


def test_binary_objective_grid_retains_large_integer_differences():
    from graphmine.algorithms._milp import BinaryModel
    from graphmine.contracts import Budget, WorkCounter

    model = BinaryModel([2**50 + 1, 2**50], WorkCounter(Budget()))
    model.constrain({0: 1, 1: 1}, lower=1, upper=1)
    solution, evidence = model.solve()
    assert solution == [0, 1]
    assert evidence["objective"] == 2**50


@pytest.mark.parametrize("mask", range(64))
def test_directed_vertex_anomaly_measure_definitions(mask):
    pairs = list(permutations(range(3), 2))
    edges = [(u, v, i - 2) for i, (u, v) in enumerate(pairs) if mask >> i & 1]
    graph = Graph.from_edges(edges, vertices=range(3), directed=True)
    measures = [
        "degree",
        "in_degree",
        "out_degree",
        "strength",
        "in_strength",
        "out_strength",
        "event_count",
        "in_event_count",
        "out_event_count",
    ]
    result = execute(
        "graph-anomalies",
        graph,
        anomaly_target="vertex",
        feature_definitions=[{"name": m, "measure": m} for m in measures],
        normality_reference={
            "kind": "statistics",
            "location": [0] * len(measures),
            "scale": [1] * len(measures),
        },
        scoring_definition={"method": "standardized_l1"},
        top_k=3,
    )["result"]
    for row in result["ranked_anomalies"]:
        v = row["entity"]
        incoming = [w for _, b, w in edges if b == v]
        outgoing = [w for a, _, w in edges if a == v]
        expected = [
            len(incoming) + len(outgoing),
            len(incoming),
            len(outgoing),
            sum(incoming) + sum(outgoing),
            sum(incoming),
            sum(outgoing),
            len(incoming) + len(outgoing),
            len(incoming),
            len(outgoing),
        ]
        assert list(row["feature_values"].values()) == expected
        assert row["score"] == sum(abs(v) for v in expected)


@pytest.mark.parametrize("target", ["vertex", "edge", "subgraph"])
def test_anomaly_empty_population_and_typed_tie_order(target):
    params = {
        "anomaly_target": target,
        "feature_definitions": [
            {"name": "value", "measure": "numeric_attribute", "field": "value"}
        ],
        "normality_reference": {"kind": "population"},
        "scoring_definition": {"method": "standardized_l2"},
        "top_k": 10,
    }
    if target == "subgraph":
        params["subgraphs"] = []
    result = execute("graph-anomalies", Graph.from_edges([]), **params)["result"]
    assert result["ranked_anomalies"] == [] and result["scored_entity_count"] == 0
    if target == "vertex":
        result = execute(
            "graph-anomalies",
            records([{"value": 1}] * 4, ids=["b", 2**60, "0", 0]),
            **params,
        )["result"]
        assert [r["entity"] for r in result["ranked_anomalies"]] == [0, 2**60, "0", "b"]


def test_anomaly_centering_keeps_deviations_around_large_origin():
    graph = records([{"value": 2**50 + d} for d in [0, 1, 2, 8]])
    result = execute(
        "graph-anomalies",
        graph,
        anomaly_target="vertex",
        feature_definitions=[
            {"name": "value", "measure": "numeric_attribute", "field": "value"}
        ],
        normality_reference={"kind": "population", "entities": [0, 1, 2]},
        scoring_definition={"method": "standardized_l1"},
        candidate_entities=[3],
        top_k=1,
    )["result"]
    assert result["ranked_anomalies"][0]["score"] == pytest.approx(7 / math.sqrt(2 / 3))
    assert result["reference_statistics"]["centering_origin"] == [2**50]
    assert result["reference_statistics"]["mean_delta"] == [1]


def test_entity_empty_records_optional_fields_and_typed_json_equality():
    params = {
        "task": "blocking",
        "blocking_rules": [
            {
                "id": "equal",
                "all": [{"field": "value", "operator": "eq", "optional": True}],
            }
        ],
    }
    result = execute("entity-resolution", records([]), **params)["result"]
    assert result["candidate_pairs"] == [] and result["reduction_ratio"] == 0
    result = execute(
        "entity-resolution",
        records(
            [
                {},
                {},
                {"value": None},
                {"value": None},
                {"value": True},
                {"value": 1},
                {"value": 1.0},
            ]
        ),
        **params,
    )["result"]
    assert [(r["source"], r["target"]) for r in result["candidate_pairs"]] == [(2, 3)]
