"""Named, spreadsheet-friendly projections of saved result ports."""
import json
from collections import OrderedDict

from .graph_context import display_name, identity


def named_rows(port, graph=None, rows=None):
    labels = {identity(v["id"]): display_name(v) for v in (graph or {}).get("vertices", [])}
    name = lambda value: labels.get(identity(value), str(value))
    joined = lambda values: "; ".join(str(value) for value in values)
    values = port.get("value")
    rows = rows if rows is not None else values if isinstance(values, list) else [values]
    kind = port.get("type")
    if kind == "vertex_partition":
        groups = OrderedDict()
        for row in rows:
            group = next((row[k] for k in ("group", "part", "community") if k in row), None)
            groups.setdefault(identity(group), {"group": group, "vertices": []})["vertices"].append(row["vertex"])
        rows, kind = groups.values(), "vertex_groups"
    for index, row in enumerate(rows, 1):
        if kind == "bipartite_groups":
            left, right = row.get("left_vertices", row.get("left", [])), row.get("right_vertices", row.get("right", []))
            yield {"index": index, "left_names": joined(map(name, left)), "right_names": joined(map(name, right)),
                   "left_size": len(left), "right_size": len(right), "left_ids": joined(left), "right_ids": joined(right)}
        elif kind == "vertex_groups":
            ids = row.get("vertices", [])
            yield {"index": index, "group": row.get("group", index), "names": joined(map(name, ids)), "size": len(ids), "ids": joined(ids)}
        elif kind == "vertex_set":
            yield {"index": index, "name": name(row), "id": row}
        elif isinstance(row, dict):
            output = {"index": index}
            for key, value in row.items():
                if key in {"vertex", "entity", "source", "target"} and type(value) in (str, int):
                    output[key + "_name"] = name(value)
                elif key in {"vertices", "left_vertices", "right_vertices"} and isinstance(value, list):
                    output[key + "_names"] = joined(map(name, value))
                    output[key + "_size"] = len(value)
                output[key] = joined(value) if isinstance(value, list) else json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
            yield output
        else:
            yield {"index": index, "value": row}
