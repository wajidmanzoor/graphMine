from __future__ import annotations

from fractions import Fraction

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._milp import BinaryModel, integral_balance_row


@register(
    id="hypergraph-partitioning",
    problem_id="hypergraph_partitioning",
    family="partitioning",
    input_kind="hypergraph",
    title="Partition a hypergraph while preserving whole-group connections",
    description="Binary assignment and hyperedge-part incidence optimize cut-net or connectivity-minus-one cost without a graph projection. Every part is nonempty and respects the upper weight bound.",
    parameters={
        "num_parts": P("integer", required=True, minimum=1),
        "imbalance_tolerance": P("number", 0.03, minimum=0),
        "objective": P(
            "string", "cut_net", choices=("cut_net", "connectivity_minus_one")
        ),
    },
    library="scipy",
    quality="numerical_optimum",
)
def partition(graph, args, work, backend="networkx"):
    n, k = graph.vertex_count, args["num_parts"]
    if k > n:
        raise GraphMineError("num_parts exceeds the number of hypergraph vertices")
    data = graph.to_canonical()
    edges = [
        ([graph.index(v) for v in e["vertices"]], e.get("weight", 1))
        for e in data["hyperedges"]
    ]
    weights = [v.get("weight", 1) for v in data["vertices"]]
    ideal = sum(Fraction(w) for w in weights) / k
    upper = ideal * (1 + Fraction(str(args["imbalance_tolerance"])))
    balance, _, balance_upper = integral_balance_row(weights, upper=upper)
    x_count, z_count = n * k, len(edges) * k
    cut_net = args["objective"] == "cut_net"
    costs = [0] * x_count + (
        [0] * z_count + [w for _, w in edges]
        if cut_net
        else [w for _, w in edges for _ in range(k)]
    )
    model = BinaryModel(costs, work)
    for v in range(n):
        model.constrain({v * k + p: 1 for p in range(k)}, 1, 1)
    for p in range(k):
        model.constrain({v * k + p: balance[v] for v in range(n)}, upper=balance_upper)
        model.constrain({v * k + p: 1 for v in range(n)}, lower=1)
    model.constrain({0: 1}, 1, 1)
    for e, (vertices, _) in enumerate(edges):
        incidence = {x_count + e * k + p: 1 for p in range(k)}
        for p in range(k):
            z = x_count + e * k + p
            for v in vertices:
                model.constrain({z: 1, v * k + p: -1}, lower=0)
            model.constrain({z: 1, **{v * k + p: -1 for v in vertices}}, upper=0)
        if cut_net:
            y = x_count + z_count + e
            model.constrain({**incidence, y: -(k - 1)}, upper=1)
            model.constrain({**incidence, y: -1}, lower=1)
    solution, evidence = model.solve()
    if solution is None:
        return AlgorithmOutput(
            {
                "partition": [],
                "objective_value": None,
                "part_weights": [],
                "feasible": False,
                "optimal": False,
                "infeasibility_certified": True,
            },
            diagnostics=evidence,
        )
    assignment = [next(p for p in range(k) if solution[v * k + p]) for v in range(n)]
    sizes = [
        sum((Fraction(weights[v]) for v in range(n) if assignment[v] == p), Fraction())
        for p in range(k)
    ]
    if any(size > upper for size in sizes) or len(set(assignment)) != k:
        raise GraphMineError("Hypergraph partition violates the requested balance")
    objective = sum(
        weight
        * (
            (len({assignment[v] for v in vertices}) > 1)
            if cut_net
            else len({assignment[v] for v in vertices}) - 1
        )
        for vertices, weight in edges
    )
    rows = [{"vertex": graph.vertex_id(v), "part": assignment[v]} for v in range(n)]
    work.output(n + k)
    evidence["objective_offset"] = 0 if cut_net else -sum(w for _, w in edges)
    return AlgorithmOutput(
        {
            "partition": rows,
            "objective_value": objective,
            "part_weights": [float(size) for size in sizes],
            "feasible": True,
            "optimal": True,
        },
        {"partition": {"type": "vertex_partition", "value": rows, "complete": True}},
        quality="numerical_optimum",
        diagnostics=evidence,
    )
