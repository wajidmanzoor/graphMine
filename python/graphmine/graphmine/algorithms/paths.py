from __future__ import annotations

from fractions import Fraction
from itertools import islice

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register


@register(
    id="widest-paths",
    problem_id="widest_paths",
    family="traversal",
    title="Find the greatest bottleneck capacity from a source",
    description="Threshold reachability using NetworkX BFS computes the max-min path objective with exact comparisons and witness predecessors. Zero capacity remains reachable.",
    parameters={"source_vertex": P("vertex_id", required=True)},
)
def widest(graph, args, work, backend="networkx"):
    if any("weight" not in e for e in graph.to_canonical()["edges"]):
        raise GraphMineError("Widest paths require a capacity on every edge")
    g = graph.to_networkx(
        direction="preserve",
        parallel_edges="max",
        self_loops="drop",
        weighted=True,
        nonnegative=True,
    )
    source = graph.index(args["source_vertex"])
    capacities, predecessors = {source: None}, {source: None}
    for threshold in sorted(
        {d["weight"] for _, _, d in g.edges(data=True)}, reverse=True
    ):
        work.tick(len(g) + g.number_of_edges())
        eligible = nx.subgraph_view(
            g,
            filter_edge=lambda u, v, threshold=threshold: (
                g[u][v]["weight"] >= threshold
            ),
        )
        for parent, vertex in nx.bfs_edges(eligible, source, backend="networkx"):
            if vertex not in capacities:
                capacities[vertex], predecessors[vertex] = threshold, parent
        if len(capacities) == len(g):
            break
    rows = [
        {
            "vertex": graph.vertex_id(v),
            "bottleneck_capacity": capacities.get(v),
            "reachable": v in capacities,
            "is_source": v == source,
            "predecessor": graph.vertex_id(predecessors[v])
            if predecessors.get(v) is not None
            else None,
        }
        for v in g
    ]
    work.output(len(rows))
    return AlgorithmOutput(
        {"vertices": rows},
        {"paths": {"type": "widest_path_tree", "value": rows, "complete": True}},
    )


@register(
    id="top-k-critical-paths",
    problem_id="top_k_critical_paths_dag",
    family="traversal",
    title="Find the k highest-cost paths through a DAG",
    description="Edge-identity expansion plus exact rational Johnson reweighting allows NetworkX's shortest-simple-path iterator to rank longest DAG paths, including negative weights and parallel arcs.",
    parameters={
        "k": P("integer", required=True, minimum=1),
        "sources": P("array", None, nullable=True),
        "sinks": P("array", None, nullable=True),
    },
)
def critical(graph, args, work, backend="networkx"):
    if not graph.directed:
        raise GraphMineError("Critical DAG paths require a directed graph")
    records = graph.to_canonical()["edges"]
    if any("weight" not in e for e in records):
        raise GraphMineError("Critical paths require a weight on every edge")
    g = graph.to_networkx(
        direction="require_directed", parallel_edges="collapse", self_loops="keep"
    )
    if not nx.is_directed_acyclic_graph(g, backend="networkx"):
        raise GraphMineError("Critical path input must be acyclic")
    sources = (
        [v for v in g if g.in_degree(v) == 0]
        if args["sources"] is None
        else [graph.index(v) for v in args["sources"]]
    )
    sinks = (
        [v for v in g if g.out_degree(v) == 0]
        if args["sinks"] is None
        else [graph.index(v) for v in args["sinks"]]
    )
    if len(set(sources)) != len(sources) or len(set(sinks)) != len(sinks):
        raise GraphMineError("Sources and sinks must not repeat vertex IDs")
    n, m = len(g), len(records)
    work.tick(n + m)
    expanded = nx.DiGraph(backend="networkx")
    start, finish = n + m, n + m + 1
    expanded.add_nodes_from(range(finish + 1))
    for i, edge in enumerate(records):
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        expanded.add_edge(u, n + i, cost=-Fraction(edge["weight"]))
        expanded.add_edge(n + i, v, cost=Fraction())
    expanded.add_edges_from((start, v, {"cost": Fraction()}) for v in sources)
    expanded.add_edges_from((v, finish, {"cost": Fraction()}) for v in sinks)
    potentials = nx.single_source_bellman_ford_path_length(
        expanded, start, weight="cost", backend="networkx"
    )
    if finish not in potentials:
        return AlgorithmOutput(
            {"paths": [], "complete": True, "all_paths_returned": True},
            {"paths": {"type": "path_set", "value": [], "complete": True}},
        )
    expanded = expanded.subgraph(potentials).copy()
    for u, v, attributes in expanded.edges(data=True):
        attributes["reweighted"] = attributes["cost"] + potentials[u] - potentials[v]
        if attributes["reweighted"] < 0:
            raise GraphMineError("Critical path reweighting produced a negative edge")

    def weight(_u, _v, attributes):
        work.tick()
        return attributes["reweighted"]

    rows = []
    paths = nx.shortest_simple_paths(
        expanded, start, finish, weight=weight, backend="networkx"
    )
    for path in islice(paths, args["k"] + 1):
        indices = [v - n for v in path if n <= v < n + m]
        total = sum((Fraction(records[i]["weight"]) for i in indices), Fraction())
        rows.append(
            {
                "edges": [records[i]["id"] for i in indices],
                "vertices": [graph.vertex_id(v) for v in path if v < n],
                "total_weight": total.numerator
                if total.denominator == 1
                else float(total),
                "weight_fraction": {
                    "numerator": total.numerator,
                    "denominator": total.denominator,
                },
            }
        )
        work.output(sum(len(row["edges"]) + len(row["vertices"]) for row in rows))
    complete = len(rows) <= args["k"]
    rows = rows[: args["k"]]
    return AlgorithmOutput(
        {"paths": rows, "complete": True, "all_paths_returned": complete},
        {"paths": {"type": "path_set", "value": rows, "complete": complete}},
        diagnostics={
            "ranking_arithmetic": "exact_rational",
            "zero_edge_paths": "included when a source is also a sink",
        },
    )
