from __future__ import annotations

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import simple, vertex_set


@register(
    id="maximum-independent-set",
    problem_id="maximum_independent_set",
    family="independent_sets",
    title="Find the largest non-conflicting group",
    description="Exact maximum independent set via maximum clique enumeration of the complement.",
    parameters={"mode": P("string", "exact", choices=("exact",))},
)
def maximum_independent(graph, args, work, backend="networkx"):
    g = simple(graph)
    complement = nx.complement(g, backend="networkx")
    best = []
    for clique in nx.find_cliques(complement, backend=backend):
        work.tick()
        if len(clique) > len(best):
            best = clique
    vertices = vertex_set(graph, best)
    work.output(len(vertices))
    return AlgorithmOutput(
        {"vertices": vertices, "size": len(vertices), "maximum_certified": True},
        {"vertices": {"type": "vertex_set", "value": vertices, "complete": True}},
    )


@register(
    id="minimum-vertex-cover",
    problem_id="minimum_vertex_cover",
    family="independent_sets",
    title="Cover every connection with as few vertices as possible",
    description="Exact minimum vertex cover through the complement of a maximum independent set.",
    parameters={
        "mode": P("string", "exact", choices=("exact", "decision")),
        "k": P("integer", None, minimum=0, nullable=True),
    },
)
def vertex_cover(graph, args, work, backend="networkx"):
    if args["mode"] == "decision" and args["k"] is None:
        raise GraphMineError("Decision mode requires k")
    independent = maximum_independent(graph, {"mode": "exact"}, work, backend)
    excluded = {graph.index(v) for v in independent.data["vertices"]}
    vertices = vertex_set(graph, set(range(graph.vertex_count)) - excluded)
    data = {"vertices": vertices, "size": len(vertices), "minimum_certified": True}
    if args["mode"] == "decision":
        data["exists"] = len(vertices) <= args["k"]
    return AlgorithmOutput(
        data, {"vertices": {"type": "vertex_set", "value": vertices, "complete": True}}
    )


@register(
    id="weighted-matching",
    problem_id="general_graph_weighted_matching",
    family="matching",
    title="Find the highest-value non-conflicting pairs",
    description="Exact maximum-weight matching on an undirected graph, without a maximum-cardinality constraint.",
    parameters={"solution_quality": P("string", "exact", choices=("exact",))},
)
def matching(graph, args, work, backend="networkx"):
    g = simple(graph, weighted=True, aggregation="max")
    selected = nx.max_weight_matching(
        g, maxcardinality=False, weight="weight", backend=backend
    )
    pairs = sorted(tuple(sorted(pair)) for pair in selected)
    rows = [
        {
            "source": graph.vertex_id(u),
            "target": graph.vertex_id(v),
            "weight": g[u][v]["weight"],
        }
        for u, v in pairs
    ]
    work.output(len(rows))
    return AlgorithmOutput(
        {"edges": rows, "total_weight": sum(r["weight"] for r in rows)},
        {"edges": {"type": "edge_set", "value": rows, "complete": True}},
    )


@register(
    id="max-flow-min-cut",
    problem_id="max_flow_min_cut",
    family="flow",
    title="Find capacity and bottlenecks between two places",
    description="Maximum flow with a minimum-cut certificate; parallel capacities are summed.",
    parameters={
        "source": P("vertex_id", required=True),
        "sink": P("vertex_id", required=True),
        "capacity_mode": P(
            "string", "edge_weight", choices=("edge_weight", "unit_capacity")
        ),
        "return_cut_side": P("boolean", True),
    },
)
def flow(graph, args, work, backend="networkx"):
    g = simple(
        graph,
        directed=True,
        weighted=args["capacity_mode"] == "edge_weight",
        nonnegative=True,
        aggregation="sum",
    )
    source, sink = graph.index(args["source"]), graph.index(args["sink"])
    if source == sink:
        raise GraphMineError("Source and sink must be distinct")
    value, flows = nx.maximum_flow(
        g,
        source,
        sink,
        capacity="weight",
        flow_func=nx.algorithms.flow.preflow_push,
        backend=backend,
    )
    cut_value, (left, right) = nx.minimum_cut(
        g,
        source,
        sink,
        capacity="weight",
        flow_func=nx.algorithms.flow.preflow_push,
        backend="networkx",
    )
    tolerance = 1e-9 * max(1.0, abs(value))
    if abs(value - cut_value) > tolerance:
        raise GraphMineError("Flow value differs from the minimum-cut certificate")
    rows = [
        {"source": graph.vertex_id(u), "target": graph.vertex_id(v), "flow": amount}
        for u, adjacent in flows.items()
        for v, amount in adjacent.items()
    ]
    work.output(len(rows))
    data = {"flow_value": value, "cut_capacity": cut_value, "flows": rows}
    ports = {"value": {"type": "scalar", "value": value, "complete": True}}
    if args["return_cut_side"]:
        data["source_side"] = vertex_set(graph, left)
        data["sink_side"] = vertex_set(graph, right)
        ports["vertices"] = {
            "type": "vertex_set",
            "value": data["source_side"],
            "complete": True,
        }
    return AlgorithmOutput(data, ports)
