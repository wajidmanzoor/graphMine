from __future__ import annotations

from fractions import Fraction
from itertools import combinations, product
from math import comb

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..inputs import finite_number
from ..registry import register
from ._common import vertex_values
from ._events import number


@register(
    id="influence-maximization",
    problem_id="influence_maximization",
    family="centrality",
    title="Choose starting points that maximize expected diffusion",
    description="Exact rational enumeration of seed sets and live-edge states using NetworkX reachability. Supports independent cascade and uniform-random linear threshold; supplied fixed thresholds use progressive activation. Parallel IC probabilities combine as 1-product(1-p); LT weights sum. Exponential reference method with explicit work budgets, no sampling or unsupported statistical promises.",
    parameters={
        "diffusion_model": P(
            "string", required=True, choices=("independent_cascade", "linear_threshold")
        ),
        "seed_set_size": P("integer", required=True, minimum=1),
        "vertex_thresholds": P(
            "array",
            None,
            nullable=True,
            description="Fixed LT thresholds as {vertex,value} rows for every vertex. Null selects independent uniform thresholds. Zero fixed thresholds activate even without active predecessors.",
        ),
    },
    references=("https://www.cs.cornell.edu/home/kleinber/kdd03-inf.pdf",),
)
def influence(graph, args, work, backend="networkx"):
    if not graph.directed:
        raise GraphMineError("Influence maximization requires a directed graph")
    n, k = graph.vertex_count, args["seed_set_size"]
    if k > n:
        raise GraphMineError("seed_set_size cannot exceed the vertex count")
    model = args["diffusion_model"]
    fixed = args["vertex_thresholds"]
    if fixed is not None and model != "linear_threshold":
        raise GraphMineError("vertex_thresholds applies only to linear_threshold")
    weights = {}
    for edge in graph.to_canonical()["edges"]:
        if "weight" not in edge:
            raise GraphMineError("Each diffusion edge needs an explicit weight")
        p = Fraction(edge["weight"])
        if not 0 <= p <= 1:
            raise GraphMineError("Diffusion weights must lie within [0,1]")
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        if u == v:
            continue
        old = weights.get((u, v), Fraction())
        weights[u, v] = (
            1 - (1 - old) * (1 - p) if model == "independent_cascade" else old + p
        )
    incoming = {v: [] for v in range(n)}
    for (u, v), weight in sorted(weights.items()):
        if weight:
            incoming[v].append((u, weight))
    if model == "linear_threshold" and any(
        sum((w for _, w in rows), Fraction()) > 1 for rows in incoming.values()
    ):
        raise GraphMineError(
            "Linear-threshold incoming weights must sum to at most one"
        )
    candidate_count = comb(n, k)
    work.tick(candidate_count * max(1, k))
    candidates = list(combinations(range(n), k))
    spreads = [Fraction() for _ in candidates]
    states_run = 0
    probability_mass = Fraction()
    if fixed is not None:
        thresholds = vertex_values(graph, fixed, "vertex_thresholds")
        thresholds = {
            v: Fraction(finite_number(value, "Threshold"))
            for v, value in thresholds.items()
        }
        if any(not 0 <= value <= 1 for value in thresholds.values()):
            raise GraphMineError("Vertex thresholds must lie within [0,1]")
        for i, seeds in enumerate(candidates):
            active = set(seeds)
            while True:
                work.tick(n + len(weights))
                added = {
                    v
                    for v in range(n)
                    if v not in active
                    and sum((w for u, w in incoming[v] if u in active), Fraction())
                    >= thresholds[v]
                }
                if not added:
                    break
                active.update(added)
            spreads[i] = Fraction(len(active))
        states_run, probability_mass = 1, Fraction(1)
    else:
        choices = []
        if model == "independent_cascade":
            for pair, p in sorted(weights.items()):
                options = []
                if p < 1:
                    options.append((None, 1 - p))
                if p:
                    options.append((pair, p))
                choices.append(options)
        else:
            for v, rows in incoming.items():
                options = [((u, v), w) for u, w in rows]
                residual = 1 - sum((w for _, w in rows), Fraction())
                if residual:
                    options.append((None, residual))
                choices.append(options)
        states = 1
        for options in choices:
            states *= len(options)
            if states > work.budget.max_candidates:
                work.tick(states)
        work.tick(states)
        for state in product(*choices):
            work.tick(n * (n + len(weights)) + candidate_count * k)
            live = nx.DiGraph(backend="networkx")
            live.add_nodes_from(range(n))
            probability = Fraction(1)
            for pair, p in state:
                probability *= p
                if pair is not None:
                    live.add_edge(*pair)
            reachable = [
                nx.descendants(live, v, backend="networkx") | {v} for v in live
            ]
            for i, seeds in enumerate(candidates):
                activated = set().union(*(reachable[v] for v in seeds))
                spreads[i] += probability * len(activated)
            probability_mass += probability
            states_run += 1
    if probability_mass != 1:
        raise GraphMineError("Diffusion state probabilities did not sum exactly to one")
    chosen = max(range(candidate_count), key=spreads.__getitem__)
    expectation = spreads[chosen]
    if not k <= expectation <= n:
        raise GraphMineError("Expected spread violated its mathematical bounds")
    seeds = [graph.vertex_id(v) for v in candidates[chosen]]
    exact = {"numerator": expectation.numerator, "denominator": expectation.denominator}
    work.output(k)
    return AlgorithmOutput(
        {
            "seed_set": seeds,
            "expected_spread": number(expectation),
            "expected_spread_rational": exact,
            "optimal": True,
            "guarantee_met": True,
            "approximation_ratio": 1,
            "failure_probability": 0,
            "seed_sets_evaluated": candidate_count,
            "diffusion_states_evaluated": states_run,
        },
        {
            "vertices": {"type": "vertex_set", "value": seeds, "complete": True},
            "spread": {
                "type": "scalar",
                "value": number(expectation),
                "complete": True,
            },
        },
        diagnostics={
            "expectation_method": "fixed_threshold_propagation"
            if fixed is not None
            else "exact_live_edge_enumeration",
            "probability_arithmetic": "exact rational values of the supplied JSON numbers",
            "seed_selection": "exhaustive subsets; input-vertex order resolves ties",
            "sampling_used": False,
            "self_loops": "removed",
        },
    )
