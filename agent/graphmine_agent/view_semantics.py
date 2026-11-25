"""Bounded auxiliary records for views; never inferred algorithm outcomes."""
from collections import Counter

from .graph_context import display_name, identity
from .view_profile import GRAPH_BUDGET, ROW_BUDGET, finite, rows_for


def semantic_data(saved, port, graph, vertices, membership, index=None):
    rows, _ = rows_for(port)
    data = {}
    problem = saved.get("problem")
    if problem == "max-flow-min-cut":
        raw = saved.get("result", {})
        if isinstance(raw.get("source_side"), list) and isinstance(raw.get("sink_side"), list):
            data["cut_sides"] = [raw["source_side"][:GRAPH_BUDGET], raw["sink_side"][:GRAPH_BUDGET]]
    if port["type"] in {"vertex_groups", "bipartite_groups", "path_set", "vertex_mappings", "pattern_collection", "motif_instances", "graphlet_instances", "temporal_occurrence_collection"} and len((graph or {}).get("edges", [])) <= GRAPH_BUDGET and len((graph or {}).get("vertices", [])) <= GRAPH_BUDGET:
        from .result_views import focus_graph
        previews = []
        port_name = next((name for name, value in saved.get("ports", {}).items() if value is port), None)
        if port_name:
            for i in range(min(24, len(rows))):
                witness, note, _, _ = focus_graph(graph, saved, port_name, i)
                shown = (witness or {}).get("vertices", [])[:20]
                keys = {identity(v["id"]) for v in shown}
                edges = [e for e in (witness or {}).get("edges", []) if identity(e["source"]) in keys and identity(e["target"]) in keys][:60]
                previews.append({"vertices": shown, "edges": edges, "directed": (witness or {}).get("graph", {}).get("directed", False), "note": note})
        data["item_previews"] = previews
    route = None
    route_partial = False
    if problem == "topological-sort" and port["type"] == "vertex_set":
        route = [{"vertex": v} for v in rows[:200]]
    elif port["type"] in {"path_set", "walk_sample", "edge_sequence_collection"}:
        values = port.get("value", [])
        chosen = values[index or 0] if values and (index or 0) < len(values) else None
        sequence = chosen if isinstance(chosen, list) and port["type"] != "edge_sequence_collection" else chosen.get("vertices", []) if isinstance(chosen, dict) else []
        route = [{"vertex": v} for v in sequence[:200] if type(v) in (str, int)]
    elif problem in {"single-source-shortest-paths", "widest-paths", "breadth-first-search"} and index is not None and isinstance(port.get("value"), list):
        values = port["value"]
        lookup = {(identity(r.get("source")), identity(r["vertex"])): r for r in values[:100000] if isinstance(r, dict) and "vertex" in r}
        cursor = values[index] if index < len(values) else None
        route, seen = [], set()
        while isinstance(cursor, dict) and "vertex" in cursor and len(route) < 200:
            key = (identity(cursor.get("source")), identity(cursor["vertex"]))
            if key in seen or cursor.get("reachable") is False or cursor.get("distance", 0) is None:
                route_partial = key in seen
                break
            seen.add(key)
            route.append({k: cursor[k] for k in ("vertex", "distance", "capacity", "arrival") if k in cursor})
            parent = cursor.get("predecessor")
            cursor = lookup.get((key[0], identity(parent))) if parent is not None else None
            if parent is not None and cursor is None:
                route_partial = True
        if cursor is not None and len(route) == 200:
            route_partial = True
        route.reverse()
    if route is not None:
        data["route"] = route
        data["route_note"] = "Recorded order, up to 200 retained steps. Edge weights and cumulative distances are shown only when explicitly recorded."
        if route_partial:
            data["route_note"] += " This route is partial: a predecessor is missing, cyclic, or outside the display budget."
    if membership:
        counts = Counter()
        for edge in (graph or {}).get("edges", [])[:GRAPH_BUDGET]:
            left, right = membership.get(identity(edge["source"]), []), membership.get(identity(edge["target"]), [])
            if len(left) == len(right) == 1:
                pair = (identity(left[0]), identity(right[0]))
                if not graph["graph"].get("directed"):
                    pair = tuple(sorted(pair))
                counts[pair] += 1
        import json
        data["group_connections"] = [{"source": json.loads(a), "target": json.loads(b), "count": n} for (a, b), n in counts.most_common(1000)]
        data["group_connections_complete"] = len((graph or {}).get("edges", [])) <= GRAPH_BUDGET and all(len(groups) == 1 for groups in membership.values())
    if port["type"] == "walk_sample":
        visits = Counter()
        ids = {}
        remaining = ROW_BUDGET
        for walk in rows:
            if not isinstance(walk, list):
                continue
            for vertex in walk[:remaining]:
                key = identity(vertex)
                visits[key] += 1
                ids[key] = vertex
            remaining -= min(remaining, len(walk))
            if remaining == 0:
                break
        data["visits"] = [{"vertex": ids[key], "count": count} for key, count in visits.most_common(2000)]
        data["visit_scan_limit"] = ROW_BUDGET
    if port["type"] == "eigenpairs":
        value = port.get("value", {})
        data["vertex_order"] = value.get("vertex_order", [])[:GRAPH_BUDGET]
    for name, other in saved.get("ports", {}).items():
        if other.get("type") == "vertex_confidence":
            data["location_dispersion"] = rows_for(other, 2000)[0]
        if other.get("type") == "learning_metrics" and isinstance(other.get("value"), dict):
            metrics = []
            for k, v in other["value"].items():
                if finite(v) is not None:
                    metrics.append({"name": k.replace("_", " "), "value": v})
                elif isinstance(v, dict):
                    metrics.extend({"name": (k + " · " + field).replace("_", " "), "value": value} for field, value in v.items() if finite(value) is not None)
            data["learning_metrics"] = metrics[:64]
        if name == "scores" and saved.get("problem") == "k-core":
            data["core_scores"] = rows_for(other, 2000)[0]
    # Confusion is valid only with an explicit retained truth per observation.
    confusion = Counter()
    parameters = saved.get("parameters", {})
    truth_rows = parameters.get("training_labels", parameters.get("graph_labels", {})).get("rows", [])
    truth_rows = [*truth_rows[:ROW_BUDGET], *parameters.get("split", {}).get("validation_labels", [])[:ROW_BUDGET], *parameters.get("split", {}).get("test_labels", [])[:ROW_BUDGET]]
    truth_map = {identity(r.get("vertex", r.get("graph"))): r.get("value") for r in truth_rows if isinstance(r, dict)}
    errors = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        truth = row.get("truth", row.get("true_label", truth_map.get(identity(row.get("vertex", row.get("graph"))))))
        prediction = row.get("predicted_class", row.get("predicted_label", row.get("prediction") if parameters.get("task") == "classification" else None))
        if truth is not None and prediction is not None:
            confusion[(identity(truth), identity(prediction))] += 1
            if identity(truth) != identity(prediction) and "vertex" in row:
                errors.append(row["vertex"])
    if confusion:
        import json
        data["confusion"] = [{"truth": json.loads(a), "prediction": json.loads(b), "count": count} for (a, b), count in confusion.items()]
        data["prediction_errors"] = errors
    if port["type"] == "cross_graph_mapping":
        other = saved.get("parameters", {}).get("other_graph")
        if isinstance(other, dict) and isinstance(other.get("vertices"), list):
            def bounded(g):
                nodes = g.get("vertices", [])[:500]
                keys = {identity(v["id"]) for v in nodes}
                return {"graph": g.get("graph", {}), "vertices": [{**v, "label": display_name(v)} for v in nodes], "edges": [e for e in g.get("edges", [])[:GRAPH_BUDGET] if identity(e["source"]) in keys and identity(e["target"]) in keys][:2000]}
            data["mapping_graphs"] = [bounded(graph or {}), bounded(other)]
    return data
