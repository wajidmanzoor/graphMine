"""Bounded planning context: earlier results, the user's selection, named entities.

Everything here is computed from saved results and uploaded inputs. The planner
receives summaries, never the full outputs, and the server resolves selections
itself rather than trusting member lists sent by the browser.
"""

from __future__ import annotations

import json
import re
from collections import Counter

RESULT_BUDGET = 6000
ENTITY_LIMIT = 20


def summarize_port(port, *, members=40, rows=10):
    kind, value = port.get("type"), port.get("value")
    summary = {"type": kind, "complete": port.get("complete")}
    if kind == "graph" and isinstance(value, dict):
        summary.update(
            vertices=len(value.get("vertices", [])), edges=len(value.get("edges", []))
        )
        return summary
    if not isinstance(value, list):
        if value is None or isinstance(value, (bool, int, float, str)):
            summary["value"] = value
        return summary
    summary["items"] = len(value)
    if kind == "vertex_groups":
        sizes = sorted(
            (
                (len(group.get("vertices", [])), index)
                for index, group in enumerate(value)
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )
        summary["largest"] = [
            {"index": index, "group": value[index].get("group"), "size": size}
            for size, index in sizes[:rows]
        ]
        if sizes:
            summary["largest_members"] = value[sizes[0][1]].get("vertices", [])[
                :members
            ]
    elif kind == "vertex_partition":
        counts = Counter(row.get("part") for row in value if isinstance(row, dict))
        summary["parts"] = len(counts)
        summary["largest_parts"] = [
            {"part": part, "size": size} for part, size in counts.most_common(rows)
        ]
    elif kind in ("vertex_scores", "edge_scores"):
        field = port.get("score_field", "score")
        scored = [
            row
            for row in value
            if isinstance(row, dict)
            and isinstance(row.get(field), (int, float))
            and not isinstance(row.get(field), bool)
        ]
        summary["highest"] = sorted(scored, key=lambda row: -row[field])[:rows]
    elif kind == "vertex_set":
        summary["members"] = value[:members]
    else:
        summary["first_items"] = value[: min(rows, 5)]
    return summary


def summarize_result(saved, budget=RESULT_BUDGET):
    """Summarize a saved workflow result, shrinking detail to fit the budget."""
    for members, rows in ((40, 10), (10, 5), (0, 3)):
        steps = []
        for step_id in saved.get("order", saved.get("steps", {})):
            step = saved.get("steps", {}).get(step_id, {})
            result = step.get("result") or {}
            steps.append(
                {
                    "step": step_id,
                    "operation": result.get("operation"),
                    "status": step.get("status"),
                    "complete": result.get("complete"),
                    "quality": result.get("quality"),
                    "ports": {
                        name: summarize_port(port, members=members, rows=rows)
                        for name, port in (result.get("ports") or {}).items()
                    },
                }
            )
        if len(json.dumps(steps, default=str)) <= budget:
            return steps
    return [
        {key: step[key] for key in ("step", "operation", "status", "complete")}
        for step in steps
    ]


def resolve_selection(saved, selection, *, members=200):
    """The item the user is looking at, read from the saved result."""
    step = saved.get("steps", {}).get(selection.step, {})
    port = ((step.get("result") or {}).get("ports") or {}).get(selection.port)
    if port is None:
        return None
    resolved = {
        "workflow_id": selection.workflow_id,
        "step": selection.step,
        "port": selection.port,
        "type": port.get("type"),
        "label": selection.label,
    }
    value = port.get("value")
    if selection.index is None or not isinstance(value, list):
        return resolved
    if selection.index >= len(value):
        return None
    item = value[selection.index]
    resolved["index"] = selection.index
    if port.get("type") == "vertex_groups" and isinstance(item, dict):
        vertices = item.get("vertices", [])
        resolved.update(
            size=len(vertices),
            vertices=vertices[:members],
            vertices_truncated=len(vertices) > members,
            binding_selection={"kind": "group_vertices", "index": selection.index},
        )
    else:
        resolved["item"] = item if len(json.dumps(item, default=str)) < 4000 else None
    return resolved


def _names(vertex):
    names = [vertex.get("id")]
    attributes = vertex.get("attributes")
    for source in (vertex, attributes if isinstance(attributes, dict) else {}):
        names += [source.get(key) for key in ("label", "name", "title")]
    return {str(name) for name in names if isinstance(name, (str, int)) and str(name)}


def matched_entities(question, inputs, limit=ENTITY_LIMIT):
    """Vertices anywhere in the inputs whose ID or name appears in the question."""
    text = question.casefold()
    # Short IDs such as "3" match only when named as one ("vertex 3"), never as
    # an ordinary number in the question.
    named = set(re.findall(r"\b(?:vertex|node|id|entity)\s+([\w.-]+)", text))
    found = []
    for alias, descriptor in inputs.items():
        data = descriptor.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("vertices"), list):
            continue
        for vertex in data["vertices"]:
            if not isinstance(vertex, dict):
                continue
            for name in _names(vertex):
                key = name.casefold()
                if key in named or (
                    len(key) >= 3
                    and key in text
                    and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text)
                ):
                    found.append((len(key), alias, vertex, name))
                    break
    found.sort(key=lambda row: -row[0])
    return [
        {
            "input": alias,
            "id": vertex.get("id"),
            "matched": name,
            **({"label": vertex["label"]} if "label" in vertex else {}),
        }
        for _length, alias, vertex, name in found[:limit]
    ]
