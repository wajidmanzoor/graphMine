from __future__ import annotations

from typing import Any

from .models import VisualizationKind, VisualizationSpec


def answer_visualizations(
    answer: dict[str, Any], prefix: str = "answer", id_prefix: str = ""
) -> list[VisualizationSpec]:
    """Tested recipes reference materialized answers, never upload previews."""
    if "steps" in answer:
        return [
            view
            for key, step in answer["steps"].items()
            for view in answer_visualizations(step, f"{prefix}.steps.{key}", f"{key}_")
        ]
    views = []
    noun = answer.get("entity_noun", "entities")

    def add(kind, name, field, title, encodings=None, description=""):
        views.append(
            VisualizationSpec(
                id=id_prefix + name,
                type=kind,
                title=title,
                data_ref=f"{prefix}.{field}",
                encodings=encodings or {},
                description=description,
                interactions=["filter"] if kind in {"network", "table"} else [],
                limit=1000,
            )
        )

    if answer["events"]:
        add(
            "timeline",
            "events",
            "events",
            "Matching event sequences",
            {"time": "timestamp", "category": "sequence"},
            f"Only matched events; timestamps are from the original data. Unit: {answer['provenance']['timestamp_unit']}.",
        )
    if answer["operation_id"] == "betweenness-centrality" and answer["rows"]:
        add(
            "bar",
            "ranking",
            "rows",
            "Who connects the network?",
            {"category": "label", "value": "score"},
            "Shortest-route mediation scores; not measured traffic or business importance.",
        )
    if answer["network"]["nodes"]:
        nodes = answer["network"]["nodes"]
        color = "community"
        if answer["operation_id"] != "community-detection":
            for attribute in ("department", "category", "city", "organism"):
                if (
                    len(
                        {
                            str(node.get("attributes", {}).get(attribute))
                            for node in nodes
                        }
                    )
                    > 1
                ):
                    color = f"attributes.{attribute}"
                    break
        add(
            "network",
            "network",
            "network",
            f"Connections among the returned {noun}",
            {"node_id": "id", "node_label": "label", "node_color": color},
            "Inspect a returned group, or show the answer overview. Names and attributes come from the original data.",
        )
    if answer["groups"]:
        field = "tables.groups" if "tables" in answer else "groups"
        count = answer.get("tables", {}).get("total_memberships")
        add(
            "table",
            "groups",
            field,
            "Group membership",
            description=(
                f"Showing {len(answer['tables']['groups'])} of {count} memberships; one row per named member. "
                if count is not None
                else ""
            )
            + "The same member may appear in several groups. Original attributes are shown alongside each name.",
        )
    if answer["rows"]:
        field = "tables.members" if "tables" in answer else "rows"
        add(
            "table",
            "members",
            field,
            f"Returned {noun} and their attributes",
            description=f"{len(answer['rows'])} named {noun}; values joined from the original data.",
        )
    if not views:
        add(
            "metric_cards",
            "measurements",
            "metrics",
            "Computed result",
            description=answer["facts"][0]["statement"] if answer.get("facts") else "",
        )
    return views


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
        elif (
            isinstance(current, list)
            and component.isdigit()
            and int(component) < len(current)
        ):
            current = current[int(component)]
        else:
            return False
    return True


def sanitize_visualizations(
    visualizations: list[VisualizationSpec], payload: dict[str, Any]
) -> list[VisualizationSpec]:
    safe = []
    for item in visualizations:
        reference = item.data_ref.removeprefix("result.")
        if not path_exists(payload, reference):
            continue
        if any(
            not isinstance(condition, dict)
            or condition.get("operator")
            not in {"eq", "ne", "gt", "gte", "lt", "lte", "in"}
            or not isinstance(condition.get("field"), str)
            or "value" not in condition
            for condition in item.filters
        ):
            continue
        safe.append(item.model_copy(update={"data_ref": reference}))
    return safe
