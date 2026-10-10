from __future__ import annotations

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import groups, scores, simple, vertex_set


@register(
    id="connected-components",
    problem_id="connected_components",
    family="connectivity",
    title="Find connected groups",
    description="Exact weakly or strongly connected components, including isolated vertices.",
    parameters={
        "connectivity_mode": P(
            "string",
            "weakly_connected",
            choices=("weakly_connected", "strongly_connected"),
        )
    },
)
def components(graph, args, work, backend="networkx"):
    g = simple(graph, directed=True)
    if not g.is_directed():
        sets = nx.connected_components(g, backend=backend)
    elif args["connectivity_mode"] == "weakly_connected":
        sets = nx.weakly_connected_components(g, backend=backend)
    else:
        sets = nx.strongly_connected_components(g, backend=backend)
    result = groups(graph, sets)
    work.output(graph.vertex_count)
    return result


@register(
    id="biconnected-components",
    problem_id="biconnected_components",
    family="connectivity",
    title="Find fragile connections and cut vertices",
    description="Exact biconnected vertex blocks, bridges and articulation points of an undirected graph.",
)
def biconnected(graph, args, work, backend="networkx"):
    g = simple(graph)
    result = groups(graph, nx.biconnected_components(g, backend=backend))
    bridges = [
        {"source": graph.vertex_id(u), "target": graph.vertex_id(v)}
        for u, v in nx.bridges(g, backend=backend)
    ]
    articulation = vertex_set(graph, nx.articulation_points(g, backend=backend))
    result.data.update(
        bridges=bridges,
        articulation_points=articulation,
        isolated_vertices=vertex_set(graph, nx.isolates(g, backend="networkx")),
    )
    result.ports.update(
        vertices={"type": "vertex_set", "value": articulation, "complete": True},
        edges={"type": "edge_set", "value": bridges, "complete": True},
    )
    work.output(
        sum(len(group["vertices"]) for group in result.data["groups"])
        + len(bridges)
        + len(articulation)
    )
    return result


@register(
    id="k-core",
    problem_id="k_core_decomposition",
    family="cores",
    title="Find the well-connected core",
    description="Exact core numbers and an optional induced k-core.",
    parameters={"requested_k": P("integer", None, minimum=0, nullable=True)},
)
def core(graph, args, work, backend="networkx"):
    g = simple(graph)
    numbers = nx.core_number(g, backend=backend)
    result = scores(graph, numbers, "core_number", quality="exact")
    k = args["requested_k"]
    if k is not None:
        vertices = vertex_set(graph, [v for v in g if numbers[v] >= k])
        result.data["selected_vertices"] = vertices
        result.ports["vertices"] = {
            "type": "vertex_set",
            "value": vertices,
            "complete": True,
        }
    work.output(graph.vertex_count)
    return result


@register(
    id="k-truss",
    problem_id="k_truss_decomposition",
    family="cores",
    title="Find connections supported by triangles",
    description="Exact edge truss numbers and an optional k-truss edge set.",
    parameters={"requested_k": P("integer", None, minimum=2, nullable=True)},
)
def truss(graph, args, work, backend="networkx"):
    g = simple(graph)
    # nx-cugraph 26.10 drops the original ID mapping when a dense integer graph
    # loses vertices during k-truss extraction. Explicit non-dense keys force
    # its public conversion path to retain and restore the original identities.
    execution_graph = (
        nx.relabel_nodes(g, {v: ("graphmine", v) for v in g}, backend="networkx")
        if backend == "cugraph"
        else g
    )
    values = {tuple(sorted(edge)): 2 for edge in g.edges}
    for k in range(3, len(g) + 1):
        work.tick()
        current = nx.k_truss(execution_graph, k, backend=backend)
        if current.number_of_edges() == 0:
            break
        for edge in current.edges:
            key = (
                tuple(sorted(v[1] for v in edge))
                if backend == "cugraph"
                else tuple(sorted(edge))
            )
            if key not in values:
                raise GraphMineError("k-truss returned an edge outside its input graph")
            values[key] = k
    edges = [
        {
            "source": graph.vertex_id(u),
            "target": graph.vertex_id(v),
            "truss_number": value,
        }
        for (u, v), value in values.items()
    ]
    selected = (
        edges
        if args["requested_k"] is None
        else [e for e in edges if e["truss_number"] >= args["requested_k"]]
    )
    work.output(len(edges))
    return AlgorithmOutput(
        {"edges": edges, "selected_edges": selected},
        {"edges": {"type": "edge_set", "value": selected, "complete": True}},
    )


@register(
    id="maximal-cliques",
    problem_id="maximal_clique_enumeration",
    family="cliques",
    title="Find complete groups that cannot be extended",
    description="Enumerate maximal cliques; these are not necessarily maximum-size cliques.",
    parameters={
        "minimum_clique_size": P("integer", 1, minimum=1),
        "result_limit": P("integer", None, minimum=1, nullable=True),
    },
)
def maximal_cliques(graph, args, work, backend="networkx"):
    sets = []
    complete = True
    for clique in nx.find_cliques(simple(graph), backend=backend):
        work.tick()
        if len(clique) < args["minimum_clique_size"]:
            continue
        if args["result_limit"] is not None and len(sets) >= args["result_limit"]:
            complete = False
            break
        sets.append(clique)
        work.output(len(sets))
    result = groups(graph, sets)
    result.complete = complete
    result.ports["groups"]["complete"] = complete
    result.data["count_is_exhaustive"] = complete
    return result


@register(
    id="maximum-clique",
    problem_id="maximum_clique",
    family="cliques",
    title="Find the largest fully connected group",
    description="Exact maximum clique, with optional enumeration of every tied optimum.",
    parameters={"return_all_ties": P("boolean", False)},
)
def maximum_clique(graph, args, work, backend="networkx"):
    best, sets = 0, []
    for clique in nx.find_cliques(simple(graph), backend=backend):
        work.tick()
        if len(clique) > best:
            best, sets = len(clique), [clique]
        elif len(clique) == best and args["return_all_ties"]:
            sets.append(clique)
        work.output(len(sets))
    result = groups(graph, sets)
    result.data["maximum_size"] = best
    if sets:
        result.ports["vertices"] = {
            "type": "vertex_set",
            "value": vertex_set(graph, sets[0]),
            "complete": True,
        }
    return result


@register(
    id="k-cliques",
    problem_id="k_clique_counting_enumeration",
    family="cliques",
    title="Count or list complete groups of a chosen size",
    description="Exact k-clique counting/enumeration with k>=2 and no implementation-imposed upper k bound.",
    parameters={
        "k": P("integer", required=True, minimum=2),
        "mode": P("string", "count", choices=("count", "enumerate")),
        "result_limit": P("integer", None, minimum=1, nullable=True),
    },
)
def k_cliques(graph, args, work, backend="networkx"):
    k = args["k"]
    total, sets = 0, []
    if k <= graph.vertex_count:
        for clique in nx.enumerate_all_cliques(simple(graph), backend=backend):
            work.tick()
            if len(clique) > k:
                break
            if len(clique) != k:
                continue
            total += 1
            if args["mode"] == "enumerate" and (
                args["result_limit"] is None or len(sets) < args["result_limit"]
            ):
                sets.append(clique)
                work.output(len(sets))
    # Counting can be complete even when the optional materialized list is not.
    result = groups(graph, sets)
    result.data.update(
        count=total, k=k, listed_count=len(sets), count_is_exhaustive=True
    )
    result.ports["groups"]["complete"] = args["mode"] == "enumerate" and total == len(
        sets
    )
    result.ports["count"] = {"type": "scalar", "value": total, "complete": True}
    return result


@register(
    id="triangle-counting",
    problem_id="triangle_counting_listing",
    family="motifs",
    title="Count three-way connections",
    description="Exact triangle count and optional per-vertex, per-edge and instance outputs.",
    parameters={
        "list_instances": P("boolean", False),
        "include_per_vertex_counts": P("boolean", False),
        "include_per_edge_counts": P("boolean", False),
        "result_limit": P("integer", None, minimum=1, nullable=True),
    },
)
def triangles(graph, args, work, backend="networkx"):
    g = simple(graph)
    counts = nx.triangles(g, backend=backend)
    total = sum(counts.values()) // 3
    result = AlgorithmOutput(
        {"count": total},
        {"count": {"type": "scalar", "value": total, "complete": True}},
    )
    if args["include_per_vertex_counts"]:
        result.data["per_vertex"] = [
            {"vertex": graph.vertex_id(v), "count": count}
            for v, count in counts.items()
        ]
        work.output(len(counts))
    if args["include_per_edge_counts"]:
        result.data["per_edge"] = [
            {
                "source": graph.vertex_id(u),
                "target": graph.vertex_id(v),
                "count": len(set(g[u]) & set(g[v])),
            }
            for u, v in g.edges
        ]
        work.output(len(result.data["per_edge"]))
    if args["list_instances"]:
        listed = k_cliques(
            graph,
            {"k": 3, "mode": "enumerate", "result_limit": args["result_limit"]},
            work,
            backend,
        )
        result.data["triangles"] = [row["vertices"] for row in listed.data["groups"]]
        result.ports["groups"] = listed.ports["groups"]
    return result


@register(
    id="overlapping-communities",
    problem_id="overlapping_community_detection",
    family="community",
    title="Find overlapping tightly connected groups",
    description="Exact k-clique percolation communities. Membership may overlap.",
    parameters={
        "k": P("integer", required=True, minimum=2),
        "minimum_community_size": P("integer", 1, minimum=1),
        "include_unassigned_vertices": P("boolean", True),
    },
)
def overlapping(graph, args, work, backend="networkx"):
    g = simple(graph)
    communities = list(nx.community.k_clique_communities(g, args["k"], backend=backend))
    result = groups(
        graph, [c for c in communities if len(c) >= args["minimum_community_size"]]
    )
    assigned = set().union(*communities) if communities else set()
    if args["include_unassigned_vertices"]:
        result.data["unassigned_vertices"] = vertex_set(graph, set(g) - assigned)
    work.output(sum(len(g["vertices"]) for g in result.data["groups"]))
    return result


@register(
    id="maximal-independent-set",
    problem_id="maximal_independent_set",
    family="independent_sets",
    title="Select a non-conflicting group that cannot be extended",
    description="A maximal independent set; no maximum-cardinality guarantee is made.",
    parameters={"random_seed": P("integer", 0)},
)
def maximal_independent(graph, args, work, backend="networkx"):
    g = simple(graph)
    chosen = (
        nx.maximal_independent_set(g, seed=args["random_seed"], backend=backend)
        if len(g)
        else []
    )
    vertices = vertex_set(graph, chosen)
    return AlgorithmOutput(
        {
            "vertices": vertices,
            "size": len(vertices),
            "maximal": True,
            "maximum_certified": False,
        },
        {"vertices": {"type": "vertex_set", "value": vertices, "complete": True}},
    )


@register(
    id="vertex-coloring",
    problem_id="vertex_coloring",
    family="coloring",
    title="Assign non-conflicting groups",
    description="A valid greedy coloring at distance one or two; the number of colors is not claimed minimal.",
    parameters={
        "distance": P("integer", 1, choices=(1, 2)),
        "random_seed": P("integer", 0),
    },
    quality="feasible",
)
def coloring(graph, args, work, backend="networkx"):
    g = simple(graph)
    if args["distance"] == 2:
        g = nx.power(g, 2, backend="networkx")
    values = nx.coloring.greedy_color(g, strategy="largest_first", backend=backend)
    if any(values[u] == values[v] for u, v in g.edges):
        raise GraphMineError("Coloring failed its feasibility certificate")
    result = scores(graph, values, "color", quality="feasible")
    result.data["color_count"] = len(set(values.values()))
    work.output(len(values))
    return result
