"""Independent event/permutation oracles and sampling distribution checks."""

import math
import random
import statistics
from collections import Counter
from fractions import Fraction
from itertools import combinations, pairwise, permutations, product

import networkx as nx
import numpy as np
import pytest
from graphmine.reference import Budget, Graph, run
from graphmine.exceptions import GraphMineError, ResourceLimit

ATLAS = [
    (i, len(g), tuple(g.edges))
    for i, g in enumerate(nx.graph_atlas_g())
    if 1 <= len(g) <= 6
]
DIRECTED = list(permutations(range(3), 2))


def execute(operation, graph, **parameters):
    result = run(operation, graph, device="cpu", parameters=parameters)
    assert result["backend"]["device"] == "cpu"
    return result


def event_graph(n, edges, directed=True):
    data = Graph.from_edges([], vertices=range(n), directed=directed).to_canonical()
    data["graph"].update(allows_parallel_edges=True, allows_self_loops=True)
    data["edges"] = [
        {
            "id": i,
            "source": u,
            "target": v,
            "timestamp": when,
            "attributes": {"duration": duration},
        }
        for i, (u, v, when, duration) in enumerate(edges)
    ]
    return Graph(data)


def journeys(n, edges, source, ready, deadline, objective):
    best = [None] * n
    best[source] = ready if objective == "earliest_arrival" else 0

    def visit(vertex, now, first, used):
        for i, (u, v, departure, duration) in enumerate(edges):
            arrival = departure + duration
            if (
                u != vertex
                or i in used
                or departure < now
                or (deadline is not None and arrival > deadline)
            ):
                continue
            initial = departure if first is None else first
            value = arrival if objective == "earliest_arrival" else arrival - initial
            if best[v] is None or value < best[v]:
                best[v] = value
            visit(v, arrival, initial, used | {i})

    visit(source, ready, None, set())
    return best


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("objective", ["earliest_arrival", "fastest_duration"])
@pytest.mark.parametrize("ready,deadline", [(0, None), (2, 5)])
def test_temporal_paths_against_all_event_journeys(mask, objective, ready, deadline):
    edges = [
        (u, v, (i * 3 + mask) % 6, (i + mask) % 3)
        for i, (u, v) in enumerate(DIRECTED)
        if mask >> i & 1
    ]
    g = event_graph(3, edges)
    for source in range(3):
        result = execute(
            "temporal-paths",
            g,
            source=source,
            ready_time=ready,
            deadline=deadline,
            objective=objective,
        )["result"]
        assert [r["value"] for r in result["values"]] == journeys(
            3, edges, source, ready, deadline, objective
        )
        for row in result["values"]:
            current, now = source, ready
            for edge_id in row["edges"]:
                u, v, when, duration = edges[edge_id]
                assert current == u and when >= now
                current, now = v, when + duration
            if row["reachable"]:
                assert current == row["vertex"]
                assert row["arrival"] == now
                assert row["value"] == (
                    now if objective == "earliest_arrival" else now - row["departure"]
                )
                assert deadline is None or now <= deadline
            else:
                assert row["edges"] == [] and row["arrival"] is None


def test_temporal_parallel_fractional_time_and_ready_waiting():
    g = event_graph(
        4, [(0, 1, 1, 1), (0, 1, 6, 0), (1, 2, 6, 0), (2, 1, 6, 0), (0, 2, 4, 4)]
    )
    fast = execute("temporal-paths", g, source=0, ready_time=0)["result"]["values"]
    early = execute(
        "temporal-paths", g, source=0, ready_time=0, objective="earliest_arrival"
    )["result"]["values"]
    assert fast[2]["value"] == 0 and fast[2]["departure"] == 6
    assert early[1]["value"] == 2 and early[2]["value"] == 6
    raw = event_graph(3, [(0, 1, 0, 0.125), (1, 2, 1, 0.25)]).to_canonical()
    raw["edges"][0]["timestamp"] = "1970-01-01T01:00:00.125000+01:00"
    raw["edges"][1]["timestamp"] = "1970-01-01T00:00:00.375000Z"
    row = execute("temporal-paths", raw, source=0, ready_time=0)["result"]["values"][2]
    assert row["value"] == 0.5 and row["arrival"] == 0.625
    assert row["value_fraction"] == "1/2"


def bounded_oracle(n, edges, task, bound, chronological, source=0, target=2, anchor=0):
    by_pair = {}
    for i, (u, v, _) in enumerate(edges):
        if u != v:
            by_pair.setdefault((u, v), []).append(i)
    results = set()
    for length in range(
        1 if task == "s_t_path" else 2, min(n, bound + (task == "s_t_path")) + 1
    ):
        # Path length here is number of vertices; cycles use number of edges.
        for vertices in permutations(range(n), length):
            if task == "s_t_path":
                if (
                    vertices[0] != source
                    or vertices[-1] != target
                    or len(vertices) - 1 > bound
                ):
                    continue
                pairs = list(pairwise(vertices))
            else:
                if task == "cycle_through_vertex" and vertices[0] != source:
                    continue
                pairs = list(pairwise((*vertices, vertices[0])))
            for indices in product(*(by_pair.get(pair, []) for pair in pairs)):
                if not indices:
                    continue
                if task == "cycle_through_edge" and anchor not in indices:
                    continue
                if task != "s_t_path" and task != "cycle_through_vertex":
                    rotations = [indices[i:] + indices[:i] for i in range(len(indices))]
                    indices = min(
                        rotations,
                        key=lambda r: (edges[r[0]][2], r) if chronological else r,
                    )
                if chronological and any(
                    edges[a][2] >= edges[b][2] for a, b in pairwise(indices)
                ):
                    continue
                results.add(indices)
    return results


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("chronological", [False, True])
def test_bounded_paths_cycles_against_vertex_permutations(mask, chronological):
    edges = [
        (u, v, (i * 3 + mask) % 7) for i, (u, v) in enumerate(DIRECTED) if mask >> i & 1
    ]
    g = event_graph(3, [(u, v, t, 0) for u, v, t in edges])
    for task in (
        "s_t_path",
        "all_cycles",
        "cycle_through_vertex",
        "cycle_through_edge",
    ):
        if task == "cycle_through_edge" and not edges:
            continue
        params = (
            {"source": 0, "target": 2}
            if task == "s_t_path"
            else {"source": 0}
            if task == "cycle_through_vertex"
            else {"anchor_edge": 0}
            if task == "cycle_through_edge"
            else {}
        )
        for bound in (1, 2, 3, 8):
            result = execute(
                "bounded-paths-cycles",
                g,
                task=task,
                max_hops=bound,
                chronological_order_required=chronological,
                **params,
            )["result"]
            expected = bounded_oracle(3, edges, task, bound, chronological)
            assert {tuple(row) for row in result["paths_or_cycles"]} == expected
            assert result["total_count"] == len(expected) and result["complete"]


def test_bounded_parallel_edges_shortest_limit_and_canonical_rotations():
    edges = [
        (0, 1, 4),
        (0, 1, 1),
        (1, 2, 2),
        (2, 0, 3),
        (0, 2, 5),
        (2, 1, 6),
        (1, 0, 7),
        (0, 0, 0),
    ]
    g = event_graph(3, [(u, v, t, 0) for u, v, t in edges])
    for chronological in (False, True):
        expected = bounded_oracle(3, edges, "all_cycles", 3, chronological)
        result = execute(
            "bounded-paths-cycles",
            g,
            task="all_cycles",
            max_hops=3,
            chronological_order_required=chronological,
            parallel_edge_policy="preserve",
            result_limit=2,
        )
        actual = result["result"]
        assert [tuple(row) for row in actual["paths_or_cycles"]] == sorted(
            expected, key=lambda p: (len(p), p)
        )[:2]
        assert actual["total_count"] == len(expected)
        assert result["complete"] == (len(expected) <= 2)
    with pytest.raises(GraphMineError, match="collapsed"):
        execute(
            "bounded-paths-cycles",
            g,
            task="cycle_through_edge",
            anchor_edge=1,
            max_hops=3,
        )


def temporal_motif_oracle(n, edges, query_n, pattern, order, duration, equal, induced):
    results = set()
    for vertices in permutations(range(n), query_n):
        for indices in permutations(range(len(edges)), len(pattern)):
            if not all(
                edges[i][:2] == (vertices[u], vertices[v])
                for (u, v), i in zip(pattern, indices, strict=True)
            ):
                continue
            when = [edges[i][2] for i in indices]
            if max(when) - min(when) > duration or any(
                when[a] > when[b] if equal else when[a] >= when[b] for a, b in order
            ):
                continue
            if induced and any(
                i not in indices
                and u in vertices
                and v in vertices
                and min(when) <= t <= max(when)
                for i, (u, v, t) in enumerate(edges)
            ):
                continue
            results.add(indices)
    return results


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("equal,induced", list(product((False, True), repeat=2)))
def test_temporal_motifs_against_all_vertex_and_event_injections(mask, equal, induced):
    edges = [
        (u, v, (mask + i) % 3) for i, (u, v) in enumerate(DIRECTED) if mask >> i & 1
    ]
    g = event_graph(3, [(u, v, t, 0) for u, v, t in edges])
    for pattern, order in [
        ([(0, 1), (1, 2)], [(0, 1)]),
        ([(0, 1), (1, 2), (2, 0)], [(0, 2), (1, 2)]),
        ([(0, 1), (0, 2)], []),
    ]:
        q = Graph.from_edges(pattern, vertices=range(3), directed=True).to_canonical()
        expected = temporal_motif_oracle(3, edges, 3, pattern, order, 1, equal, induced)
        result = execute(
            "temporal-motifs",
            g,
            temporal_motif={"graph": q, "order": [list(p) for p in order]},
            maximum_duration_seconds=1,
            allow_equal_timestamps=equal,
            temporal_induced=induced,
            list_instances=True,
        )["result"]
        assert {tuple(row["edge_ids"]) for row in result["instances"]} == expected
        assert (
            result["occurrence_count"] == len(expected) and result["instances_complete"]
        )
        for row in result["per_vertex_participation"]:
            assert row["value"] == sum(
                any(row["vertex"] in edges[i][:2] for i in occurrence)
                for occurrence in expected
            )


def test_temporal_motif_parallel_events_predicates_and_listing_limit():
    g = event_graph(
        2, [(0, 1, 1, 0), (0, 1, 1, 0), (0, 1, 2, 0), (0, 0, 1, 0)], directed=False
    )
    q = event_graph(2, [(0, 1, 0, 0), (0, 1, 0, 0)], directed=False).to_canonical()
    result = execute(
        "temporal-motifs",
        g,
        temporal_motif={"graph": q},
        maximum_duration_seconds=1,
        allow_equal_timestamps=True,
        list_instances=True,
        result_limit=1,
    )
    assert result["result"]["occurrence_count"] == 4
    assert (
        len(result["result"]["instances"]) == 1
        and not result["result"]["instances_complete"]
    )
    assert result["complete"] and not result["ports"]["instances"]["complete"]
    pred = {"field": "timestamp", "operator": "eq", "value": 2, "query_edge": 1}
    result = execute(
        "temporal-motifs",
        g,
        temporal_motif={"graph": q, "edge_predicates": [pred]},
        maximum_duration_seconds=1,
    )["result"]
    assert result["occurrence_count"] == 2
    with pytest.raises(GraphMineError, match="acyclic"):
        execute(
            "temporal-motifs",
            g,
            temporal_motif={"graph": q, "order": [[0, 1], [1, 0]]},
            maximum_duration_seconds=1,
        )


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
@pytest.mark.parametrize("model", ["uniform", "weighted", "node2vec"])
def test_random_walks_and_neighborhoods_on_graph_atlas(case, model):
    _, n, edges = case
    g = Graph.from_edges([(u, v, (u + v) % 3) for u, v in edges], vertices=range(n))
    result = execute(
        "random-walks",
        g,
        start_vertices=list(range(n)),
        length=12,
        walk_model=model,
        random_seed=37,
    )
    assert result["backend"]["library"] == "numpy"
    for source, path, length in zip(
        range(n), result["result"]["walks"], result["result"]["lengths"], strict=True
    ):
        assert path[0] == source and length == len(path) - 1
        for u, v in pairwise(path):
            assert (min(u, v), max(u, v)) in edges
            assert model == "uniform" or (u + v) % 3 > 0
        if length < 12:
            assert not any(
                path[-1] in pair and (model == "uniform" or sum(pair) % 3 > 0)
                for pair in edges
            )
    params = {
        "seeds": list(range(n)),
        "fanouts": [2, -1],
        "sampling_model": "weighted" if model == "weighted" else "uniform",
        "random_seed": 71,
    }
    result = execute("neighborhood-sampling", g, **params)["result"]
    assert execute("neighborhood-sampling", g, **params)["result"] == result
    raw = g.to_canonical()["edges"]
    by_source = Counter()
    for row in result["sampled_edges"]:
        edge = raw[row["edge_id"]]
        assert {row["source"], row["target"]} == {edge["source"], edge["target"]}
        assert row["seed"] == row["batch"]
        if row["hop"] == 1:
            assert row["source"] == row["seed"]
            by_source[row["source"]] += 1
            assert model != "weighted" or edge["weight"] > 0
    assert all(v <= 2 for v in by_source.values())
    assert set(result["sampled_vertices"]) == set(range(n))


def test_walk_transition_probabilities_with_independent_rng_spy(monkeypatch):
    from graphmine.algorithms import sampling

    class Spy:
        def __init__(self):
            self.calls = []

        def choice(self, n, *, p):
            self.calls.append(p.tolist())
            return 0 if len(self.calls) == 1 else n - 1

    spy = Spy()
    monkeypatch.setattr(sampling, "random_generator", lambda seed: (spy, seed))
    g = Graph.from_edges(
        [(0, 1, 1), (1, 0, 4), (1, 2, 2), (1, 3, 8), (0, 2, 1)], directed=True
    )
    result = execute(
        "random-walks",
        g,
        start_vertices=[0],
        length=2,
        walk_model="node2vec",
        p=2,
        q=4,
        random_seed=0,
    )
    assert result["result"]["walks"] == [[0, 1, 3]]
    assert spy.calls[0] == pytest.approx([0.5, 0.5])
    assert spy.calls[1] == pytest.approx([1 / 3] * 3)


def test_sampling_empirical_frequencies_parallel_edges_and_zero_weights():
    raw = event_graph(
        4, [(0, 1, 0, 0), (0, 1, 0, 0), (0, 2, 0, 0), (0, 3, 0, 0)]
    ).to_canonical()
    for edge, weight in zip(raw["edges"], [1, 2, 1, 0], strict=True):
        edge["weight"] = weight
    g = Graph(raw)
    for operation, params in [
        (
            "random-walks",
            {"start_vertices": [0] * 6000, "length": 1, "walk_model": "weighted"},
        ),
        (
            "neighborhood-sampling",
            {
                "seeds": [0],
                "fanouts": [6000],
                "replacement": True,
                "sampling_model": "weighted",
            },
        ),
    ]:
        result = execute(operation, g, random_seed=18, **params)["result"]
        samples = (
            [path[-1] for path in result["walks"]]
            if operation == "random-walks"
            else [row["target"] for row in result["sampled_edges"]]
        )
        counts = Counter(samples)
        assert set(counts) == {1, 2}
        assert counts[1] / len(samples) == pytest.approx(0.75, abs=0.025)
    result = execute(
        "neighborhood-sampling",
        g,
        seeds=[0],
        fanouts=[-1],
        sampling_model="weighted",
        random_seed=18,
    )["result"]
    assert {r["edge_id"] for r in result["sampled_edges"]} == {0, 1, 2, 3}
    raw = g.to_canonical()
    for i, edge in enumerate(raw["edges"]):
        edge.update(type="a" if i < 2 else "b", timestamp=i)
    result = execute(
        "neighborhood-sampling",
        raw,
        seeds=[0],
        fanouts=[-1],
        edge_type_fanouts={"a": [1]},
        time_cutoff=2,
        random_seed=7,
    )["result"]
    assert len(result["sampled_edges"]) == 2
    assert {r["edge_id"] for r in result["sampled_edges"]} <= {0, 1, 2}


def degrees(n, edges, directed):
    out, incoming = [0] * n, [0] * n
    for u, v in edges:
        out[u] += 1
        incoming[v] += 1
        if not directed:
            out[v] += 1
            incoming[u] += 1
    return out, incoming


def triangle_stat(edges, n, directed):
    e = set(map(tuple, edges))
    if directed:
        return (
            sum(
                (a, b) in e and (b, c) in e and (c, a) in e
                for a, b, c in permutations(range(n), 3)
            )
            // 3
        )
    e |= {(v, u) for u, v in e}
    return sum(
        (a, b) in e and (b, c) in e and (c, a) in e
        for a, b, c in combinations(range(n), 3)
    )


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("directed", [False, True])
@pytest.mark.parametrize("model", ["degree_preserving_configuration", "erdos_renyi"])
def test_null_model_samples_invariants_and_statistics(mask, directed, model):
    n = 3 if directed else 4
    pairs = DIRECTED if directed else list(combinations(range(n), 2))
    edges = [pair for i, pair in enumerate(pairs) if mask >> i & 1]
    g = Graph.from_edges(edges, vertices=range(n), directed=directed)
    params = {
        "sample_count": 7,
        "statistic_definition": {
            "name": "directed_triangles" if directed else "triangles"
        },
        "null_model": model,
        "random_seed": mask,
        "return_randomized_edges": True,
    }
    result = execute("null-model-significance", g, **params)["result"]
    assert execute("null-model-significance", g, **params)["result"] == result
    values = []
    for sample in result["randomized_edges"]:
        assert len(sample) == len(edges)
        assert all(u != v for u, v in sample)
        assert len(
            {tuple(pair) if directed else tuple(sorted(pair)) for pair in sample}
        ) == len(sample)
        if model == "degree_preserving_configuration":
            assert degrees(n, sample, directed) == degrees(n, edges, directed)
        values.append(triangle_stat(sample, n, directed))
    assert result["null_distribution_samples"] == values
    observed = triangle_stat(edges, n, directed)
    assert result["observed_value"] == observed
    summary = result["null_distribution_summary"]
    assert summary["mean"] == pytest.approx(statistics.mean(values))
    assert summary["standard_deviation"] == pytest.approx(statistics.pstdev(values))
    if summary["standard_deviation"]:
        assert result["z_score"] == pytest.approx(
            (observed - summary["mean"]) / summary["standard_deviation"]
        )
    else:
        assert result["z_score"] is None
    assert result["empirical_p_value"] == sum(v >= observed for v in values) / len(
        values
    )


def test_configuration_sampler_uniform_small_realizations_and_budget():
    from graphmine.algorithms.null_models import configuration_sample
    from graphmine.contracts import WorkCounter

    base = nx.cycle_graph(4, backend="networkx")
    rng = random.Random(129)
    count = Counter()
    work = WorkCounter(Budget(max_candidates=2_000_000))
    for _ in range(6000):
        sample, _ = configuration_sample(base, rng, work, 10_000)
        count[tuple(sorted(tuple(sorted(e)) for e in sample.edges))] += 1
    assert len(count) == 3
    assert all(abs(v / 6000 - 1 / 3) < 0.025 for v in count.values())
    with pytest.raises(ResourceLimit):
        configuration_sample(base, rng, work, 0)


@pytest.mark.parametrize("case", ATLAS, ids=lambda c: f"atlas-{c[0]}")
def test_seeded_community_conductance_and_independent_diffusion_sweep(case):
    _, n, edges = case
    weights = {(u, v): Fraction((u + v) % 3) for u, v in edges}
    graph = Graph.from_edges(
        [(u, v, int(w)) for (u, v), w in weights.items()], vertices=range(n)
    )
    degree = [sum(w for pair, w in weights.items() if v in pair) for v in range(n)]
    total = sum(degree)
    matrix = np.zeros((n, n))
    personal = np.eye(n)[0]
    for u in range(n):
        if degree[u]:
            for (a, b), w in weights.items():
                if u == a:
                    matrix[b, u] = float(w / degree[u])
                if u == b:
                    matrix[a, u] = float(w / degree[u])
        else:
            matrix[:, u] = personal
    ppr = np.linalg.solve(np.eye(n) - 0.85 * matrix, 0.15 * personal)
    for bound in (None, float(degree[0] + (total - degree[0]) / 2)):
        result = execute(
            "seeded-local-community", graph, seeds=[0], maximum_volume=bound
        )
        rows = result["result"]
        selected = set(rows["vertices"])
        assert (
            0 in selected and not rows["optimal"] and result["quality"] == "heuristic"
        )
        volume = sum(degree[v] for v in selected)
        cut = sum(
            w for (u, v), w in weights.items() if (u in selected) != (v in selected)
        )
        denominator = min(volume, total - volume)
        assert rows["volume"] == volume and rows["cut_weight"] == cut
        assert rows["conductance"] == (
            float(cut / denominator) if denominator else None
        )
        assert bound is None or volume <= bound
        # The diffusion must agree with a direct independent linear solve;
        # ties within numerical tolerance may appear in either order.
        order = result["diagnostics"]["sweep_order"]
        rank = [ppr[v] / float(degree[v]) if degree[v] else 0 for v in order]
        assert all(a >= b - 1e-9 for a, b in pairwise(rank))
        candidates = []
        prefix = {0}
        for step in range(len(order) + 1):
            volume = sum(degree[v] for v in prefix)
            if bound is not None and volume > bound:
                break
            cut = sum(
                w for (u, v), w in weights.items() if (u in prefix) != (v in prefix)
            )
            den = min(volume, total - volume)
            if den:
                candidates.append(float(cut / den))
            if step < len(order):
                prefix.add(order[step])
        assert rows["conductance"] == (min(candidates) if candidates else None)


@pytest.mark.parametrize(
    "operation,params",
    [
        ("random-walks", {"start_vertices": [0], "length": 3, "p": 2}),
        (
            "random-walks",
            {"start_vertices": [0], "length": 3, "walk_model": "node2vec", "p": 0},
        ),
        ("neighborhood-sampling", {"seeds": [0], "fanouts": [True]}),
        (
            "neighborhood-sampling",
            {"seeds": [0], "fanouts": [1], "edge_type_fanouts": {"a": []}},
        ),
        ("neighborhood-sampling", {"seeds": [0], "fanouts": [1], "time_cutoff": 2}),
        ("temporal-paths", {"source": 0, "ready_time": 3, "deadline": 2}),
        (
            "bounded-paths-cycles",
            {"task": "s_t_path", "source": 0, "target": 0, "max_hops": 2},
        ),
        ("bounded-paths-cycles", {"task": "all_cycles", "source": 0, "max_hops": 2}),
        (
            "null-model-significance",
            {
                "sample_count": 1,
                "statistic_definition": {"name": "eval", "code": "1+1"},
            },
        ),
        ("seeded-local-community", {"seeds": [], "solution_quality": "exact"}),
    ],
)
def test_new_profile_rejects_invalid_or_inapplicable_parameters(operation, params):
    with pytest.raises(GraphMineError):
        execute(operation, Graph.from_edges([(0, 1)], directed=True), **params)


def test_sampling_output_budgets_apply_before_large_allocation():
    g = Graph.from_edges([(0, 1)])
    for operation, params in [
        ("random-walks", {"start_vertices": [0], "length": 10**12}),
        (
            "neighborhood-sampling",
            {"seeds": [0], "fanouts": [10**12], "replacement": True},
        ),
    ]:
        with pytest.raises(ResourceLimit):
            run(
                operation,
                g,
                device="cpu",
                parameters=params,
                budget=Budget(max_output_items=10),
            )


def test_sampling_entropy_seed_reproduces_and_cpu_backend_is_explicit():
    graph = Graph.from_edges([(0, "0"), (0, 2**60)], vertices=[0, "0", 2**60])
    args = {"start_vertices": [0, "0", 2**60], "length": 12}
    first = run("random-walks", graph, device="cpu", backend="numpy", parameters=args)
    second = run(
        "random-walks",
        graph,
        device="cpu",
        parameters={**args, "random_seed": first["diagnostics"]["random_seed"]},
    )
    assert first["result"] == second["result"]
    with pytest.raises(GraphMineError, match="conflicts"):
        run("random-walks", graph, device="gpu", backend="numpy", parameters=args)
    assert math.isfinite(first["elapsed_seconds"])


def test_sampling_probability_range_and_large_integer_weights():
    from graphmine.algorithms.sampling import probabilities

    assert probabilities([10**500, 3 * 10**500]).tolist() == pytest.approx([0.25, 0.75])
    with pytest.raises(GraphMineError, match="underflowed"):
        probabilities([1e-300, 1e300])
    graph = Graph.from_edges([(0, 1, 10**500), (0, 2, 3 * 10**500)], directed=True)
    result = execute(
        "random-walks",
        graph,
        start_vertices=[0],
        length=1,
        walk_model="weighted",
        random_seed=1,
    )
    assert result["result"]["walks"] == [[0, 2]]


@pytest.mark.parametrize("tail", ["greater", "less", "two_sided_about_null_mean"])
def test_null_model_tail_conventions_and_declared_statistics(tail):
    graph = Graph.from_edges(
        [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4), (4, 5)], vertices=range(6)
    )
    for definition in (
        {"name": "density"},
        {"name": "k_cliques", "k": 2},
        {"name": "modularity", "partition": [[0, 1, 2], [3, 4, 5]], "resolution": 0.7},
    ):
        result = execute(
            "null-model-significance",
            graph,
            statistic_definition=definition,
            sample_count=13,
            null_model="erdos_renyi",
            random_seed=64,
            tail=tail,
            return_randomized_edges=True,
        )["result"]
        values = []
        for edges in result["randomized_edges"]:
            if definition["name"] == "density":
                value = len(edges) / 15
            elif definition["name"] == "k_cliques":
                value = len(edges)
            else:
                degree, _ = degrees(6, edges, False)
                value = sum(
                    sum(u in part and v in part for u, v in edges) / 6
                    - 0.7 * (sum(degree[v] for v in part) / 12) ** 2
                    for part in definition["partition"]
                )
            values.append(value)
        assert result["null_distribution_samples"] == pytest.approx(values)
        actual = result["null_distribution_samples"]
        observed, mean = result["observed_value"], statistics.mean(actual)
        extreme = (
            sum(v >= observed for v in actual)
            if tail == "greater"
            else sum(v <= observed for v in actual)
            if tail == "less"
            else sum(abs(v - mean) >= abs(observed - mean) for v in actual)
        )
        assert result["empirical_p_value"] == extreme / len(actual)


def test_directed_sampling_retains_loops_and_deduplicates_frontiers():
    raw = event_graph(
        3, [(0, 1, 0, 0), (0, 1, 1, 0), (1, 1, 1, 0), (1, 2, 1, 0)]
    ).to_canonical()
    result = execute(
        "neighborhood-sampling", raw, seeds=[0, 0], fanouts=[-1, -1], random_seed=0
    )["result"]
    assert len(result["sampled_edges"]) == 8
    assert Counter((row["batch"], row["hop"]) for row in result["sampled_edges"]) == {
        (0, 1): 2,
        (0, 2): 2,
        (1, 1): 2,
        (1, 2): 2,
    }
    walks = execute("random-walks", raw, start_vertices=[2], length=10, random_seed=0)[
        "result"
    ]
    assert walks["walks"] == [[2]]


def test_local_community_multiseed_and_invalid_method_bounds():
    graph = Graph.from_edges([(0, 1, 0), (1, 2, 2), (2, 3, 1)], vertices=range(5))
    result = execute("seeded-local-community", graph, seeds=[0, 4], maximum_volume=0)[
        "result"
    ]
    assert result["vertices"] == [0, 4] and result["conductance"] is None
    for args in (
        {"seeds": [1], "maximum_volume": 1},
        {"seeds": [0, 0]},
        {"seeds": []},
        {"seeds": [0], "method_parameters": {"alpha": 1}},
        {"seeds": [0], "method_parameters": {"unused": 1}},
    ):
        with pytest.raises(GraphMineError):
            execute("seeded-local-community", graph, **args)


@pytest.mark.parametrize(
    "bad_time", ["not-a-date", "2026-10-10T14:00:00", "0001-01-01T00:00:00+01:00"]
)
def test_temporal_input_rejects_invalid_unzoned_or_overflowing_utc(bad_time):
    graph = event_graph(2, [(0, 1, bad_time, 0)])
    with pytest.raises(GraphMineError):
        execute("temporal-paths", graph, source=0, ready_time=0)


def test_null_model_does_not_guess_clique_order():
    with pytest.raises(GraphMineError, match="positive integer k"):
        execute(
            "null-model-significance",
            Graph.from_edges([(0, 1)]),
            sample_count=1,
            statistic_definition={"name": "k_cliques"},
        )
