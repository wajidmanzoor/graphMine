"""One Vertex table, explicit labels, and lossless snapshot-backed identities.

COPY handles the graph rows. Bounded, vectorized updates restore label lists and
tagged UNION variants because CSV cannot distinguish the text '5' from number 5.
Nested or otherwise irregular values use JSON columns, never lossy coercion.
"""

from collections import defaultdict
from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path

from .errors import AnalyticsError


INTERNAL = {"__gm_key", "__gm_id", "__gm_labels", "__gm_properties"}
CHUNK_ROWS = 512


def key(value):
    if type(value) not in {str, int} or value == "":
        raise AnalyticsError("Graph IDs must be nonempty strings or integers.", "semantic_mapping")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def quoted(name):
    return "`" + name.replace("`", "``") + "`"


def execute(connection, statement, parameters=None):
    result = connection.execute(statement, parameters or {})
    try:
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        return rows
    finally:
        result.close()


def value_kind(value):
    if value is None:
        return None
    if type(value) is int and -(2**63) <= value < 2**63:
        return "integer"
    if type(value) is float and math.isfinite(value):
        return "number"
    return {str: "text", bool: "boolean"}.get(type(value), "json")


TYPES = {"integer": "INT64", "number": "DOUBLE", "text": "STRING", "boolean": "BOOLEAN", "json": "JSON"}


def properties(records):
    names = sorted({name for record in records for name in record.get("attributes", {})})
    folded = defaultdict(list)
    for name in names:
        folded[name.casefold()].append(name)
    used, result = {name.casefold() for name in INTERNAL}, []
    for name in names:
        field = name
        if not name or name.casefold() in used or len(folded[name.casefold()]) > 1 or name.startswith("__gm_"):
            field = "property_" + hashlib.sha256(name.encode()).hexdigest()[:16]
        while field.casefold() in used:
            field += "_"
        used.add(field.casefold())
        kinds = sorted({value_kind(row.get("attributes", {}).get(name)) for row in records} - {None})
        if not kinds or "json" in kinds:
            kind, native = "json", "JSON"
        elif len(kinds) == 1:
            kind, native = kinds[0], TYPES[kinds[0]]
        else:
            kind, native = "union", "UNION(" + ", ".join(f"{k} {TYPES[k]}" for k in kinds) + ")"
        result.append({"name": field, "source_property": name, "type": native, "encoding": kind,
                       "variants": kinds if kind == "union" else []})
    return result


def labels(record):
    value = record.get("attributes", {}).get("neo4j_labels")
    if value is None:
        value = [record["type"]] if record.get("type") else []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise AnalyticsError("Node labels must be a list of nonempty strings.", "semantic_mapping")
    return sorted(set(value))


def schema(graph):
    vertices, edges = {}, {}
    groups = defaultdict(list)
    try:
        encoded(graph)  # reject non-finite/non-JSON properties before native code
        for vertex in graph["vertices"]:
            identity = key(vertex["id"])
            if identity in vertices:
                raise ValueError("Duplicate vertex")
            if not isinstance(vertex.get("attributes", {}), dict):
                raise ValueError("Invalid properties")
            labels(vertex)
            vertices[identity] = vertex
        for edge in graph["edges"]:
            identity = key(edge["id"])
            if identity in edges or key(edge["source"]) not in vertices or key(edge["target"]) not in vertices:
                raise ValueError("Invalid relationship identity or endpoints")
            edge_type = edge.get("type") or "RELATED"
            if not isinstance(edge_type, str) or not isinstance(edge.get("attributes", {}), dict):
                raise ValueError("Invalid relationship type or properties")
            edges[identity] = edge
            groups[edge_type].append(edge)
        tables, used = [], {"vertex"}
        for edge_type in sorted(groups):
            table = edge_type
            if table.casefold() in used or table.startswith("__gm_"):
                table = "Edge_" + hashlib.sha256(edge_type.encode()).hexdigest()[:16]
            while table.casefold() in used:
                table += "_"
            used.add(table.casefold())
            tables.append({"table": table, "source_type": edge_type, "properties": properties(groups[edge_type])})
        return {"mapping": "explicit-labels-v1", "vertex_table": "Vertex", "vertex_properties": properties(list(vertices.values())),
                "labels": sorted({label for v in vertices.values() for label in labels(v)}), "relationships": tables,
                "helpers": ["has_label(n, label)", "labels_of(n)", "graph_id(n)", "has_property(n, name)", "property_names(n)"],
                "nested_properties": "JSON; returned JSON cells are decoded without changing their types"}
    except (ValueError, KeyError, TypeError, OverflowError):
        raise AnalyticsError("The snapshot cannot be mapped losslessly: check IDs, endpoints and JSON properties.", "semantic_mapping") from None


@dataclass
class LoadedGraph:
    graph: dict
    schema: dict
    vertices: dict
    edges: dict
    native_nodes: dict


def batches(rows):
    for start in range(0, len(rows), CHUNK_ROWS):
        yield rows[start:start + CHUNK_ROWS]


def load_graph(connection, graph, directory, *, progress=lambda *args: None):
    description = schema(graph)
    vertices = {key(v["id"]): v for v in graph["vertices"]}
    edges = {key(e["id"]): e for e in graph["edges"]}
    groups = [("Vertex", list(vertices.values()), description["vertex_properties"], False)]
    groups.extend((table["table"], [e for e in edges.values() if (e.get("type") or "RELATED") == table["source_type"]], table["properties"], True)
                  for table in description["relationships"])
    for index, (table, records, fields, relationship) in enumerate(groups):
        columns = [("__gm_key", "STRING"), ("__gm_id", "JSON"), ("__gm_properties", "STRING[]")]
        if not relationship:
            columns.append(("__gm_labels", "STRING[]"))
        columns.extend((field["name"], field["type"]) for field in fields)
        declarations = ", ".join(f"{quoted(name)} {native}" for name, native in columns)
        statement = (f"CREATE REL TABLE {quoted(table)}(FROM Vertex TO Vertex, {declarations})" if relationship else
                     f"CREATE NODE TABLE Vertex({declarations}, PRIMARY KEY(__gm_key))")
        execute(connection, statement)
        path = Path(directory) / f"table-{index}.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow((["FROM", "TO"] if relationship else []) + [name for name, _ in columns])
            for record in records:
                values = ([key(record["source"]), key(record["target"])] if relationship else [])
                values += [key(record["id"]), key(record["id"]), None]
                if not relationship:
                    values.append(None)
                for field in fields:
                    value = record.get("attributes", {}).get(field["source_property"])
                    kind = field["encoding"]
                    values.append(None if value is None or kind == "union" else "s" + value if kind == "text" else
                                  encoded(value) if kind == "json" else value)
                writer.writerow(values)
        # Generated paths are trusted and quoted separately from all user data.
        escaped = str(path).replace("\\", "\\\\").replace("'", "\\'")
        if records:
            execute(connection, f"COPY {quoted(table)} FROM '{escaped}' (HEADER=true, PARALLEL=false)")
        pattern = f"()-[n:{quoted(table)}]->()" if relationship else "(n:Vertex)"
        for field in fields:
            column = quoted(field["name"])
            if field["encoding"] == "text":
                execute(connection, f"MATCH {pattern} SET n.{column}=substring(n.{column},2,size(n.{column}))")
            elif field["encoding"] == "union":
                for kind in field["variants"]:
                    rows = [{"k": key(r["id"]), "v": r.get("attributes", {}).get(field["source_property"])} for r in records
                            if value_kind(r.get("attributes", {}).get(field["source_property"])) == kind]
                    for batch in batches(rows):
                        execute(connection, f"UNWIND $rows AS row MATCH {pattern} WHERE n.__gm_key=row.k SET n.{column}=union_value({kind}:=row.v)", {"rows": batch})
        for column, getter in [("__gm_properties", lambda r: sorted(r.get("attributes", {}))),
                               *([] if relationship else [("__gm_labels", labels)])]:
            execute(connection, f"MATCH {pattern} SET n.{column}=CAST([] AS STRING[])")
            rows = [{"k": key(r["id"]), "v": getter(r)} for r in records if getter(r)]
            for batch in batches(rows):
                execute(connection, f"UNWIND $rows AS row MATCH {pattern} WHERE n.__gm_key=row.k SET n.{column}=row.v", {"rows": batch})
        progress("loading", index + 1, len(groups))
    for name, parameters, expression in [
        ("has_label", "n,l", "list_contains(n.__gm_labels,l)"), ("labels_of", "n", "n.__gm_labels"),
        ("graph_id", "n", "n.__gm_id"), ("has_property", "n,p", "list_contains(n.__gm_properties,p)"),
        ("property_names", "n", "n.__gm_properties"),
    ]:
        execute(connection, f"CREATE MACRO {name}({parameters}) AS {expression}")
    native = {(identity["table"], identity["offset"]): name for name, identity in
              execute(connection, "MATCH (n:Vertex) RETURN n.__gm_key,id(n)")}
    return LoadedGraph(graph, description, vertices, edges, native)
