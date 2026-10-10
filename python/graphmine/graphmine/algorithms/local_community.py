from __future__ import annotations

from fractions import Fraction

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import vertex_set
from ._events import number
from ._numeric import float64
from .centrality import _pagerank


@register(
    id="seeded-local-community",
    problem_id="seeded_local_community_detection",
    family="communities",
    title="Find a community around required seed vertices",
    description="NetworkX personalized PageRank followed by a weighted-degree-normalized sweep. All seeds are required; the lowest defined conductance among feasible sweep prefixes is selected. This is a heuristic, with recomputed cut and volume, and makes no global optimality claim. Parallel weights sum; self-loops are rejected.",
    parameters={
        "seeds": P("array", required=True),
        "maximum_volume": P("number", None, minimum=0, nullable=True),
        "method_parameters": P(
            "object",
            {},
            description="alpha (default 0.85), tolerance (1e-10), max_iterations (1000).",
        ),
        "solution_quality": P("string", "heuristic", choices=("heuristic",)),
    },
    quality="heuristic",
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.link_analysis.pagerank_alg.pagerank.html",
    ),
)
def local_community(graph, args, work, backend="networkx"):
    methods = {
        "alpha": P("number", 0.85, minimum=0, maximum=1),
        "tolerance": P("number", 1e-10, minimum=0),
        "max_iterations": P("integer", 1000, minimum=1),
    }
    supplied = args["method_parameters"]
    if set(supplied) - set(methods):
        raise GraphMineError("Unsupported local-community method_parameters")
    params = {
        name: definition.validate(name, supplied.get(name, definition.default))
        for name, definition in methods.items()
    }
    seeds = {graph.index(v) for v in args["seeds"]}
    if not seeds or len(seeds) != len(args["seeds"]):
        raise GraphMineError("seeds must be nonempty and distinct")
    g = graph.to_networkx(
        direction="require_undirected",
        parallel_edges="sum",
        self_loops="reject",
        weighted=True,
        nonnegative=True,
    )
    weights = {(u, v): Fraction(d["weight"]) for u, v, d in g.edges(data=True)}
    degree = {v: Fraction() for v in g}
    for (u, v), w in weights.items():
        degree[u] += w
        degree[v] += w
        g[u][v]["weight"] = float64(g[u][v]["weight"])
    total = sum(degree.values(), Fraction())
    bound = (
        Fraction(args["maximum_volume"])
        if args["maximum_volume"] is not None
        else total
    )
    seed_volume = sum(degree[v] for v in seeds)
    if seed_volume > bound:
        raise GraphMineError("Required seeds alone exceed maximum_volume")
    scores = _pagerank(
        graph, g, **params, personalization={v: 1 for v in seeds}, backend="networkx"
    )
    values = {
        graph.index(row["vertex"]): row["score"] for row in scores.data["vertices"]
    }
    order = sorted(
        (v for v in g if v not in seeds),
        key=lambda v: (
            -(Fraction(values[v]) / degree[v] if degree[v] else Fraction()),
            v,
        ),
    )
    selected = set(seeds)
    volume = seed_volume
    cut = sum(w for (u, v), w in weights.items() if (u in selected) != (v in selected))
    best = None
    sweep = []
    for step in range(len(order) + 1):
        work.tick()
        denominator = min(volume, total - volume)
        conductance = cut / denominator if denominator else None
        sweep.append(
            {
                "size": len(selected),
                "volume": number(volume),
                "cut_weight": number(cut),
                "conductance": number(conductance) if conductance is not None else None,
            }
        )
        if conductance is not None and (best is None or conductance < best[0]):
            best = conductance, selected.copy(), volume, cut
        if step == len(order):
            break
        v = order[step]
        if volume + degree[v] > bound:
            break
        for u in g[v]:
            w = weights[(v, u)] if (v, u) in weights else weights[(u, v)]
            cut += -w if u in selected else w
        selected.add(v)
        volume += degree[v]
    if best is None:
        best = (
            None,
            seeds,
            seed_volume,
            sum(w for (u, v), w in weights.items() if (u in seeds) != (v in seeds)),
        )
    conductance, chosen, volume, cut = best
    vertices = vertex_set(graph, chosen)
    data = {
        "vertices": vertices,
        "conductance": number(conductance) if conductance is not None else None,
        "optimal": False,
        "volume": number(volume),
        "cut_weight": number(cut),
        "sweep_candidates": sweep,
    }
    work.output(len(vertices) + len(sweep) + len(order))
    return AlgorithmOutput(
        data,
        {"vertices": {"type": "vertex_set", "value": vertices, "complete": True}},
        quality="heuristic",
        diagnostics={
            **scores.diagnostics,
            "method": "personalized_pagerank_degree_normalized_seed_first_sweep",
            "sweep_order": [graph.vertex_id(v) for v in order],
            "undefined_conductance_policy": "return_seeds_if_no_feasible_prefix_has_positive_denominator",
        },
    )
