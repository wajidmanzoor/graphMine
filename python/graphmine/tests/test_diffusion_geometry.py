"""Independent diffusion dynamics, force equations and quadratic-form oracles."""

from __future__ import annotations

import math
from fractions import Fraction
from itertools import combinations, pairwise, product

import networkx as nx
import numpy as np
import pytest
from graphmine import Budget, Graph, list_algorithms, run
from graphmine.exceptions import GraphMineError, ResourceLimit

ATLAS = [
    (i, len(g), tuple(g.edges)) for i, g in enumerate(nx.graph_atlas_g()) if len(g) <= 6
]
ARCS = tuple((u, v) for u in range(3) for v in range(3) if u != v)
DIRECTED = [
    tuple(edge for bit, edge in enumerate(ARCS) if mask & (1 << bit))
    for mask in range(64)
]


def call(operation, graph, **parameters):
    result = run(operation, graph, device="cpu", parameters=parameters)
    assert result["backend"]["device"] == "cpu"
    return result


def closure(n, edges, seeds):
    reachable = np.eye(n, dtype=bool)
    for u, v in edges:
        reachable[u, v] = True
    for pivot in range(n):
        reachable |= reachable[:, pivot, None] & reachable[None, pivot, :]
    return sum(any(reachable[u, v] for u in seeds) for v in range(n))


def threshold_spread(n, edges, thresholds, seeds):
    active = set(seeds)
    for _ in range(n + 1):
        total = [Fraction() for _ in range(n)]
        for u, v, w in edges:
            if u in active:
                total[v] += Fraction(w)
        next_active = active | {v for v in range(n) if total[v] >= thresholds[v]}
        if next_active == active:
            return len(active)
        active = next_active
    raise AssertionError("Progressive process failed to terminate")


def diffusion_oracle(n, edges, k, model):
    seeds = list(combinations(range(n), k))
    expectation = {s: Fraction() for s in seeds}
    if model == "independent_cascade":
        # Original edge trials and Floyd-Warshall closure, without NetworkX or
        # the production wrapper's parallel-edge normalization/reachability.
        for bits in product((0, 1), repeat=len(edges)):
            probability = math.prod(
                Fraction(w) if bit else 1 - Fraction(w)
                for (_, _, w), bit in zip(edges, bits, strict=True)
            )
            if not probability:
                continue
            active_edges = [
                (u, v) for (u, v, _), bit in zip(edges, bits, strict=True) if bit
            ]
            for s in seeds:
                expectation[s] += probability * closure(n, active_edges, s)
    else:
        # Integrate the independent uniform thresholds over all intervals
        # between subset-sum breakpoints. This is a different representation
        # from the implementation's one-live-incoming-edge distribution.
        partitions = []
        for v in range(n):
            incoming = [Fraction(w) for _, target, w in edges if target == v]
            cuts = {Fraction(), Fraction(1)}
            for bits in product((0, 1), repeat=len(incoming)):
                cuts.add(
                    sum(
                        (w for w, bit in zip(incoming, bits, strict=True) if bit),
                        Fraction(),
                    )
                )
            cuts = sorted(cuts)
            partitions.append([((a + b) / 2, b - a) for a, b in pairwise(cuts)])
        for intervals in product(*partitions):
            thresholds = [x for x, _ in intervals]
            probability = math.prod(w for _, w in intervals)
            for s in seeds:
                expectation[s] += probability * threshold_spread(
                    n, edges, thresholds, s
                )
    return expectation


@pytest.mark.parametrize("arcs", DIRECTED)
@pytest.mark.parametrize("model", ["independent_cascade", "linear_threshold"])
def test_all_three_vertex_digraphs_against_independent_diffusion_models(arcs, model):
    edges = [(u, v, Fraction(1, 4) if u % 2 else Fraction(1, 2)) for u, v in arcs]
    graph = Graph.from_edges(
        [(u, v, float(w)) for u, v, w in edges], vertices=range(3), directed=True
    )
    for k in (1, 2, 3):
        reference = diffusion_oracle(3, edges, k, model)
        actual = call(
            "influence-maximization", graph, diffusion_model=model, seed_set_size=k
        )
        result = actual["result"]
        rational = result["expected_spread_rational"]
        value = Fraction(rational["numerator"], rational["denominator"])
        assert value == max(reference.values())
        assert reference[tuple(result["seed_set"])] == value
        assert result["expected_spread"] == float(value)
        assert result["guarantee_met"] and result["optimal"]
        assert result["failure_probability"] == 0
        assert actual["quality"] == "exact"


@pytest.mark.parametrize("arcs", DIRECTED)
@pytest.mark.parametrize("thresholds", list(product((0, 0.5, 1), repeat=3)))
def test_all_small_fixed_threshold_dynamics(arcs, thresholds):
    edges = [(u, v, 0.5) for u, v in arcs]
    graph = Graph.from_edges(edges, vertices=range(3), directed=True)
    k = 1 if thresholds[0] == 0 else 2
    values = {
        s: threshold_spread(3, edges, thresholds, s) for s in combinations(range(3), k)
    }
    result = call(
        "influence-maximization",
        graph,
        diffusion_model="linear_threshold",
        seed_set_size=k,
        vertex_thresholds=[{"vertex": v, "value": t} for v, t in enumerate(thresholds)],
    )["result"]
    assert result["expected_spread"] == max(values.values())
    assert values[tuple(result["seed_set"])] == result["expected_spread"]


def test_parallel_diffusion_probabilities_typed_ids_and_small_probability_distinctions():
    graph = Graph(
        {
            "graph": {
                "id": "parallel",
                "directed": True,
                "allows_self_loops": True,
                "allows_parallel_edges": True,
            },
            "vertices": [{"id": v} for v in [0, "0", 9007199254740993]],
            "edges": [
                {"id": "a", "source": 0, "target": "0", "weight": 0.5},
                {"id": "b", "source": 0, "target": "0", "weight": 0.5},
                {"id": "c", "source": "0", "target": 9007199254740993, "weight": 0.5},
                {"id": "loop", "source": 0, "target": 0, "weight": 1},
            ],
        }
    )
    for model, expected in [
        ("independent_cascade", Fraction(17, 8)),
        ("linear_threshold", Fraction(5, 2)),
    ]:
        actual = call(
            "influence-maximization", graph, diffusion_model=model, seed_set_size=1
        )["result"]
        assert actual["seed_set"] == [0]
        assert actual["expected_spread"] == expected
    tiny = Graph.from_edges(
        [(0, 2, 1e-200), (1, 2, 2e-200)], vertices=range(3), directed=True
    )
    actual = call(
        "influence-maximization",
        tiny,
        diffusion_model="independent_cascade",
        seed_set_size=1,
    )["result"]
    assert actual["seed_set"] == [1]  # Both float expected spreads round to 1.
    rational = actual["expected_spread_rational"]
    assert Fraction(rational["numerator"], rational["denominator"]) == 1 + Fraction(
        2e-200
    )


def force_oracle(positions, edges, k):
    energy = 0.0
    force = np.zeros_like(positions)
    weights = {(min(u, v), max(u, v)): w for u, v, w in edges}
    for u, v in combinations(range(len(positions)), 2):
        difference = positions[u] - positions[v]
        r = math.sqrt(sum(float(x) ** 2 for x in difference))
        w = weights.get((u, v), 0)
        # Antiderivatives of the piecewise clipped force, with continuity.
        if r >= 0.01:
            energy += w * r**3 / (3 * k) - k**2 * math.log(r)
        else:
            energy += (
                w * (0.01 * r * r / 2 - 0.01**3 / 6) / k
                - k * k * math.log(0.01)
                + k * k / 2 * (1 - r * r / 0.01**2)
            )
        for axis in range(positions.shape[1]):
            contribution = difference[axis] * (
                k * k / max(r, 0.01) ** 2 - w * max(r, 0.01) / k
            )
            force[u, axis] += contribution
            force[v, axis] -= contribution
    return energy, force


@pytest.mark.parametrize("record", [row for row in ATLAS if row[1] <= 5])
@pytest.mark.parametrize("dimensions", [2, 3])
@pytest.mark.parametrize("weighted", [False, True])
def test_layout_energy_force_and_seed_reproducibility(record, dimensions, weighted):
    _, n, edges = record
    weights = [(u, v, 0.25 + (u + v) / 2 if weighted else 1) for u, v in edges]
    graph = Graph.from_edges(weights, vertices=range(n))
    args = {
        "dimensions": dimensions,
        "iterations": 7,
        "weight_mode": "edge_weight" if weighted else "unweighted",
        "random_seed": 23,
    }
    result = call("force-directed-layout", graph, **args)["result"]
    pos = np.array([r["coordinates"] for r in result["vertex_positions"]]).reshape(
        n, dimensions
    )
    expected_energy, expected_force = force_oracle(
        pos, weights, 1 / math.sqrt(max(1, n))
    )
    assert result["final_energy"] == pytest.approx(
        expected_energy, rel=1e-11, abs=1e-11
    )
    norm = max(
        (math.sqrt(sum(float(x) ** 2 for x in row)) for row in expected_force),
        default=0,
    )
    assert result["max_force_norm"] == pytest.approx(norm, rel=1e-10, abs=1e-10)
    assert result["converged"] == (norm <= 1e-6)
    assert result["iterations_run"] == (7 if n > 1 else 0)
    again = call("force-directed-layout", graph, **args)["result"]
    assert again == result


@pytest.mark.parametrize("n", [2, 5, 500])
def test_force_iteration_is_the_declared_model_including_networkx_size_boundary(n):
    initial = np.array([[math.cos(i + 0.2), math.sin(i + 0.2)] for i in range(n)])
    edges = [(i, i + 1, 1) for i in range(n - 1)]
    k = 0.7
    _, force = force_oracle(initial, edges, k)
    temperature = 0.1 * max(np.ptp(initial[:, 0]), np.ptp(initial[:, 1]))
    expected = initial.copy()
    for i in range(n):
        expected[i] += temperature * force[i] / max(0.01, np.linalg.norm(force[i]))
    result = call(
        "force-directed-layout",
        Graph.from_edges(edges, vertices=range(n)),
        initial_positions=[
            {"vertex": i, "value": p.tolist()} for i, p in enumerate(initial)
        ],
        optimal_distance=k,
        iterations=1,
    )["result"]
    actual = np.array([r["coordinates"] for r in result["vertex_positions"]])
    assert np.allclose(actual, expected, rtol=1e-5, atol=1e-6)


def test_layout_zero_iterations_coincidences_projection_and_matching_potential():
    vertices = [0, "0", 9007199254740993]
    graph = Graph(
        {
            "graph": {
                "id": "layout",
                "directed": True,
                "allows_self_loops": True,
                "allows_parallel_edges": True,
            },
            "vertices": [{"id": v} for v in vertices],
            "edges": [
                {"id": "a", "source": 0, "target": "0", "weight": 2},
                {"id": "b", "source": "0", "target": 0, "weight": 3},
                {"id": "loop", "source": 0, "target": 0, "weight": 99},
            ],
        }
    )
    for small in (0, 0.005, 0.01, 0.02):
        positions = np.array([[0, 0, 0], [small, 0, 0], [0, 1, 2]], dtype=float)
        result = call(
            "force-directed-layout",
            graph,
            dimensions=3,
            weight_mode="edge_weight",
            iterations=0,
            initial_positions=[
                {"vertex": v, "value": p.tolist()}
                for v, p in zip(vertices, positions, strict=True)
            ],
        )["result"]
        assert [r["vertex"] for r in result["vertex_positions"]] == vertices
        assert [
            r["coordinates"] for r in result["vertex_positions"]
        ] == positions.tolist()
        expected, _ = force_oracle(positions, [(0, 1, 5)], 1 / math.sqrt(3))
        assert result["final_energy"] == pytest.approx(expected, rel=1e-12, abs=1e-12)


def matrix(n, edges):
    result = np.zeros((n, n))
    for u, v, w in edges:
        result[u, u] += w
        result[v, v] += w
        result[u, v] -= w
        result[v, u] -= w
    return result


@pytest.mark.parametrize("record", ATLAS)
@pytest.mark.parametrize("weighted", [False, True])
def test_sparsifier_all_vector_bounds_against_independent_orthogonal_basis(
    record, weighted
):
    _, n, pairs = record
    edges = [(u, v, (u + v + 1) / 4 if weighted else 1) for u, v in pairs]
    graph = Graph.from_edges(edges, vertices=range(n))
    original = matrix(n, edges)
    eigenvalues, eigenvectors = np.linalg.eigh(original)
    positive = eigenvalues > 1e-10
    whitening = eigenvectors[:, positive] / np.sqrt(eigenvalues[positive])
    for budget in sorted({0, len(edges) // 2, max(0, len(edges) - 1), len(edges)}):
        actual = call(
            "spectral-sparsification", graph, edge_budget=budget, random_seed=record[0]
        )
        result = actual["result"]
        output = result["sparsifier"]
        assert output["vertices"] == graph.to_canonical()["vertices"]
        assert len(output["edges"]) <= budget
        by_id = {e["id"]: e for e in graph.to_canonical()["edges"]}
        for edge in output["edges"]:
            assert edge["source"] == by_id[edge["id"]]["source"]
            assert edge["target"] == by_id[edge["id"]]["target"]
            assert edge["weight"] > 0
        candidate = matrix(
            n, [(e["source"], e["target"], e["weight"]) for e in output["edges"]]
        )
        ratios = np.linalg.eigvalsh(whitening.T @ candidate @ whitening)
        summary = result["quality_summary"]
        error = float(np.max(np.abs(ratios - 1), initial=0))
        assert summary["maximum_relative_spectral_error"] == pytest.approx(
            error, abs=1e-8
        )
        if len(ratios):
            assert summary["lower_quadratic_form_ratio"] == pytest.approx(
                min(ratios), abs=1e-8
            )
            assert summary["upper_quadratic_form_ratio"] == pytest.approx(
                max(ratios), abs=1e-8
            )
        assert summary["probabilistic_guarantee_claimed"] is False
        if error < 1 - 1e-8:
            assert summary["positive_weight_components_preserved"]
        assert (
            actual["ports"]["graph"]["graph_fingerprint"] == Graph(output).fingerprint
        )


@pytest.mark.parametrize("scale", [1e-200, 1, 1e200])
def test_spectral_reweighting_triangle_zero_edges_and_target_enforcement(scale):
    graph = Graph.from_edges(
        [
            (0, "0", scale),
            ("0", 9007199254740993, scale),
            (0, 9007199254740993, scale),
            (0, "isolated", 0),
        ],
        vertices=[0, "0", 9007199254740993, "isolated"],
    )
    for seed in range(12):
        result = call(
            "spectral-sparsification", graph, edge_budget=2, random_seed=seed
        )["result"]
        for edge in result["sparsifier"]["edges"]:
            assert edge["weight"] / scale == pytest.approx(
                1.5 if len(result["sparsifier"]["edges"]) == 2 else 3, rel=1e-12
            )
        assert result["quality_summary"][
            "maximum_relative_spectral_error"
        ] == pytest.approx(
            0.5 if len(result["sparsifier"]["edges"]) == 2 else 1, abs=1e-10
        )
    with pytest.raises(GraphMineError, match="not met"):
        call("spectral-sparsification", graph, edge_budget=1, epsilon=0.1)
    exact = call("spectral-sparsification", graph, edge_budget=3, epsilon=1e-15)[
        "result"
    ]
    assert exact["quality_summary"]["maximum_relative_spectral_error"] == 0
    assert exact["quality_summary"]["exact_bound"]
    assert len(exact["sparsifier"]["vertices"]) == 4


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("force-directed-layout", {"force_model": "force_atlas2"}),
        ("force-directed-layout", {"iterations": None}),
        ("force-directed-layout", {"dimensions": 4}),
        ("force-directed-layout", {"force_tolerance": 0}),
        (
            "force-directed-layout",
            {"initial_positions": [{"vertex": 0, "value": [0, 0]}]},
        ),
        ("force-directed-layout", {"optimal_distance": 0}),
        ("spectral-sparsification", {"edge_budget": 1, "mode": "dynamic_updates"}),
        ("spectral-sparsification", {"edge_budget": 1, "update_stream": []}),
        ("spectral-sparsification", {"edge_budget": 1, "epsilon": 0}),
        ("spectral-sparsification", {"edge_budget": 1, "epsilon": 1}),
        (
            "influence-maximization",
            {"seed_set_size": 3, "diffusion_model": "independent_cascade"},
        ),
        (
            "influence-maximization",
            {
                "seed_set_size": 1,
                "diffusion_model": "independent_cascade",
                "vertex_thresholds": [],
            },
        ),
        (
            "influence-maximization",
            {
                "seed_set_size": 1,
                "diffusion_model": "independent_cascade",
                "estimation_method": "reverse_influence_sampling",
            },
        ),
    ],
)
def test_unsupported_parameters_are_rejected(operation, arguments):
    graph = Graph.from_edges(
        [(0, 1, 0.5)], directed=operation == "influence-maximization"
    )
    with pytest.raises(GraphMineError):
        call(operation, graph, **arguments)


def test_invalid_models_weights_and_budgets_have_no_plausible_success():
    for weight in (-0.1, 1.1):
        with pytest.raises(GraphMineError, match="within"):
            call(
                "influence-maximization",
                Graph.from_edges([(0, 1, weight)], directed=True),
                diffusion_model="independent_cascade",
                seed_set_size=1,
            )
    with pytest.raises(GraphMineError, match="sum"):
        call(
            "influence-maximization",
            Graph.from_edges([(0, 2, 0.6), (1, 2, 0.6)], directed=True),
            diffusion_model="linear_threshold",
            seed_set_size=1,
        )
    with pytest.raises(GraphMineError, match="requires a directed"):
        call(
            "influence-maximization",
            Graph.from_edges([(0, 1, 0.5)]),
            diffusion_model="independent_cascade",
            seed_set_size=1,
        )
    with pytest.raises(GraphMineError, match="force_tolerance"):
        call(
            "force-directed-layout",
            Graph.from_edges([(0, 1)]),
            solution_quality="converged",
            iterations=0,
        )
    with pytest.raises(GraphMineError, match="undirected"):
        call(
            "spectral-sparsification",
            Graph.from_edges([(0, 1, 1)], directed=True),
            edge_budget=1,
        )
    for operation, arguments in [
        ("force-directed-layout", {"iterations": 10}),
        ("spectral-sparsification", {"edge_budget": 3}),
        (
            "influence-maximization",
            {"diffusion_model": "independent_cascade", "seed_set_size": 2},
        ),
    ]:
        graph = Graph.from_edges(
            [(u, v, 0.5) for u, v in combinations(range(5), 2)],
            directed=operation == "influence-maximization",
        )
        with pytest.raises(ResourceLimit):
            run(
                operation,
                graph,
                parameters=arguments,
                device="cpu",
                budget=Budget(max_candidates=1),
            )
    cards = {c["id"]: c for c in list_algorithms()}
    assert "update_stream" not in cards["spectral-sparsification"]["parameters"]
    assert "estimation_method" not in cards["influence-maximization"]["parameters"]


@pytest.mark.parametrize("seed", range(16))
def test_missing_bridges_cannot_pass_a_near_one_spectral_target(seed):
    graph = Graph.from_edges([(i, i + 1, 1) for i in range(4)])
    with pytest.raises(GraphMineError, match="not met"):
        call(
            "spectral-sparsification",
            graph,
            edge_budget=3,
            epsilon=float(np.nextafter(1.0, 0.0)),
            random_seed=seed,
        )


def test_nonidentity_spectral_target_and_ill_conditioned_weight_rejection():
    graph = Graph.from_edges([(0, 1, 1), (1, 2, 1), (0, 2, 1)])
    result = call(
        "spectral-sparsification", graph, edge_budget=2, epsilon=0.51, random_seed=0
    )["result"]
    assert result["quality_summary"]["epsilon_met_numerically"]
    assert not result["quality_summary"]["exact_bound"]
    extreme = Graph.from_edges([(0, 1, 1e-300), (1, 2, 1e300), (0, 2, 1e300)])
    with pytest.raises(GraphMineError, match="dynamic range"):
        call("spectral-sparsification", extreme, edge_budget=2)
    identity = call("spectral-sparsification", extreme, edge_budget=3)["result"]
    assert identity["quality_summary"]["exact_bound"]
