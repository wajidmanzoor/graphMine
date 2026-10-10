"""Exhaustive reference mining with BLISS canonical forms and VF2 embeddings.

Transaction support and minimum-image support are different objectives. Both
use simple normalized graphs, explicit labels and budgets, without an arbitrary
pattern-edge ceiling. Canonical pattern IDs belong to each pattern, not a host.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from itertools import combinations

import igraph as ig
import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register

_REFERENCES = (
    "https://python.igraph.org/en/main/api/igraph.GraphBase.html#canonical_permutation",
    "https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html",
)


def _normalize(graph, *, vertex_field, edge_field, loops, parallel, work):
    data = graph.to_canonical()
    result = (
        nx.DiGraph(backend="networkx")
        if graph.directed
        else nx.Graph(backend="networkx")
    )
    for i, vertex in enumerate(data["vertices"]):
        work.tick()
        result.add_node(i, value=vertex.get(vertex_field) if vertex_field else None)
    for edge in data["edges"]:
        work.tick()
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        if u == v:
            if loops == "reject":
                raise GraphMineError("Frequent-pattern profiles reject self-loops")
            continue
        value = edge.get(edge_field) if edge_field else None
        if result.has_edge(u, v):
            if parallel == "reject":
                raise GraphMineError("Parallel edges require explicit collapse")
            if result[u][v]["value"] != value:
                raise GraphMineError(
                    "Cannot collapse parallel edges with different selected types"
                )
        result.add_edge(u, v, value=value)
    return result


def _canonical(graph, vertex_field, edge_field, work):
    """Encode edge colors as colored subdivision vertices for BLISS.

    Original/edge vertex roles have disjoint colors. Directed edges become
    directed two-arc paths. The full canonical key (not a hash) deduplicates
    patterns, and retains label values as well as local color partitions.
    """
    work.tick()
    vertices, edges = list(graph), list(graph.edges)
    index = {v: i for i, v in enumerate(vertices)}
    colors = [("vertex", graph.nodes[v]["value"]) for v in vertices]
    colors += [("edge", graph[u][v]["value"]) for u, v in edges]
    palette = {
        token: i
        for i, token in enumerate(sorted(set(colors), key=lambda c: json.dumps(c)))
    }
    arcs = []
    for i, (u, v) in enumerate(edges, start=len(vertices)):
        arcs.extend(((index[u], i), (i, index[v])))
    encoded = ig.Graph(len(colors), arcs, directed=graph.is_directed())
    encoded.vs["original"] = vertices + [None] * len(edges)
    # Use the documented composition rather than assuming a permutation's
    # orientation. igraph's API documentation has used both conventions.
    permuted = encoded.permute_vertices(
        encoded.canonical_permutation(color=[palette[c] for c in colors])
    )
    order = [v for v in permuted.vs["original"] if v is not None]
    canonical_index = {v: i for i, v in enumerate(order)}
    node_values = [graph.nodes[v]["value"] for v in order]
    canonical_edges = []
    for u, v in edges:
        a, b = canonical_index[u], canonical_index[v]
        if not graph.is_directed() and a > b:
            a, b = b, a
        canonical_edges.append((a, b, graph[u][v]["value"]))
    canonical_edges.sort(key=lambda row: (row[0], row[1]))
    key = json.dumps(
        [graph.is_directed(), vertex_field, edge_field, node_values, canonical_edges],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    pattern_id = "pattern-" + hashlib.sha256(key.encode()).hexdigest()
    pattern = {
        "graph": {
            "id": pattern_id,
            "directed": graph.is_directed(),
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [
            {
                "id": i,
                **({vertex_field: value} if vertex_field and value is not None else {}),
            }
            for i, value in enumerate(node_values)
        ],
        "edges": [
            {
                "id": i,
                "source": u,
                "target": v,
                **({edge_field: value} if edge_field and value is not None else {}),
            }
            for i, (u, v, value) in enumerate(canonical_edges)
        ],
    }
    representative = (
        nx.DiGraph(backend="networkx")
        if graph.is_directed()
        else nx.Graph(backend="networkx")
    )
    representative.add_nodes_from(
        (i, {"value": value}) for i, value in enumerate(node_values)
    )
    representative.add_edges_from(
        (u, v, {"value": value}) for u, v, value in canonical_edges
    )
    work.tick(0)
    return key, pattern, representative


def _subgraph(host, vertices, edges):
    graph = (
        nx.DiGraph(backend="networkx")
        if host.is_directed()
        else nx.Graph(backend="networkx")
    )
    graph.add_nodes_from((v, host.nodes[v]) for v in vertices)
    graph.add_edges_from((u, v, host[u][v]) for u, v in edges)
    return graph


def _transaction_candidates(host, args, work):
    maximum = args["maximum_vertices"]
    maximum = len(host) if maximum is None else min(maximum, len(host))
    for size in range(args["minimum_vertices"], maximum + 1):
        for vertices in combinations(host, size):
            work.tick()
            induced = host.subgraph(vertices)
            edges = list(induced.edges)
            if args["induced"]:
                if args["minimum_edges"] <= len(edges) <= args["maximum_edges"]:
                    yield induced
            else:
                for edge_count in range(
                    args["minimum_edges"], min(args["maximum_edges"], len(edges)) + 1
                ):
                    for chosen in combinations(edges, edge_count):
                        work.tick()
                        yield _subgraph(host, vertices, chosen)


@register(
    id="frequent-subgraphs",
    problem_id="frequent_subgraph_mining",
    family="pattern_mining",
    title="Frequent patterns across graphs",
    description=(
        "Exhaustive simple directed/undirected transaction mining. Support counts graphs, "
        "not occurrences. Includes disconnected patterns and isolated vertices within the "
        "declared edge/vertex bounds. Types are categorical; weights/times are ignored. "
        "Nonempty patterns by default; minimum_vertices=0 includes the empty pattern. "
        "BLISS canonicalization; exponential enumeration uses explicit work/output budgets."
    ),
    library="igraph",
    input_kind="graph_collection",
    references=_REFERENCES,
    parameters={
        "minimum_support_fraction": P(
            "number",
            required=True,
            minimum=0,
            maximum=1,
            description="Strictly positive fraction of transactions containing the pattern.",
        ),
        "minimum_edges": P("integer", default=1, minimum=0),
        "maximum_edges": P("integer", required=True, minimum=0),
        "minimum_vertices": P("integer", default=1, minimum=0),
        "maximum_vertices": P("integer", default=None, nullable=True, minimum=0),
        "induced": P("boolean", default=False),
        "label_semantics": P(
            "string",
            default="vertex_and_edge_type",
            choices=("unlabeled", "vertex_type", "edge_type", "vertex_and_edge_type"),
        ),
        "self_loops": P("string", default="reject", choices=("reject", "drop")),
        "parallel_edges": P(
            "string",
            default="reject",
            choices=("reject", "collapse"),
            description="Collapse requires identical selected edge types.",
        ),
        "include_supporting_graph_ids": P("boolean", default=False),
    },
)
def frequent_subgraphs(collection, args, work, backend):
    fraction = Fraction(str(args["minimum_support_fraction"]))
    if fraction <= 0:
        raise GraphMineError("minimum_support_fraction must be strictly positive")
    if args["maximum_edges"] < args["minimum_edges"]:
        raise GraphMineError("maximum_edges must be >= minimum_edges")
    if (
        args["maximum_vertices"] is not None
        and args["maximum_vertices"] < args["minimum_vertices"]
    ):
        raise GraphMineError("maximum_vertices must be >= minimum_vertices")
    semantics = args["label_semantics"]
    vertex_field = (
        "type" if semantics in ("vertex_type", "vertex_and_edge_type") else None
    )
    edge_field = "type" if semantics in ("edge_type", "vertex_and_edge_type") else None
    records = {}
    for graph in collection.graphs:
        host = _normalize(
            graph,
            vertex_field=vertex_field,
            edge_field=edge_field,
            loops=args["self_loops"],
            parallel=args["parallel_edges"],
            work=work,
        )
        transaction_id = graph.to_canonical()["graph"]["id"]
        seen = set()
        for candidate in _transaction_candidates(host, args, work):
            key, pattern, _ = _canonical(candidate, vertex_field, edge_field, work)
            if key in seen:
                continue
            seen.add(key)
            if key not in records:
                records[key] = {"pattern": pattern, "graphs": []}
            records[key]["graphs"].append(transaction_id)
    patterns = []
    output_items = 0
    for key in sorted(records):
        record = records[key]
        count = len(record["graphs"])
        if Fraction(count, collection.graph_count) < fraction:
            continue
        pattern = record["pattern"]
        row = {
            "pattern_id": pattern["graph"]["id"],
            "pattern": pattern,
            "vertex_count": len(pattern["vertices"]),
            "edge_count": len(pattern["edges"]),
            "support_graph_count": count,
            "support_fraction": count / collection.graph_count,
        }
        if args["include_supporting_graph_ids"]:
            row["supporting_graph_ids"] = sorted(record["graphs"])
            output_items += count
        output_items += 1 + row["vertex_count"] + row["edge_count"]
        work.output(output_items)
        patterns.append(row)
    return AlgorithmOutput(
        {
            "patterns": patterns,
            "complete": True,
            "frequent_pattern_count": len(patterns),
            "transaction_count": collection.graph_count,
        },
        {
            "patterns": {
                "type": "pattern_collection",
                "value": patterns,
                "complete": True,
            },
            "count": {"type": "scalar", "value": len(patterns), "complete": True},
        },
        diagnostics={
            "support": "transaction_presence",
            "canonicalization": "igraph BLISS edge-subdivision coloring",
            "threshold_comparison": "exact decimal rational",
            "candidates": work.candidates,
            "pattern_vertex_namespace": "local to each canonical pattern",
        },
    )


def _connected_candidates(host, maximum_edges, induced, work):
    for vertex in host:
        work.tick()
        yield host.subgraph([vertex])
    edges = list(host.edges)
    for size in range(1, min(maximum_edges, len(edges)) + 1):
        for chosen in combinations(edges, size):
            work.tick()
            vertices = sorted({v for edge in chosen for v in edge})
            if len(vertices) > size + 1:
                continue
            candidate = _subgraph(host, vertices, chosen)
            if not nx.is_connected(candidate, backend="networkx"):
                continue
            if induced and host.subgraph(vertices).number_of_edges() != size:
                continue
            yield candidate


@register(
    id="single-graph-frequent-subgraphs",
    problem_id="single_graph_frequent_subgraph_mining",
    family="pattern_mining",
    title="Frequent labeled patterns within one graph",
    description=(
        "Exact connected labeled patterns, including single-vertex patterns, in an "
        "undirected graph. Minimum-image support is the smallest distinct host image-set "
        "size across pattern vertices over all VF2 embeddings. BLISS deduplicates patterns. "
        "Every vertex needs the selected string label/type. Edge labels, weights and times "
        "are ignored. Count mode does not provide a pattern collection. Exponential work is budgeted."
    ),
    library="igraph",
    references=_REFERENCES,
    parameters={
        "minimum_image_support": P("integer", required=True, minimum=1),
        "max_pattern_edges": P("integer", required=True, minimum=1),
        "match_mode": P(
            "string", default="non_induced", choices=("non_induced", "induced")
        ),
        "output_mode": P("string", default="count", choices=("count", "patterns")),
        "vertex_label_field": P("string", default="label", choices=("label", "type")),
        "parallel_edges": P("string", default="reject", choices=("reject", "collapse")),
        "include_images": P(
            "boolean",
            default=False,
            description="Include original host image sets per pattern vertex; requires patterns output.",
        ),
    },
)
def single_graph_frequent_subgraphs(graph, args, work, backend):
    if graph.directed:
        raise GraphMineError("Single-graph MNI mining requires an undirected graph")
    field = args["vertex_label_field"]
    if any(field not in vertex for vertex in graph.to_canonical()["vertices"]):
        raise GraphMineError(f"Every vertex must provide the selected {field} field")
    if args["include_images"] and args["output_mode"] != "patterns":
        raise GraphMineError("include_images requires output_mode=patterns")
    host = _normalize(
        graph,
        vertex_field=field,
        edge_field=None,
        loops="reject",
        parallel=args["parallel_edges"],
        work=work,
    )
    patterns = [] if args["output_mode"] == "patterns" else None
    seen, count, output_items = set(), 0, 0
    induced = args["match_mode"] == "induced"
    candidates = (
        _connected_candidates(host, args["max_pattern_edges"], induced, work)
        if args["minimum_image_support"] <= len(host)
        else ()
    )
    for candidate in candidates:
        key, pattern, representative = _canonical(candidate, field, None, work)
        if key in seen:
            continue
        seen.add(key)
        matcher = nx.isomorphism.GraphMatcher(
            host, representative, node_match=lambda a, b: a["value"] == b["value"]
        )
        mappings = (
            matcher.subgraph_isomorphisms_iter()
            if induced
            else matcher.subgraph_monomorphisms_iter()
        )
        images = [set() for _ in representative]
        for mapping in mappings:
            work.tick()
            for host_vertex, pattern_vertex in mapping.items():
                images[pattern_vertex].add(host_vertex)
        support = min(map(len, images))
        if support < args["minimum_image_support"]:
            continue
        count += 1
        if patterns is not None:
            row = {
                "pattern_id": pattern["graph"]["id"],
                "pattern": pattern,
                "vertex_count": len(representative),
                "edge_count": representative.number_of_edges(),
                "minimum_image_support": support,
                "image_counts": [
                    {"pattern_vertex": i, "count": len(values)}
                    for i, values in enumerate(images)
                ],
            }
            if args["include_images"]:
                row["images"] = [
                    {
                        "pattern_vertex": i,
                        "host_vertices": [graph.vertex_id(v) for v in sorted(values)],
                    }
                    for i, values in enumerate(images)
                ]
                output_items += sum(map(len, images))
            output_items += (
                1 + 2 * len(representative) + representative.number_of_edges()
            )
            work.output(output_items)
            patterns.append(row)
    ports = {"count": {"type": "scalar", "value": count, "complete": True}}
    if patterns is not None:
        patterns.sort(key=lambda row: row["pattern_id"])
        ports = {
            "patterns": {
                "type": "pattern_collection",
                "value": patterns,
                "complete": True,
            },
            **ports,
        }
    return AlgorithmOutput(
        {"frequent_pattern_count": count, "patterns": patterns, "completed": True},
        ports,
        diagnostics={
            "support": "minimum_image_support",
            "embeddings": "NetworkX VF2",
            "canonicalization": "igraph BLISS edge-subdivision coloring",
            "candidates": work.candidates,
            "pattern_vertex_namespace": "local to each canonical pattern",
        },
    )
