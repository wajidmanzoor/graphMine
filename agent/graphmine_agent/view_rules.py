"""Deterministic view choices, shared by saved results and legacy adapters."""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from .models import ViewSpec

RULES_VERSION = "2026-11-18.3"
COLORS = ("#0072b2", "#d55e00", "#009e73", "#cc79a7", "#e69f00", "#56b4e9", "#7465a8", "#76722e")


def type_shape(name):
    """A type keeps its shape across inputs, subsets and saved analyses."""
    fixed = {"user": "ellipse", "business": "rectangle", "entity": "ellipse"}
    return fixed.get(str(name).casefold(), ("ellipse", "diamond", "rectangle", "triangle")[
        int(hashlib.sha256(str(name).casefold().encode()).hexdigest()[:8], 16) % 4])


def category_encoding(field, view, facts):
    counts = Counter(json.dumps(v.get("view", {}).get(field), sort_keys=True)
                     for v in view.get("vertices", []) if v.get("view", {}).get("result", True)
                     and v.get("view", {}).get(field) is not None)
    if field == "group":
        keys = sorted({json.dumps(row["id"], sort_keys=True) for row in facts["groups"]["sizes"]} | set(counts))
    else:
        keys = sorted(counts)
    result = []
    for index, key in enumerate(keys):
        value = json.loads(key)
        label = str(value)
        if field == "side" and value in (0, 1):
            label = view.get("bipartite_names", ["Left", "Right"])[value]
        elif field == "group":
            label = "Shared members" if value == "Shared" else f"Group {index + 1}"
        result.append({"value": value, "label": label, "color": COLORS[index % len(COLORS)], "count": counts[key]})
    return result
# Primary view, layout, linked templates, alternates. Every native profile has a
# deliberate entry; graph availability is checked separately for each port.
DEFAULTS = {
    "path": ("graph", "hierarchical", ["route"], ["table", "small_multiples"]),
    "path_tree": ("graph", "hierarchical", ["route"], ["radial", "table"]),
    "ordered": ("graph", "hierarchical", ["route"], ["table"]),
    "subgraph": ("graph", "force", ["metrics"], ["result_only", "concentric", "table"]),
    "vertices": ("graph", "force", ["metrics"], ["table"]),
    "groups": ("graph", "clustered", ["group_sizes"], ["small_multiples", "meta_graph", "table"]),
    "partition": ("graph", "clustered", ["group_sizes", "group_matrix"], ["meta_graph", "table"]),
    "bipartite": ("graph", "bipartite", ["biclique_sizes"], ["matrix", "small_multiples", "table"]),
    "edges": ("graph", "force", ["edge_weights"], ["table"]),
    "scores": ("graph", "force", ["ranked_scores", "score_histogram"], ["concentric", "table"]),
    "colors": ("graph", "clustered", ["group_sizes"], ["grid", "table"]),
    "graph": ("graph", "force", ["degrees"], ["matrix", "table"]),
    "patterns": ("small_multiples", "force", ["support"], ["graph", "table"]),
    "instances": ("small_multiples", "force", ["occurrences"], ["graph", "table"]),
    "flow": ("graph", "hierarchical", ["flow_capacity"], ["cut", "matrix", "table"]),
    "pairs": ("matrix", "none", ["pair_values"], ["table"]),
    "mapping": ("mapping", "none", ["match_scores"], ["merged_mapping", "table"]),
    "embedding": ("scatter", "none", [], ["table"]),
    "predictions": ("graph", "force", ["prediction_metrics"], ["table"]),
    "locations": ("coordinates", "none", ["confidence"], ["map", "table"]),
    "positions": ("graph", "computed", [], ["coordinates", "table"]),
    "intervals": ("barcode", "none", ["persistence"], ["scatter", "filtration", "table"]),
    "samples": ("histogram", "none", [], ["table"]),
    "spectrum": ("spectrum", "none", [], ["eigenvector", "table"]),
    "scalar": ("metric", "none", [], ["table"]),
    "table": ("table", "none", [], []),
}
CHARTS = {
    "route": ("route", "Recorded route", "step", "distance", "entity"),
    "metrics": ("metrics", "Result and saved input", None, None, "none"),
    "group_sizes": ("bar", "Group sizes", "group", "size", "group"),
    "group_matrix": ("heatmap", "Connections between groups", "source", "target", "group"),
    "biclique_sizes": ("scatter", "Biclique sizes", "left_size", "right_size", "item"),
    "edge_weights": ("histogram", "Recorded edge weights", "weight", None, "edge"),
    "ranked_scores": ("bar", "Ranked values", "entity", "score", "entity"),
    "score_histogram": ("histogram", "Score distribution", "score", None, "entity"),
    "degrees": ("histogram", "Degree distribution", "degree", None, "entity"),
    "support": ("bar", "Pattern support", "pattern", "support", "item"),
    "occurrences": ("bar", "Retained occurrences by pattern", "pattern", "count", "item"),
    "flow_capacity": ("bar", "Recorded flow and capacity", "edge", "flow", "edge"),
    "pair_values": ("histogram", "Pair values", "value", None, "pair"),
    "match_scores": ("histogram", "Match scores", "score", None, "pair"),
    "prediction_metrics": ("metrics", "Recorded learning metrics", None, None, "none"),
    "confidence": ("histogram", "Recorded neighbor dispersion (km)", "weighted_mean_neighbor_distance_km", None, "entity"),
    "recorded_counts": ("bar", "Recorded pattern counts", "pattern", "count", "none"),
    "persistence": ("scatter", "Birth and death", "birth", "death", "item"),
    "visits": ("bar", "Retained walk visits", "vertex", "count", "entity"),
}


def choose_view(profile, facts, view, *, provenance=None):
    kind = profile["kind"]
    primary, layout, chart_ids, alternates = DEFAULTS.get(kind, DEFAULTS["table"])
    alternates = list(alternates)
    rules = ["profile_" + kind]
    notes = []
    if facts.get("port_type") == "walk_sample":
        chart_ids = ["route", "visits"]
        alternates = ["walk", "visit_heat", *alternates]
    if facts.get("problem") == "link-prediction":
        alternates.insert(0, "predicted_edges")
    if facts.get("problem") == "temporal-paths":
        alternates.insert(0, "timeline")
    if kind == "instances":
        alternates.insert(0, "occurrence_overlay")
    if kind == "graph":
        alternates.insert(0, "input_comparison")
    roles = facts["field_roles"]
    role_names = set(row["role"] for row in roles.values())
    count_only = "metric" in role_names and role_names <= {"metric", "diagnostic"}
    if facts.get("port_type") == "learning_metrics":
        primary, layout, chart_ids, alternates = "table", "none", ["prediction_metrics"], []
        rules.append("recorded_learning_metrics")
    elif count_only and not (kind == "flow" and view.get("vertex_count", 0)):
        primary, layout, chart_ids, alternates = "metric", "none", [], ["table"]
        rules.append("count_only")
    elif kind == "instances" and facts.get("port_type") == "table":
        primary, layout, chart_ids, alternates = "table", "none", ["recorded_counts"], []
        rules.append("count_table")
    elif kind == "bipartite":
        rules.append("bipartite_items")
    elif kind in {"partition", "groups"}:
        if facts["groups"]["count"] > 8 and not facts["groups"]["overlap"] and facts["groups"].get("statistics_complete", True):
            primary = "meta_graph"
            alternates = ["graph", *[v for v in alternates if v != "meta_graph"]]
            rules.append("partition_many_groups")
        else:
            rules.append("partition_few_groups")
    if kind == "subgraph" and facts.get("coverage") is not None and facts["coverage"] >= .8:
        rules.append("subgraph_covers_input")
        notes.append("The returned vertices cover most of the saved input.")
    graph = facts.get("witness") or facts.get("input") or {}
    if graph.get("density") is not None and graph["density"] > .3 and graph.get("vertices", 0) <= 300:
        if "matrix" not in alternates and primary != "matrix":
            alternates.insert(0, "matrix")
        rules.append("dense_small_graph")
    nodes = {
        "color": {"field": "vertex_type", "scale": "categorical"},
        "size": {"field": "degree", "scale": "sqrt", "range_px": [14, 36]},
        "label": {"field": "display_name", "density": "all" if view.get("vertex_count", 0) <= 60 else "selected_and_ranked"},
        "shape": {"field": "role", "scale": "categorical"},
    }
    legend = [{"channel": "color", "field": "vertex_type", "title": "Entity type"}, {"channel": "size", "field": "degree", "title": "Connections in input"}]
    if kind in {"groups", "partition", "colors"}:
        nodes["color"]["field"] = "group"
        legend[0] = {"channel": "color", "field": "group", "title": "Color class" if kind == "colors" else "Group"}
    if kind == "bipartite":
        nodes["color"]["field"] = "side"
        legend[0] = {"channel": "color", "field": "side", "title": "Bipartite side"}
    scores = facts.get("scores")
    ranking_namespace = roles.get("entity", {}).get("namespace") if facts.get("port_type") == "entity_ranking" else "input"
    if scores and ranking_namespace == "input" and kind not in {"colors", "intervals", "spectrum", "samples"}:
        scale = "symlog" if scores["signed"] and abs(scores["skew"]) > 2 else "log1p" if scores["minimum"] >= 0 and scores["skew"] > 2 else "sqrt"
        nodes["size"] = {"field": "score", "scale": scale, "domain": [scores["minimum"], scores["maximum"]], "range_px": [14, 36]}
        nodes["lightness"] = {"field": "score", "scale": "diverging" if scores["signed"] else "sequential", "domain": [scores["minimum"], scores["maximum"]]}
        legend[1] = {"channel": "size", "field": "score", "title": scores["field"], "scale": scale}
        if scale in {"log1p", "symlog"}:
            rules.append("scores_skewed")
    if len(graph.get("vertex_types", {})) > 1:
        rules.append("typed_vertices")
        if kind in {"groups", "partition", "colors", "bipartite", "scores", "predictions"}:
            nodes["shape"]["field"] = "vertex_type"
            legend.append({"channel": "shape", "field": "vertex_type", "title": "Entity type"})
    if kind == "bipartite" and nodes["shape"].get("field") == "vertex_type":
        side_types = [{v.get("view", {}).get("vertex_type") for v in view.get("vertices", [])
                       if v.get("view", {}).get("side") == side} for side in (0, 1)]
        if all(len(values) == 1 for values in side_types) and not side_types[0] & side_types[1]:
            nodes["shape"] = {"value": "ellipse", "scale": "constant"}
            legend = [row for row in legend if row["channel"] != "shape"]
            rules.append("redundant_type_shape_removed")
    if kind == "predictions":
        nodes["color"]["field"] = "prediction"
        legend[0] = {"channel": "color", "field": "prediction", "title": "Predicted class or value"}
    nodes["color"]["categories"] = category_encoding(nodes["color"]["field"], view, facts)
    if nodes["shape"].get("field") == "vertex_type":
        nodes["shape"]["categories"] = [
            {"value": name, "label": name, "shape": type_shape(name)}
            for name in sorted(graph.get("vertex_types", {}))
        ]
    if len(graph.get("edge_types", {})) > 1:
        rules.append("typed_edges")
    if not view.get("graph_available") and primary == "graph":
        primary, layout = "table", "none"
        notes.append("This output does not contain a recorded graph witness.")
    sides = view.get("bipartite_names", ["Left", "Right"]) if kind == "bipartite" else []
    linked = [{"id": name, "chart": CHARTS[name][0], "title": CHARTS[name][1], "dataset": name, "x": CHARTS[name][2], "y": CHARTS[name][3], "select": CHARTS[name][4]} for name in chart_ids]
    sampled = bool(view.get("vertices_truncated") or view.get("edges_truncated"))
    visible = len(view.get("vertices", []))
    # WebGL is only enabled after the renderer benchmark and feature gate. The
    # saved spec records the request; client capability may safely fall back.
    large = visible > 2000 or len(view.get("edges", [])) > 5000
    if large:
        rules.append("large_graph")
    if not facts["statistics_complete"]:
        notes.append("Distribution and type summaries use a bounded scan; counts retain their saved totals.")
    edge_color = {"field": "relationship_type", "scale": "categorical"}
    edge_width = {"field": "flow" if kind == "flow" else "weight", "scale": "sqrt", "range_px": [1, 4]}
    if scores and ranking_namespace == "input_edge":
        edge_color = {"field": "score", "scale": "diverging" if scores["signed"] else "sequential"}
        edge_width["field"] = "score"
        legend.append({"channel": "width", "field": "score", "title": "Edge anomaly score"})
        rules.append("edge_scores")
    return ViewSpec.model_validate({
        "rules_version": RULES_VERSION, "profile": kind, "view": primary, "title": profile["title"],
        "layout": {"name": layout, "seed": 0, "sides": sides, "positions_source": "saved" if layout == "computed" else "server" if visible > 500 else "browser",
                   "alternates": list(dict.fromkeys([layout, "force", "grid"] if layout != "force" else ["force", "concentric", "grid"]))[:3] if layout != "none" else []},
        "nodes": nodes, "edges": {"color": edge_color, "width": edge_width, "style": {"field": "edge_role", "scale": "categorical"}, "arrows": {"value": bool(graph.get("directed") or kind == "flow")}},
        "legend": legend, "linked": linked, "alternates": [name for name in dict.fromkeys(alternates) if name != "table"],
        "emphasis": {"item": view.get("index"), "context_opacity": .25},
        "limits": {"shown_vertices": visible, "total_vertices": view.get("vertex_count", 0), "shown_edges": len(view.get("edges", [])), "total_edges": view.get("edge_count", 0), "sampled": sampled, "collection_complete": view.get("complete", True)},
        "rules_applied": rules, "notes": notes, "field_roles": roles,
        "provenance": provenance or {}, "renderer": "cytoscape-webgl" if large else "cytoscape",
    }).model_dump()
