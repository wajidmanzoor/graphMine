"""Complete database inputs and bounded, optional graph visualization."""

import json
from itertools import islice

GRAPH_PREVIEW_NODES = 500


def is_database_query(source):
    """Recognize provenance created by the server's database query executor."""
    while isinstance(source, dict):
        if source.get("type") == "database_query":
            return True
        parent = source.get("parent")
        source = parent.get("source") if source.get("type") == "upload" and isinstance(parent, dict) else None
    return False


def preview_message(vertex_count):
    return (
        f"Graph preview skipped: {vertex_count:,} nodes exceeds the "
        f"{GRAPH_PREVIEW_NODES:,}-node display threshold. "
        "The full graph is available for conversation and analysis."
    )


def skipped_graph_preview(vertex_count, edge_count, *, graph=None):
    return {
        "graph": graph or {}, "vertices": [], "edges": [],
        "vertex_count": vertex_count, "edge_count": edge_count,
        "vertices_truncated": True, "edges_truncated": bool(edge_count),
        "preview_skipped": True, "preview_message": preview_message(vertex_count),
    }


def graph_preview(graph, *, vertex_limit=GRAPH_PREVIEW_NODES, edge_limit=2_000):
    count, edge_count = len(graph["vertices"]), len(graph["edges"])
    if count > GRAPH_PREVIEW_NODES:
        return skipped_graph_preview(count, edge_count, graph=graph["graph"])
    vertices = graph["vertices"][:vertex_limit]
    keys = {json.dumps(vertex["id"], sort_keys=True) for vertex in vertices}
    edges = list(islice((
        edge for edge in graph["edges"]
        if json.dumps(edge["source"], sort_keys=True) in keys
        and json.dumps(edge["target"], sort_keys=True) in keys
    ), edge_limit))
    return {
        **graph, "vertices": vertices, "edges": edges,
        "vertex_count": count, "edge_count": edge_count,
        "vertices_truncated": len(vertices) < count,
        "edges_truncated": len(edges) < edge_count,
        "preview_skipped": False, "preview_message": None,
    }
