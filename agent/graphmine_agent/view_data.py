"""Render-ready, bounded data attached to the existing saved witness response."""
from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict

from .graph_context import display_name, identity
from .view_profile import MEMBERSHIP_BUDGET, edge_type, finite, fingerprint, node_type, profile_result, rows_for
from .view_rules import RULES_VERSION, choose_view

CHART_LIMIT = 2000


def property_fields(vertices, edges):
    """A bounded property catalog, without identifiers or presentation internals."""
    labels = {"degree": "Connections in input", "vertex_type": "Entity type", "side": "Bipartite side",
              "review_count": "Review count", "average_stars": "Average stars", "stars": "Average stars",
              "relationship_type": "Relationship type"}
    internal = {"id", "element_id", "source", "target", "label", "name", "display_name", "type",
                "result", "expanded", "more_neighbors", "prediction_error", "shared", "role", "edge_role"}
    result = []
    for target, records in (("node", vertices), ("edge", edges)):
        values = defaultdict(list)
        for record in records[:2000]:
            for key, value in record.get("view", {}).items():
                if key not in internal and type(value) in (str, int, float, bool) and value != "":
                    values[key].append(value)
            for key, value in record.get("attributes", {}).items():
                if key not in internal and not key.startswith("_") and type(value) in (str, int, float, bool) and value != "":
                    values["attributes." + key].append(value)
        for field, items in sorted(values.items(), key=lambda pair: (pair[0].startswith("attributes."), pair[0])):
            numeric = all(finite(v) is not None and not isinstance(v, bool) for v in items)
            short = field.removeprefix("attributes.")
            categories = list(dict.fromkeys(items)) if not numeric else []
            result.append({"field": field, "label": labels.get(short, short.replace("_", " ").capitalize()),
                           "target": target, "group": "Entity properties" if field.startswith("attributes.") or field in {"degree", "vertex_type", "relationship_type", "weight"} else "Result fields",
                           "kind": "numeric" if numeric else "category", "minimum": min(items) if numeric else None,
                           "maximum": max(items) if numeric else None, "categories": categories[:8] if len(categories) <= 8 else [],
                           "unique_allowed": not numeric and len(categories) <= 8})
    return result[:128]


def chart_rows(rows, budget=100000):
    """Bound nested memberships and vectors as well as the outer row count."""
    remaining, truncated = budget, False
    def bounded(value, depth=0):
        nonlocal remaining, truncated
        remaining -= 1
        if remaining < 0 or depth > 12:
            truncated = True
            return None
        if isinstance(value, (list, dict)):
            result = [] if isinstance(value, list) else {}
            items = enumerate(value) if isinstance(value, list) else value.items()
            for i, (key, item) in enumerate(items):
                if i >= CHART_LIMIT or remaining <= 0:
                    truncated = True
                    break
                item = bounded(item, depth + 1)
                if isinstance(result, list):
                    result.append(item)
                else:
                    result[key] = item
            return result
        return value
    result = bounded(rows[:CHART_LIMIT])
    return result, truncated or len(rows) > CHART_LIMIT


def label_records(graph, requested=None, limit=500):
    requested = None if requested is None else {identity(v) for v in requested}
    rows = []
    for vertex in (graph or {}).get("vertices", []):
        if requested is None or identity(vertex["id"]) in requested:
            label = display_name(vertex)
            rows.append({"id": vertex["id"], "label": label, "named": label != str(vertex["id"]), "type": node_type(vertex)})
            if len(rows) >= limit:
                break
    return rows


def group_memberships(port, rows, *, limit=MEMBERSHIP_BUDGET):
    result = defaultdict(list)
    scanned = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if port.get("type") == "vertex_groups":
            members = row.get("vertices", [])
            if scanned + len(members) > limit:
                raise ValueError("Group membership exceeds the bounded display budget.")
            scanned += len(members)
            for vertex in members:
                result[identity(vertex)].append(row.get("group", index))
        elif port.get("type") == "vertex_partition":
            group = next((row[k] for k in ("group", "part", "community") if k in row), None)
            if "vertex" in row and group is not None:
                result[identity(row["vertex"])].append(group)
    return result


def display_positions(vertices, layout="force", groups=None):
    """Deterministic bounded initial positions; force refinement is a separate action.

    This seed layout does not claim to optimize a graph metric. Large scenes
    can display immediately without blocking the browser's main thread.
    """
    positions = []
    columns = max(1, math.ceil(math.sqrt(len(vertices))))
    for i, vertex in enumerate(vertices):
        if layout == "hierarchical":
            x, y = i * 96, 0
        elif layout == "grid":
            x, y = (i % columns) * 110, (i // columns) * 72
        else:
            angle = i * math.pi * (3 - math.sqrt(5))
            radius = 42 * math.sqrt(i)
            x, y = math.cos(angle) * radius, math.sin(angle) * radius
        positions.append({"id": vertex["id"], "x": x, "y": y})
    return positions


def enrich_view(view, saved, port_name, original, focused=None, *, provenance=None, cached_profile=None):
    """Never mutate saved inputs, native outputs, IDs, or witness membership."""
    port = saved["ports"][port_name]
    rows, total = rows_for(port)
    facts = copy.deepcopy(cached_profile) if cached_profile else profile_result(saved.get("operation"), port, original, focused)
    if port["type"] in {"vertex_predictions", "graph_predictions"}:
        facts["task"] = saved.get("parameters", {}).get("task")
        if facts["task"] == "classification":
            facts["scores"] = None
            facts["field_roles"]["prediction"] = {"role": "group_key", "meaning": "predicted_class"}
    try:
        membership = group_memberships(port, rows)
    except ValueError:
        membership = {}
        view["membership_note"] = "Group styling is unavailable because membership exceeds the display scan budget. Open a smaller result or individual item."
    selected = {identity(v) for v in view.get("selected_vertices", [])}
    selected_edges = {identity(v) for v in view.get("selected_edges", [])}
    degree = Counter()
    for edge in (original or view).get("edges", []):
        degree[identity(edge["source"])] += 1
        degree[identity(edge["target"])] += 1
    scores = {}
    score_field = (facts.get("scores") or {}).get("field")
    for row in rows:
        if isinstance(row, dict):
            vertex = row.get(port.get("vertex_field", "vertex"), row.get("entity"))
            if port["type"] == "entity_ranking" and row.get("anomaly_target") != "vertex":
                vertex = None
            if vertex is not None and score_field and finite(row.get(score_field)) is not None:
                scores[identity(vertex)] = row[score_field]
            if port["type"] == "vertex_signal" and vertex is not None and isinstance(row.get("value"), list) and row["value"] and finite(row["value"][0]) is not None:
                scores[identity(vertex)] = row["value"][0]
            if saved.get("operation") == "vertex-coloring" and vertex is not None:
                membership[identity(vertex)] = [row.get(port.get("score_field", "color"), row.get("score"))]
    sides = {identity(v): side for side, values in enumerate(view.get("bipartite_sides", [])) for v in values}
    predictions = {identity(r["vertex"]): r.get("prediction") for r in rows if isinstance(r, dict) and "vertex" in r and "prediction" in r}
    ranks = {key: rank + 1 for rank, (key, _) in enumerate(sorted(scores.items(), key=lambda item: -item[1]))}
    vertices = []
    for vertex in view.get("vertices", []):
        key = identity(vertex["id"])
        groups = membership.get(key, [])
        row = {**vertex, "label": display_name(vertex), "view": {
            "display_name": display_name(vertex), "vertex_type": node_type(vertex), "degree": degree[key],
            "group": groups[0] if len(groups) == 1 else "Shared" if groups else None,
            "groups": groups[:64], "shared": len(groups) > 1,
            "side": sides.get(key), "score": scores.get(key), "rank": ranks.get(key),
            "prediction": predictions.get(key),
            "role": "member" if key in selected or not view.get("context") else "context",
            "result": key in selected or not view.get("context"),
        }}
        vertices.append(row)
    view["vertices"] = vertices
    edge_scores = {identity(r.get("edge")): r.get("score") for r in rows if isinstance(r, dict) and "edge" in r}
    edge_scores.update({identity(r["entity"]): r.get("score") for r in rows if isinstance(r, dict) and r.get("anomaly_target") == "edge" and "entity" in r})
    flow = {identity(r["id"]): r for r in view.get("flow_rows", []) if "id" in r}
    raw = saved.get("result", {})
    cut = {identity(v) for v in raw.get("min_cut_edges", []) if type(v) in (str, int)}
    for row in vertices:
        if row["id"] == saved.get("parameters", {}).get("source"):
            row["view"]["role"] = "source"
        elif row["id"] == saved.get("parameters", {}).get("sink"):
            row["view"]["role"] = "sink"
    view["edges"] = [{**edge, "view": {
        "relationship_type": edge_type(edge), "weight": edge.get("weight"), "score": edge_scores.get(identity(edge["id"])),
        "flow": flow.get(identity(edge["id"]), {}).get("flow"), "capacity": flow.get(identity(edge["id"]), {}).get("capacity"), "cut": identity(edge["id"]) in cut,
        "edge_role": "derived" if saved.get("operation") in {"knn-graph", "graph-coarsening", "graph-condensation"} else "context" if view.get("context") and selected_edges and identity(edge["id"]) not in selected_edges else "recorded",
        "result": not view.get("context") or identity(edge["id"]) in selected_edges,
    }} for edge in view.get("edges", [])]
    parameters = saved.get("parameters", {})
    input_sides = [parameters.get(name + "_partition", []) for name in ("left", "right")]
    if all(input_sides):
        view["input_bipartite_sides"] = input_sides
        lookup = {identity(v["id"]): node_type(v) for v in (original or {}).get("vertices", [])}
        types = [{lookup.get(identity(v)) for v in values} for values in input_sides]
        if all(len(values) == 1 and None not in values for values in types):
            view["bipartite_names"] = [next(iter(values)) for values in types]
    if sides:
        types = [set(v["view"]["vertex_type"] for v in vertices if v["view"]["side"] == side) for side in (0, 1)]
        names = [next(iter(values)) if len(values) == 1 and "Entity" not in values else default for values, default in zip(types, ("Left", "Right"))]
        view["bipartite_names"] = names if names[0] != names[1] else ["Left · " + names[0], "Right · " + names[1]]
    # Labels are bounded and namespaced; the label endpoint resolves other pages.
    label_source = focused if port.get("type") in {"graph", "pattern_collection"} else original
    requested = [v["id"] for v in (label_source or {}).get("vertices", [])[:1500]]
    for row in rows[:500]:
        if port.get("type") == "vertex_set":
            requested.append(row)
        elif isinstance(row, dict):
            requested.extend(row[k] for k in ("vertex", "source", "target") if type(row.get(k)) in (int, str))
    view["labels"] = label_records(label_source, requested, 1500)
    view["profile_facts"] = facts
    view["property_fields"] = property_fields(vertices, view["edges"])
    view["view_spec"] = choose_view(view["profile"], facts, view, provenance=provenance)
    if port["type"] == "vertex_partition":
        from .result_views import view_items
        rows = view_items(port)
        total = len(rows)
    bounded_rows, nested_truncated = chart_rows(rows)
    view["chart_data"] = {
        "rows": bounded_rows, "total_rows": total, "nested_truncated": nested_truncated,
        "rows_complete": len(bounded_rows) == total and not nested_truncated and port.get("complete", False),
        "group_sizes": facts["groups"]["sizes"],
        "metrics": [{"name": key.replace("_", " "), "value": value} for key, value in saved.get("result", {}).items() if finite(value) is not None][:24],
        "baseline": facts.get("input"),
        "degrees": [{"vertex": v["id"], "degree": v["view"]["degree"]} for v in vertices[:CHART_LIMIT]],
    }
    from .view_semantics import semantic_data
    view["chart_data"].update(semantic_data(saved, port, original, vertices, membership, view.get("index")))
    if port["type"] in {"vertex_partition", "vertex_groups"}:
        indices = {str(row.get("group", i)): i for i, row in enumerate(rows)}
        view["chart_data"]["group_sizes"] = [{**row, "index": indices.get(str(row["id"]), i)} for i, row in enumerate(facts["groups"]["sizes"])]
    errors = {identity(v) for v in view["chart_data"].get("prediction_errors", [])}
    for vertex in vertices:
        vertex["view"]["prediction_error"] = identity(vertex["id"]) in errors
    if view["view_spec"]["layout"]["positions_source"] == "server":
        view["positions"] = display_positions(vertices, view["view_spec"]["layout"]["name"])
        view["position_note"] = "Deterministic initial display positions; no optimized layout calculation has been run."
    return view


def saved_view_manifest(service, record, step, saved):
    """Called on the execution path after the native result is safely saved."""
    from .result_views import default_index, focus_graph, input_graph, profile
    result = saved.get("result", {})
    if not result.get("ports"):
        return None
    original = input_graph(service, record, step)
    provenance = {"workflow_id": record["id"], "revision": record["revision"], "step": step,
                  "input_fingerprint": fingerprint(original), "result_fingerprint": fingerprint(result)}
    views = {}
    for name, port in result["ports"].items():
        index = default_index(port, None)
        focused, _, selected, edges = focus_graph(original, result, name, index)
        view = {"profile": profile(result.get("operation")), "index": index, "complete": port.get("complete", False),
                "graph_available": focused is not None, "vertices": (focused or {}).get("vertices", [])[:2000], "edges": (focused or {}).get("edges", [])[:5000],
                "vertex_count": len((focused or {}).get("vertices", [])), "edge_count": len((focused or {}).get("edges", []))}
        facts = profile_result(result.get("operation"), port, original, focused)
        if port["type"] in {"vertex_predictions", "graph_predictions"} and result.get("parameters", {}).get("task") == "classification":
            facts["scores"] = None
            facts["field_roles"]["prediction"] = {"role": "group_key", "meaning": "predicted_class"}
        views[name] = {"profile": facts, "spec": choose_view(view["profile"], facts, view, provenance={**provenance, "port": name})}
    return {"schema_version": "1.0.0", "rules_version": RULES_VERSION, "provenance": provenance, "ports": views}
