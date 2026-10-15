"""Bounded CPU import for ordinary UTF-8 relationship CSVs and edge lists."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import re
from datetime import datetime

from .native_ingestion import IngestionError

INTEGER = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
MAX_ROWS = 100_000
MAX_CELLS = 2_000_000


def scalar(text):
    if INTEGER.fullmatch(text):
        return integer(text)
    if NUMBER.fullmatch(text):
        value = float(text)
        if math.isfinite(value):
            return value
    return text


def integer(text):
    try:
        return int(text)
    except ValueError as exc:
        raise IngestionError("CSV integer exceeds the supported digit limit") from exc


def identifier(text, *, edge_list=False):
    if not text or not text.strip():
        raise IngestionError("Graph endpoint and edge IDs must be nonempty")
    # Leading zeroes, plus signs and whitespace are part of text identifiers.
    if edge_list and re.fullmatch(r"\+(?:0|[1-9][0-9]*)", text):
        return integer(text)
    return integer(text) if INTEGER.fullmatch(text) else text


def checked_lines(stream):
    """Reject quotes inside unquoted fields, which csv.reader otherwise accepts."""
    state = "start"
    for line in stream:
        for char in line:
            if state == "quoted":
                if char == '"':
                    state = "closed"
            elif state == "closed":
                if char == '"':
                    state = "quoted"
                elif char in ",\r\n":
                    state = "start"
                else:
                    raise IngestionError(
                        "Unexpected character after a closing CSV quote"
                    )
            elif char in ",\r\n":
                state = "start"
            elif char == '"':
                if state != "start":
                    raise IngestionError("CSV quotes must enclose the whole field")
                state = "quoted"
            else:
                state = "plain"
        yield line


def read_table(path):
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            if path.suffix.lower() == ".csv":
                rows = csv.reader(checked_lines(stream), strict=True)
                header = next(rows, [])
            else:
                rows = (
                    line.split()
                    for line in stream
                    if line.strip() and not line.lstrip().startswith(("#", "%"))
                )
                first = next(rows, [])
                if first and first[0].lower() in {"source", "src", "from"}:
                    header = first
                else:
                    header = ["source", "target", "weight", "timestamp"][: len(first)]
                    rows = itertools.chain([first], rows)
            if (
                not header
                or len(header) > 64
                or any(not name.strip() for name in header)
            ):
                raise IngestionError("CSV needs between 1 and 64 nonempty column names")
            if len(header) != len(set(header)):
                raise IngestionError("CSV column names must be unique")
            values = []
            for index, row in enumerate(rows, 1):
                if index > MAX_ROWS or index * len(header) > MAX_CELLS:
                    raise IngestionError(
                        "CSV exceeds the 100,000 row or 2,000,000 cell import limit"
                    )
                if len(row) != len(header):
                    raise IngestionError(
                        f"CSV record {index} has a different number of values than its header"
                    )
                if any("\x00" in cell for cell in row):
                    raise IngestionError("CSV must not contain NUL characters")
                values.append(dict(zip(header, row, strict=True)))
    except (UnicodeError, csv.Error) as exc:
        raise IngestionError(f"Invalid UTF-8 CSV: {exc}") from exc
    if any("\x00" in name for name in header):
        raise IngestionError("CSV must not contain NUL characters")
    return {"columns": header, "rows": values}


def graph_from_table(
    table,
    *,
    directed,
    source_column=None,
    target_column=None,
    name="imported-network",
    digest=None,
    edge_list=False,
    typed_endpoints=False,
):
    columns = table["columns"]
    source_column = source_column or next(
        (c for c in ("source", "src", "from") if c in columns), columns[0]
    )
    target_column = target_column or next(
        (c for c in ("target", "dst", "to") if c in columns),
        columns[1] if len(columns) > 1 else None,
    )
    if (
        source_column not in columns
        or target_column not in columns
        or source_column == target_column
    ):
        raise IngestionError(
            "Choose two different existing columns for connection endpoints"
        )
    vertices, edges, pairs = {}, [], set()
    parallel, loops = False, False
    reserved = {
        source_column,
        target_column,
        "id",
        "weight",
        "timestamp",
        "type",
        "source_label",
        "target_label",
        "source_type",
        "target_type",
    }
    for index, row in enumerate(table["rows"]):
        endpoints = []
        for side, column in (("source", source_column), ("target", target_column)):
            entity = (
                row[column]
                if typed_endpoints
                else identifier(row[column], edge_list=edge_list)
            )
            if (
                type(entity) not in (int, str)
                or isinstance(entity, str)
                and not entity.strip()
            ):
                raise IngestionError(
                    "Connection endpoints must be nonempty strings or integers"
                )
            key = json.dumps(entity, ensure_ascii=False)
            endpoints.append(key)
            vertex = vertices.setdefault(key, {"id": entity})
            for field in ("label", "type"):
                if row.get(f"{side}_{field}"):
                    value = row[f"{side}_{field}"]
                    if field in vertex and vertex[field] != value:
                        raise IngestionError(
                            f"Conflicting {field} for vertex {entity!r}"
                        )
                    vertex[field] = value
            for column_name, text in row.items():
                if column_name.startswith(side + ".") and text != "":
                    attribute = column_name[len(side) + 1 :]
                    value = scalar(text)
                    attributes = vertex.setdefault("attributes", {})
                    if attribute in attributes and attributes[attribute] != value:
                        raise IngestionError(
                            f"Conflicting attribute for vertex {entity!r}"
                        )
                    attributes[attribute] = value
        edge = {
            "id": identifier(row["id"]) if "id" in row else index,
            "source": vertices[endpoints[0]]["id"],
            "target": vertices[endpoints[1]]["id"],
        }
        if row.get("weight"):
            weight = scalar(row["weight"])
            try:
                finite = isinstance(weight, (int, float)) and math.isfinite(
                    float(weight)
                )
            except OverflowError:
                finite = False
            if not finite:
                raise IngestionError(
                    f"Invalid finite numeric weight in record {index + 1}"
                )
            edge["weight"] = weight
        if row.get("timestamp"):
            timestamp = row["timestamp"]
            if not INTEGER.fullmatch(timestamp):
                try:
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if "T" not in timestamp or parsed.tzinfo is None:
                        raise ValueError("timezone missing")
                except ValueError as exc:
                    raise IngestionError(
                        "Timestamps must be integer epochs or RFC 3339 date-times with a timezone"
                    ) from exc
            edge["timestamp"] = (
                integer(timestamp) if INTEGER.fullmatch(timestamp) else timestamp
            )
        if row.get("type"):
            edge["type"] = row["type"]
        attributes = {
            key: scalar(value)
            for key, value in row.items()
            if key not in reserved
            and not key.startswith(("source.", "target."))
            and value != ""
        }
        if attributes:
            edge["attributes"] = attributes
        pair = tuple(endpoints if directed else sorted(endpoints))
        parallel |= pair in pairs
        loops |= endpoints[0] == endpoints[1]
        pairs.add(pair)
        edges.append(edge)
    provenance = {
        "reader": "python_csv",
        "device": "cpu",
        "source_column": source_column,
        "target_column": target_column,
        "input_sha256": digest,
        "id_policy": "canonical integers; other identifiers retained as text",
        "row_count": len(edges),
        "complete": True,
    }
    return {
        "graph": {
            "id": name,
            "directed": directed,
            "allows_self_loops": loops,
            "allows_parallel_edges": parallel,
            "attributes": {"ingestion": provenance},
        },
        "vertices": list(vertices.values()),
        "edges": edges,
    }


def read_graph(path, *, directed, source_column=None, target_column=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return graph_from_table(
        read_table(path),
        directed=directed,
        source_column=source_column,
        target_column=target_column,
        name=path.stem,
        digest=digest.hexdigest(),
        edge_list=path.suffix.lower() != ".csv",
    )
