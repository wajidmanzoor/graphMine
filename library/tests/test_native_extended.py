# Local oracle closures execute synchronously within each exhaustive case.
# ruff: noqa: B023
"""Independent small-graph oracles for the remaining native family migrations.

NetworkX and Python fractions are test dependencies only. Every system under
test call crosses the native C ABI, with CUDA hidden for CPU evidence.
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import random
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import networkx as nx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "extended_native_binding", ROOT / "python/graphmine/graphmine/native/__init__.py"
)
BINDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BINDING)


@pytest.fixture(scope="module")
def native(request):
    library = BINDING.NativeLibrary(
        Path(os.environ["GRAPHMINE_NATIVE_CPU_BUILD"]) / "libgraphmine_runtime.so"
    )
    transport = library.request

    def observe(value):
        result = transport(value)
        if value.get("command") == "run":
            key = result["operation"] + ":" + result["backend"]["id"]
            counts = request.session.native_observed_operations
            counts[key] = counts.get(key, 0) + 1
        return result

    library.request = observe
    return library


def canonical(n, edges, *, directed=False, sides=None):
    vertices = [{"id": i} for i in range(n)]
    if sides is not None:
        for row, side in zip(vertices, sides, strict=True):
            row["attributes"] = {"side": side}
    records = []
    for i, edge in enumerate(edges):
        u, v, *weight = edge
        records.append({"id": i, "source": u, "target": v})
        if weight:
            records[-1]["weight"] = weight[0]
    return {
        "graph": {
            "id": "native-independent-oracle",
            "directed": directed,
            "allows_self_loops": True,
            "allows_parallel_edges": True,
        },
        "vertices": vertices,
        "edges": records,
    }


def run(native, operation, graph, **parameters):
    result = native.run(operation, graph, parameters=parameters, device="cpu")
    assert result["backend"]["id"] == "cpp"
    assert result["backend"]["python_runtime_required"] is False
    return result


def test_temporal_motifs_event_permutation_oracle(native):
    rng = random.Random(748)
    query = canonical(3, [(0, 1), (1, 2)], directed=True)
    for _ in range(35):
        data = canonical(4, [rng.sample(range(4), 2) for _ in range(8)], directed=True)
        for edge in data["edges"]:
            edge["timestamp"] = 2**53 + rng.randrange(6)
        for equal, induced, ordered in itertools.product((False, True), repeat=3):
            expected = set()
            participation = [0] * 4
            for a, b in itertools.permutations(range(8), 2):
                first, second = data["edges"][a], data["edges"][b]
                vertices = {first["source"], first["target"], second["target"]}
                if first["target"] != second["source"] or len(vertices) != 3:
                    continue
                times = [first["timestamp"], second["timestamp"]]
                if ordered and (times[0] > times[1] if equal else times[0] >= times[1]):
                    continue
                if max(times) - min(times) > 2:
                    continue
                if induced and any(
                    i not in (a, b)
                    and edge["source"] in vertices
                    and edge["target"] in vertices
                    and min(times) <= edge["timestamp"] <= max(times)
                    for i, edge in enumerate(data["edges"])
                ):
                    continue
                expected.add((a, b))
                for v in vertices:
                    participation[v] += 1
            spec = {"graph": query, **({} if ordered else {"order": []})}
            result = run(
                native,
                "temporal-motifs",
                data,
                temporal_motif=spec,
                maximum_duration_seconds=2,
                allow_equal_timestamps=equal,
                temporal_induced=induced,
                list_instances=True,
            )["result"]
            assert {tuple(row["edge_ids"]) for row in result["instances"]} == expected
            assert result["occurrence_count"] == len(expected)
            assert [
                row["value"] for row in result["per_vertex_participation"]
            ] == participation
    with pytest.raises(BINDING.NativeError, match="acyclic"):
        run(
            native,
            "temporal-motifs",
            data,
            temporal_motif={"graph": query, "order": [[0, 1], [1, 0]]},
            maximum_duration_seconds=2,
            allow_equal_timestamps=True,
        )


def test_knn_independent_distances_and_structured_contract(native):
    import numpy as np
    from scipy.spatial.distance import cdist

    values = [[1, 0], [0, 1], [1, 1], [1, 0], [-1, -2]]
    ids = [1, "1", "x", -7, 90]
    data = {
        "dataset_id": "vectors",
        "dimension": 2,
        "vectors": [{"id": i, "values": v} for i, v in zip(ids, values, strict=True)],
    }
    for metric, symmetry, k in itertools.product(
        ("euclidean", "squared_euclidean", "cosine"),
        ("directed", "union", "mutual"),
        (0, 1, 4),
    ):
        distances = cdist(
            values, values, "sqeuclidean" if metric == "squared_euclidean" else metric
        )
        expected = [
            sorted((j for j in range(5) if j != i), key=lambda j: (distances[i, j], j))[
                :k
            ]
            for i in range(5)
        ]
        result = run(
            native, "knn-graph", data, k=k, distance=metric, symmetrization=symmetry
        )
        assert result["input_kind"] == "feature_vectors"
        assert (
            result["ports"]["graph"]["graph_fingerprint"] != result["input_fingerprint"]
        )
        for i, row in enumerate(result["result"]["neighbor_lists"]):
            assert row["neighbors"] == [ids[j] for j in expected[i]]
            np.testing.assert_allclose(
                row["distances"], [distances[i, j] for j in expected[i]], atol=1e-15
            )
        arcs = {(i, j) for i in range(5) for j in expected[i]}
        pairs = (
            arcs
            if symmetry == "directed"
            else {
                tuple(sorted((i, j)))
                for i, j in arcs
                if symmetry == "union" or (j, i) in arcs
            }
        )
        assert [
            (e["source"], e["target"]) for e in result["result"]["graph"]["edges"]
        ] == [(ids[i], ids[j]) for i, j in sorted(pairs)]
    duplicate = deepcopy(data)
    duplicate["vectors"][1]["id"] = 1
    with pytest.raises(BINDING.NativeError, match="Duplicate"):
        run(native, "knn-graph", duplicate, k=1)
    with pytest.raises(BINDING.NativeError, match="zero vector"):
        run(
            native,
            "knn-graph",
            {**data, "vectors": [{"id": i, "values": [0, 0]} for i in ids]},
            k=1,
            distance="cosine",
        )


def test_hypergraph_partitions_exact_assignment_oracle(native):
    rng = random.Random(186)
    for _ in range(30):
        n = 5
        weights = [rng.randrange(4) for _ in range(n)]
        edges = [
            (rng.sample(range(n), rng.randrange(1, n + 1)), rng.randrange(5))
            for _ in range(5)
        ]
        data = {
            "graph": {"id": "hypergraph"},
            "vertices": [{"id": v, "weight": w} for v, w in enumerate(weights)],
            "hyperedges": [
                {"id": i, "vertices": vs, "weight": w}
                for i, (vs, w) in enumerate(edges)
            ],
        }
        for k, objective in itertools.product(
            (1, 2, 3), ("cut_net", "connectivity_minus_one")
        ):
            costs = []
            upper = Fraction(sum(weights), k) * Fraction(6, 5)
            for assignment in itertools.product(range(k), repeat=n):
                if len(set(assignment)) != k or any(
                    sum(weights[v] for v in range(n) if assignment[v] == p) > upper
                    for p in range(k)
                ):
                    continue
                costs.append(
                    sum(
                        w
                        * (
                            (len({assignment[v] for v in vs}) > 1)
                            if objective == "cut_net"
                            else len({assignment[v] for v in vs}) - 1
                        )
                        for vs, w in edges
                    )
                )
            result = run(
                native,
                "hypergraph-partitioning",
                data,
                num_parts=k,
                objective=objective,
                imbalance_tolerance=0.2,
            )["result"]
            assert result["feasible"] == bool(costs)
            if costs:
                assert fraction(result, "objective_value") == min(costs)
                assert all(w <= upper for w in result["part_weights"])
            else:
                assert result["infeasibility_certified"]


def _pattern_networkx(data):
    graph = nx.DiGraph() if data["graph"]["directed"] else nx.Graph()
    graph.add_nodes_from(
        (v["id"], {"label": v.get("label", v.get("type"))}) for v in data["vertices"]
    )
    graph.add_edges_from(
        (e["source"], e["target"], {"label": e.get("type")}) for e in data["edges"]
    )
    return graph


def _replay_native_edits(result):
    source, target = result["normalized_source"], result["normalized_target"]
    handles = {row["id"]: i for i, row in enumerate(source["vertices"])}
    vertices = {i: deepcopy(row) for i, row in enumerate(source["vertices"])}
    edges = {
        i: {**row, "source": handles[row["source"]], "target": handles[row["target"]]}
        for i, row in enumerate(source["edges"])
    }
    total = Fraction()
    for operation in result["edit_path"]:
        total += Fraction(
            int(operation["cost_numerator"]), int(operation["cost_denominator"])
        )
        kind = operation["operation"]
        if kind == "edge_deletion":
            del edges[operation["edge_handle"]]
        elif kind == "vertex_deletion":
            h = operation["vertex_handle"]
            assert all(h not in (e["source"], e["target"]) for e in edges.values())
            del vertices[h]
        elif kind.startswith("vertex_"):
            vertices[operation["vertex_handle"]] = operation["vertex_record"]
        else:
            edge = operation["edge_record"]
            assert edge["source"] in vertices and edge["target"] in vertices
            edges[operation["edge_handle"]] = edge
    final_edges = [
        {
            **row,
            "source": vertices[row["source"]]["id"],
            "target": vertices[row["target"]]["id"],
        }
        for row in edges.values()
    ]
    assert sorted(vertices.values(), key=lambda r: r["id"]) == sorted(
        target["vertices"], key=lambda r: r["id"]
    )
    if not target["graph"]["directed"]:
        for row in [*final_edges, *target["edges"]]:
            row["source"], row["target"] = sorted((row["source"], row["target"]))
    assert sorted(final_edges, key=lambda r: r["id"]) == sorted(
        target["edges"], key=lambda r: r["id"]
    )
    assert total == fraction(result["task_result"], "distance")


def _ged_assignment_oracle(a, b, edge_substitution):
    """Independent binary vertex/edge assignment MILP, not correspondence DFS.

    NetworkX 3.7's GED search misses a valid cost-five script in one fixture
    when vertex replacement ties deletion plus insertion. The MILP handles
    that tie explicitly; the separate replay checks the primal edit witness.
    """
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp

    pairs = list(itertools.product(a, b))
    x = {pair: i for i, pair in enumerate(pairs)}
    costs = [
        (-2 if a.nodes[u]["label"] == b.nodes[v]["label"] else 0) for u, v in pairs
    ]
    edges_a, edges_b = list(a.edges), list(b.edges)
    candidates = []
    for i, (u, v) in enumerate(edges_a):
        for j, (p, q) in enumerate(edges_b):
            for source, target in [(p, q)] if a.is_directed() else [(p, q), (q, p)]:
                candidates.append((i, j, x[u, source], x[v, target]))
                costs.append(
                    (0 if a[u][v]["label"] == b[p][q]["label"] else edge_substitution)
                    - 2
                )
    rows, upper = [], []

    def constrain(entries, bound):
        row = np.zeros(len(costs))
        for index, coefficient in entries:
            row[index] = coefficient
        rows.append(row)
        upper.append(bound)

    for u in a:
        constrain([(x[u, v], 1) for v in b], 1)
    for v in b:
        constrain([(x[u, v], 1) for u in a], 1)
    for r, (_, _, first, second) in enumerate(candidates, len(pairs)):
        constrain([(r, 1), (first, -1)], 0)
        constrain([(r, 1), (second, -1)], 0)
    for side, edges in enumerate((edges_a, edges_b)):
        for index in range(len(edges)):
            constrain(
                [
                    (len(pairs) + r, 1)
                    for r, candidate in enumerate(candidates)
                    if candidate[side] == index
                ],
                1,
            )
    solution = milp(
        costs,
        integrality=np.ones(len(costs)),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(np.array(rows), -np.inf, upper),
    )
    assert solution.success
    assert np.max(np.abs(solution.x - np.rint(solution.x))) < 1e-7
    value = len(a) + len(b) + len(edges_a) + len(edges_b) + solution.fun
    assert abs(value - round(value)) < 1e-7
    return round(value)


def test_graph_edit_objective_and_executable_script(native):
    rng = random.Random(1245)
    for directed in (False, True):
        for _ in range(35):
            pair = []
            for n in (3, 4):
                data = canonical(
                    n,
                    [
                        e
                        for e in itertools.permutations(range(n), 2)
                        if (directed or e[0] < e[1]) and rng.random() < 0.3
                    ],
                    directed=directed,
                )
                for row in data["vertices"]:
                    row["label"] = rng.choice(("a", "b"))
                for row in data["edges"]:
                    row["type"] = rng.choice(("x", "y"))
                pair.append(data)
            a, b = map(_pattern_networkx, pair)
            edge_substitution = rng.choice((1, 4))
            expected = _ged_assignment_oracle(a, b, edge_substitution)
            result = run(
                native,
                "graph-edit-distance",
                pair[0],
                other_graph=pair[1],
                edit_costs={"edge_substitution": edge_substitution},
            )["result"]
            assert fraction(result["task_result"], "distance") == expected
            _replay_native_edits(result)
    result = run(
        native,
        "graph-edit-distance",
        canonical(0, []),
        other_graph=canonical(3, [(0, 1)]),
        edit_costs={"vertex_insertion": 0.1, "edge_insertion": 0.2},
    )["result"]
    assert fraction(result["task_result"], "distance") == Fraction(1, 2)
    _replay_native_edits(result)


def test_maximum_common_subgraph_independent_subsets(native):
    rng = random.Random(285)
    for directed in (False, True):
        for _ in range(20):
            pair = [
                canonical(
                    n,
                    [
                        e
                        for e in itertools.permutations(range(n), 2)
                        if (directed or e[0] < e[1]) and rng.random() < 0.4
                    ],
                    directed=directed,
                )
                for n in (3, 4)
            ]
            for data in pair:
                for row in data["vertices"]:
                    row["type"] = rng.choice(("a", "b"))
            a, b = map(_pattern_networkx, pair)
            for induced in (False, True):
                if induced:
                    optimum = max(
                        k
                        for k in range(4)
                        if any(
                            _same_pattern(a.subgraph(va), b.subgraph(vb))
                            for va in itertools.combinations(a, k)
                            for vb in itertools.combinations(b, k)
                        )
                    )
                else:
                    optimum = sum(
                        min(
                            sum(d["label"] == label for _, d in a.nodes(data=True)),
                            sum(d["label"] == label for _, d in b.nodes(data=True)),
                        )
                        for label in ("a", "b")
                    )
                result = run(
                    native,
                    "maximum-common-subgraph",
                    pair[0],
                    other_graph=pair[1],
                    induced=induced,
                )["result"]
                assert result["task_result"]["vertex_count"] == optimum
                mapping = {
                    r["graph_a_vertex"]: r["graph_b_vertex"]
                    for r in result["vertex_correspondence"]
                }
                assert len(set(mapping.values())) == len(mapping)
                common = _pattern_networkx(result["task_result"]["subgraph"])
                assert set(common) == set(mapping)
                for u, v in common.edges:
                    assert b.has_edge(mapping[u], mapping[v])


def test_coarsening_quotient_and_aggregate_precision(native):
    data = canonical(5, [(0, 1, 0.1), (0, 1, 0.2), (1, 2, 2), (2, 3, 7), (3, 4, 4)])
    for v in data["vertices"]:
        v["attributes"] = {"features": [v["id"], v["id"] + 0.5]}
    assignment = [-5, -5, 2, 2, 8]
    for loops, reduction in itertools.product(("keep", "drop"), ("sum", "mean")):
        result = run(
            native,
            "graph-coarsening",
            data,
            cluster_assignment=[
                {"vertex": v, "value": c} for v, c in enumerate(assignment)
            ],
            self_loop_policy=loops,
            feature_reduction=reduction,
        )
        expected = {}
        for e in data["edges"]:
            pair = tuple(sorted((assignment[e["source"]], assignment[e["target"]])))
            if pair[0] == pair[1] and loops == "drop":
                continue
            expected[pair] = expected.get(pair, Fraction()) + Fraction(e["weight"])
        actual = result["result"]["coarse_graph"]
        exact = {
            row["edge"]: Fraction(
                int(row["value"]["numerator"]), int(row["value"]["denominator"])
            )
            for row in result["diagnostics"]["exact_edge_weights"]
        }
        assert {
            (e["source"], e["target"]): exact[e["id"]] for e in actual["edges"]
        } == expected
        for vertex in actual["vertices"]:
            members = [v for v, c in enumerate(assignment) if c == vertex["id"]]
            for j, value in enumerate(vertex["attributes"]["features"]):
                expected_value = sum(
                    data["vertices"][v]["attributes"]["features"][j] for v in members
                )
                if reduction == "mean":
                    expected_value /= len(members)
                assert value == expected_value
        if loops == "keep":
            assert result["diagnostics"]["binary64_output_rounded"]


def test_spectral_sparsification_all_vector_oracle(native):
    import numpy as np
    from scipy.linalg import eigvalsh

    data = canonical(
        7, [(u, v, 1 + (u + v) % 3) for u, v in itertools.combinations(range(6), 2)]
    )
    g = nx.Graph()
    g.add_nodes_from(range(7))
    g.add_weighted_edges_from(
        (e["source"], e["target"], e["weight"]) for e in data["edges"]
    )
    laplacian = nx.laplacian_matrix(g, nodelist=range(7)).toarray().astype(float)
    inverse = np.linalg.pinv(laplacian)
    masses = [
        e["weight"]
        * (
            inverse[e["source"], e["source"]]
            + inverse[e["target"], e["target"]]
            - 2 * inverse[e["source"], e["target"]]
        )
        / 5
        for e in data["edges"]
    ]
    for budget in (0, 3, 7, 12, 15, 50):
        for seed in (0, 71):
            result = run(
                native,
                "spectral-sparsification",
                data,
                edge_budget=budget,
                random_seed=seed,
            )
            output = result["result"]["sparsifier"]
            summary = result["result"]["quality_summary"]
            assert len(output["edges"]) <= budget
            candidate = np.zeros((7, 7))
            for edge in output["edges"]:
                u, v, w = edge["source"], edge["target"], edge["weight"]
                candidate[u, u] += w
                candidate[v, v] += w
                candidate[u, v] -= w
                candidate[v, u] -= w
            ratios = eigvalsh(candidate[:5, :5], laplacian[:5, :5])
            assert summary["lower_quadratic_form_ratio"] == pytest.approx(
                ratios[0], abs=1e-9
            )
            assert summary["upper_quadratic_form_ratio"] == pytest.approx(
                ratios[-1], abs=1e-9
            )
            assert summary["maximum_relative_spectral_error"] == pytest.approx(
                max(abs(1 - ratios[0]), abs(ratios[-1] - 1)), abs=1e-9
            )
            if 0 < budget < 15:
                draws = result["diagnostics"]["draws"]
                np.testing.assert_allclose(
                    [r["probability_mass"] for r in draws], masses, rtol=1e-8
                )
                assert sum(row["draws"] for row in draws) == budget
    with pytest.raises(BINDING.NativeError, match="epsilon"):
        run(native, "spectral-sparsification", data, edge_budget=0, epsilon=0.9)


def test_entity_resolution_unicode_and_clustering_objective(native):
    import unicodedata

    from rapidfuzz.distance import Levenshtein

    names = ["Straße", "STRASSE", "Ｓｔｒａｓｓｅ", "Strase", "abc 😀", "ABC 😃"]
    data = canonical(len(names), [(0, 5)])
    for row, name in zip(data["vertices"], names, strict=True):
        row["attributes"] = {"name": name, "amount": 2**53 + row["id"]}
    normalized = [unicodedata.normalize("NFKC", name).casefold() for name in names]
    blocking = [
        {
            "id": "near",
            "all": [
                {
                    "field": "name",
                    "operator": "edit_distance",
                    "normalization": "nfkc_casefold",
                    "max_distance": 1,
                }
            ],
        }
    ]
    decisions = {
        pair: normalized[pair[0]] == normalized[pair[1]]
        for pair in itertools.combinations(range(6), 2)
        if Levenshtein.distance(normalized[pair[0]], normalized[pair[1]]) <= 1
    }
    for policy in ("connected_components", "correlation_clustering"):
        result = run(
            native,
            "entity-resolution",
            data,
            task="resolution",
            blocking_rules=blocking,
            match_decision_rule={
                "all": [
                    {
                        "field": "name",
                        "operator": "eq",
                        "normalization": "nfkc_casefold",
                    }
                ]
            },
            clustering_policy=policy,
        )["result"]
        assert {
            (r["source"], r["target"]): r["match"] for r in result["match_decision"]
        } == decisions
        assert result["candidate_pair_disagreements"] == 0
        cluster = {r["vertex"]: r["cluster"] for r in result["resolved_entity_id"]}
        for (u, v), matched in decisions.items():
            assert (cluster[u] == cluster[v]) == matched
    numeric = run(
        native,
        "entity-resolution",
        data,
        task="blocking",
        blocking_rules=[
            {
                "id": 1,
                "all": [
                    {
                        "field": "amount",
                        "operator": "numeric_difference",
                        "max_distance": 1,
                    }
                ],
            }
        ],
    )["result"]
    assert {(r["source"], r["target"]) for r in numeric["candidate_pairs"]} == {
        (i, i + 1) for i in range(5)
    }
    # A nontransitive positive relation forces a real correlation-clustering choice.
    small = canonical(4, [])
    for row in small["vertices"]:
        row["attributes"] = {"x": row["id"], "block": True}
    result = run(
        native,
        "entity-resolution",
        small,
        task="resolution",
        blocking_rules=[{"id": 0, "all": [{"field": "block", "operator": "eq"}]}],
        match_decision_rule={
            "all": [{"field": "x", "operator": "numeric_difference", "max_distance": 1}]
        },
        clustering_policy="correlation_clustering",
    )["result"]
    optimum = min(
        sum(
            ((parts[u] == parts[v]) != (v - u == 1))
            for u, v in itertools.combinations(range(4), 2)
        )
        for parts in itertools.product(range(4), repeat=4)
    )
    assert result["candidate_pair_disagreements"] == optimum


def test_anomaly_features_and_declared_statistics(native):
    import numpy as np

    data = canonical(4, [(0, 0, 2), (0, 1, 3), (0, 1, 4), (1, 2, 5), (2, 0, 6)])
    measures = ["degree", "strength", "triangle_count", "ego_edge_count", "event_count"]
    expected = np.array(
        [[4, 17, 1, 3, 4], [2, 12, 1, 3, 3], [2, 11, 1, 3, 2], [0, 0, 0, 0, 0]],
        dtype=float,
    )
    for method in ("standardized_l1", "standardized_l2", "max_abs_z"):
        result = run(
            native,
            "graph-anomalies",
            data,
            anomaly_target="vertex",
            feature_definitions=[{"name": m, "measure": m} for m in measures],
            normality_reference={"kind": "population"},
            scoring_definition={"method": method, "minimum_scale": 0.1},
            top_k=4,
        )
        np.testing.assert_allclose(
            result["result"]["reference_statistics"]["location"], expected.mean(axis=0)
        )
        np.testing.assert_allclose(
            result["result"]["reference_statistics"]["scale"], expected.std(axis=0)
        )
        z = (expected - expected.mean(axis=0)) / np.maximum(expected.std(axis=0), 0.1)
        scores = (
            np.sqrt((z * z).sum(axis=1))
            if method == "standardized_l2"
            else np.abs(z).sum(axis=1)
            if method == "standardized_l1"
            else np.abs(z).max(axis=1)
        )
        for row in result["result"]["ranked_anomalies"]:
            assert row["score"] == pytest.approx(scores[row["entity"]])
            assert [row["feature_values"][m] for m in measures] == expected[
                row["entity"]
            ].tolist()
    for v in data["vertices"]:
        v["attributes"] = {"x": 1 if v["id"] < 3 else 2}
    args = {
        "anomaly_target": "vertex",
        "feature_definitions": [
            {"name": "x", "measure": "numeric_attribute", "field": "x"}
        ],
        "normality_reference": {"kind": "population", "entities": [0, 1, 2]},
        "scoring_definition": {"method": "standardized_l2"},
        "top_k": 2,
    }
    with pytest.raises(BINDING.NativeError, match="zero-variance"):
        run(native, "graph-anomalies", data, **args)
    args["scoring_definition"]["minimum_scale"] = 0.5
    result = run(native, "graph-anomalies", data, **args)
    assert result["result"]["ranked_anomalies"][0]["entity"] == 3
    assert result["result"]["ranked_anomalies"][0]["score"] == 2
    assert not result["ports"]["ranking"]["complete"]


def _same_pattern(a, b):
    return nx.is_isomorphic(
        a,
        b,
        node_match=lambda x, y: x["label"] == y["label"],
        edge_match=lambda x, y: x["label"] == y["label"],
    )


def test_frequent_transactions_support_and_canonicalization(native):
    for directed, induced in itertools.product((False, True), repeat=2):
        sources = [
            canonical(3, [(0, 1), (1, 2), (0, 2)], directed=directed),
            canonical(3, [(2, 1), (1, 0)], directed=directed),
            canonical(2, [], directed=directed),
        ]
        for i, source in enumerate(sources):
            source["graph"]["id"] = str(i)
            for v in source["vertices"]:
                v["type"] = "a" if v["id"] == 1 else "b"
            for e in source["edges"]:
                e["type"] = "connection"
        records = []
        for transaction, source in enumerate(sources):
            host = _pattern_networkx(source)
            for size in range(4):
                for vertices in itertools.combinations(host, size):
                    inside = list(host.subgraph(vertices).edges)
                    subsets = (
                        [inside]
                        if induced
                        else [
                            chosen
                            for k in range(min(2, len(inside)) + 1)
                            for chosen in itertools.combinations(inside, k)
                        ]
                    )
                    for edges in subsets:
                        if len(edges) > 2:
                            continue
                        candidate = host.subgraph(vertices).copy()
                        candidate.remove_edges_from(set(candidate.edges) - set(edges))
                        record = next(
                            (r for r in records if _same_pattern(r[0], candidate)), None
                        )
                        if record is None:
                            record = (candidate, set())
                            records.append(record)
                        record[1].add(str(transaction))
        expected = [r for r in records if len(r[1]) >= 2]
        data = {"dataset_id": "transactions", "graphs": sources}
        result = run(
            native,
            "frequent-subgraphs",
            data,
            minimum_support_fraction=0.5,
            minimum_edges=0,
            maximum_edges=2,
            minimum_vertices=0,
            maximum_vertices=3,
            induced=induced,
            include_supporting_graph_ids=True,
        )
        assert result["input_kind"] == "graph_collection"
        actual = result["result"]["patterns"]
        assert len(actual) == len(expected)
        for row in actual:
            match = [
                r
                for r in expected
                if _same_pattern(r[0], _pattern_networkx(row["pattern"]))
            ]
            assert len(match) == 1
            assert row["supporting_graph_ids"] == sorted(match[0][1])
        # Vertex and transaction order cannot change canonical pattern IDs.
        reordered = deepcopy(data)
        reordered["graphs"].reverse()
        for graph in reordered["graphs"]:
            graph["vertices"].reverse()
            graph["edges"].reverse()
        again = run(
            native,
            "frequent-subgraphs",
            reordered,
            minimum_support_fraction=0.5,
            minimum_edges=0,
            maximum_edges=2,
            minimum_vertices=0,
            maximum_vertices=3,
            induced=induced,
            include_supporting_graph_ids=True,
        )
        assert again["result"] == result["result"]


def test_single_graph_minimum_image_support_oracle(native):
    data = canonical(5, [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4), (4, 0)])
    for v in data["vertices"]:
        v["label"] = "a" if v["id"] % 2 else "b"
    host = _pattern_networkx(data)
    for induced in (False, True):
        candidates = [host.subgraph([v]).copy() for v in host]
        for k in (1, 2, 3):
            for chosen in itertools.combinations(host.edges, k):
                vs = {v for pair in chosen for v in pair}
                candidate = host.subgraph(vs).copy()
                if induced and len(candidate.edges) != k:
                    continue
                candidate.remove_edges_from(set(candidate.edges) - set(chosen))
                if nx.is_connected(candidate) and not any(
                    _same_pattern(candidate, old) for old in candidates
                ):
                    candidates.append(candidate)
        unique = []
        for candidate in candidates:
            if not any(_same_pattern(candidate, old) for old in unique):
                unique.append(candidate)
        expected = []
        for candidate in unique:
            matcher = nx.algorithms.isomorphism.GraphMatcher(
                host, candidate, node_match=lambda a, b: a["label"] == b["label"]
            )
            mappings = (
                matcher.subgraph_isomorphisms_iter()
                if induced
                else matcher.subgraph_monomorphisms_iter()
            )
            images = {v: set() for v in candidate}
            for mapping in mappings:
                for h, q in mapping.items():
                    images[q].add(h)
            support = min(map(len, images.values()))
            if support >= 2:
                expected.append((candidate, support))
        result = run(
            native,
            "single-graph-frequent-subgraphs",
            data,
            minimum_image_support=2,
            max_pattern_edges=3,
            match_mode="induced" if induced else "non_induced",
            output_mode="patterns",
            include_images=True,
        )["result"]
        assert result["frequent_pattern_count"] == len(expected)
        for row in result["patterns"]:
            matches = [
                support
                for candidate, support in expected
                if _same_pattern(candidate, _pattern_networkx(row["pattern"]))
            ]
            assert matches == [row["minimum_image_support"]]
            assert (
                min(len(image["host_vertices"]) for image in row["images"])
                == matches[0]
            )


def fraction(row, name):
    value = row[name + "_exact"]
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def graphs(n, directed=False):
    pairs = list(
        itertools.permutations(range(n), 2)
        if directed
        else itertools.combinations(range(n), 2)
    )
    for mask in range(1 << len(pairs)):
        edges = [pair for i, pair in enumerate(pairs) if mask >> i & 1]
        g = nx.DiGraph() if directed else nx.Graph()
        g.add_nodes_from(range(n))
        g.add_edges_from(edges)
        yield g, canonical(n, edges, directed=directed)


def subsets(n, minimum=1):
    for mask in range(1, 1 << n):
        selected = frozenset(v for v in range(n) if mask >> v & 1)
        if len(selected) >= minimum:
            yield selected


def test_density_exhaustive(native):
    for g, graph in graphs(4):
        choices = list(subsets(len(g)))
        for order in (2, 3, 4, 5):
            cliques = [set(c) for c in nx.enumerate_all_cliques(g) if len(c) == order]
            for minimum in (1, 2):
                expected = max(
                    Fraction(sum(c <= s for c in cliques), len(s))
                    for s in choices
                    if len(s) >= minimum
                )
                result = run(
                    native,
                    "densest-subgraph",
                    graph,
                    clique_order=order,
                    minimum_vertices=minimum,
                )["result"]
                assert fraction(result, "density") == expected
                selected = set(result["vertices"])
                assert len(selected) >= minimum
                assert (
                    Fraction(sum(c <= selected for c in cliques), len(selected))
                    == expected
                )
        for k in range(1, len(g) + 1):
            expected = max(
                g.subgraph(s).number_of_edges() for s in choices if len(s) == k
            )
            result = run(native, "densest-k-subgraph", graph, k=k)["result"]
            assert len(result["vertices"]) == k
            assert fraction(result, "induced_edge_value") == expected
            assert g.subgraph(result["vertices"]).number_of_edges() == expected


def test_quasi_cliques_exhaustive(native):
    for g, graph in graphs(4):
        for gamma in (0.14, 0.5, 0.67, 1):
            for upper in (3, 4):
                accepted = [
                    s
                    for s in subsets(len(g), 2)
                    if len(s) <= upper
                    and all(
                        Fraction(g.subgraph(s).degree(v))
                        >= Fraction(str(gamma)) * (len(s) - 1)
                        for v in s
                    )
                ]
                for maximal in (False, True):
                    expected = {
                        s
                        for s in accepted
                        if not maximal or not any(s < t for t in accepted)
                    }
                    result = run(
                        native,
                        "quasi-cliques",
                        graph,
                        gamma=gamma,
                        minimum_size=2,
                        maximum_size=upper,
                        maximal_only=maximal,
                    )
                    assert {
                        frozenset(row["vertices"])
                        for row in result["result"]["quasi_cliques"]
                    } == expected
                    assert result["complete"]


def test_bipartite_exhaustive(native):
    pairs = list(itertools.product(range(3), range(3, 6)))
    for mask in range(1 << len(pairs)):
        edges = [pair for i, pair in enumerate(pairs) if mask >> i & 1]
        graph = canonical(6, edges, sides=["left"] * 3 + ["right"] * 3)
        edge_set = set(edges)
        expected = set()
        for left in subsets(3):
            for raw_right in subsets(3):
                right = frozenset(v + 3 for v in raw_right)
                if all((u, v) in edge_set for u in left for v in right):
                    expected.add((left, right))
        maximal = {
            (l, r)
            for l, r in expected
            if not any(l <= a and r <= b and (l, r) != (a, b) for a, b in expected)
        }
        result = run(
            native,
            "maximal-bicliques",
            graph,
            left_partition=[0, 1, 2],
            right_partition=[3, 4, 5],
        )
        actual = {
            (frozenset(row["left_vertices"]), frozenset(row["right_vertices"]))
            for row in result["result"]["bicliques"]
        }
        assert actual == maximal
        butterflies = [(l, r) for l, r in expected if len(l) == len(r) == 2]
        result = run(native, "butterfly-counting", graph, mode="per_vertex")["result"]
        assert result["butterfly_count"] == len(butterflies)
        assert [row["count"] for row in result["vertices"]] == [
            sum(v in l | r for l, r in butterflies) for v in range(6)
        ]
        result = run(native, "butterfly-counting", graph, mode="per_edge")["result"]
        for row in result["edges"]:
            u, v = row["source"], row["target"]
            assert row["count"] == sum(u in l and v in r for l, r in butterflies)
        for measure in ("degree", "butterfly_participation"):
            remaining = set(range(6))
            while True:
                if measure == "degree":
                    scores = {
                        v: sum(v in e and set(e) <= remaining for e in edges)
                        for v in remaining
                    }
                else:
                    scores = {
                        v: sum(
                            v in l | r and l | r <= remaining for l, r in butterflies
                        )
                        for v in remaining
                    }
                removed = {
                    v for v, score in scores.items() if score < (1 if v < 3 else 2)
                }
                if not removed:
                    break
                remaining -= removed
            result = run(
                native,
                "butterfly-counting",
                graph,
                mode="alpha_beta_core",
                alpha=1,
                beta=2,
                core_measure=measure,
            )
            assert set(result["result"]["cores"][0]["vertices"]) == remaining


def test_reachability_exhaustive(native):
    for g, graph in graphs(3, directed=True):
        expected = set(nx.transitive_closure(g, reflexive=True).edges())
        result = run(native, "transitive-closure", graph)
        assert {
            (row["source"], row["target"]) for row in result["result"]["pairs"]
        } == expected
        result = run(native, "transitive-closure", graph, enumerate_closure_edges=False)
        assert result["result"]["count"] == len(expected)
        assert result["ports"]["count"]["complete"]
        assert not result["ports"]["pairs"]["complete"]
        pairs = list(itertools.product(range(3), repeat=2))
        result = run(
            native,
            "transitive-closure",
            graph,
            query_mode="batch_pairs",
            query_pairs=pairs,
        )
        assert [row["reachable"] for row in result["result"]["pairs"]] == [
            pair in expected for pair in pairs
        ]


def test_overlapping_exhaustive(native):
    for g, graph in graphs(5):
        for k in (2, 3, 4):
            expected = {frozenset(c) for c in nx.community.k_clique_communities(g, k)}
            result = run(native, "overlapping-communities", graph, k=k)
            assert {
                frozenset(row["vertices"]) for row in result["result"]["groups"]
            } == expected
            assigned = set().union(*expected) if expected else set()
            assert set(result["result"]["unassigned_vertices"]) == set(g) - assigned


def test_density_weight_precision_and_scale(native):
    graph = canonical(
        5, [(0, 1, 2**52), (0, 1, 0.5), (2, 3, 2**52), (2, 3, 0.25), (4, 4, 100)]
    )
    result = run(native, "densest-subgraph", graph, weight_mode="edge_weight")["result"]
    assert set(result["vertices"]) == {0, 1}
    assert fraction(result, "density") == (Fraction(2**52) + Fraction(1, 2)) / 2
    graph = canonical(257, [(v, v + 1) for v in range(255)])
    result = run(native, "densest-subgraph", graph)["result"]
    assert len(result["vertices"]) == 256
    assert fraction(result, "density") == Fraction(255, 256)


def all_partitions(n):
    # Test oracle uses all labeled assignments, independent of the native
    # restricted-growth enumeration and community local-move implementation.
    for assignment in itertools.product(range(n), repeat=n):
        if assignment and assignment[0] != 0:
            continue
        yield [
            {v for v, p in enumerate(assignment) if p == label}
            for label in sorted(set(assignment))
        ]


def test_community_exact_objectives(native):
    partitions = list(all_partitions(4))
    for g, graph in graphs(4):
        for objective in ("modularity", "constant_potts_model"):
            if objective == "modularity":
                score = lambda parts: (
                    nx.community.modularity(g, parts, resolution=0.75)
                    if g.number_of_edges()
                    else 0
                )
            else:
                score = lambda parts: sum(
                    g.subgraph(p).number_of_edges() - 0.75 * len(p) * (len(p) - 1) / 2
                    for p in parts
                )
            expected = max(score(parts) for parts in partitions)
            result = run(
                native,
                "community-detection",
                graph,
                quality_function=objective,
                resolution=0.75,
                solution_quality="exact",
            )
            assert float(fraction(result["result"], "quality_score")) == pytest.approx(
                expected
            )
            parts = [set(row["vertices"]) for row in result["result"]["groups"]]
            assert score(parts) == pytest.approx(expected)
            assert result["quality"] == "exact"
            heuristic = run(
                native,
                "community-detection",
                graph,
                quality_function=objective,
                resolution=0.75,
                seed=19,
            )
            parts = [set(row["vertices"]) for row in heuristic["result"]["groups"]]
            assert float(
                fraction(heuristic["result"], "quality_score")
            ) == pytest.approx(score(parts))
            assert score(parts) <= expected + 1e-12


def test_balanced_partitions_exhaustive(native):
    partitions = [
        p for p in all_partitions(4) if len(p) == 2 and all(len(s) == 2 for s in p)
    ]
    for g, graph in graphs(4):

        def cut(parts):
            return sum((u in parts[0]) != (v in parts[0]) for u, v in g.edges())

        for objective in ("edge_cut", "normalized_cut"):
            expected = min(cut(p) for p in partitions)
            result = run(
                native,
                "balanced-partitioning",
                graph,
                num_parts=2,
                imbalance_tolerance=0,
                objective=objective,
            )["result"]
            assert result["feasible"] and result["balanced"]
            assert fraction(result, "objective_value") == expected
            parts = [set(row["vertices"]) for row in result["groups"]]
            assert all(len(p) == 2 for p in parts) and cut(parts) == expected
    result = run(
        native,
        "balanced-partitioning",
        canonical(5, []),
        num_parts=2,
        imbalance_tolerance=0,
    )
    assert result["result"]["infeasibility_certified"] and result["ports"] == {}


def test_signed_balance_exhaustive(native):
    edges = list(itertools.combinations(range(4), 2))
    for signs in itertools.product((None, "positive", "negative"), repeat=len(edges)):
        graph = canonical(
            4, [edge for edge, sign in zip(edges, signs, strict=True) if sign]
        )
        active = [sign for sign in signs if sign]
        for row, sign in zip(graph["edges"], active, strict=True):
            row["type"] = sign

        def violations(bits):
            return sum(
                (bits[row["source"]] != bits[row["target"]])
                != (row["type"] == "negative")
                for row in graph["edges"]
            )

        expected = min(map(violations, itertools.product((0, 1), repeat=4)))
        result = run(native, "signed-balance", graph, task="frustration_minimization")[
            "result"
        ]
        assert fraction(result, "frustrated_weight") == expected
        assert result["balanced"] == (expected == 0)
        assert (
            violations([row["faction"] for row in result["faction_assignment"]])
            == expected
        )


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("quasi-cliques", {"gamma": 0, "minimum_size": 2}),
        ("densest-k-subgraph", {"k": 6}),
        ("densest-subgraph", {"clique_order": 3, "weight_mode": "edge_weight"}),
        ("maximal-bicliques", {"left_partition": [0], "right_partition": [1]}),
        ("butterfly-counting", {"alpha": 2}),
        (
            "transitive-closure",
            {"query_mode": "single_pair", "query_pairs": [[0, 1], [1, 0]]},
        ),
        ("overlapping-communities", {"k": 1}),
        ("community-detection", {"resolution": 0}),
        ("balanced-partitioning", {"num_parts": 2, "vertex_weights": []}),
        ("signed-balance", {"task": "balance_check"}),
    ],
)
def test_extended_invalid_contracts(native, operation, parameters):
    with pytest.raises(BINDING.NativeError):
        run(native, operation, canonical(4, [(0, 1), (2, 3)]), **parameters)


def test_extended_truncation_and_budgets(native):
    graph = canonical(4, [(0, 2), (1, 3)])
    result = run(
        native,
        "maximal-bicliques",
        graph,
        left_partition=[0, 1],
        right_partition=[2, 3],
        result_limit=1,
    )
    assert not result["complete"] and not result["ports"]["bicliques"]["complete"]
    assert "total_count" not in result["result"]
    with pytest.raises(BINDING.NativeError, match="budget"):
        native.run(
            "quasi-cliques",
            canonical(25, []),
            parameters={"gamma": 0.5, "minimum_size": 2},
            device="cpu",
            budget={"max_candidates": 100},
        )
    with pytest.raises(BINDING.NativeError):
        native.run("densest-subgraph", graph, device="gpu")


def test_widest_paths_exhaustive(native):
    for g, graph in graphs(3, directed=True):
        for edge in graph["edges"]:
            edge["weight"] = (0, 0.5, 3)[edge["id"] % 3]
            g[edge["source"]][edge["target"]]["weight"] = edge["weight"]
        result = run(native, "widest-paths", graph, source_vertex=0)["result"]
        for row in result["vertices"]:
            vertex = row["vertex"]
            if vertex == 0:
                assert (
                    row["is_source"]
                    and row["reachable"]
                    and row["bottleneck_capacity"] is None
                )
                continue
            paths = list(nx.all_simple_paths(g, 0, vertex))
            assert row["reachable"] == bool(paths)
            if paths:
                expected = max(
                    min(g[u][v]["weight"] for u, v in itertools.pairwise(path))
                    for path in paths
                )
                assert fraction(row, "bottleneck_capacity") == expected
                witness = [vertex]
                while witness[-1] != 0:
                    witness.append(result["vertices"][witness[-1]]["predecessor"])
                    assert len(witness) <= len(g)
                assert (
                    min(
                        g[u][v]["weight"]
                        for u, v in itertools.pairwise(reversed(witness))
                    )
                    == expected
                )


def test_critical_dag_paths_exhaustive(native):
    for _, graph in graphs(4):
        graph["graph"]["directed"] = True
        for edge in graph["edges"]:
            edge["weight"] = (2, -3, 0, 0.5)[edge["id"] % 4]
        # Add one parallel edge with a different cost to test path identity.
        if graph["edges"]:
            graph["edges"].append(
                {**graph["edges"][0], "id": len(graph["edges"]), "weight": -1}
            )
        g = nx.MultiDiGraph()
        g.add_nodes_from(range(4))
        g.add_edges_from((e["source"], e["target"], e["id"]) for e in graph["edges"])
        for sources, sinks in ((None, None), ([0, 2], [2, 3])):
            starts = (
                sources if sources is not None else [v for v in g if not g.in_degree(v)]
            )
            ends = sinks if sinks is not None else [v for v in g if not g.out_degree(v)]
            expected = []
            for start, end in itertools.product(starts, ends):
                for path in nx.all_simple_edge_paths(g, start, end):
                    expected.append(
                        sum(
                            (
                                Fraction(graph["edges"][key]["weight"])
                                for _, _, key in path
                            ),
                            Fraction(),
                        )
                    )
            expected.sort(reverse=True)
            for k in (1, 3, 50):
                result = run(
                    native,
                    "top-k-critical-paths",
                    graph,
                    k=k,
                    sources=sources,
                    sinks=sinks,
                )
                actual = [
                    fraction(row, "total_weight") for row in result["result"]["paths"]
                ]
                assert actual == expected[:k]
                assert result["complete"]
                assert result["ports"]["paths"]["complete"] == (len(expected) <= k)
                for row in result["result"]["paths"]:
                    assert row["vertices"][0] in starts and row["vertices"][-1] in ends
                    for u, v, edge_id in zip(
                        row["vertices"], row["vertices"][1:], row["edges"]
                    ):
                        assert (u, v) == (
                            graph["edges"][edge_id]["source"],
                            graph["edges"][edge_id]["target"],
                        )
                    assert sum(
                        (
                            Fraction(graph["edges"][key]["weight"])
                            for key in row["edges"]
                        ),
                        Fraction(),
                    ) == fraction(row, "total_weight")


def test_bounded_paths_cycles_exhaustive(native):
    for g, graph in graphs(3, directed=True):
        lookup = {(e["source"], e["target"]): e["id"] for e in graph["edges"]}
        for task in ("s_t_path", "all_cycles", "cycle_through_vertex"):
            expected = set()
            if task == "s_t_path":
                candidates = nx.all_simple_paths(g, 0, 2)
                args = {"source": 0, "target": 2}
            else:
                candidates = (
                    c + [c[0]]
                    for c in nx.simple_cycles(g)
                    if task == "all_cycles" or 0 in c
                )
                args = {"source": 0} if task == "cycle_through_vertex" else {}
            for path in candidates:
                sequence = [lookup[u, v] for u, v in itertools.pairwise(path)]
                if task != "s_t_path":
                    first = (
                        path.index(0)
                        if task == "cycle_through_vertex"
                        else sequence.index(min(sequence))
                    )
                    sequence = sequence[first:] + sequence[:first]
                expected.add(tuple(sequence))
            ordered = sorted(expected, key=lambda p: (len(p), p))
            for cap in (None, 1):
                result = run(
                    native,
                    "bounded-paths-cycles",
                    graph,
                    task=task,
                    max_hops=3,
                    result_limit=cap,
                    **args,
                )
                assert result["result"]["paths_or_cycles"] == [
                    list(p) for p in ordered[:cap]
                ]
                assert result["result"]["total_count"] == len(expected)
                assert result["complete"] == (cap is None or len(expected) <= cap)


def test_temporal_paths_event_oracle(native):
    rng = random.Random(4219)
    for case in range(100):
        graph = canonical(
            4, [(rng.randrange(4), rng.randrange(4)) for _ in range(6)], directed=True
        )
        origin = 9007199254740993 if case % 5 == 0 else 0
        for edge in graph["edges"]:
            edge["timestamp"] = origin + rng.randrange(5)
            edge["attributes"] = {"duration": rng.choice([0, 0.25, 1, 2])}
        for objective in ("earliest_arrival", "fastest_duration"):
            ready, deadline = origin, origin + 5
            best = {
                0: (
                    Fraction(ready) if objective == "earliest_arrival" else Fraction(0),
                    Fraction(ready),
                )
            }

            def visit(vertex, arrival, departure, used):
                for edge in graph["edges"]:
                    if (
                        edge["id"] in used
                        or edge["source"] != vertex
                        or edge["timestamp"] < arrival
                    ):
                        continue
                    end = Fraction(edge["timestamp"]) + Fraction(
                        edge["attributes"]["duration"]
                    )
                    if end > deadline:
                        continue
                    start = edge["timestamp"] if departure is None else departure
                    value = end if objective == "earliest_arrival" else end - start
                    target = edge["target"]
                    candidate = (value, end)
                    if target not in best or candidate < best[target]:
                        best[target] = candidate
                    visit(target, end, start, used | {edge["id"]})

            visit(0, Fraction(ready), None, set())
            result = run(
                native,
                "temporal-paths",
                graph,
                source=0,
                ready_time=ready,
                deadline=deadline,
                objective=objective,
            )["result"]
            for row in result["values"]:
                vertex = row["vertex"]
                assert row["reachable"] == (vertex in best)
                if vertex not in best:
                    continue
                assert fraction(row, "value") == best[vertex][0]
                current, time = 0, Fraction(ready)
                for i in row["edges"]:
                    edge = graph["edges"][i]
                    assert edge["source"] == current and edge["timestamp"] >= time
                    current = edge["target"]
                    time = Fraction(edge["timestamp"]) + Fraction(
                        edge["attributes"]["duration"]
                    )
                assert current == vertex
                assert fraction(row, "arrival") == time


def test_laplacian_eigenpairs_independent(native):
    import numpy as np
    from scipy.linalg import eigh

    for g, graph in graphs(4):
        for edge in graph["edges"]:
            edge["weight"] = (0, 0.25, 2)[edge["id"] % 3]
            g[edge["source"]][edge["target"]]["weight"] = edge["weight"]
        for kind in ("combinatorial", "symmetric_normalized"):
            matrix = (
                (
                    nx.laplacian_matrix(g)
                    if kind == "combinatorial"
                    else nx.normalized_laplacian_matrix(g)
                )
                .toarray()
                .astype(float)
            )
            expected = eigh(matrix, eigvals_only=True)
            for selection in ("smallest", "largest"):
                result = run(
                    native,
                    "laplacian-eigenpairs",
                    graph,
                    num_eigenpairs=3,
                    laplacian=kind,
                    selection=selection,
                    tolerance=1e-10,
                )["result"]
                values, vectors = (
                    np.asarray(result["eigenvalues"]),
                    np.asarray(result["eigenvectors"]),
                )
                assert values == pytest.approx(
                    expected[:3] if selection == "smallest" else expected[-3:],
                    abs=1e-10,
                )
                assert (
                    np.max(np.linalg.norm(matrix @ vectors - vectors * values, axis=0))
                    <= 1e-10
                )
                assert (
                    np.linalg.norm(vectors.T @ vectors - np.eye(3), ord=np.inf) <= 1e-10
                )


def test_denoising_independent_convex_oracle(native):
    import cvxpy as cp
    import numpy as np

    rng = np.random.default_rng(117)
    for case in range(8):
        graph = canonical(
            4,
            [(0, 1, 0.5), (1, 2, 2), (2, 3, 1)] if case % 2 else [(0, 1, 1), (2, 3, 2)],
        )
        g = nx.Graph()
        g.add_nodes_from(range(4))
        g.add_weighted_edges_from(
            (e["source"], e["target"], e["weight"]) for e in graph["edges"]
        )
        matrix = nx.laplacian_matrix(g).toarray().astype(float)
        y = rng.normal(size=(4, 2))
        rows = [{"vertex": i, "value": row.tolist()} for i, row in enumerate(y)]
        for regularizer, order in (
            ("laplacian_quadratic", 0),
            ("total_variation", 0),
            ("trend_filtering", 0),
            ("trend_filtering", 1),
            ("trend_filtering", 2),
        ):
            variable = cp.Variable(y.shape)
            loss = 0.5 * cp.sum_squares(variable - y)
            if regularizer == "laplacian_quadratic":
                penalty = (
                    sum(
                        cp.quad_form(variable[:, j], cp.psd_wrap(matrix))
                        for j in range(2)
                    )
                    * 0.25
                )
            else:
                difference = np.zeros((len(graph["edges"]), 4))
                for i, edge in enumerate(graph["edges"]):
                    weight = (
                        edge["weight"]
                        if regularizer == "total_variation"
                        else np.sqrt(edge["weight"])
                    )
                    difference[i, edge["source"]], difference[i, edge["target"]] = (
                        weight,
                        -weight,
                    )
                if regularizer == "trend_filtering":
                    difference = (
                        np.linalg.matrix_power(matrix, (order + 1) // 2)
                        if order % 2
                        else difference @ np.linalg.matrix_power(matrix, order // 2)
                    )
                penalty = 0.5 * cp.norm1(difference @ variable)
            problem = cp.Problem(cp.Minimize(loss + penalty))
            problem.solve(solver="CLARABEL", tol_gap_abs=1e-10, tol_gap_rel=1e-10)
            result = run(
                native,
                "graph-signal-denoising",
                graph,
                observed_signal=rows,
                regularizer=regularizer,
                difference_order=order,
                regularization_strength=0.5,
                tolerance=1e-5,
                max_iterations=5000,
            )
            x = np.asarray(
                [row["value"] for row in result["result"]["estimated_signal"]]
            )
            assert result["result"]["objective_value"] == pytest.approx(
                problem.value, abs=1.1e-5
            )
            assert (
                np.linalg.norm(x - variable.value)
                <= result["diagnostics"]["solution_l2_error_bound"] + 2e-5
            )
            assert result["diagnostics"]["objective_gap_bound"] <= 1e-5


def test_simrank_linear_system_oracle(native):
    import numpy as np
    from scipy.linalg import solve

    for g, graph in graphs(3, directed=True):
        for direction in ("incoming", "undirected_projection"):
            network = g if direction == "incoming" else g.to_undirected()
            transition = np.zeros((3, 3))
            for v in network:
                neighbors = list(
                    network.predecessors(v)
                    if network.is_directed()
                    else network.neighbors(v)
                )
                if neighbors:
                    transition[v, neighbors] = 1 / len(neighbors)
            system = np.eye(9) - 0.8 * np.kron(transition, transition)
            rhs = np.zeros(9)
            for v in range(3):
                system[v * 3 + v, :] = 0
                system[v * 3 + v, v * 3 + v] = 1
                rhs[v * 3 + v] = 1
            expected = solve(system, rhs).reshape((3, 3))
            result = run(
                native,
                "simrank",
                graph,
                query_mode="top_k_pairs",
                direction_mode=direction,
                convergence_tolerance=1e-8,
            )
            for row in result["result"]["similarity_scores"]:
                assert (
                    abs(row["similarity"] - expected[row["source"], row["target"]])
                    <= 1.01e-8
                )
            assert result["result"]["error_bound"] <= 1e-8
            assert result["quality"] == "numerical"


def test_numerical_contract_failures(native):
    graph = canonical(2, [(0, 1, 1)])
    for operation, args in (
        ("laplacian-eigenpairs", {"num_eigenpairs": 3}),
        ("laplacian-eigenpairs", {"num_eigenpairs": 1, "tolerance": 0}),
        (
            "graph-signal-denoising",
            {
                "observed_signal": [{"vertex": 0, "value": 1}],
                "regularization_strength": 1,
            },
        ),
        (
            "graph-signal-denoising",
            {
                "observed_signal": [
                    {"vertex": 0, "value": 9007199254740993},
                    {"vertex": 1, "value": 0},
                ],
                "regularization_strength": 1,
            },
        ),
        (
            "simrank",
            {
                "query_mode": "single_pair",
                "source_vertex": 0,
                "target_vertex": 1,
                "decay_factor": 1,
            },
        ),
    ):
        with pytest.raises(BINDING.NativeError):
            run(native, operation, graph, **args)


def test_persistence_gudhi_oracle(native):
    import gudhi

    for _, graph in graphs(4):
        for edge in graph["edges"]:
            edge["weight"] = (0, 0.25, 1, 2)[edge["id"] % 4]
        for prime in (2, 3):
            for maximum, cutoff in ((0, None), (1, None), (2, 1)):
                tree = gudhi.SimplexTree()
                for v in range(4):
                    tree.insert([v], filtration=0)
                for edge in graph["edges"]:
                    if cutoff is None or edge["weight"] <= cutoff:
                        tree.insert(
                            [edge["source"], edge["target"]], filtration=edge["weight"]
                        )
                tree.expansion(maximum + 1)
                expected = sorted(
                    (d, birth, death)
                    for d, (birth, death) in tree.persistence(
                        homology_coeff_field=prime, persistence_dim_max=True
                    )
                    if d <= maximum
                )
                result = run(
                    native,
                    "persistent-homology",
                    graph,
                    field_prime=prime,
                    max_homology_dimension=maximum,
                    max_filtration=cutoff,
                )
                actual = [
                    (
                        r["dimension"],
                        r["birth"],
                        float("inf") if r["death"] is None else r["death"],
                    )
                    for r in result["result"]["intervals"]
                ]
                assert actual == expected
                assert result["quality"] == "exact"
    with pytest.raises(BINDING.NativeError, match="prime"):
        run(native, "persistent-homology", canonical(2, [(0, 1, 1)]), field_prime=9)


def test_seeded_local_community_objective(native):
    graph = canonical(5, [(0, 1, 1), (1, 2, 1), (2, 3, 1)])
    result = run(native, "seeded-local-community", graph, seeds=[0], maximum_volume=3)
    assert result["result"]["vertices"] == [0, 1]
    assert fraction(result["result"], "conductance") == Fraction(1, 3)
    assert fraction(result["result"], "volume") == 3
    assert not result["result"]["optimal"] and result["quality"] == "heuristic"
    isolated = run(native, "seeded-local-community", canonical(3, []), seeds=[1])
    assert isolated["result"]["vertices"] == [1]
    assert isolated["result"]["conductance"] is None
    with pytest.raises(BINDING.NativeError, match="volume"):
        run(native, "seeded-local-community", graph, seeds=[1], maximum_volume=1)


def test_layout_force_energy_and_iterations(native):
    import numpy as np

    graph = canonical(3, [(0, 1, 0.5), (1, 2, 2)])
    initial = np.array([[0, 0], [0.005, 0], [1, 1]])
    for iterations in (0, 1, 8):
        result = run(
            native,
            "force-directed-layout",
            graph,
            weight_mode="edge_weight",
            initial_positions=[
                {"vertex": v, "value": p.tolist()} for v, p in enumerate(initial)
            ],
            iterations=iterations,
            optimal_distance=0.7,
        )
        positions = np.array(
            [row["coordinates"] for row in result["result"]["vertex_positions"]]
        )
        if not iterations:
            assert np.array_equal(positions, initial)
        delta = positions[:, None, :] - positions[None, :, :]
        distances = np.linalg.norm(delta, axis=-1)
        clipped = np.maximum(distances, 0.01)
        weights = np.array([[0, 0.5, 0], [0.5, 0, 2], [0, 2, 0]])
        forces = np.einsum(
            "ijk,ij->ik", delta, 0.7**2 / clipped**2 - weights * clipped / 0.7
        )
        repulsion = np.where(
            distances >= 0.01,
            -(0.7**2) * np.log(clipped),
            -(0.7**2) * np.log(0.01) + 0.5 * 0.7**2 * (1 - (distances / 0.01) ** 2),
        )
        attraction = np.where(
            distances >= 0.01,
            distances**3 / (3 * 0.7),
            0.01 * distances**2 / (2 * 0.7) - 0.01**3 / (6 * 0.7),
        )
        assert result["result"]["max_force_norm"] == pytest.approx(
            max(np.linalg.norm(forces, axis=1))
        )
        assert result["result"]["final_energy"] == pytest.approx(
            np.triu(repulsion + weights * attraction, 1).sum()
        )
        assert result["result"]["iterations_run"] == iterations
    one = run(native, "force-directed-layout", graph, random_seed=27)
    two = run(native, "force-directed-layout", graph, random_seed=27)
    assert one["result"] == two["result"]


def test_influence_exact_live_state_oracle(native):
    for _, graph in graphs(3, directed=True):
        for edge in graph["edges"]:
            edge["weight"] = 0.5
        for model in ("independent_cascade", "linear_threshold"):
            if model == "independent_cascade":
                options = [
                    [
                        (None, Fraction(1, 2)),
                        ((e["source"], e["target"]), Fraction(1, 2)),
                    ]
                    for e in graph["edges"]
                ]
            else:
                options = []
                for v in range(3):
                    choices = [
                        ((e["source"], v), Fraction(1, 2))
                        for e in graph["edges"]
                        if e["target"] == v
                    ]
                    if len(choices) < 2:
                        choices.append((None, 1 - Fraction(len(choices), 2)))
                    options.append(choices)
            for k in (1, 2):
                spreads = dict.fromkeys(itertools.combinations(range(3), k), Fraction())
                for state in itertools.product(*options):
                    live = nx.DiGraph()
                    live.add_nodes_from(range(3))
                    probability = Fraction(1)
                    for edge, mass in state:
                        probability *= mass
                        if edge is not None:
                            live.add_edge(*edge)
                    for seeds in spreads:
                        activated = set(seeds)
                        for seed in seeds:
                            activated.update(nx.descendants(live, seed))
                        spreads[seeds] += probability * len(activated)
                result = run(
                    native,
                    "influence-maximization",
                    graph,
                    diffusion_model=model,
                    seed_set_size=k,
                )["result"]
                assert fraction(result, "expected_spread") == max(spreads.values())
                assert spreads[tuple(result["seed_set"])] == max(spreads.values())
    fixed = run(
        native,
        "influence-maximization",
        canonical(3, [], directed=True),
        diffusion_model="linear_threshold",
        seed_set_size=1,
        vertex_thresholds=[{"vertex": v, "value": 0} for v in range(3)],
    )
    assert fraction(fixed["result"], "expected_spread") == 3


def test_null_model_invariants_and_statistics(native):
    import statistics

    cases = [
        canonical(5, [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)]),
        canonical(5, [e for e in itertools.combinations(range(5), 2) if e != (0, 1)]),
        canonical(4, [(0, 1), (1, 2), (2, 3), (3, 0)], directed=True),
    ]
    for graph in cases:
        directed = graph["graph"]["directed"]
        base = nx.DiGraph() if directed else nx.Graph()
        base.add_nodes_from(range(len(graph["vertices"])))
        base.add_edges_from((e["source"], e["target"]) for e in graph["edges"])
        for model in ("erdos_renyi", "degree_preserving_configuration"):
            for tail in ("greater", "less", "two_sided_about_null_mean"):
                result = run(
                    native,
                    "null-model-significance",
                    graph,
                    null_model=model,
                    statistic_definition={
                        "name": "directed_triangles" if directed else "triangles"
                    },
                    sample_count=40,
                    random_seed=391,
                    tail=tail,
                    return_randomized_edges=True,
                )["result"]
                samples = []
                for edges in result["randomized_edges"]:
                    trial = nx.DiGraph() if directed else nx.Graph()
                    trial.add_nodes_from(base)
                    trial.add_edges_from(edges)
                    assert (
                        trial.number_of_edges() == base.number_of_edges() == len(edges)
                    )
                    assert nx.number_of_selfloops(trial) == 0
                    if model == "degree_preserving_configuration":
                        assert dict(trial.degree()) == dict(base.degree())
                        if directed:
                            assert dict(trial.in_degree()) == dict(base.in_degree())
                            assert dict(trial.out_degree()) == dict(base.out_degree())
                    value = (
                        sum(
                            len(c) == 3 for c in nx.simple_cycles(trial, length_bound=3)
                        )
                        if directed
                        else sum(nx.triangles(trial).values()) // 3
                    )
                    samples.append(value)
                assert samples == result["null_distribution_samples"]
                mean = statistics.mean(samples)
                assert result["null_distribution_summary"]["mean"] == mean
                assert result["null_distribution_summary"][
                    "standard_deviation"
                ] == pytest.approx(statistics.pstdev(samples))
                observed = result["observed_value"]
                extreme = (
                    sum(v >= observed for v in samples)
                    if tail == "greater"
                    else sum(v <= observed for v in samples)
                    if tail == "less"
                    else sum(
                        abs(Fraction(v) - Fraction(sum(samples), len(samples)))
                        >= abs(
                            Fraction(observed) - Fraction(sum(samples), len(samples))
                        )
                        for v in samples
                    )
                )
                assert result["empirical_p_value"] == extreme / len(samples)


def test_group_steiner_edge_subset_oracle(native):
    for g, graph in graphs(4):
        for edge in graph["edges"]:
            edge["weight"] = (0.25, 2, 0, 1)[edge["id"] % 4]
        groups = [{0, 1}, {2, 3}]
        candidates = []
        for mask in range(1 << len(graph["edges"])):
            chosen = [edge for edge in graph["edges"] if mask >> edge["id"] & 1]
            tree = nx.Graph()
            tree.add_edges_from((e["source"], e["target"]) for e in chosen)
            if tree and nx.is_tree(tree) and all(set(tree) & group for group in groups):
                candidates.append(
                    sum((Fraction(e["weight"]) for e in chosen), Fraction())
                )
        result = run(
            native, "group-steiner-tree", graph, groups=[sorted(s) for s in groups]
        )
        assert result["result"]["feasible"] == bool(candidates)
        if candidates:
            assert fraction(result["result"], "tree_weight") == min(candidates)
            witness = nx.Graph()
            witness.add_nodes_from(result["result"]["selected_vertices"])
            witness.add_edges_from(
                (graph["edges"][i]["source"], graph["edges"][i]["target"])
                for i in result["result"]["tree_edges"]
            )
            assert nx.is_tree(witness) and all(set(witness) & group for group in groups)
    overlap = run(
        native, "group-steiner-tree", canonical(3, []), groups=[[0, 1], [1, 2]]
    )
    assert overlap["result"]["selected_vertices"] == [1]
    assert fraction(overlap["result"], "tree_weight") == 0


def test_network_alignment_permutation_oracle(native):
    for directed in (False, True):
        for _, graph in graphs(3, directed=directed):
            other = canonical(
                4, [(0, 1, 2), (1, 2, 1), (2, 3, 0.25)], directed=directed
            )
            for edge in graph["edges"]:
                edge["weight"] = (0.25, 1, 2)[edge["id"] % 3]
            prior = [{"graph_a_vertex": 0, "graph_b_vertex": 2, "value": 0.5}]
            b = {
                (e["source"], e["target"]): Fraction(e["weight"])
                for e in other["edges"]
            }

            def score(mapping):
                value = Fraction(1, 2) if mapping[0] == 2 else Fraction()
                for edge in graph["edges"]:
                    pair = (mapping[edge["source"]], mapping[edge["target"]])
                    if not directed:
                        pair = tuple(sorted(pair))
                    if pair in b:
                        value += 2 * min(Fraction(edge["weight"]), b[pair])
                return value

            expected = max(
                score(mapping) for mapping in itertools.permutations(range(4), 3)
            )
            result = run(
                native,
                "network-alignment",
                graph,
                other_graph=other,
                node_similarity_prior=prior,
                topology_weight=2,
                weight_mode="edge_weight",
            )["result"]
            assert fraction(result, "objective_value") == expected
            mapping = {
                r["graph_a_vertex"]: r["graph_b_vertex"]
                for r in result["vertex_mapping"]
            }
            assert len(mapping) == len(set(mapping.values())) == 3
            assert score(mapping) == expected
            assert (
                sum(fraction(row, "score") for row in result["vertex_mapping"])
                == expected
            )


def test_pattern_matching_exhaustive(native):
    patterns = [
        canonical(2, [(0, 1)]),
        canonical(3, [(0, 1), (1, 2)]),
        canonical(2, []),
        canonical(0, []),
    ]
    for g, graph in graphs(4):
        for query in patterns:
            q = nx.Graph()
            q.add_nodes_from(range(len(query["vertices"])))
            q.add_edges_from((e["source"], e["target"]) for e in query["edges"])
            for induced in (False, True):
                matcher = nx.isomorphism.GraphMatcher(g, q)
                expected = {
                    tuple(
                        next(v for v, mapped in row.items() if mapped == i) for i in q
                    )
                    for row in (
                        matcher.subgraph_isomorphisms_iter()
                        if induced
                        else matcher.subgraph_monomorphisms_iter()
                    )
                }
                result = run(
                    native,
                    "subgraph-isomorphism",
                    graph,
                    query_graph=query,
                    induced=induced,
                )
                assert {
                    tuple(row["data_vertex"] for row in match)
                    for match in result["result"]["matches"]
                } == expected


def test_pattern_predicates_multiplicity_and_types(native):
    graph = canonical(2, [(0, 1, 1), (0, 1, 1.0)], directed=True)
    graph["vertices"][0]["attributes"] = {}
    graph["edges"][0]["type"], graph["edges"][1]["type"] = "a", "b"
    query = canonical(2, [(0, 1, 1), (0, 1, 1.0)], directed=True)
    predicates = [
        {"field": "type", "operator": "in", "value": ["a", "b"], "query_edge": 0},
        {"field": "type", "operator": "eq", "value": "a", "query_edge": 1},
    ]
    result = run(
        native,
        "subgraph-isomorphism",
        graph,
        query_graph=query,
        edge_predicates=predicates,
    )
    assert (
        result["result"]["returned_count"] == 1
    )  # Requires an augmenting reassignment.
    predicates = [{"field": "weight", "operator": "eq_query"}]
    assert (
        run(
            native,
            "subgraph-isomorphism",
            graph,
            query_graph=query,
            edge_predicates=predicates,
        )["result"]["returned_count"]
        == 1
    )
    query["edges"][0]["weight"] = 1.0
    assert (
        run(
            native,
            "subgraph-isomorphism",
            graph,
            query_graph=query,
            edge_predicates=predicates,
        )["result"]["returned_count"]
        == 0
    )
    singleton = canonical(1, [])
    for exists, expected in ((True, 0), (False, 1)):
        result = run(
            native,
            "subgraph-isomorphism",
            graph,
            query_graph={
                **singleton,
                "graph": {**singleton["graph"], "directed": True},
            },
            vertex_predicates=[
                {"field": "attributes", "operator": "exists", "value": exists}
            ],
        )
        assert [match[0]["data_vertex"] for match in result["result"]["matches"]] == [
            expected
        ]
    derived = run(
        native, "induced-subgraph", graph, mode="induced", vertices_or_seeds=[0, 1]
    )["result"]["graph"]
    assert (
        "attributes" in derived["vertices"][0]
        and "attributes" not in derived["vertices"][1]
    )
    assert type(derived["edges"][0]["weight"]) is int
    assert type(derived["edges"][1]["weight"]) is float


def test_motif_identity_and_count_completeness(native):
    graph = canonical(3, [(0, 1), (1, 2), (0, 2)])
    query = canonical(3, [(0, 1), (1, 2)])
    for identity, expected in (
        ("all_embeddings", 6),
        ("unique_vertex_set_and_mapping_class", 3),
    ):
        result = run(
            native,
            "motif-counting",
            graph,
            motifs=[query],
            occurrence_identity=identity,
            list_instances=True,
            result_limit_per_motif=1,
        )
        assert result["result"]["count_by_motif"][query["graph"]["id"]] == expected
        assert (
            result["ports"]["counts"]["complete"]
            and not result["ports"]["instances"]["complete"]
        )
    result = run(native, "motif-counting", graph, motifs=[query], induced=True)
    assert result["result"]["count_by_motif"][query["graph"]["id"]] == 0


def test_graphlet_classification_and_orbits(native):
    atlas = [
        (i, g)
        for i, g in enumerate(nx.graph_atlas_g())
        if 2 <= len(g) <= 5 and nx.is_connected(g)
    ]
    for index, g in atlas:
        ids = list(reversed(range(len(g))))
        graph = canonical(len(g), [(ids[u], ids[v]) for u, v in g.edges()])
        result = run(
            native,
            "graphlet-counting",
            graph,
            graphlet_sizes=[len(g)],
            include_orbit_counts=True,
            list_instances=True,
        )["result"]
        assert {
            key: count for key, count in result["count_by_graphlet"].items() if count
        } == {f"atlas-{index}": 1}
        union = nx.utils.UnionFind(g)
        for mapping in nx.isomorphism.GraphMatcher(g, g).isomorphisms_iter():
            for v, image in mapping.items():
                union.union(v, image)
        orbits = sorted(
            (sorted(group) for group in union.to_sets()), key=lambda group: group[0]
        )
        for orbit, vertices in enumerate(orbits):
            key = f"atlas-{index}:orbit-{orbit}"
            for v in vertices:
                assert result["orbit_counts_by_vertex"][ids[v]]["counts"] == {key: 1}
    for index in (208, 500, 1000, 1252):
        g = nx.graph_atlas(index)
        if nx.is_connected(g):
            result = run(
                native,
                "graphlet-counting",
                canonical(len(g), list(g.edges())),
                graphlet_sizes=[len(g)],
            )["result"]
            assert {
                key: count
                for key, count in result["count_by_graphlet"].items()
                if count
            } == {f"atlas-{index}": 1}
