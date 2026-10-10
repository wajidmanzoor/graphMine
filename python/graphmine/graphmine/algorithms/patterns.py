from __future__ import annotations

import json
import operator
from collections import Counter, defaultdict
from functools import lru_cache
from itertools import combinations

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph
from ..registry import register
from ._common import simple

_MISSING = object()


def _field(record, path):
    for name in path.split("."):
        if not isinstance(record, dict) or name not in record:
            return _MISSING
        record = record[name]
    return record


def _predicates(specs, query, *, edge=False):
    allowed_roots = (
        {"type", "weight", "timestamp", "attributes"}
        if edge
        else {"label", "type", "attributes"}
    )
    binding = "query_edge" if edge else "query_vertex"
    ids = {
        record["id"] for record in query.to_canonical()["edges" if edge else "vertices"]
    }
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) - {
            "field",
            "operator",
            "value",
            "query_field",
            binding,
        }:
            raise GraphMineError("Unknown predicate fields")
        if not isinstance(spec.get("operator"), str) or spec["operator"] not in {
            "eq",
            "ne",
            "lt",
            "le",
            "gt",
            "ge",
            "in",
            "exists",
            "eq_query",
        }:
            raise GraphMineError("Unsupported attribute predicate operator")
        for path in [
            spec.get("field"),
            *([spec["query_field"]] if "query_field" in spec else []),
        ]:
            if (
                not isinstance(path, str)
                or not all(path.split("."))
                or path.split(".")[0] not in allowed_roots
            ):
                raise GraphMineError("Invalid attribute predicate field path")
        op = spec["operator"]
        if binding in spec:
            value = spec[binding]
            if type(value) not in (str, int) or value not in ids:
                raise GraphMineError(f"Unknown {binding} predicate binding")
        if op == "eq_query":
            if "value" in spec:
                raise GraphMineError(
                    "eq_query reads the query field and does not accept value"
                )
        else:
            if "query_field" in spec:
                raise GraphMineError("query_field applies only to eq_query")
            if op != "exists" and "value" not in spec:
                raise GraphMineError("Predicate is missing value")
            if op == "in" and not isinstance(spec["value"], list):
                raise GraphMineError("The in predicate needs an array value")
            if op == "exists" and type(spec.get("value", True)) is not bool:
                raise GraphMineError("The exists predicate needs a boolean value")

    def compare(data, pattern):
        for spec in specs:
            if binding in spec and pattern["id"] != spec[binding]:
                continue
            value = _field(data, spec["field"])
            op = spec["operator"]
            if op == "exists":
                if (value is not _MISSING) != spec.get("value", True):
                    return False
                continue
            expected = (
                _field(pattern, spec.get("query_field", spec["field"]))
                if op == "eq_query"
                else spec["value"]
            )
            if value is _MISSING or expected is _MISSING:
                return False
            if op in {"eq", "ne", "eq_query"}:
                equal = json.dumps(value, sort_keys=True) == json.dumps(
                    expected, sort_keys=True
                )
                if equal == (op == "ne"):
                    return False
            elif op == "in":
                if not any(
                    json.dumps(value, sort_keys=True) == json.dumps(v, sort_keys=True)
                    for v in expected
                ):
                    return False
            else:
                if type(value) not in (str, int, float) or type(expected) not in (
                    str,
                    int,
                    float,
                ):
                    return False
                try:
                    if not getattr(operator, op)(value, expected):
                        return False
                except TypeError:
                    return False
        return True

    return compare


def _multigraph(graph):
    g = (
        nx.MultiDiGraph(backend="networkx")
        if graph.directed
        else nx.MultiGraph(backend="networkx")
    )
    for v in graph.to_canonical()["vertices"]:
        g.add_node(graph.index(v["id"]), **v)
    for i, edge in enumerate(graph.to_canonical()["edges"]):
        g.add_edge(
            graph.index(edge["source"]),
            graph.index(edge["target"]),
            key=i,
            **{k: v for k, v in edge.items() if k not in {"source", "target"}},
        )
    return g


def _mapping_rows(graph, query, mapping):
    reverse = {q: v for v, q in mapping.items()}
    return [
        {"query_vertex": query.vertex_id(q), "data_vertex": graph.vertex_id(reverse[q])}
        for q in range(query.vertex_count)
    ]


@register(
    id="subgraph-isomorphism",
    problem_id="subgraph_isomorphism",
    family="pattern_mining",
    title="Find every match for a supplied graph pattern",
    description="NetworkX VF2 induced or non-induced matching. Preserves direction, loops and distinct parallel edges; declarative predicates constrain vertex and edge attributes.",
    parameters={
        "query_graph": P("object", required=True),
        "induced": P("boolean", False),
        "vertex_predicates": P("array", []),
        "edge_predicates": P("array", []),
        "result_limit": P("integer", None, minimum=1, nullable=True),
    },
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html",
    ),
)
def subgraph_isomorphism(graph, args, work, backend="networkx"):
    query = Graph(args["query_graph"])
    if graph.directed != query.directed:
        raise GraphMineError("Query and data graph direction must match")
    vertex_match = _predicates(args["vertex_predicates"], query)
    edge_match = _predicates(args["edge_predicates"], query, edge=True)

    def node_check(data, pattern):
        work.tick()
        return vertex_match(data, pattern)

    def bundle_check(data, pattern):
        # VF2 checks multiplicities. Attribute matching additionally requires
        # an injective assignment of each query edge to a distinct data edge.
        candidates = nx.Graph(backend="networkx")
        left = [("query", i) for i in pattern]
        candidates.add_nodes_from(left)
        candidates.add_nodes_from(("data", j) for j in data)
        for i, p in pattern.items():
            for j, d in data.items():
                work.tick()
                if edge_match(d, p):
                    candidates.add_edge(("query", i), ("data", j))
        matched = nx.algorithms.bipartite.maximum_matching(
            candidates, top_nodes=left, backend="networkx"
        )
        return all(v in matched for v in left)

    cls = (
        nx.algorithms.isomorphism.MultiDiGraphMatcher
        if graph.directed
        else nx.algorithms.isomorphism.MultiGraphMatcher
    )
    matcher = cls(
        _multigraph(graph),
        _multigraph(query),
        node_match=node_check,
        edge_match=bundle_check,
    )
    iterator = (
        matcher.subgraph_isomorphisms_iter()
        if args["induced"]
        else matcher.subgraph_monomorphisms_iter()
    )
    rows, complete = [], True
    for mapping in iterator:
        work.tick()
        if args["result_limit"] is not None and len(rows) >= args["result_limit"]:
            complete = False
            break
        rows.append(_mapping_rows(graph, query, mapping))
        work.output(len(rows) * max(1, query.vertex_count))
    return AlgorithmOutput(
        {"matches": rows, "returned_count": len(rows), "complete": complete},
        {
            "matches": {
                "type": "vertex_mappings",
                "value": rows,
                "complete": complete,
                "query_graph_fingerprint": query.fingerprint,
            }
        },
        complete=complete,
    )


@register(
    id="motif-counting",
    problem_id="graph_motif_counting",
    family="pattern_mining",
    title="Count occurrences of supplied graph motifs",
    description="VF2 embeddings with explicit automorphism identity. Non-induced occurrences sharing a vertex set can still be different motif instances.",
    parameters={
        "motifs": P("array", required=True),
        "induced": P("boolean", False),
        "occurrence_identity": P(
            "string",
            "unique_vertex_set_and_mapping_class",
            choices=("unique_vertex_set_and_mapping_class", "all_embeddings"),
        ),
        "list_instances": P("boolean", False),
        "result_limit_per_motif": P("integer", None, minimum=1, nullable=True),
    },
)
def motifs(graph, args, work, backend="networkx"):
    if not args["motifs"]:
        raise GraphMineError("At least one connected motif is required")
    g = simple(graph, directed=True)
    counts, completeness, instances = {}, {}, {}
    total_materialized = 0
    for record in args["motifs"]:
        query = Graph(record)
        motif_id = record["graph"]["id"]
        if motif_id in counts:
            raise GraphMineError("Motif graph IDs must be unique")
        if query.directed != graph.directed:
            raise GraphMineError("Motif direction must match data graph direction")
        q = simple(query, directed=True)
        if not q or not nx.is_connected(q.to_undirected(), backend="networkx"):
            raise GraphMineError("Every motif must be nonempty and connected")
        cls = (
            nx.algorithms.isomorphism.DiGraphMatcher
            if graph.directed
            else nx.algorithms.isomorphism.GraphMatcher
        )

        def count_visit(_data, _query):
            work.tick()
            return True

        matcher = cls(g, q, node_match=count_visit)
        iterator = (
            matcher.subgraph_isomorphisms_iter()
            if args["induced"]
            else matcher.subgraph_monomorphisms_iter()
        )
        seen, rows, count = set(), [], 0
        for mapping in iterator:
            work.tick()
            if args["occurrence_identity"] != "all_embeddings":
                inverse = {v: u for u, v in mapping.items()}
                image_edges = tuple(
                    sorted(
                        (inverse[u], inverse[v])
                        if graph.directed
                        else tuple(sorted((inverse[u], inverse[v])))
                        for u, v in q.edges
                    )
                )
                key = (tuple(sorted(mapping)), image_edges)
                if key in seen:
                    continue
                seen.add(key)
            count += 1
            if args["list_instances"] and (
                args["result_limit_per_motif"] is None
                or len(rows) < args["result_limit_per_motif"]
            ):
                rows.append(_mapping_rows(graph, query, mapping))
                total_materialized += max(1, len(q))
                work.output(total_materialized)
        counts[motif_id] = count
        completeness[motif_id] = len(rows) == count
        if args["list_instances"]:
            instances[motif_id] = rows
    data = {"count_by_motif": counts, "instances_complete_by_motif": completeness}
    ports = {
        "counts": {
            "type": "table",
            "value": [{"motif": k, "count": v} for k, v in counts.items()],
            "complete": True,
        }
    }
    if args["list_instances"]:
        data["instances_by_motif"] = instances
        ports["instances"] = {
            "type": "motif_instances",
            "value": instances,
            "complete": all(completeness.values()),
        }
    return AlgorithmOutput(data, ports)


@lru_cache(maxsize=1)
def _atlas():
    return [
        (i, g)
        for i, g in enumerate(nx.graph_atlas_g())
        if len(g) >= 2 and nx.is_connected(g, backend="networkx")
    ]


def _signature(g):
    return len(g), g.number_of_edges(), tuple(sorted(d for _, d in g.degree()))


def _orbits(pattern, work):
    union = nx.utils.UnionFind(pattern.nodes)
    for mapping in nx.algorithms.isomorphism.GraphMatcher(
        pattern, pattern
    ).isomorphisms_iter():
        work.tick()
        for v, image in mapping.items():
            union.union(v, image)
    parts = sorted((sorted(s) for s in union.to_sets()), key=lambda s: s[0])
    return {v: i for i, part in enumerate(parts) for v in part}, parts


@register(
    id="graphlet-counting",
    problem_id="graphlet_counting",
    family="pattern_mining",
    title="Count connected induced graph shapes and vertex roles",
    description="Classify induced subgraphs against NetworkX's complete graph atlas through seven vertices, with optional exact automorphism-orbit participation.",
    parameters={
        "graphlet_sizes": P(
            "array",
            required=True,
            description="Unique integer sizes 2 through 7; the atlas contains every unlabeled class in that range.",
        ),
        "include_orbit_counts": P("boolean", False),
        "list_instances": P("boolean", False),
        "result_limit_per_graphlet": P("integer", None, minimum=1, nullable=True),
    },
    references=(
        "https://networkx.org/documentation/stable/reference/generated/networkx.generators.atlas.graph_atlas_g.html",
    ),
)
def graphlets(graph, args, work, backend="networkx"):
    sizes = args["graphlet_sizes"]
    if (
        not sizes
        or any(type(s) is not int or not 2 <= s <= 7 for s in sizes)
        or len(set(sizes)) != len(sizes)
    ):
        raise GraphMineError(
            "graphlet_sizes must contain distinct integer sizes from 2 through 7"
        )
    g = simple(graph)
    patterns = [
        (f"atlas-{i}", pattern) for i, pattern in _atlas() if len(pattern) in sizes
    ]
    lookup = defaultdict(list)
    dictionary, counts, instances, orbit_dictionary, orbit_maps = {}, {}, {}, {}, {}
    roles = {v: Counter() for v in g}
    for key, pattern in patterns:
        lookup[_signature(pattern)].append((key, pattern))
        canonical = Graph.from_edges(
            pattern.edges, vertices=pattern.nodes
        ).to_canonical()
        canonical["graph"]["id"] = key
        dictionary[key], counts[key], instances[key] = canonical, 0, []
        if args["include_orbit_counts"]:
            orbit_maps[key], parts = _orbits(pattern, work)
            for i, part in enumerate(parts):
                orbit_dictionary[f"{key}:orbit-{i}"] = {
                    "graphlet": key,
                    "pattern_vertices": part,
                }
    listed = 0
    for size in sorted(sizes):
        for selected in combinations(g.nodes, size):
            work.tick()
            subgraph = g.subgraph(selected)
            if not nx.is_connected(subgraph, backend="networkx"):
                continue
            classified = False
            for key, pattern in lookup[_signature(subgraph)]:
                work.tick()
                match = next(
                    nx.algorithms.isomorphism.GraphMatcher(
                        subgraph, pattern
                    ).isomorphisms_iter(),
                    None,
                )
                if match is None:
                    continue
                counts[key] += 1
                if args["include_orbit_counts"]:
                    for v, p in match.items():
                        roles[v][f"{key}:orbit-{orbit_maps[key][p]}"] += 1
                if args["list_instances"] and (
                    args["result_limit_per_graphlet"] is None
                    or len(instances[key]) < args["result_limit_per_graphlet"]
                ):
                    instances[key].append([graph.vertex_id(v) for v in selected])
                    listed += size
                    work.output(listed)
                classified = True
                break
            if not classified:
                raise GraphMineError(
                    "Connected graphlet was not present in the declared atlas"
                )
    data = {"count_by_graphlet": counts, "graphlet_dictionary": dictionary}
    ports = {
        "counts": {
            "type": "table",
            "value": [{"graphlet": k, "count": v} for k, v in counts.items()],
            "complete": True,
        }
    }
    if args["include_orbit_counts"]:
        data["orbit_dictionary"] = orbit_dictionary
        data["orbit_counts_by_vertex"] = [
            {"vertex": graph.vertex_id(v), "counts": dict(roles[v])} for v in g
        ]
    if args["list_instances"]:
        complete = {k: len(instances[k]) == v for k, v in counts.items()}
        data.update(
            instances_by_graphlet=instances, instances_complete_by_graphlet=complete
        )
        ports["instances"] = {
            "type": "graphlet_instances",
            "value": instances,
            "complete": all(complete.values()),
        }
    work.output(
        listed
        + sum(len(p) + p.number_of_edges() for _, p in patterns)
        + sum(len(v) for v in roles.values())
    )
    return AlgorithmOutput(data, ports)
