from __future__ import annotations

from typing import Any

from .models import VisualizationKind, VisualizationSpec


def default_visualizations(
    operation_id: str, payload: dict[str, Any]
) -> list[VisualizationSpec]:
    """Safe fallback views; the analyst model may replace or extend them."""

    output = payload.get("output", {})
    views: list[VisualizationSpec] = []
    if operation_id == "community-detection":
        views.append(
            VisualizationSpec(
                type=VisualizationKind.network,
                title="Detected communities",
                data_ref="output.assignment_by_vertex",
                encodings={"node_id": "vertex", "node_color": "community"},
                interactions=["zoom", "pan", "select_node", "filter"],
                description="Vertices colored by their assigned community.",
            )
        )
        if "communities" in output:
            views.append(
                VisualizationSpec(
                    type=VisualizationKind.bar,
                    title="Community membership",
                    data_ref="output.communities",
                    encodings={"category": "id", "value": "vertices.length"},
                    interactions=["select_row", "filter"],
                )
            )
    elif operation_id == "betweenness-centrality":
        views.extend(
            [
                VisualizationSpec(
                    type=VisualizationKind.network,
                    title="Betweenness centrality",
                    data_ref="output.score_by_vertex",
                    encodings={
                        "node_id": "vertex",
                        "node_size": "score",
                        "node_color": "score",
                    },
                    interactions=["zoom", "pan", "select_node"],
                ),
                VisualizationSpec(
                    type=VisualizationKind.bar,
                    title="Highest-centrality vertices",
                    data_ref="output.ranking"
                    if "ranking" in output
                    else "output.score_by_vertex",
                    encodings={"category": "vertex", "value": "score"},
                    interactions=["select_row", "filter"],
                    limit=50,
                ),
            ]
        )
    elif operation_id == "k-core":
        views.extend(
            [
                VisualizationSpec(
                    type=VisualizationKind.network,
                    title="Core decomposition",
                    data_ref="output.core_number_by_vertex",
                    encodings={"node_id": "vertex", "node_color": "core_number"},
                    interactions=["zoom", "pan", "select_node", "filter"],
                ),
                VisualizationSpec(
                    type=VisualizationKind.histogram,
                    title="Core-number distribution",
                    data_ref="output.core_number_by_vertex",
                    encodings={"value": "core_number"},
                    interactions=["brush", "filter"],
                ),
            ]
        )
    elif operation_id == "temporal-motif-mining":
        views.append(
            VisualizationSpec(
                type=VisualizationKind.timeline,
                title="Temporal motif instances",
                data_ref="output.instances" if "instances" in output else "output",
                encodings={
                    "vertices": "vertices_by_role",
                    "edges": "edges_in_temporal_order",
                },
                interactions=["time_range", "select_row", "filter"],
            )
        )
    elif operation_id == "graph-motifs":
        views.append(
            VisualizationSpec(
                type=VisualizationKind.bar,
                title="Motif counts",
                data_ref="output.motifs",
                encodings={"category": "motif_id", "value": "count"},
                interactions=["select_row", "filter"],
            )
        )
    elif operation_id == "triangle-counting":
        views.append(
            VisualizationSpec(
                type=VisualizationKind.metric_cards,
                title="Triangle summary",
                data_ref="output",
                encodings={"primary": "global_triangle_count"},
            )
        )
        if "per_vertex_count" in output:
            views.append(
                VisualizationSpec(
                    type=VisualizationKind.bar,
                    title="Triangles per vertex",
                    data_ref="output.per_vertex_count",
                    encodings={"category": "vertex", "value": "count"},
                    interactions=["select_row", "filter"],
                    limit=100,
                )
            )
    elif operation_id == "dynamic-triangle-counting":
        views.append(
            VisualizationSpec(
                type=VisualizationKind.metric_cards,
                title="Triangle update summary",
                data_ref="output",
                encodings={
                    "deleted": "deleted_triangle_count",
                    "inserted": "inserted_triangle_count",
                    "net": "net_triangle_change",
                },
            )
        )
    else:
        candidate_fields = {
            "maximal-cliques": "cliques",
            "maximum-clique": "cliques",
            "k-cliques": "cliques",
            "quasi-cliques": "quasi_cliques",
            "maximal-bicliques": "bicliques",
            "subgraph-isomorphism": "embeddings",
        }
        field = candidate_fields.get(operation_id)
        if field and field in output:
            views.append(
                VisualizationSpec(
                    type=VisualizationKind.network,
                    title=f"{operation_id.replace('-', ' ').title()} results",
                    data_ref=f"output.{field}",
                    encodings={"selection": "items"},
                    interactions=["zoom", "pan", "select_row", "filter"],
                    limit=1_000,
                )
            )
        views.append(
            VisualizationSpec(
                type=VisualizationKind.table,
                title="Result details",
                data_ref="output",
                interactions=["select_row", "filter"],
                limit=1_000,
            )
        )
    return views


def path_exists(payload: Any, path: str) -> bool:
    current = payload
    for component in path.split("."):
        if isinstance(current, dict) and component in current:
            current = current[component]
        else:
            return False
    return True


def sanitize_visualizations(
    visualizations: list[VisualizationSpec], payload: dict[str, Any]
) -> list[VisualizationSpec]:
    return [item for item in visualizations if path_exists(payload, item.data_ref)]
