"""Closed record queries over canonical graphs; no query language or code eval."""

from __future__ import annotations

import math
from collections import deque
from copy import deepcopy
from fractions import Fraction

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph, external_id
from ..registry import register

_MISSING = object()
_SCALAR = {"type": ["string", "integer", "number", "boolean", "null"]}
FILTER_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "field": {"type": "string", "minLength": 1},
            "op": {
                "enum": [
                    "eq",
                    "ne",
                    "lt",
                    "lte",
                    "gt",
                    "gte",
                    "in",
                    "not_in",
                    "contains",
                    "exists",
                ]
            },
            "value": {"anyOf": [_SCALAR, {"type": "array", "items": _SCALAR}]},
        },
        "required": ["field", "op", "value"],
        "additionalProperties": False,
    },
}


def _scalar(value):
    if type(value) not in (str, int, float, bool, type(None)) or (
        type(value) is float and not math.isfinite(value)
    ):
        raise GraphMineError("Filter values must be finite JSON scalars")


def _field_name(value):
    if not isinstance(value, str) or not value or any(not p for p in value.split(".")):
        raise GraphMineError("A field must be a nonempty dotted record path")


def validate_filters(filters):
    if not isinstance(filters, list):
        raise GraphMineError("Filters must be an array")
    for rule in filters:
        if not isinstance(rule, dict) or set(rule) != {"field", "op", "value"}:
            raise GraphMineError("Every filter needs exactly field, op and value")
        _field_name(rule["field"])
        op, value = rule["op"], rule["value"]
        if op not in FILTER_SCHEMA["items"]["properties"]["op"]["enum"]:
            raise GraphMineError("Unknown filter operator")
        if op in ("in", "not_in"):
            if not isinstance(value, list):
                raise GraphMineError("Membership filters require an array value")
            for item in value:
                _scalar(item)
        else:
            _scalar(value)
        if op == "exists" and type(value) is not bool:
            raise GraphMineError("exists requires a boolean value")
        if op in ("lt", "lte", "gt", "gte") and type(value) not in (str, int, float):
            raise GraphMineError("Ordered filters require a string or number")
        if rule["field"] in {"id", "source", "target"} and op != "exists":
            if op == "contains":
                raise GraphMineError("IDs support exact comparisons, not contains")
            for item in value if op in ("in", "not_in") else [value]:
                external_id(item)


FILTERS = P(
    "array",
    [],
    validator=validate_filters,
    json_schema=FILTER_SCHEMA,
    description="AND of {field, op, value} predicates. Use explicit paths such as attributes.amount. Missing fields never match except exists=false; ID types are preserved.",
)
LIMIT = P(
    "integer",
    None,
    minimum=1,
    nullable=True,
    description="Optional retained-row cap. All matches are counted; capped collections are incomplete and cannot feed a downstream step.",
)
DIRECTION = P(
    "string",
    "out",
    choices=("out", "in", "both"),
    description="Traversal or per-vertex edge direction. Undirected edges are traversable both ways; self-loops count once per vertex.",
)


def _index(graph):
    # Graph has no mutation API. This private cache belongs to its immutable
    # canonical snapshot, not to a graph name or a mutable caller dictionary.
    cached = getattr(graph, "_query_record_index", None)
    if cached is None:
        data = graph.to_canonical()
        vertices = {v["id"]: v for v in data["vertices"]}
        edges = {e["id"]: e for e in data["edges"]}
        outgoing, incoming = {v: [] for v in vertices}, {v: [] for v in vertices}
        for edge in data["edges"]:
            outgoing[edge["source"]].append(edge)
            incoming[edge["target"]].append(edge)
        cached = (data, vertices, edges, outgoing, incoming)
        graph._query_record_index = cached
    return cached


def field_value(row, field):
    value = row
    for key in field.split("."):
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _key(value):
    _scalar(value)
    if type(value) in (int, float):
        return ("number", Fraction(str(value)))
    return (type(value).__name__, value)


def _matches(row, filters):
    for rule in filters:
        value, wanted, op = field_value(row, rule["field"]), rule["value"], rule["op"]
        if op == "exists":
            match = (value is not _MISSING) == wanted
        elif value is _MISSING:
            match = False
        elif op == "contains":
            match = (
                type(value) is str and type(wanted) is str and wanted in value
            ) or (
                isinstance(value, list)
                and any(
                    type(v) in (str, int, float, bool, type(None))
                    and _key(v) == _key(wanted)
                    for v in value
                )
            )
        elif type(value) not in (str, int, float, bool, type(None)):
            match = False
        elif op in ("eq", "ne", "in", "not_in"):
            match = any(
                _key(value) == _key(v)
                for v in (wanted if op in ("in", "not_in") else [wanted])
            )
            if op in ("ne", "not_in"):
                match = not match
        else:
            left, right = _key(value), _key(wanted)
            if left[0] != right[0] or left[0] not in {"number", "str"}:
                match = False
            else:
                match = {
                    "lt": left[1] < right[1],
                    "lte": left[1] <= right[1],
                    "gt": left[1] > right[1],
                    "gte": left[1] >= right[1],
                }[op]
        if not match:
            return False
    return True


def _check_field(records, field, kind, *, allow_absent=False):
    _field_name(field)
    base = (
        {"id", "label", "type", "attributes"}
        if kind == "vertices"
        else {"id", "source", "target", "weight", "timestamp", "type", "attributes"}
    )
    if field in base:
        return
    if not field.startswith("attributes."):
        raise GraphMineError(f"Unknown {kind} field: {field}")
    # An empty derived scope has no record from which to infer domain fields.
    # A well-formed attribute predicate still has the exact empty answer; it
    # must not turn an empty predecessor into a failed workflow.
    if not records:
        return
    if not allow_absent and not any(
        field_value(row, field) is not _MISSING for row in records
    ):
        raise GraphMineError(f"Unknown {kind} field: {field}")


def _check_filters(records, filters, kind):
    validate_filters(filters)
    for rule in filters:
        _check_field(records, rule["field"], kind, allow_absent=rule["op"] == "exists")


def validate_query_input(graph, args):
    data, vertices, edges, _, _ = _index(graph)
    for name in ("source", "target", "entity"):
        if name in args and args[name] is not None:
            graph.index(args[name])
    for name in ("vertices", "edge_ids"):
        if args.get(name) is not None:
            known = vertices if name == "vertices" else edges
            for value in args[name]:
                if external_id(value) not in known:
                    raise GraphMineError(f"Unknown ID in {name}: {value!r}")
    for name, kind in (
        ("vertex_filters", "vertices"),
        ("source_filters", "vertices"),
        ("target_filters", "vertices"),
        ("edge_filters", "edges"),
    ):
        if name in args:
            _check_filters(data[kind], args[name], kind)
    if "scope" in args:
        kind = args["scope"]
        if args.get("direction", "out") != "out" and (
            kind != "edges" or args.get("group_by") != "vertex"
        ):
            raise GraphMineError(
                "direction applies only to per-vertex edge aggregation"
            )
        if "filters" in args:
            _check_filters(data[kind], args["filters"], kind)
        if args.get("field") is not None:
            _check_field(data[kind], args["field"], kind)
        if (
            args.get("metric") not in (None, "count")
            and "field" in args
            and args["field"] is None
        ):
            raise GraphMineError("Numeric aggregation requires an explicit field")
        if args.get("metric") == "count" and args.get("field") is not None:
            raise GraphMineError("count counts records; omit field")
        if args.get("group_by") not in (None, "vertex"):
            _check_field(data[kind], args["group_by"], kind)
        for row in data[kind]:
            if not _matches(row, args.get("filters", [])):
                continue
            if (
                args.get("metric") not in (None, "count")
                and args.get("field") is not None
                and type(field_value(row, args["field"])) not in (int, float)
            ):
                raise GraphMineError(
                    "Every matched record needs a finite numeric aggregate field"
                )
            if args.get("group_by") not in (None, "vertex"):
                value = field_value(row, args["group_by"])
                if value is _MISSING:
                    raise GraphMineError(
                        "Every matched record needs the explicit group_by field"
                    )
                _scalar(value)
    if (
        args.get("mode") == "vertices"
        and "vertices" in args
        and args["vertices"] is None
    ):
        raise GraphMineError(
            "Vertex-induced extraction requires an explicit vertices array"
        )
    if (
        args.get("mode") == "neighborhood"
        and "entity" in args
        and args["entity"] is None
    ):
        raise GraphMineError("Neighborhood extraction requires an explicit entity")
    if args.get("mode") in ("vertices", "edges") and (
        args.get("entity") is not None
        or args.get("hops", 1) != 1
        or args.get("direction", "out") != "out"
    ):
        raise GraphMineError(
            "entity, hops and direction apply only to neighborhood extraction"
        )
    if args.get("mode") == "neighborhood" and args.get("vertices") is not None:
        raise GraphMineError(
            "Use vertices mode for an explicit vertex list; neighborhood mode uses entity and hops"
        )


def _register(id, title, description, parameters):
    return register(
        id=id,
        problem_id="graph_record_queries",
        family="query",
        title=title,
        description=description,
        parameters=parameters,
        library="python",
        input_validator=validate_query_input,
    )


def _port(kind, value, complete=True, **extra):
    return {"type": kind, "value": value, "complete": complete, **extra}


def _collect(rows, args, work):
    retained, total = [], 0
    for row in rows:
        work.tick()
        total += 1
        if args["result_limit"] is None or len(retained) < args["result_limit"]:
            work.output(len(retained) + 1)
            retained.append(deepcopy(row))
    return retained, total, len(retained) == total


def _result(rows, total, complete, ports):
    return AlgorithmOutput(
        {"rows": rows, "matched_count": total, "returned_count": len(rows)},
        {
            "rows": _port("table", rows, complete),
            "count": _port("scalar", total),
            **ports,
        },
        complete=complete,
        diagnostics={}
        if complete
        else {
            "narrowing_hint": "Add field filters or select a smaller neighborhood, or increase result_limit. Incomplete collections cannot supply later steps."
        },
    )


@_register(
    "node-lookup",
    "Look up entities",
    "Select original vertex records by typed IDs and AND predicates; no fuzzy name matching. An explicit empty IDs array selects nothing.",
    {
        "vertices": P("array", None, nullable=True),
        "vertex_filters": FILTERS,
        "result_limit": LIMIT,
    },
)
def node_lookup(graph, args, work, backend="python"):
    data = _index(graph)[0]
    selected = None if args["vertices"] is None else set(args["vertices"])

    def matches():
        for row in data["vertices"]:
            work.tick()
            if (selected is None or row["id"] in selected) and _matches(
                row, args["vertex_filters"]
            ):
                yield row

    rows, total, complete = _collect(matches(), args, work)
    return _result(
        rows,
        total,
        complete,
        {
            "vertices": _port("vertex_set", [v["id"] for v in rows], complete),
            "rows": _port("table", rows, complete, vertex_field="id"),
        },
    )


def _filtered_edges(graph, args, work):
    data, vertices, _, _, _ = _index(graph)
    selected = None if args.get("edge_ids") is None else set(args["edge_ids"])
    for edge in data["edges"]:
        work.tick()
        if (
            (selected is None or edge["id"] in selected)
            and _matches(edge, args.get("edge_filters", []))
            and _matches(vertices[edge["source"]], args.get("source_filters", []))
            and _matches(vertices[edge["target"]], args.get("target_filters", []))
        ):
            yield edge


@_register(
    "edge-filter",
    "Filter relationships",
    "Select original relationship records without collapsing parallel edges or loops. Endpoint predicates use the stored source/target even on undirected inputs.",
    {
        "edge_ids": P("array", None, nullable=True),
        "edge_filters": FILTERS,
        "source_filters": FILTERS,
        "target_filters": FILTERS,
        "result_limit": LIMIT,
    },
)
def edge_filter(graph, args, work, backend="python"):
    rows, total, complete = _collect(_filtered_edges(graph, args, work), args, work)
    vertices = {v for row in rows for v in (row["source"], row["target"])}
    return _result(
        rows,
        total,
        complete,
        {
            "edges": _port("edge_ids", [row["id"] for row in rows], complete),
            "vertices": _port(
                "vertex_set", [v for v in graph.node_ids if v in vertices], complete
            ),
        },
    )


def _adjacency(graph, args, work):
    _, vertices, _, outgoing, incoming = _index(graph)
    result = {v: [] for v in vertices}
    direction = args["direction"] if graph.directed else "both"
    selected_edges = None if args.get("edge_ids") is None else set(args["edge_ids"])
    for vertex in vertices:
        work.tick()
        seen = set()
        for rows in (
            [outgoing[vertex]]
            if direction == "out"
            else [incoming[vertex]]
            if direction == "in"
            else [outgoing[vertex], incoming[vertex]]
        ):
            for edge in rows:
                work.tick()
                if (
                    edge["id"] not in seen
                    and (selected_edges is None or edge["id"] in selected_edges)
                    and _matches(edge, args["edge_filters"])
                ):
                    seen.add(edge["id"])
                    other = (
                        edge["target"] if edge["source"] == vertex else edge["source"]
                    )
                    result[vertex].append((other, edge["id"]))
    return result


def _distances(adj, entity, hops, work):
    distances, queue = {entity: 0}, deque([entity])
    while queue:
        vertex = queue.popleft()
        if distances[vertex] >= hops:
            continue
        for other, _ in adj[vertex]:
            work.tick()
            if other not in distances:
                distances[other] = distances[vertex] + 1
                queue.append(other)
    return distances


@_register(
    "neighbors",
    "Find nearby entities",
    "Find vertices reachable within hops over filtered relationships, with exact hop distances. Parallel edges do not duplicate vertices; include_seed controls the starting vertex.",
    {
        "entity": P("vertex_id", required=True),
        "hops": P("integer", 1, minimum=0),
        "direction": DIRECTION,
        "edge_filters": FILTERS,
        "include_seed": P("boolean", False),
        "result_limit": LIMIT,
    },
)
def neighbors(graph, args, work, backend="python"):
    distances = _distances(
        _adjacency(graph, args, work), args["entity"], args["hops"], work
    )
    rows, total, complete = _collect(
        (
            {"vertex": v, "distance": distances[v]}
            for v in graph.node_ids
            if v in distances and (args["include_seed"] or v != args["entity"])
        ),
        args,
        work,
    )
    return _result(
        rows,
        total,
        complete,
        {"vertices": _port("vertex_set", [row["vertex"] for row in rows], complete)},
    )


@_register(
    "common-neighbors",
    "Find shared neighbors",
    "Intersect the direct neighbor sets of two typed entities in the requested direction. Self-loops retain their adjacency meaning.",
    {
        "source": P("vertex_id", required=True),
        "target": P("vertex_id", required=True),
        "direction": DIRECTION,
        "edge_filters": FILTERS,
        "result_limit": LIMIT,
    },
)
def common_neighbors(graph, args, work, backend="python"):
    adj = _adjacency(graph, args, work)
    shared = {v for v, _ in adj[args["source"]]} & {v for v, _ in adj[args["target"]]}
    rows, total, complete = _collect(
        ({"vertex": v} for v in graph.node_ids if v in shared), args, work
    )
    return _result(
        rows,
        total,
        complete,
        {"vertices": _port("vertex_set", [row["vertex"] for row in rows], complete)},
    )


@_register(
    "query-paths",
    "Find connections between two entities",
    "Enumerate all hop-shortest or all vertex-simple paths within max_hops, preserving edge IDs and parallel-edge alternatives. This is unweighted hop length, not minimum weight.",
    {
        "source": P("vertex_id", required=True),
        "target": P("vertex_id", required=True),
        "mode": P("string", "shortest", choices=("shortest", "all_simple")),
        "max_hops": P("integer", 3, minimum=0),
        "direction": DIRECTION,
        "edge_filters": FILTERS,
        "result_limit": LIMIT,
    },
)
def query_paths(graph, args, work, backend="python"):
    adj = _adjacency(graph, args, work)
    source, target = args["source"], args["target"]
    max_hops = min(args["max_hops"], max(0, graph.vertex_count - 1))
    distances = _distances(adj, source, max_hops, work)

    def paths():
        if target not in distances:
            return
        if source == target:
            yield {"vertices": [source], "edges": [], "hops": 0}
            return
        limit = distances[target] if args["mode"] == "shortest" else max_hops
        vertices, edges, visited = [source], [], {source}
        stack = [iter(adj[source])]
        while stack:
            try:
                other, edge = next(stack[-1])
            except StopIteration:
                stack.pop()
                visited.remove(vertices.pop())
                if edges:
                    edges.pop()
                continue
            work.tick()
            if other in visited or len(edges) >= limit:
                continue
            if args["mode"] == "shortest" and distances[other] != len(edges) + 1:
                continue
            if other == target:
                yield {
                    "vertices": [*vertices, other],
                    "edges": [*edges, edge],
                    "hops": len(edges) + 1,
                }
            elif len(edges) + 1 < limit:
                vertices.append(other)
                edges.append(edge)
                visited.add(other)
                stack.append(iter(adj[other]))

    rows, total, complete = _collect(paths(), args, work)
    vertices = {v for row in rows for v in row["vertices"]}
    edges = {e for row in rows for e in row["edges"]}
    return _result(
        rows,
        total,
        complete,
        {
            "vertices": _port(
                "vertex_set", [v for v in graph.node_ids if v in vertices], complete
            ),
            "edges": _port(
                "edge_ids", [e for e in _index(graph)[2] if e in edges], complete
            ),
        },
    )


def _rational(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def _display(value):
    if value is None:
        return None, None, False
    if value.denominator == 1:
        return value.numerator, _rational(value), False
    try:
        display = float(value)
    except OverflowError as exc:
        raise GraphMineError(
            "Aggregate cannot be displayed as a finite JSON number"
        ) from exc
    if not math.isfinite(display):
        raise GraphMineError("Aggregate cannot be displayed as a finite JSON number")
    return display, _rational(value), Fraction.from_float(display) != value


@_register(
    "graph-aggregate",
    "Summarize recorded values",
    "Count records or sum/average/min/max an explicit numeric field, grouped by a field or vertex. Decimal arithmetic is exact in exact_value; value may be rounded. Missing numeric fields are errors. Per-vertex edge groups include isolates and count loops once.",
    {
        "scope": P("string", "edges", choices=("vertices", "edges")),
        "filters": FILTERS,
        "metric": P("string", "count", choices=("count", "sum", "avg", "min", "max")),
        "field": P("string", None, nullable=True),
        "group_by": P(
            "string",
            None,
            nullable=True,
            description="A record field, vertex for per-vertex groups, or null for one overall group. Edge source/target group by stored endpoints; vertex uses direction.",
        ),
        "direction": DIRECTION,
        "order": P("string", "input", choices=("input", "ascending", "descending")),
        "result_limit": LIMIT,
    },
)
def aggregate(graph, args, work, backend="python"):
    data = _index(graph)[0]
    vertex_groups = args["group_by"] == "vertex"
    buckets = {}
    if vertex_groups and args["scope"] == "edges":
        buckets = {
            (type(v).__name__, v): {
                "group": v,
                "count": 0,
                "sum": Fraction(0),
                "min": None,
                "max": None,
            }
            for v in graph.node_ids
        }
    elif args["group_by"] is None:
        buckets[None] = {
            "group": None,
            "count": 0,
            "sum": Fraction(0),
            "min": None,
            "max": None,
        }
    for record in data[args["scope"]]:
        work.tick()
        if not _matches(record, args["filters"]):
            continue
        if vertex_groups:
            if args["scope"] == "vertices":
                keys = [record["id"]]
            else:
                direction = args["direction"] if graph.directed else "both"
                keys = (
                    [record["source"]]
                    if direction == "out"
                    else [record["target"]]
                    if direction == "in"
                    else list(dict.fromkeys([record["source"], record["target"]]))
                )
        elif args["group_by"] is None:
            keys = [None]
        else:
            value = field_value(record, args["group_by"])
            if value is _MISSING:
                raise GraphMineError(
                    "Every matched record needs the explicit group_by field"
                )
            _scalar(value)
            keys = [value]
        value = Fraction(1)
        if args["metric"] != "count":
            raw = field_value(record, args["field"])
            if type(raw) not in (int, float):
                raise GraphMineError(
                    "Every matched record needs a finite numeric aggregate field"
                )
            value = Fraction(str(raw))
        for group in keys:
            key = (type(group).__name__, group) if vertex_groups else _key(group)
            if args["group_by"] is None:
                key = None
            bucket = buckets.setdefault(
                key,
                {
                    "group": group,
                    "count": 0,
                    "sum": Fraction(0),
                    "min": None,
                    "max": None,
                },
            )
            bucket["count"] += 1
            bucket["sum"] += value
            bucket["min"] = (
                value if bucket["min"] is None else min(value, bucket["min"])
            )
            bucket["max"] = (
                value if bucket["max"] is None else max(value, bucket["max"])
            )
    rows = []
    for bucket in buckets.values():
        work.tick()
        metric = args["metric"]
        value = (
            Fraction(bucket["count"])
            if metric == "count"
            else bucket["sum"]
            if metric == "sum"
            else bucket["sum"] / bucket["count"]
            if metric == "avg" and bucket["count"]
            else None
            if metric == "avg"
            else bucket[metric]
        )
        display, exact, rounded = _display(value)
        rows.append(
            {
                "vertex" if vertex_groups else "group": bucket["group"],
                "value": display,
                "exact_value": exact,
                "rounded": rounded,
                "record_count": bucket["count"],
            }
        )
        work.output(len(rows))
    if args["order"] != "input":

        def order_key(row):
            exact = row["exact_value"]
            value = Fraction(exact["numerator"], exact["denominator"]) if exact else 0
            return (exact is None, -value if args["order"] == "descending" else value)

        rows.sort(key=order_key)
    rows, total, complete = _collect(rows, args, work)
    ports = (
        {
            "scores": _port(
                "vertex_scores",
                rows,
                complete,
                score_field="value",
                exact_score_field="exact_value",
            )
        }
        if vertex_groups
        else {}
    )
    return _result(rows, total, complete, ports)


@_register(
    "query-subgraph",
    "Extract records as a graph",
    "Extract a vertex-induced, edge-induced, or filtered-neighborhood graph. Preserve original records, direction, weights, loops and parallel edges. Edge mode retains only endpoints; vertices mode can retain isolates.",
    {
        "mode": P("string", "vertices", choices=("vertices", "edges", "neighborhood")),
        "vertices": P("array", None, nullable=True),
        "edge_ids": P("array", None, nullable=True),
        "entity": P("vertex_id", None, nullable=True),
        "hops": P("integer", 1, minimum=0),
        "direction": DIRECTION,
        "vertex_filters": FILTERS,
        "edge_filters": FILTERS,
    },
)
def query_subgraph(graph, args, work, backend="python"):
    data = _index(graph)[0]
    mode = args["mode"]
    if mode == "neighborhood":
        selected = set(
            _distances(
                _adjacency(graph, args, work), args["entity"], args["hops"], work
            )
        )
    elif mode == "vertices":
        selected = set(args["vertices"])
    else:
        selected = set(graph.node_ids)
    if args["vertices"] is not None:
        selected &= set(args["vertices"])
    selected = {
        v["id"]
        for v in data["vertices"]
        if v["id"] in selected and _matches(v, args["vertex_filters"])
    }
    edges = []
    endpoints = set()
    for edge in _filtered_edges(graph, args, work):
        if edge["source"] in selected and edge["target"] in selected:
            edges.append(deepcopy(edge))
            endpoints.update((edge["source"], edge["target"]))
            work.output(len(edges))
    if mode == "edges":
        selected &= endpoints
    vertices = [deepcopy(v) for v in data["vertices"] if v["id"] in selected]
    work.output(len(vertices) + len(edges))
    meta = deepcopy(data["graph"])
    meta["id"] = f"query:{graph.fingerprint}"
    projected = Graph({"graph": meta, "vertices": vertices, "edges": edges})
    return AlgorithmOutput(
        {
            "graph": projected.to_canonical(),
            "vertex_count": len(vertices),
            "edge_count": len(edges),
        },
        {
            "graph": _port("graph", projected.to_canonical()),
            "vertices": _port("vertex_set", [v["id"] for v in vertices]),
            "edges": _port("edge_ids", [e["id"] for e in edges]),
        },
    )
