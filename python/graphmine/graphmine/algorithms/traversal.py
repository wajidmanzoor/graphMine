from __future__ import annotations

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import simple, vertex_set


@register(
    id="breadth-first-search",
    problem_id="breadth_first_search",
    family="traversal",
    title="Connections within a number of steps",
    description="Exact unweighted distances from independent sources or the nearest supplied source.",
    parameters={
        "sources": P("array", required=True),
        "source_mode": P(
            "string", "independent", choices=("independent", "nearest_source")
        ),
        "depth_limit": P("integer", None, minimum=0, nullable=True),
        "return_predecessors": P("boolean", True),
    },
)
def bfs(graph, args, work, backend="networkx"):
    g = simple(graph, directed=True)
    sources = list(dict.fromkeys(graph.index(v) for v in args["sources"]))
    if not sources:
        raise GraphMineError("At least one source is required")
    rows = []
    source_groups = (
        [[s] for s in sources] if args["source_mode"] == "independent" else [sources]
    )
    for seeds in source_groups:
        work.tick()
        # Multi-source BFS is Dijkstra with unit weights, preserving exact hops.
        if backend == "networkx":
            distances, paths = nx.multi_source_dijkstra(
                g, seeds, cutoff=args["depth_limit"], weight=None, backend=backend
            )
        else:
            # nx-cugraph exposes single-source traversal. Merge independently
            # computed source distances to implement nearest-source semantics.
            distances, paths = {}, {}
            for seed in seeds:
                found, routes = nx.single_source_dijkstra(
                    g, seed, cutoff=args["depth_limit"], weight=None, backend=backend
                )
                for vertex, distance in found.items():
                    if vertex not in distances or distance < distances[vertex]:
                        distances[vertex], paths[vertex] = distance, routes[vertex]
        for i, vertex in enumerate(graph.node_ids):
            row = {"vertex": vertex, "distance": distances.get(i)}
            if args["source_mode"] == "independent":
                row["source"] = graph.vertex_id(seeds[0])
            else:
                row["source"] = graph.vertex_id(paths[i][0]) if i in paths else None
            if args["return_predecessors"]:
                row["predecessor"] = (
                    graph.vertex_id(paths[i][-2])
                    if i in paths and len(paths[i]) > 1
                    else None
                )
            rows.append(row)
            work.output(len(rows))
    reached = vertex_set(
        graph,
        {graph.index(row["vertex"]) for row in rows if row["distance"] is not None},
    )
    return AlgorithmOutput(
        {"distances": rows},
        {
            "vertices": {"type": "vertex_set", "value": reached, "complete": True},
            "distances": {"type": "table", "value": rows, "complete": True},
        },
    )


@register(
    id="single-source-shortest-paths",
    problem_id="single_source_shortest_paths",
    family="traversal",
    title="Shortest routes from one starting point",
    description="Exact shortest distances and predecessors with nonnegative edge lengths.",
    parameters={
        "source": P("vertex_id", required=True),
        "cutoff": P("number", None, minimum=0, nullable=True),
        "return_predecessors": P("boolean", True),
    },
)
def sssp(graph, args, work, backend="networkx"):
    g = simple(graph, directed=True, weighted=True, nonnegative=True, aggregation="min")
    source = graph.index(args["source"])
    distance, paths = nx.single_source_dijkstra(
        g, source, cutoff=args["cutoff"], weight="weight", backend=backend
    )
    rows = []
    for i, vertex in enumerate(graph.node_ids):
        row = {"vertex": vertex, "distance": distance.get(i)}
        if args["return_predecessors"]:
            row["predecessor"] = (
                graph.vertex_id(paths[i][-2])
                if i in paths and len(paths[i]) > 1
                else None
            )
        rows.append(row)
    work.output(len(rows))
    return AlgorithmOutput(
        {"distances": rows},
        {
            "distances": {
                "type": "vertex_scores",
                "value": rows,
                "score_field": "distance",
                "complete": True,
            }
        },
    )


@register(
    id="many-source-shortest-paths",
    problem_id="many_source_shortest_paths",
    family="traversal",
    title="Shortest routes between selected places",
    description="Exact pairwise distances; absent routes are returned as null.",
    parameters={
        "origins": P("array", None, nullable=True),
        "destinations": P("array", None, nullable=True),
        "weight_mode": P(
            "string", "edge_weight", choices=("unweighted", "edge_weight")
        ),
    },
)
def many_paths(graph, args, work, backend="networkx"):
    g = simple(graph, directed=True, weighted=True, nonnegative=True, aggregation="min")
    sources = (
        range(graph.vertex_count)
        if args["origins"] is None
        else list(dict.fromkeys(graph.index(v) for v in args["origins"]))
    )
    targets = (
        list(range(graph.vertex_count))
        if args["destinations"] is None
        else list(dict.fromkeys(graph.index(v) for v in args["destinations"]))
    )
    work.output(len(sources) * len(targets))
    rows = []
    for source in sources:
        work.tick()
        distances = nx.single_source_dijkstra_path_length(
            g,
            source,
            weight="weight" if args["weight_mode"] == "edge_weight" else None,
            backend=backend,
        )
        rows.extend(
            {
                "source": graph.vertex_id(source),
                "target": graph.vertex_id(target),
                "distance": distances.get(target),
            }
            for target in targets
        )
    return AlgorithmOutput(
        {"distances": rows},
        {"distances": {"type": "table", "value": rows, "complete": True}},
    )


@register(
    id="spanning-tree-forest",
    problem_id="spanning_tree_forest",
    family="trees",
    title="Connect the network with minimum or maximum total weight",
    description="An exact minimum or maximum spanning forest, retaining isolated vertices.",
    parameters={
        "objective": P("string", "minimum", choices=("minimum", "maximum")),
        "require_connected": P("boolean", False),
    },
)
def spanning_tree(graph, args, work, backend="networkx"):
    g = simple(
        graph,
        weighted=True,
        aggregation="min" if args["objective"] == "minimum" else "max",
    )
    if args["require_connected"] and (
        not len(g) or not nx.is_connected(g, backend="networkx")
    ):
        raise GraphMineError("A connected graph is required")
    function = (
        nx.minimum_spanning_tree
        if args["objective"] == "minimum"
        else nx.maximum_spanning_tree
    )
    if backend == "cugraph":
        from ..backends.cugraph import spanning_forest

        tree = spanning_forest(g, maximum=args["objective"] == "maximum")
    else:
        tree = function(g, weight="weight", backend=backend)
    edges = [
        {
            "source": graph.vertex_id(u),
            "target": graph.vertex_id(v),
            "weight": d["weight"],
        }
        for u, v, d in tree.edges(data=True)
    ]
    work.output(len(edges))
    return AlgorithmOutput(
        {
            "vertices": list(graph.node_ids),
            "edges": edges,
            "total_weight": sum(e["weight"] for e in edges),
        },
        {
            "edges": {"type": "edge_set", "value": edges, "complete": True},
            "vertices": {
                "type": "vertex_set",
                "value": list(graph.node_ids),
                "complete": True,
            },
        },
    )


@register(
    id="topological-sort",
    problem_id="topological_sort",
    family="traversal",
    title="Order tasks by their dependencies",
    description="A topological vertex order for a directed acyclic graph; cycles are rejected.",
)
def topological(graph, args, work, backend="networkx"):
    g = graph.to_networkx(
        direction="require_directed", self_loops="keep", parallel_edges="collapse"
    )
    try:
        order = [graph.vertex_id(v) for v in nx.topological_sort(g, backend=backend)]
    except nx.NetworkXUnfeasible as exc:
        raise GraphMineError(
            "The graph has a directed cycle; no topological ordering exists"
        ) from exc
    work.output(len(order))
    return AlgorithmOutput(
        {"order": order},
        {"vertices": {"type": "vertex_set", "value": order, "complete": True}},
    )


@register(
    id="induced-subgraph",
    problem_id="induced_subgraph_ego_extraction",
    family="subgraphs",
    title="Explore a selected group or neighborhood",
    description="An induced graph on explicit vertices or a bounded-hop neighborhood, with original IDs and attributes.",
    parameters={
        "mode": P("string", "induced", choices=("induced", "ego")),
        "vertices_or_seeds": P("array", required=True),
        "radius": P("integer", 1, minimum=0),
        "direction_mode": P(
            "string",
            "outgoing",
            choices=("outgoing", "incoming", "undirected_projection"),
        ),
    },
)
def induced(graph, args, work, backend="networkx"):
    selected = {graph.index(v) for v in args["vertices_or_seeds"]}
    if args["mode"] == "ego":
        g = simple(graph, directed=True)
        if args["direction_mode"] == "incoming" and g.is_directed():
            g = g.reverse(copy=False)
        elif args["direction_mode"] == "undirected_projection":
            g = g.to_undirected()
        reached = set()
        for seed in selected:
            work.tick()
            reached.update(
                nx.single_source_shortest_path_length(
                    g, seed, cutoff=args["radius"], backend=backend
                )
            )
        selected = reached
    vertices = vertex_set(graph, selected)
    derived = graph.induced_subgraph(vertices)
    work.output(derived.vertex_count + derived.edge_count)
    return AlgorithmOutput(
        {"graph": derived.to_canonical()},
        {
            "graph": {
                "type": "graph",
                "value": derived.to_canonical(),
                "complete": True,
            },
            "vertices": {"type": "vertex_set", "value": vertices, "complete": True},
        },
    )


@register(
    id="transitive-closure",
    problem_id="transitive_closure_reachability",
    family="traversal",
    title="Find which places can reach each other",
    description="Exact reachability with a zero-length path allowed from each vertex to itself.",
    parameters={
        "query_mode": P(
            "string",
            "full_transitive_closure",
            choices=("single_pair", "batch_pairs", "full_transitive_closure"),
        ),
        "query_pairs": P("array", None, nullable=True),
        "enumerate_closure_edges": P("boolean", True),
    },
)
def reachability(graph, args, work, backend="networkx"):
    g = simple(graph, directed=True)
    if args["query_mode"] == "full_transitive_closure":
        rows = []
        total = 0
        for source in g:
            work.tick()
            targets = nx.single_source_shortest_path_length(g, source, backend=backend)
            total += len(targets)
            if args["enumerate_closure_edges"]:
                rows.extend(
                    {"source": graph.vertex_id(source), "target": graph.vertex_id(t)}
                    for t in targets
                )
                work.output(len(rows))
        return AlgorithmOutput(
            {
                "count": total,
                "pairs": rows if args["enumerate_closure_edges"] else None,
            },
            {
                "pairs": {
                    "type": "table",
                    "value": rows,
                    "complete": args["enumerate_closure_edges"],
                }
            },
        )
    pairs = args["query_pairs"]
    if not pairs or (args["query_mode"] == "single_pair" and len(pairs) != 1):
        raise GraphMineError("Supply the requested nonempty query_pairs array")
    work.output(len(pairs))
    rows = []
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise GraphMineError("Each query pair must contain source and target IDs")
        u, v = map(graph.index, pair)
        work.tick()
        rows.append(
            {
                "source": pair[0],
                "target": pair[1],
                "reachable": nx.has_path(g, u, v, backend=backend),
            }
        )
    return AlgorithmOutput({"pairs": rows})
