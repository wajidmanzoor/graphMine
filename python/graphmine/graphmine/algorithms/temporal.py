from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from itertools import pairwise, product

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph, external_id
from ..registry import register
from ._events import nonnegative_fraction, number, timestamp
from .patterns import _predicates


@register(
    id="temporal-paths",
    problem_id="temporal_fastest_paths",
    family="temporal",
    title="Find earliest arrivals or fastest journeys through timed events",
    description="NetworkX shortest paths on an exact-rational time-expanded graph. Waiting is allowed; fastest duration excludes waiting before the first departure. Parallel events remain distinct candidates.",
    parameters={
        "source": P("vertex_id", required=True),
        "ready_time": P("number", required=True),
        "deadline": P("number", None, nullable=True),
        "objective": P(
            "string",
            "fastest_duration",
            choices=("fastest_duration", "earliest_arrival"),
        ),
        "duration_attribute": P("string", "duration"),
    },
)
def temporal_paths(graph, args, work, backend="networkx"):
    if not graph.directed:
        raise GraphMineError("Temporal paths require a directed graph")
    if not args["duration_attribute"]:
        raise GraphMineError("duration_attribute must be nonempty")
    source, ready = graph.index(args["source"]), Fraction(args["ready_time"])
    deadline = Fraction(args["deadline"]) if args["deadline"] is not None else None
    if deadline is not None and deadline < ready:
        raise GraphMineError("deadline must not precede ready_time")
    events, times = [], defaultdict(set)
    times[source].add(ready)
    for edge in graph.to_canonical()["edges"]:
        work.tick()
        departure = timestamp(edge.get("timestamp"))
        duration = nonnegative_fraction(
            edge.get("attributes", {}).get(args["duration_attribute"]), "Event duration"
        )
        arrival = departure + duration
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        if departure < ready or (deadline is not None and arrival > deadline):
            continue
        events.append((u, v, departure, arrival, edge["id"]))
        times[u].add(departure)
        times[v].add(arrival)
    expanded = nx.DiGraph(backend="networkx")
    for vertex, values in times.items():
        ordered = sorted(values)
        expanded.add_nodes_from((vertex, time) for time in ordered)
        for before, after in pairwise(ordered):
            expanded.add_edge(
                (vertex, before), (vertex, after), weight=after - before, edge_id=None
            )
    for u, v, departure, arrival, edge_id in events:
        first, second = (u, departure), (v, arrival)
        if not expanded.has_edge(first, second):
            expanded.add_edge(
                first, second, weight=arrival - departure, edge_id=edge_id
            )
    start = (source, ready)
    if args["objective"] == "fastest_duration":
        start = ("start",)
        expanded.add_node(start)
        for time in times[source]:
            expanded.add_edge(start, (source, time), weight=Fraction(), edge_id=None)
    work.tick(expanded.number_of_nodes() + expanded.number_of_edges())
    distances, paths = nx.single_source_dijkstra(
        expanded, start, weight="weight", backend="networkx"
    )
    best = {}
    for node, distance in distances.items():
        if node == ("start",):
            continue
        v, arrival = node
        value = arrival if args["objective"] == "earliest_arrival" else distance
        if v not in best or (value, arrival) < (best[v][0], best[v][1][1]):
            best[v] = value, node
    rows = []
    for v in range(graph.vertex_count):
        if v not in best:
            rows.append(
                {
                    "vertex": graph.vertex_id(v),
                    "value": None,
                    "reachable": False,
                    "edges": [],
                    "departure": None,
                    "arrival": None,
                    "value_fraction": None,
                }
            )
            continue
        value, end = best[v]
        path = paths[end]
        steps = [
            (u, w, expanded[u][w])
            for u, w in pairwise(path)
            if expanded[u][w]["edge_id"] is not None
        ]
        departure = steps[0][0][1] if steps else ready
        arrival = steps[-1][1][1] if steps else ready
        rows.append(
            {
                "vertex": graph.vertex_id(v),
                "value": number(value),
                "value_fraction": str(value),
                "reachable": True,
                "edges": [step[2]["edge_id"] for step in steps],
                "departure": number(departure),
                "arrival": number(arrival),
            }
        )
    work.output(sum(1 + len(row["edges"]) for row in rows))
    return AlgorithmOutput(
        {"values": rows, "complete": True},
        {"paths": {"type": "temporal_path_table", "value": rows, "complete": True}},
        diagnostics={
            "arithmetic": "exact_rational",
            "waiting_before_first_departure": "excluded_from_fastest_duration",
        },
    )


@register(
    id="temporal-motifs",
    problem_id="temporal_motif_mining",
    family="pattern_mining",
    title="Count ordered temporal edge patterns",
    description="NetworkX VF2 structural matching followed by injective event assignment, exact UTC time comparisons, order constraints and optional temporal inducedness. Distinct tuples in motif-edge order identify occurrences.",
    parameters={
        "temporal_motif": P(
            "object",
            required=True,
            description="graph: canonical motif; optional order: [before_edge_id, after_edge_id] pairs (default: total input-edge order); optional vertex_predicates/edge_predicates use the structural matching predicate schema.",
        ),
        "maximum_duration_seconds": P("number", required=True, minimum=0),
        "allow_equal_timestamps": P("boolean", False),
        "temporal_induced": P("boolean", False),
        "list_instances": P("boolean", False),
        "result_limit": P("integer", None, minimum=1, nullable=True),
    },
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html",
    ),
)
def temporal_motifs(graph, args, work, backend="networkx"):
    spec = args["temporal_motif"]
    if (
        set(spec) - {"graph", "order", "vertex_predicates", "edge_predicates"}
        or "graph" not in spec
    ):
        raise GraphMineError(
            "temporal_motif needs graph and only declared order/predicate fields"
        )
    query = Graph(spec["graph"])
    if graph.directed != query.directed:
        raise GraphMineError("Data and temporal motif direction must match")
    raw, pattern = graph.to_canonical(), query.to_canonical()
    events, query_edges = raw["edges"], pattern["edges"]
    if not query_edges:
        raise GraphMineError("A temporal motif needs at least one edge event")
    incident = {v for edge in query_edges for v in (edge["source"], edge["target"])}
    if len(incident) != query.vertex_count:
        raise GraphMineError("Temporal motifs do not accept isolated pattern vertices")
    if args["result_limit"] is not None and not args["list_instances"]:
        raise GraphMineError("result_limit applies only when list_instances is true")
    for name in ("vertex_predicates", "edge_predicates"):
        if not isinstance(spec.get(name, []), list):
            raise GraphMineError(f"{name} must be an array")
    vertex_match = _predicates(spec.get("vertex_predicates", []), query)
    edge_match = _predicates(spec.get("edge_predicates", []), query, edge=True)
    ids = {e["id"]: i for i, e in enumerate(query_edges)}
    order = spec.get("order", [[a["id"], b["id"]] for a, b in pairwise(query_edges)])
    if not isinstance(order, list):
        raise GraphMineError("Temporal order must be an array of edge-ID pairs")
    constraints = []
    for pair in order:
        if not isinstance(pair, list) or len(pair) != 2:
            raise GraphMineError("Each temporal order constraint needs two edge IDs")
        before, after = [external_id(v) for v in pair]
        if before not in ids or after not in ids:
            raise GraphMineError("Temporal order references an unknown motif edge")
        constraints.append((ids[before], ids[after]))
    precedence = nx.DiGraph(backend="networkx")
    precedence.add_edges_from(constraints)
    if not nx.is_directed_acyclic_graph(precedence, backend="networkx"):
        raise GraphMineError("Temporal order must be acyclic")
    times = [timestamp(e.get("timestamp")) for e in events]
    maximum = Fraction(args["maximum_duration_seconds"])
    g, q = (
        (nx.DiGraph(backend="networkx"), nx.DiGraph(backend="networkx"))
        if graph.directed
        else (nx.Graph(backend="networkx"), nx.Graph(backend="networkx"))
    )
    for target, canonical, data in ((g, raw, graph), (q, pattern, query)):
        target.add_nodes_from((data.index(v["id"]), v) for v in canonical["vertices"])
        target.add_edges_from(
            (data.index(e["source"]), data.index(e["target"]))
            for e in canonical["edges"]
        )
    endpoints = [(graph.index(e["source"]), graph.index(e["target"])) for e in events]
    by_pair = defaultdict(list)
    for i, pair in enumerate(endpoints):
        by_pair[pair if graph.directed else tuple(sorted(pair))].append(i)
    matcher_type = (
        nx.isomorphism.DiGraphMatcher if graph.directed else nx.isomorphism.GraphMatcher
    )
    matcher = matcher_type(g, q, node_match=vertex_match)
    seen, instances = set(), []
    participation = [0] * graph.vertex_count
    for mapping in matcher.subgraph_monomorphisms_iter():
        work.tick()
        reverse = {v: u for u, v in mapping.items()}
        candidates = []
        for edge in query_edges:
            pair = (
                reverse[query.index(edge["source"])],
                reverse[query.index(edge["target"])],
            )
            choices = by_pair[pair if graph.directed else tuple(sorted(pair))]
            candidates.append([i for i in choices if edge_match(events[i], edge)])
        for chosen in product(*candidates):
            work.tick()
            if chosen in seen or len(set(chosen)) != len(chosen):
                continue
            when = [times[i] for i in chosen]
            if any(
                when[a] > when[b]
                if args["allow_equal_timestamps"]
                else when[a] >= when[b]
                for a, b in constraints
            ):
                continue
            first, last = min(when), max(when)
            if last - first > maximum:
                continue
            vertices = set(mapping)
            if args["temporal_induced"]:
                selected = set(chosen)
                if any(
                    i not in selected
                    and u in vertices
                    and v in vertices
                    and first <= times[i] <= last
                    for i, (u, v) in enumerate(endpoints)
                ):
                    continue
            seen.add(chosen)
            for v in vertices:
                participation[v] += 1
            if args["list_instances"] and (
                args["result_limit"] is None or len(instances) < args["result_limit"]
            ):
                instances.append(
                    {
                        "edge_ids": [events[i]["id"] for i in chosen],
                        "timestamps": [number(t) for t in when],
                        "duration": number(last - first),
                        "vertices": [
                            {
                                "query_vertex": query.vertex_id(v),
                                "data_vertex": graph.vertex_id(reverse[v]),
                            }
                            for v in range(query.vertex_count)
                        ],
                    }
                )
                work.output(
                    len(instances) * (1 + len(query_edges) + query.vertex_count)
                )
    complete = args["list_instances"] and len(instances) == len(seen)
    data = {
        "occurrence_count": len(seen),
        "instances_complete": complete,
        "per_vertex_participation": [
            {"vertex": graph.vertex_id(v), "value": value}
            for v, value in enumerate(participation)
        ],
    }
    ports = {}
    if args["list_instances"]:
        data["instances"] = instances
        ports["instances"] = {
            "type": "temporal_occurrence_collection",
            "value": instances,
            "complete": complete,
        }
    work.output(
        len(participation)
        + len(instances) * (1 + len(query_edges) + query.vertex_count)
    )
    return AlgorithmOutput(
        data,
        ports,
        diagnostics={
            "count_complete": True,
            "occurrence_identity": "edge_id_tuple_in_motif_input_order",
            "arithmetic": "exact_rational",
        },
    )
