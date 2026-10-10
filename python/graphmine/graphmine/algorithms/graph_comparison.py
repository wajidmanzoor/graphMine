"""Exact graph-pair references using NetworkX matching and shortest paths.

GED is reduced to a nonnegative rational-weighted correspondence-state DAG.
This keeps small decimal costs distinct instead of converting an assignment
matrix to float64. MCIS uses VF2; the vertex-maximizing non-induced objective
also permits isolated vertices and therefore reduces to label matching.
"""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction
from itertools import combinations, pairwise

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph
from ..inputs import finite_number
from ..registry import register
from ._events import number

_PARAMETERS = {
    "other_graph": P("object", required=True),
    "label_match_policy": P("string", "exact", choices=("exact", "ignore_labels")),
    "vertex_label_fields": P(
        "array",
        ["label", "type"],
        description="Distinct selected categorical fields: label and/or type. Missing differs from empty.",
    ),
    "edge_label_fields": P(
        "array", ["type"], description="Either [type] or [] for no edge category."
    ),
    "self_loops": P("string", "drop", choices=("drop", "reject")),
    "parallel_edges": P(
        "string",
        "reject",
        choices=("reject", "collapse"),
        description="Collapse retains the first edge and requires equal selected types unless labels are ignored.",
    ),
}
_DEFAULT_COSTS = {
    name: 1
    for name in (
        "vertex_insertion",
        "vertex_deletion",
        "edge_insertion",
        "edge_deletion",
        "edge_substitution",
    )
}


def _fields(args):
    for name, allowed in (
        ("vertex_label_fields", {"label", "type"}),
        ("edge_label_fields", {"type"}),
    ):
        fields = args[name]
        if any(
            type(field) is not str or field not in allowed for field in fields
        ) or len(set(fields)) != len(fields):
            raise GraphMineError(
                f"{name} must contain distinct supported categorical fields"
            )


def _label(record, fields, ignore):
    return (
        ()
        if ignore
        else tuple(
            (field in record, json.dumps(record.get(field), ensure_ascii=False))
            for field in sorted(fields)
        )
    )


def _normalize(graph, args, work):
    raw = graph.to_canonical()
    result = (
        nx.DiGraph(backend="networkx")
        if graph.directed
        else nx.Graph(backend="networkx")
    )
    ignore = args["label_match_policy"] == "ignore_labels"
    for i, row in enumerate(raw["vertices"]):
        work.tick()
        record = {
            key: deepcopy(row[key])
            for key in ["id", *args["vertex_label_fields"]]
            if key in row
        }
        result.add_node(
            i, record=record, label=_label(row, args["vertex_label_fields"], ignore)
        )
    edges = []
    for row in raw["edges"]:
        work.tick()
        u, v = graph.index(row["source"]), graph.index(row["target"])
        if u == v:
            if args["self_loops"] == "reject":
                raise GraphMineError(
                    "The selected comparison profile rejects self-loops"
                )
            continue
        label = _label(row, args["edge_label_fields"], ignore)
        if result.has_edge(u, v):
            if args["parallel_edges"] == "reject":
                raise GraphMineError("Parallel edges require explicit collapse")
            if result[u][v]["label"] != label:
                raise GraphMineError(
                    "Cannot collapse edges with different selected types"
                )
            continue
        record = {
            key: deepcopy(row[key])
            for key in ["id", "source", "target", *args["edge_label_fields"]]
            if key in row
        }
        result.add_edge(u, v, handle=len(edges), record=record, label=label)
        edges.append((u, v, result[u][v]))
    result.graph["edge_rows"] = edges
    result.graph["metadata"] = {
        "id": raw["graph"]["id"],
        "directed": graph.directed,
        "allows_self_loops": False,
        "allows_parallel_edges": False,
    }
    return result


def _pair(graph, args, work):
    _fields(args)
    other = Graph(args["other_graph"])
    if graph.directed != other.directed:
        raise GraphMineError("Comparison graphs must have the same direction")
    return other, _normalize(graph, args, work), _normalize(other, args, work)


def _data(graph):
    return {
        "graph": deepcopy(graph.graph["metadata"]),
        "vertices": [deepcopy(graph.nodes[v]["record"]) for v in graph],
        "edges": [deepcopy(data["record"]) for _, _, data in graph.graph["edge_rows"]],
    }


def _label_matching(a, b, work):
    pairs = nx.Graph(backend="networkx")
    left = [(0, u) for u in a]
    pairs.add_nodes_from(left)
    pairs.add_nodes_from((1, v) for v in b)
    for u in a:
        for v in b:
            work.tick()
            if a.nodes[u]["label"] == b.nodes[v]["label"]:
                pairs.add_edge((0, u), (1, v))
    result = nx.bipartite.maximum_matching(pairs, top_nodes=left, backend="networkx")
    work.tick(0)
    return {u: result[(0, u)][1] for u in a if (0, u) in result}


def _matcher(host, pattern, work):
    def match(first, second):
        work.tick()
        return first["label"] == second["label"]

    cls = (
        nx.isomorphism.DiGraphMatcher
        if host.is_directed()
        else nx.isomorphism.GraphMatcher
    )
    return cls(host, pattern, node_match=match, edge_match=match)


def _costs(value):
    if set(value) - set(_DEFAULT_COSTS):
        raise GraphMineError(
            "edit_costs accepts vertex_insertion/deletion and edge_insertion/deletion/substitution. Exact vertex-label replacement costs insertion+deletion; an independent vertex_substitution cost is unsupported."
        )
    return {
        name: Fraction(
            str(finite_number(value.get(name, default), name, nonnegative=True))
        )
        for name, default in _DEFAULT_COSTS.items()
    }


def _node_cost(a, b, u, v, costs):
    return (
        Fraction()
        if a.nodes[u]["label"] == b.nodes[v]["label"]
        else costs["vertex_insertion"] + costs["vertex_deletion"]
    )


def _edge_cost(first, second, costs):
    if first is None:
        return costs["edge_insertion"] if second is not None else Fraction()
    if second is None:
        return costs["edge_deletion"]
    return (
        Fraction()
        if first["label"] == second["label"]
        else min(
            costs["edge_substitution"], costs["edge_deletion"] + costs["edge_insertion"]
        )
    )


def _mapping_cost(a, b, mapping, costs):
    value = (len(a) - len(mapping)) * costs["vertex_deletion"]
    value += (len(b) - len(mapping)) * costs["vertex_insertion"]
    value += sum(
        (_node_cost(a, b, u, v, costs) for u, v in mapping.items()), Fraction()
    )
    covered = set()
    for u, v, first in a.graph["edge_rows"]:
        second = (
            b.get_edge_data(mapping[u], mapping[v])
            if u in mapping and v in mapping
            else None
        )
        value += _edge_cost(first, second, costs)
        if second is not None:
            covered.add(second["handle"])
    value += sum(
        costs["edge_insertion"]
        for _, _, data in b.graph["edge_rows"]
        if data["handle"] not in covered
    )
    return value


def _edit_optimum(a, b, costs, work):
    # A label-compatible matching supplies a feasible incumbent. If both graphs
    # are edgeless, it is also optimal for the specified replacement cost.
    incumbent = _label_matching(a, b, work)
    upper = _mapping_cost(a, b, incumbent, costs)
    if not upper or not a.graph["edge_rows"] and not b.graph["edge_rows"]:
        return incumbent, upper, {"method": "NetworkX label matching", "states": 0}
    if len(a) == len(b):
        same = next(_matcher(a, b, work).isomorphisms_iter(), None)
        if same is not None:
            return (
                same,
                Fraction(),
                {"method": "NetworkX VF2 zero-cost isomorphism", "states": 0},
            )
    search = nx.DiGraph(backend="networkx")
    # A direct source-to-sink arc represents the feasible incumbent. Every other
    # complete path assigns each A vertex either a distinct B image or deletion.
    search.add_edge(0, 1, weight=upper)
    frontier, serial = [(0, (), 0, Fraction())], 2
    for u in a:
        following = []
        for parent, prefix, used, value in frontier:
            for v in [None, *(v for v in b if not used & (1 << v))]:
                work.tick(1 + len(prefix) * (2 if a.is_directed() else 1))
                increment = (
                    costs["vertex_deletion"]
                    if v is None
                    else _node_cost(a, b, u, v, costs)
                )
                for old, image in enumerate(prefix):
                    pairs = (
                        ((u, old, v, image), (old, u, image, v))
                        if a.is_directed()
                        else ((u, old, v, image),)
                    )
                    for x, y, p, q in pairs:
                        first = a.get_edge_data(x, y)
                        second = (
                            b.get_edge_data(p, q)
                            if p is not None and q is not None
                            else None
                        )
                        increment += _edge_cost(first, second, costs)
                total = value + increment
                if total >= upper:
                    continue  # All remaining arc weights are nonnegative.
                search.add_edge(parent, serial, weight=increment, vertex=u, image=v)
                following.append(
                    (
                        serial,
                        prefix + (v,),
                        used if v is None else used | (1 << v),
                        total,
                    )
                )
                serial += 1
        frontier = following
    for state, _, used, value in frontier:
        work.tick(1 + len(b.graph["edge_rows"]))
        terminal = (len(b) - used.bit_count()) * costs["vertex_insertion"]
        terminal += sum(
            costs["edge_insertion"]
            for u, v, _ in b.graph["edge_rows"]
            if not (used & (1 << u) and used & (1 << v))
        )
        if value + terminal < upper:
            search.add_edge(state, 1, weight=terminal)

    def weight(u, v, data):
        work.tick()
        return data["weight"]

    value, path = nx.single_source_dijkstra(
        search, 0, target=1, weight=weight, backend="networkx"
    )
    if path == [0, 1]:
        return (
            incumbent,
            upper,
            {
                "method": "NetworkX Dijkstra on rational correspondence DAG",
                "states": serial,
            },
        )
    mapping = {}
    for parent, child in pairwise(path[:-1]):
        transition = search[parent][child]
        if transition["image"] is not None:
            mapping[transition["vertex"]] = transition["image"]
    if value != _mapping_cost(a, b, mapping, costs):
        raise GraphMineError(
            "Edit-state objective disagrees with the returned correspondence"
        )
    return (
        mapping,
        value,
        {
            "method": "NetworkX Dijkstra on rational correspondence DAG",
            "states": serial,
        },
    )


def _edit_script(a, b, mapping, costs, work):
    """Stable handles avoid collisions while external vertex IDs are replaced.

    Delete incident edges before deleting vertices; create all required vertices
    before inserting edges. Reidentification and ignored labels have zero cost.
    """
    operations, retained, covered = [], [], set()

    def emit(kind, cost, **fields):
        work.output(len(operations) + 1)
        operations.append(
            {
                "operation": kind,
                **fields,
                "cost": number(cost),
                "cost_numerator": cost.numerator,
                "cost_denominator": cost.denominator,
            }
        )

    for u, v, first in a.graph["edge_rows"]:
        second = (
            b.get_edge_data(mapping[u], mapping[v])
            if u in mapping and v in mapping
            else None
        )
        split = (
            second is not None
            and first["label"] != second["label"]
            and costs["edge_substitution"]
            > costs["edge_deletion"] + costs["edge_insertion"]
        )
        if second is None or split:
            emit("edge_deletion", costs["edge_deletion"], edge_handle=first["handle"])
        else:
            retained.append((first, second))
            covered.add(second["handle"])
    for u in a:
        if u not in mapping:
            emit("vertex_deletion", costs["vertex_deletion"], vertex_handle=u)
    b_handles = {v: u for u, v in mapping.items()}
    for u, v in mapping.items():
        emit(
            "vertex_substitution",
            _node_cost(a, b, u, v, costs),
            vertex_handle=u,
            vertex_record=deepcopy(b.nodes[v]["record"]),
        )
    for v in b:
        if v not in b_handles:
            b_handles[v] = len(a) + v
            emit(
                "vertex_insertion",
                costs["vertex_insertion"],
                vertex_handle=b_handles[v],
                vertex_record=deepcopy(b.nodes[v]["record"]),
            )

    target_ids = {b.nodes[v]["record"]["id"]: b_handles[v] for v in b}

    def target_record(data):
        row = deepcopy(data["record"])
        # The source/target fields of an operation refer to stable handles.
        row["source"], row["target"] = (
            target_ids[row["source"]],
            target_ids[row["target"]],
        )
        return row

    for first, second in retained:
        emit(
            "edge_substitution",
            _edge_cost(first, second, costs),
            edge_handle=first["handle"],
            edge_record=target_record(second),
        )
    for _, _, second in b.graph["edge_rows"]:
        if second["handle"] not in covered:
            emit(
                "edge_insertion",
                costs["edge_insertion"],
                edge_handle=len(a.graph["edge_rows"]) + second["handle"],
                edge_record=target_record(second),
            )
    return operations


@register(
    id="graph-edit-distance",
    problem_id="graph_edit_distance_mcs",
    family="comparison",
    title="Minimum graph edit cost",
    description="Exact reference edit distance between simple directed/undirected graphs using NetworkX rational shortest paths over partial correspondences. Exact vertex-label replacement costs insertion+deletion; equal selected labels cost zero. Edge relabeling competes with deletion+insertion. Weights/times/unselected attributes are ignored. Returns an ordered edit script on normalized graphs with stable handles and original IDs. Exponential work is budgeted; no timed-out or approximate result is advertised as optimal.",
    parameters={
        **_PARAMETERS,
        "edit_costs": P(
            "object",
            {},
            description="Optional nonnegative decimal costs: vertex_insertion, vertex_deletion, edge_insertion, edge_deletion, edge_substitution. Each defaults to 1. Vertex-label replacement is their insertion+deletion sum, so independent vertex_substitution is not accepted.",
        ),
    },
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.weighted.single_source_dijkstra.html",
    ),
)
def graph_edit_distance(graph, args, work, backend):
    other, a, b = _pair(graph, args, work)
    costs = _costs(args["edit_costs"])
    mapping, value, diagnostics = _edit_optimum(a, b, costs, work)
    script = _edit_script(a, b, mapping, costs, work)
    displayed = number(value)
    if (
        sum(
            (
                Fraction(row["cost_numerator"], row["cost_denominator"])
                for row in script
            ),
            Fraction(),
        )
        != value
    ):
        raise GraphMineError("Ordered edit script does not realize the optimum cost")
    rows = [
        {"graph_a_vertex": graph.vertex_id(u), "graph_b_vertex": other.vertex_id(v)}
        for u, v in sorted(mapping.items())
    ]
    rows += [
        {"graph_a_vertex": graph.vertex_id(u), "graph_b_vertex": None}
        for u in a
        if u not in mapping
    ]
    images = set(mapping.values())
    rows += [
        {"graph_a_vertex": None, "graph_b_vertex": other.vertex_id(v)}
        for v in b
        if v not in images
    ]
    work.output(
        len(script)
        + len(rows)
        + len(a)
        + len(b)
        + len(a.graph["edge_rows"])
        + len(b.graph["edge_rows"])
    )
    return AlgorithmOutput(
        {
            "task": "graph_edit_distance",
            "task_result": {
                "distance": displayed,
                "distance_numerator": value.numerator,
                "distance_denominator": value.denominator,
            },
            "optimal": True,
            "vertex_correspondence": rows,
            "edit_path": script,
            "normalized_source": _data(a),
            "normalized_target": _data(b),
            "source_vertex_handles": [
                {"vertex_handle": u, "vertex": graph.vertex_id(u)} for u in a
            ],
            "source_edge_handles": [
                {"edge_handle": data["handle"], "edge": data["record"]["id"]}
                for _, _, data in a.graph["edge_rows"]
            ],
        },
        {
            "distance": {
                "type": "rational_scalar",
                "value": {
                    "numerator": value.numerator,
                    "denominator": value.denominator,
                    "display": displayed,
                    "display_is_exact": value.denominator == 1
                    or Fraction(str(displayed)) == value,
                },
                "complete": True,
            },
            "mapping": {
                "type": "cross_graph_mapping",
                "value": rows,
                "complete": True,
                "other_graph_fingerprint": other.fingerprint,
            },
            "edits": {"type": "table", "value": script, "complete": True},
        },
        diagnostics={
            **diagnostics,
            "other_graph_fingerprint": other.fingerprint,
            "arithmetic": "exact decimal rational; displayed distance may be rounded",
            "vertex_substitution": "zero for equal/ignored labels; insertion+deletion otherwise",
            "witness_namespace": "vertex_handle and edge_handle identify stable source/insertion slots; external IDs are record data until final serialization",
        },
    )


@register(
    id="maximum-common-subgraph",
    problem_id="graph_edit_distance_mcs",
    family="comparison",
    title="Largest common subgraph by vertex count",
    description="Exact maximum vertex count, with a checked graph and injective correspondence. Induced matching uses NetworkX VF2 on successively smaller subsets. Non-induced matching permits disconnected/edgeless results and uses maximum label-compatible matching; it does not maximize the number of edges. Preserves direction and selected categorical labels; ignores weights/times. Exponential induced search is budgeted.",
    parameters={**_PARAMETERS, "induced": P("boolean", True)},
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/isomorphism.vf2.html",
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.bipartite.matching.hopcroft_karp_matching.html",
    ),
)
def maximum_common_subgraph(graph, args, work, backend):
    other, a, b = _pair(graph, args, work)
    mapping = _label_matching(a, b, work)
    upper = len(mapping)
    if args["induced"]:
        mapping = {}
        smaller, host = (a, b) if len(a) <= len(b) else (b, a)
        for size in range(upper, 0, -1):
            for vertices in combinations(smaller, size):
                work.tick()
                matched = next(
                    _matcher(
                        host, smaller.subgraph(vertices), work
                    ).subgraph_isomorphisms_iter(),
                    None,
                )
                if matched is not None:
                    mapping = (
                        {u: v for v, u in matched.items()} if smaller is a else matched
                    )
                    break
            if mapping:
                break
    if len(set(mapping.values())) != len(mapping) or any(
        a.nodes[u]["label"] != b.nodes[v]["label"] for u, v in mapping.items()
    ):
        raise GraphMineError("Common-subgraph mapping violates vertex eligibility")
    rows = [
        {"graph_a_vertex": graph.vertex_id(u), "graph_b_vertex": other.vertex_id(v)}
        for u, v in sorted(mapping.items())
    ]
    edges = []
    for u, v, data in a.graph["edge_rows"]:
        if u in mapping and v in mapping:
            counterpart = b.get_edge_data(mapping[u], mapping[v])
            if counterpart is not None and data["label"] == counterpart["label"]:
                edges.append(deepcopy(data["record"]))
            elif args["induced"]:
                raise GraphMineError("Induced common-subgraph edge mismatch")
    if args["induced"]:
        reverse = {v: u for u, v in mapping.items()}
        if any(
            u in reverse and v in reverse and not a.has_edge(reverse[u], reverse[v])
            for u, v, _ in b.graph["edge_rows"]
        ):
            raise GraphMineError("Induced common-subgraph nonedge mismatch")
    common = {
        "graph": {
            **a.graph["metadata"],
            # Original A vertex IDs remain in this graph. Include both parents
            # so unrelated comparisons cannot share their vertex namespace.
            "id": f"common-subgraph:{graph.fingerprint}:{other.fingerprint}",
        },
        "vertices": [deepcopy(a.nodes[u]["record"]) for u in sorted(mapping)],
        "edges": edges,
    }
    Graph(common)
    work.output(2 * len(mapping) + len(edges))
    return AlgorithmOutput(
        {
            "task": "maximum_common_subgraph",
            "task_result": {
                "subgraph": common,
                "vertex_count": len(mapping),
                "edge_count": len(edges),
            },
            "vertex_correspondence": rows,
            "optimal": True,
        },
        {
            "graph": {"type": "graph", "value": common, "complete": True},
            "mapping": {
                "type": "cross_graph_mapping",
                "value": rows,
                "complete": True,
                "other_graph_fingerprint": other.fingerprint,
            },
            "size": {"type": "scalar", "value": len(mapping), "complete": True},
        },
        diagnostics={
            "method": "NetworkX VF2 induced-subset search"
            if args["induced"]
            else "NetworkX maximum label-compatible matching",
            "objective": "maximum vertex count; no edge-count tie objective",
            "label_matching_upper_bound": upper,
            "other_graph_fingerprint": other.fingerprint,
            "candidates": work.candidates,
        },
    )
