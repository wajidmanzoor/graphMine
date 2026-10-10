from __future__ import annotations

import math
from fractions import Fraction

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import simple, vertex_set
from ._milp import BinaryModel, induced_model


def _selection(graph, selected, data, *, quality="exact", diagnostics=None):
    vertices = vertex_set(graph, selected)
    return AlgorithmOutput(
        {"vertices": vertices, **data},
        {"vertices": {"type": "vertex_set", "value": vertices, "complete": True}},
        quality=quality,
        diagnostics=diagnostics or {},
    )


def _terms(g, order, weighted, work):
    if order > len(g):
        return []
    if order == 2:
        return [
            (tuple(e[:2]), e[2]["weight"] if weighted else 1)
            for e in g.edges(data=True)
        ]
    terms = []
    for clique in nx.enumerate_all_cliques(g, backend="networkx"):
        work.tick()
        if len(clique) > order:
            break
        if len(clique) == order:
            terms.append((tuple(clique), 1))
    return terms


def _maximum_density_closure(n, terms, work):
    # Dinkelbach's finite ratio iteration. Maximum-weight closure is reduced
    # to a min cut. Binary floating inputs are converted to exact integer units
    # so NetworkX's flow arithmetic cannot reverse two close objectives.
    fractions = [Fraction(w) for _, w in terms]
    scale = math.lcm(*(w.denominator for w in fractions))
    weights = [int(w * scale) for w in fractions]
    best = set(range(n))
    numerator, denominator = sum(weights), n
    source, sink = n + len(terms), n + len(terms) + 1
    while True:
        work.tick(n + len(terms))
        closure = nx.DiGraph(backend="networkx")
        closure.add_nodes_from(range(sink + 1))
        infinity = sum(weights) * denominator + n * numerator + 1
        for i, ((vertices, _), weight) in enumerate(zip(terms, weights, strict=True)):
            closure.add_edge(source, n + i, capacity=weight * denominator)
            for v in vertices:
                closure.add_edge(n + i, v, capacity=infinity)
        for v in range(n):
            closure.add_edge(v, sink, capacity=numerator)
        _, (reached, _) = nx.minimum_cut(
            closure, source, sink, capacity="capacity", backend="networkx"
        )
        selected = reached & set(range(n))
        value = sum(
            w
            for (vertices, _), w in zip(terms, weights, strict=True)
            if set(vertices) <= selected
        )
        if value * denominator <= numerator * len(selected):
            ratio = Fraction(numerator, denominator * scale)
            return best, {
                "solver": "networkx.minimum_cut/maximum_weight_closure",
                "certificate": "exact_integer_capacity_ratio_optimality",
                "density_fraction": {
                    "numerator": ratio.numerator,
                    "denominator": ratio.denominator,
                },
            }
        best, numerator, denominator = selected, value, len(selected)


@register(
    id="densest-subgraph",
    problem_id="densest_subgraph",
    family="dense_structures",
    title="Find the region with the most edges or cliques per vertex",
    description="Maximize induced k-clique count / vertex count. k is clique order, not result size. Weighted density is defined only for k=2.",
    parameters={
        "clique_order": P("integer", 2, minimum=2),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "minimum_vertices": P("integer", 1, minimum=1),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.flow.minimum_cut.html",
    ),
)
def densest(graph, args, work, backend="networkx"):
    k, minimum = args["clique_order"], args["minimum_vertices"]
    weighted = args["weight_mode"] == "edge_weight"
    if weighted and k != 2:
        raise GraphMineError(
            "Weighted higher-order clique density is not defined by this contract"
        )
    g = simple(
        graph,
        weighted=weighted,
        nonnegative=True,
        aggregation="sum" if weighted else "collapse",
    )
    if not g or minimum > len(g):
        raise GraphMineError("There is no feasible nonempty set with minimum_vertices")
    terms = _terms(g, k, weighted, work)
    quality = "exact"
    if minimum == 1:
        selected, evidence = _maximum_density_closure(len(g), terms, work)
    else:
        best, selected, evidence = Fraction(-1), set(), {}
        certificates = []
        for size in range(minimum, len(g) + 1):
            model = induced_model(len(g), terms, work)
            model.constrain(dict.fromkeys(range(len(g)), 1), size, size)
            values, certificate = model.solve()
            if values is None:
                raise GraphMineError(
                    "Cardinality-constrained density unexpectedly infeasible"
                )
            candidate = {v for v in g if values[v]}
            ratio = (
                sum(
                    (
                        Fraction(w)
                        for vertices, w in terms
                        if set(vertices) <= candidate
                    ),
                    Fraction(),
                )
                / size
            )
            certificates.append({"size": size, **certificate})
            if ratio > best:
                best, selected = ratio, candidate
        evidence = {"cardinality_certificates": certificates}
        quality = "numerical_optimum"
    count = sum(set(vertices) <= selected for vertices, _ in terms)
    numerator = sum(
        (Fraction(w) for vertices, w in terms if set(vertices) <= selected), Fraction()
    )
    edge_value = sum(
        g[u][v]["weight"] for u, v in g.edges if u in selected and v in selected
    )
    work.output(len(selected))
    return _selection(
        graph,
        selected,
        {
            "density": float(numerator / len(selected)),
            "clique_order": k,
            "clique_count": count,
            "induced_edge_value": edge_value,
            "optimal": True,
        },
        quality=quality,
        diagnostics=evidence,
    )


@register(
    id="densest-k-subgraph",
    problem_id="densest_k_subgraph",
    family="dense_structures",
    title="Find exactly k vertices with the greatest internal edge value",
    description="Binary vertex/edge optimization with an exact cardinality constraint; solver optimality and the recomputed objective are checked.",
    parameters={
        "k": P("integer", required=True, minimum=1),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
    library="scipy",
    quality="numerical_optimum",
    references=(
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html",
    ),
)
def densest_k(graph, args, work, backend="networkx"):
    weighted = args["weight_mode"] == "edge_weight"
    g = simple(
        graph,
        weighted=weighted,
        nonnegative=True,
        aggregation="sum" if weighted else "collapse",
    )
    k = args["k"]
    if k > len(g):
        raise GraphMineError("k exceeds the number of vertices")
    model = induced_model(len(g), _terms(g, 2, weighted, work), work)
    model.constrain(dict.fromkeys(range(len(g)), 1), k, k)
    values, evidence = model.solve()
    if values is None:
        raise GraphMineError("No feasible k-vertex selection")
    selected = {v for v in g if values[v]}
    value = sum(
        g[u][v]["weight"] for u, v in g.edges if u in selected and v in selected
    )
    if len(selected) != k:
        raise GraphMineError("The solver violated the requested cardinality")
    work.output(k)
    return _selection(
        graph,
        selected,
        {"induced_edge_value": value, "density": value / k, "optimal": True},
        quality="numerical_optimum",
        diagnostics=evidence,
    )


@register(
    id="quasi-cliques",
    problem_id="quasi_clique_mining",
    family="dense_structures",
    title="Find groups meeting a minimum internal-degree fraction",
    description="Enumerate all gamma quasi-cliques via binary feasibility models; maximality is checked against all qualifying larger sets within the size bounds.",
    parameters={
        "gamma": P("number", required=True, minimum=0, maximum=1),
        "minimum_size": P("integer", required=True, minimum=2),
        "maximum_size": P("integer", None, minimum=2, nullable=True),
        "maximal_only": P("boolean", True),
    },
    library="scipy",
)
def quasi_cliques(graph, args, work, backend="networkx"):
    if args["gamma"] <= 0:
        raise GraphMineError("gamma must be greater than zero")
    minimum = args["minimum_size"]
    upper = args["maximum_size"]
    if upper is not None and upper < minimum:
        raise GraphMineError("maximum_size must be at least minimum_size")
    g = simple(graph)
    accepted = []
    # Decimal semantics avoid accidental ceil(0.14 * 50) == 8 from binary
    # rounding. This threshold rule is part of the operation's public contract.
    gamma = Fraction(str(args["gamma"]))
    for size in range(
        min(len(g), upper if upper is not None else len(g)), minimum - 1, -1
    ):
        threshold = math.ceil(gamma * (size - 1))
        model = BinaryModel([0] * len(g), work)
        model.constrain(dict.fromkeys(range(len(g)), 1), size, size)
        for v in g:
            model.constrain({v: -threshold, **dict.fromkeys(g[v], 1)}, lower=0)
        while True:
            values, _ = model.solve()
            if values is None:
                break
            selected = frozenset(v for v in g if values[v])
            if len(selected) != size or any(
                len(set(g[v]) & selected) < threshold for v in selected
            ):
                raise GraphMineError("Quasi-clique feasibility check failed")
            model.constrain(dict.fromkeys(selected, 1), upper=size - 1)
            if not args["maximal_only"] or not any(
                selected < bigger for bigger in accepted
            ):
                accepted.append(selected)
                work.output(len(accepted))
    records = []
    for selected in accepted:
        degrees = [len(set(g[v]) & selected) for v in selected]
        edges = sum(degrees) // 2
        records.append(
            {
                "vertices": vertex_set(graph, selected),
                "size": len(selected),
                "induced_edge_count": edges,
                "density": 2 * edges / (len(selected) * (len(selected) - 1)),
                "minimum_internal_degree": min(degrees),
            }
        )
    return AlgorithmOutput(
        {"quasi_cliques": records, "count": len(records), "complete": True},
        {"groups": {"type": "vertex_groups", "value": records, "complete": True}},
        diagnostics={
            "solver": "scipy.optimize.milp/HiGHS",
            "threshold_arithmetic": "decimal_rational",
            "maximality_scope": "qualifying_sets_within_size_bounds",
            "feasibility_rechecked": True,
        },
    )
