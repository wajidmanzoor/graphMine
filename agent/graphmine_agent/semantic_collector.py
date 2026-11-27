"""Collect by native logical type, recovering original records from the snapshot."""

import copy
import json
import math
import re

from .database_sources import json_value
from .errors import AnalyticsError
from .semantic_loader import key
from .table_artifacts import make_table


def struct_fields(logical):
    content = logical[logical.index("(") + 1:-1]
    depth, start, fields = 0, 0, []
    for i, ch in enumerate(content + ","):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and not depth:
            field = content[start:i].strip()
            match = re.match(r"(.+?)\s+((?:NODE|REL|RECURSIVE_REL|STRUCT|UNION|MAP|STRING|JSON|INT\d*|UINT\d*|DOUBLE|FLOAT|BOOLEAN|BOOL|DATE|TIMESTAMP|INTERVAL|INTERNAL_ID|DECIMAL|BLOB|UUID).*)$", field)
            if match:
                fields.append((match[1].strip("`"), match[2]))
            start = i + 1
    return dict(fields)


def contains_graph(logical):
    if logical.endswith("]"):
        return contains_graph(logical[:logical.rfind("[")])
    if logical in {"NODE", "REL", "RECURSIVE_REL"}:
        return True
    return any(contains_graph(value) for value in struct_fields(logical).values()) if logical.startswith(("STRUCT(", "UNION(")) else False


class SemanticCollector:
    def __init__(self, loaded, *, projection="elements", directed=None, weight_property=None, max_bytes=64 * 1024 * 1024):
        self.loaded, self.projection = loaded, projection
        self.directed = loaded.graph["graph"]["directed"] if directed is None else directed
        self.weight_property, self.max_bytes = weight_property, max_bytes
        self.vertices, self.edges = {}, {}
        self.used = 0

    def put(self, target, identity, document):
        if identity not in target:
            self.used += len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode())
            if self.used > self.max_bytes:
                raise AnalyticsError("Semantic output exceeds the result byte budget.", "resource_limit")
            target[identity] = copy.deepcopy(document)

    def node(self, value):
        identity = value.get("__gm_key")
        internal = value.get("_ID", {})
        if identity not in self.loaded.vertices or self.loaded.native_nodes.get((internal.get("table"), internal.get("offset"))) != identity:
            raise AnalyticsError("The semantic result has an invalid vertex identity.", "semantic_identity")
        self.put(self.vertices, identity, self.loaded.vertices[identity])
        return self.loaded.vertices[identity]["id"]

    def relationship(self, value):
        identity = value.get("__gm_key")
        edge = self.loaded.edges.get(identity)
        if edge is None:
            raise AnalyticsError("The semantic result has an invalid edge identity.", "semantic_identity")
        for field, endpoint in [("_SRC", "source"), ("_DST", "target")]:
            native = value.get(field, {})
            expected = key(edge[endpoint])
            if self.loaded.native_nodes.get((native.get("table"), native.get("offset"))) != expected:
                raise AnalyticsError("The semantic result has inconsistent edge endpoints.", "semantic_identity")
            self.put(self.vertices, expected, self.loaded.vertices[expected])
        result = copy.deepcopy(edge)
        if self.weight_property:
            weight = result.get("attributes", {}).get(self.weight_property)
            if type(weight) not in {int, float} or not math.isfinite(weight):
                raise AnalyticsError("The selected edge weight must be a finite number.", "query_projection")
            result["weight"] = weight
        self.put(self.edges, identity, result)
        return edge["id"]

    def collect(self, value, logical):
        if value is None:
            return None
        if logical.endswith("[]") or re.search(r"\[\d+\]$", logical):
            inner = logical[:logical.rfind("[")]
            return [self.collect(item, inner) for item in value]
        if logical == "NODE":
            return {"node": self.node(value)}
        if logical == "REL":
            return {"relationship": self.relationship(value)}
        if logical == "RECURSIVE_REL":
            return {"vertices": [self.node(node) for node in value["_NODES"]],
                    "edges": [self.relationship(edge) for edge in value["_RELS"]]}
        if logical.startswith("STRUCT("):
            fields = struct_fields(logical)
            if set(fields) != set(value):
                raise AnalyticsError("Use separate return columns for this structured result.", "semantic_projection")
            return {name: self.collect(item, fields[name]) for name, item in value.items()}
        if logical.startswith("UNION(") and contains_graph(logical):
            raise AnalyticsError("Return graph elements directly rather than inside a UNION value.", "semantic_projection")
        if logical == "JSON":
            return json.loads(value) if isinstance(value, str) else json_value(value)
        return json_value(value)

    def row(self, row, columns, logical_types, number):
        if self.projection != "rows":
            return {name: self.collect(value, logical) for name, value, logical in zip(columns, row, logical_types)}
        values, types = dict(zip(columns, row)), dict(zip(columns, logical_types))
        if any(types.get(name) != "NODE" or values.get(name) is None for name in ("source", "target")):
            raise AnalyticsError("Row projection requires real nodes returned AS source and AS target.", "query_projection")
        source, target = self.node(values["source"]), self.node(values["target"])
        if any(contains_graph(types[name]) for name in columns if name not in {"source", "target"}):
            raise AnalyticsError("Return scalar attributes beside source and target in row projection.", "query_projection")
        attributes = {name: self.collect(value, types[name]) for name, value in values.items() if name not in {"source", "target"}}
        edge_type, weight = attributes.get("type", "DERIVED"), attributes.get("weight")
        if not isinstance(edge_type, str) or not edge_type.strip() or "weight" in attributes and (type(weight) not in {int, float} or not math.isfinite(weight)):
            raise AnalyticsError("Derived edges need a nonempty type and a finite numeric weight.", "query_projection")
        edge = {"id": f"semantic-edge:{number}", "source": source, "target": target, "type": edge_type, "attributes": attributes}
        if "weight" in attributes:
            edge["weight"] = weight
        self.put(self.edges, key(edge["id"]), edge)
        return {"source": {"node": source}, "target": {"node": target}, **attributes}

    def read(self, result):
        columns, logical_types = result.get_column_names(), result.get_column_data_types()
        if not columns or len(columns) != len(set(columns)):
            raise AnalyticsError("Return unique column names using explicit aliases.", "semantic_projection")
        graph_result = self.projection == "rows" or any(contains_graph(logical) for logical in logical_types)
        if self.projection == "rows" and not {"source", "target"}.issubset(columns):
            raise AnalyticsError("Row projection requires source and target columns.", "query_projection")
        sample, scalar_rows, count, scalar_bytes, sample_bytes = [], [], 0, 0, 0
        while result.has_next():
            count += 1
            row = self.row(result.get_next(), columns, logical_types, count)
            size = len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode())
            if count <= 50 and sample_bytes + size <= 256 * 1024:
                sample.append(row); sample_bytes += size
            if not graph_result:
                scalar_bytes += size
                if scalar_bytes > self.max_bytes or count > 100_000:
                    raise AnalyticsError("Semantic table exceeds the output budget.", "resource_limit")
                scalar_rows.append(row)
        descriptor = {**copy.deepcopy(self.loaded.graph["graph"]), "directed": self.directed}
        if self.projection == "rows":
            descriptor.update(allows_self_loops=True, allows_parallel_edges=True)
        graph = {"graph": descriptor,
                 "vertices": list(self.vertices.values()), "edges": list(self.edges.values())}
        return {"kind": "graph" if graph_result else "table", "value": graph if graph_result else make_table(columns, scalar_rows),
                "rows": sample, "row_count": count, "rows_truncated": count > len(sample), "column_types": dict(zip(columns, logical_types))}
