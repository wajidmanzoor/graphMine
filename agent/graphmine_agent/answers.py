"""Materialize trustworthy application-facing answers before narration/rendering."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .graph_context import (
    attribute_profile,
    display_name,
    identity,
    project_graph,
    timestamp_unit,
)
from .models import EvidenceItem, ExecutionPlan, Interpretation, VisualizationSpec
from .presentation import answer_tables, followup_options


def build_answer(
    graph: dict[str, Any],
    plan: ExecutionPlan,
    payload: dict[str, Any],
    *,
    source_hash: str,
) -> dict[str, Any]:
    filters = plan.application_intent.filters if plan.application_intent else []
    original = graph
    types = {row.get("type") for row in graph["vertices"]}
    entity_type = next(iter(types)) if len(types) == 1 and None not in types else None
    noun = {
        "employee": "employees",
        "participant": "participants",
        "customer": "customers",
        "account": "accounts",
        "protein": "proteins",
        "host": "hosts",
        "airport": "airports",
        "product": "products",
        "router": "routers",
    }.get(entity_type, "entities")
    graph = project_graph(graph, filters)
    vertices = {identity(row["id"]): row for row in graph["vertices"]}
    edge_by_id = {identity(row["id"]): row for row in graph["edges"]}
    incident = defaultdict(set)
    for index, edge in enumerate(graph["edges"]):
        incident[identity(edge["source"])].add(index)
        incident[identity(edge["target"])].add(index)
    output = payload.get("output", {})
    operation = plan.operation_id
    facts: list[dict[str, Any]] = []
    limitations: list[str] = []
    groups: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    selected: set[str] = set()
    metrics: dict[str, Any] = {}

    def fact(statement: str, value: Any, source: str, kind: str = "computed") -> None:
        facts.append(
            {
                "id": f"fact_{len(facts)}",
                "statement": statement,
                "value": value,
                "source": source,
                "kind": kind,
            }
        )

    def node(identifier: Any, **extra: Any) -> dict[str, Any]:
        record = vertices.get(identity(identifier))
        if record is None:
            raise ValueError(
                f"Result references a vertex outside its input graph: {identifier!r}"
            )
        return {
            **record,
            "key": identity(identifier),
            "label": display_name(record),
            **extra,
        }

    def add_group(identifier: Any, members: list[Any], **extra: Any) -> None:
        keys = {identity(value) for value in members}
        if not keys <= vertices.keys():
            raise ValueError("Result group references vertices outside its input graph")
        selected.update(keys)
        touching = {index for key in keys for index in incident[key]}
        internal = [
            graph["edges"][index]
            for index in touching
            if identity(graph["edges"][index]["source"]) in keys
            and identity(graph["edges"][index]["target"]) in keys
        ]
        boundary = [
            graph["edges"][index]
            for index in touching
            if (identity(graph["edges"][index]["source"]) in keys)
            != (identity(graph["edges"][index]["target"]) in keys)
        ]
        records = [vertices[key] for key in keys]
        attributes = {
            key: value
            for key, value in attribute_profile(records).items()
            if key.startswith("attributes.") or key == "type"
        }
        groups.append(
            {
                "id": identifier,
                "label": f"Group {len(groups) + 1}",
                "vertices": members,
                "members": [
                    display_name(vertices[identity(value)]) for value in members
                ],
                "size": len(keys),
                "internal_connections": len(internal),
                "external_connections": len(boundary),
                "attribute_summary": attributes,
                **extra,
            }
        )

    if operation == "connected-components":
        membership = defaultdict(list)
        for item in output["component_assignment"]:
            membership[item["component"]].append(item["vertex"])
        for component, members in membership.items():
            add_group(component, members)
        metrics.update(
            component_count=output["component_count"],
            component_sizes=output["component_sizes"],
        )
        mode = plan.parameters["connectivity_mode"]
        meaning = (
            "paths in both directions"
            if mode == "strongly_connected"
            else "paths ignoring direction"
        )
        fact(
            f"Found {output['component_count']} connected groups using {meaning}.",
            metrics,
            "output.component_assignment",
        )
    elif operation == "max-flow-min-cut":
        metrics.update(
            max_flow_value=output["max_flow_value"],
            min_cut_value=output["min_cut_value"],
            optimal=output["optimal"],
        )
        source = node(plan.parameters["source"])["label"]
        sink = node(plan.parameters["sink"])["label"]
        fact(
            f"The maximum flow from {source} to {sink} is {output['max_flow_value']}; the minimum cut has capacity {output['min_cut_value']}.",
            metrics,
            "output",
        )
        cut = [edge_by_id[identity(value)] for value in output["min_cut_edges"]]
        names = [
            f"{node(edge['source'])['label']} → {node(edge['target'])['label']}"
            for edge in cut[:10]
        ]
        fact(
            f"The minimum cut contains {len(cut)} relationships"
            + (": " + "; ".join(names) if names else "")
            + ".",
            output["min_cut_edges"],
            "output.min_cut_edges",
        )
        selected.update(
            identity(value) for value in output.get("source_side_vertices", [])
        )
        limitations.append(
            "Capacities constrain each directed relationship; vertex capacities and fractional capacities are not supported."
        )
    elif operation == "linear-assignment":
        from .graph_context import field_value

        metrics.update(
            matching_size=output["matching_size"],
            objective_value=output["objective_value"],
            optimal=output["optimal"],
        )
        fact(
            f"Assigned {output['matching_size']} pairs with minimum total cost {output['objective_value']}.",
            metrics,
            "output",
        )
        cost_field = (
            plan.application_intent.weight_attribute
            if plan.application_intent and plan.application_intent.weight_attribute
            else "weight"
        )
        for edge_id in output["matching_edges"]:
            edge = edge_by_id[identity(edge_id)]
            left, right = edge["source"], edge["target"]
            if vertices[identity(left)]["attributes"]["side"] != "left":
                left, right = right, left
            rows.append(
                node(
                    left,
                    assigned_to=node(right)["label"],
                    assignment_cost=field_value(edge, cost_field),
                )
            )
        limitations.append(
            "The result is a minimum-cost perfect assignment on the supplied complete square bipartite graph."
        )
    elif operation == "transitive-closure":
        metrics.update(
            reachable_pair_count=output["reachable_pair_count"],
            complete=output["complete"],
        )
        fact(
            f"There are {output['reachable_pair_count']} reachable ordered pairs, including each entity reaching itself.",
            metrics,
            "output.reachable_pair_count",
        )
        limitations.append(
            "Full directed reachability is materialized in the result; no reusable reachability index was built."
        )
    elif operation == "butterfly-counting":
        metrics.update(
            butterfly_count=output["butterfly_count"], complete=output["complete"]
        )
        fact(
            f"Found {output['butterfly_count']} distinct patterns in which two entities on each side share all four cross-group relationships.",
            metrics,
            "output.butterfly_count",
        )
        limitations.append(
            "This is a global count; individual participation counts and core decomposition were not computed."
        )
    elif operation == "community-detection":
        membership: dict[Any, list[Any]] = defaultdict(list)
        for item in output.get("assignment_by_vertex", []):
            membership[item["community"]].append(item["vertex"])
        for group_id, members in membership.items():
            add_group(group_id, members)
        metrics.update(
            community_count=output.get("community_count", len(groups)),
            assigned_entities=sum(g["size"] for g in groups),
        )
        fact(
            f"Found {metrics['community_count']} groups among {metrics['assigned_entities']} {noun}, based on their connections.",
            metrics,
            "output.assignment_by_vertex",
        )
        limitations.append(
            "These are connection-based groups, not verified departments, fraud rings, or statistically significant segments."
        )
        assignments = {
            identity(item["vertex"]): item["community"]
            for item in output.get("assignment_by_vertex", [])
        }
        crossing = [
            edge
            for edge in graph["edges"]
            if assignments.get(identity(edge["source"]))
            != assignments.get(identity(edge["target"]))
        ]
        if crossing:
            named = [
                f"{display_name(vertices[identity(edge['source'])])} ↔ {display_name(vertices[identity(edge['target'])])}"
                for edge in crossing[:8]
            ]
            fact(
                f"{len(crossing)} recorded connections join different groups: {', '.join(named)}"
                + (", …" if len(crossing) > 8 else "."),
                {"count": len(crossing), "examples": named},
                "original_graph.edges + output.assignment_by_vertex",
            )
    elif operation in {"betweenness-centrality", "k-core"}:
        key, measure = (
            ("score_by_vertex", "score")
            if operation == "betweenness-centrality"
            else ("core_number_by_vertex", "core_number")
        )
        values = output.get(key, [])
        threshold = (
            plan.parameters.get("requested_k") if operation == "k-core" else None
        )
        if threshold is not None:
            values = [row for row in values if row[measure] >= threshold]
        values = sorted(
            values, key=lambda row: (-row[measure], identity(row["vertex"]))
        )
        ranks = {}
        rows = [
            node(
                row["vertex"],
                **{
                    measure: row[measure],
                    "rank": ranks.setdefault(row[measure], index + 1),
                },
            )
            for index, row in enumerate(values)
        ]
        selected.update(row["key"] for row in rows)
        metrics["returned_entities"] = len(rows)
        if operation == "k-core":
            fact(
                f"{len(rows)} {noun} remain"
                + (
                    f" after repeatedly removing {noun} with fewer than {threshold} partners."
                    if threshold is not None
                    else " in the connection-core analysis."
                ),
                len(rows),
                f"output.{key}",
            )
            if threshold is not None and rows:
                add_group("core", [row["id"] for row in rows])
        elif rows:
            top = rows[0]["score"]
            leaders = [row["label"] for row in rows if row["score"] == top]
            statement = (
                f"{', '.join(leaders[:8])} {'ranks' if len(leaders) == 1 else 'rank'} highest for connecting shortest routes between other {noun} (score {top:g})."
                if top != 0
                else f"All {noun} have a shortest-route mediation score of 0; this measure does not distinguish a connector in this sample."
            )
            fact(statement, {"leaders": leaders, "score": top}, f"output.{key}")
            limitations.append(
                "This score measures shortest-route mediation in this graph; it does not measure actual traffic, business value, or causation."
            )
        else:
            fact(f"No {noun} matched the requested analysis.", 0, f"output.{key}")
    elif operation == "temporal-motif-mining":
        metrics["matching_sequences"] = output.get("count", 0)
        fact(
            f"Found {metrics['matching_sequences']} matching ordered event sequences within the requested time window.",
            metrics["matching_sequences"],
            "output.count",
        )
        used_edges = set()
        for index, instance in enumerate(output.get("instances", [])):
            ids = instance.get("edges_in_temporal_order", [])
            members = instance.get("vertices_by_role", [])
            if isinstance(members, dict):
                members = list(members.values())
            add_group(index, members)
            for order, edge_id in enumerate(ids):
                edge = edge_by_id.get(identity(edge_id))
                if edge is None:
                    raise ValueError("Matched event is missing from the original graph")
                used_edges.add(identity(edge_id))
                events.append(
                    {
                        **edge,
                        "sequence": index + 1,
                        "order": order + 1,
                        "source_label": display_name(
                            vertices[identity(edge["source"])]
                        ),
                        "target_label": display_name(
                            vertices[identity(edge["target"])]
                        ),
                    }
                )
        if output.get("instances_complete") and "instances" in output:
            unused = len(graph["edges"]) - len(used_edges)
            fact(
                f"{len(used_edges)} distinct events participate in the matches; {unused} input events do not.",
                {"used": len(used_edges), "unused": unused},
                "output.instances",
            )
        limitations.append(
            "This tool matches the ordered three-entity pattern A→B, B→C, A→C only; it does not detect arbitrary event chains."
        )
    else:
        group_field = {
            "maximal-cliques": "cliques",
            "maximum-clique": "cliques",
            "k-cliques": "cliques",
            "quasi-cliques": "quasi_cliques",
            "maximal-bicliques": "bicliques",
            "triangle-counting": "triangles",
            "subgraph-isomorphism": "embeddings",
        }.get(operation)
        for index, item in enumerate(
            output.get(group_field, []) if group_field else []
        ):
            extra = {}
            if isinstance(item, list):
                members = item
                if members and isinstance(members[0], dict):
                    members = [entry["data_vertex"] for entry in members]
            else:
                members = item.get("vertices", item.get("clique", []))
                if "left" in item:
                    members = item["left"] + item["right"]
                    extra = {"left": item["left"], "right": item["right"]}
                if "mapping" in item:
                    members = [entry["data_vertex"] for entry in item["mapping"]]
            add_group(index, members, **extra)
        for key, value in output.items():
            if isinstance(value, (int, float, bool, str)):
                metrics[key] = value
        if operation == "maximum-clique":
            size = output.get(
                "clique_number",
                output.get("maximum_size", max((g["size"] for g in groups), default=0)),
            )
            fact(
                f"The largest returned fully connected group contains {size} {noun}.",
                size,
                "output",
            )
            if output.get("optimal") is not True:
                limitations.append(
                    "A returned group is not a proof of the global maximum unless the solver reports optimality."
                )
        elif operation == "triangle-counting":
            fact(
                f"Found {output.get('global_triangle_count', 0)} three-entity groups where every pair is connected.",
                output.get("global_triangle_count", 0),
                "output.global_triangle_count",
            )
        elif groups:
            fact(
                f"Found {len(groups)} matching groups of {noun}.",
                len(groups),
                f"output.{group_field}",
            )
        elif group_field and (
            output.get("total_count") == 0
            or (output.get("complete") is True and output.get(group_field) == [])
        ):
            fact(
                f"No groups of {noun} match the requested conditions.",
                {"matching_groups": 0, "complete": True},
                "output",
            )
        else:
            fact(
                "The analysis returned these computed measurements.", metrics, "output"
            )

    for group in groups[:10]:
        names = ", ".join(group["members"][:8]) + (", …" if group["size"] > 8 else "")
        fact(
            f"{group['label']}: {names}. {group['size']} {noun}."
            + (
                f" {group['internal_connections']} connections within the group and {group['external_connections']} to others."
                if operation == "community-detection"
                else ""
            ),
            {
                key: group[key]
                for key in (
                    "id",
                    "size",
                    "internal_connections",
                    "external_connections",
                )
            },
            "original_graph + result membership",
        )
    for group in groups[:10]:
        for field, profile in [
            (key, value)
            for key, value in group["attribute_summary"].items()
            if key != "type"
            and not key.endswith("_id")
            and key
            not in {"attributes.name", "attributes.gene_name", "attributes.label"}
        ][:3]:
            if profile["examples"]:
                description = (
                    f"average {profile['mean']:.3g}; range {profile['minimum']:g}–{profile['maximum']:g}"
                    if "mean" in profile
                    else "; ".join(
                        f"{entry['value']}: {entry['count']}"
                        for entry in profile["examples"]
                    )
                )
                fact(
                    f"{group['label']} — {field.removeprefix('attributes.').replace('_', ' ')}: {description}.",
                    profile,
                    "original_graph.attributes",
                    "attribute_summary",
                )

    memberships: dict[str, list[Any]] = defaultdict(list)
    for group in groups:
        for identifier in group["vertices"]:
            memberships[identity(identifier)].append(group["id"])
    if not rows:
        rows = [
            node(
                vertices[key]["id"],
                groups=memberships[key],
                community=memberships[key][0] if memberships[key] else None,
            )
            for key in sorted(selected)
        ]
    else:
        for row in rows:
            row["groups"] = memberships[row["key"]]
            if row["groups"]:
                row["community"] = row["groups"][0]
    for row in rows[:10] if operation == "betweenness-centrality" else []:
        fact(
            f"{row['label']}: shortest-route mediation score {row['score']:g}.",
            {"id": row["id"], "score": row["score"]},
            "output.score_by_vertex",
        )

    filter_evidence = []
    for condition in filters:
        # Statistics belong to this exact field, not a similarly named column.
        single = project_graph(original, [condition])
        count = len(single[condition.target])
        profile = attribute_profile(original[condition.target]).get(condition.field, {})
        evidence = {
            "filter": condition.model_dump(mode="json"),
            "matched_records": count,
            "source_records": len(original[condition.target]),
            "field_statistics": profile,
        }
        filter_evidence.append(evidence)
        field = condition.field.removeprefix("attributes.").replace("_", " ")
        relation = {
            "eq": "=",
            "ne": "≠",
            "gt": ">",
            "gte": "≥",
            "lt": "<",
            "lte": "≤",
            "in": "in",
        }[condition.operator]
        value = json.dumps(condition.value, ensure_ascii=False)
        scope = noun if condition.target == "vertices" else "relationships"
        statement = f"Filter {field} {relation} {value[:120]}: {count} of {len(original[condition.target])} supplied {scope} match this condition."
        if "minimum" in profile:
            statement += f" Recorded {field} ranges from {profile['minimum']:g} to {profile['maximum']:g}."
        fact(
            statement,
            evidence,
            f"original_graph.{condition.target}.{condition.field}",
            "filter_evidence",
        )
    if filters:
        fact(
            f"After applying all filters, the analysis uses {len(graph['vertices'])} {noun} and {len(graph['edges'])} relationships.",
            {"vertices": len(graph["vertices"]), "edges": len(graph["edges"])},
            "projected_graph",
            "scope",
        )

    # Exact answer selection FIRST, display limits SECOND. Never join against the
    # first N vertices of an upload preview.
    view_nodes = rows[:500]
    view_ids = {row["key"] for row in view_nodes}
    event_ids = (
        {identity(row["id"]) for row in events}
        if operation == "temporal-motif-mining"
        else None
    )
    answer_edges = [
        edge
        for edge in graph["edges"]
        if identity(edge["source"]) in selected
        and identity(edge["target"]) in selected
        and (event_ids is None or identity(edge["id"]) in event_ids)
    ]
    view_edges = [
        {
            **edge,
            "source_key": identity(edge["source"]),
            "target_key": identity(edge["target"]),
        }
        for edge in answer_edges
        if identity(edge["source"]) in view_ids and identity(edge["target"]) in view_ids
    ][:2000]
    complete = output.get(
        "complete",
        output.get(
            "instances_complete",
            output.get(
                "embeddings_complete", output.get("changed_instances_complete", True)
            ),
        ),
    )
    if not complete:
        limitations.append(
            "Returned instances are incomplete; membership and attribute summaries describe only the materialized matches."
        )
    if len(rows) > len(view_nodes) or len(answer_edges) > len(view_edges):
        limitations.append(
            f"The network view displays {len(view_nodes)} of {len(rows)} answer entities and {len(view_edges)} of {len(answer_edges)} answer connections."
        )
    if operation in {"max-flow-min-cut", "linear-assignment"}:
        if plan.parameters.get("unit_capacity"):
            limitations.append(
                "Each relationship was assigned capacity one as requested; original weights were not used."
            )
    elif any("weight" in edge for edge in graph["edges"]):
        limitations.append(
            "Original weights are retained for display; this computation does not use them as costs or strengths."
        )
    if entity_type == "protein":
        limitations.append(
            "Recorded associations do not establish physical binding, causation, or experimental success."
        )
    if entity_type == "participant":
        limitations.append(
            "Recorded contacts in this supplied sample do not establish friendship, productivity, or transmission."
        )
    return {
        "question": plan.application_intent.objective
        if plan.application_intent
        else "",
        "operation_id": operation,
        "entity_noun": noun,
        "facts": facts,
        "metrics": metrics,
        "groups": groups,
        "rows": rows,
        "events": events,
        "tables": answer_tables(rows, groups),
        "network": {
            "nodes": view_nodes,
            "edges": view_edges,
            "layout": "bipartite" if operation == "maximal-bicliques" else "groups",
            "groups": [
                {key: g[key] for key in ("id", "label", "size")} for g in groups
            ],
            "default_group": groups[0]["id"] if len(groups) > 12 else None,
            "entity_noun": noun,
            "total_nodes": len(rows),
            "total_edges": len(answer_edges),
            "truncated": len(rows) > len(view_nodes)
            or len(answer_edges) > len(view_edges),
        },
        "limitations": list(dict.fromkeys(limitations)),
        "diagnostics": {
            "backend_notes": [str(value) for value in payload.get("warnings", [])],
            "unverified_planner_notes": plan.application_intent.assumptions
            if plan.application_intent
            else [],
            "note": "Planner notes are unverified and are not factual answer evidence.",
        },
        "provenance": {
            "source_sha256": source_hash,
            "graph_id": plan.graph_id,
            "directed": graph["graph"]["directed"],
            "filters": [f.model_dump() for f in filters],
            "filter_evidence": filter_evidence,
            "input_vertices": len(vertices),
            "input_edges": len(graph["edges"]),
            "attribute_use": "joined from original input for explanation and display; filters are applied before execution",
            "timestamp_unit": timestamp_unit(graph),
        },
    }


def answer_interpretation(
    answer: dict[str, Any],
    views: list[VisualizationSpec],
    *,
    fact_ids: list[str] | None = None,
    hypotheses: list[str] | None = None,
    followups: list[str] | None = None,
    followup_ids: list[str] | None = None,
) -> Interpretation:
    facts = answer["facts"]
    requested = set(fact_ids or [fact["id"] for fact in facts[:6]])
    chosen = [fact for fact in facts if fact["id"] in requested][:8] or facts[:6]
    # The main computed outcome is always visible, even if the model omitted it.
    if facts and facts[0] not in chosen:
        chosen.insert(0, facts[0])
    # Scope and empty-result evidence must survive narrative selection too.
    for item in facts:
        if item["kind"] in {"filter_evidence", "scope"} and item not in chosen:
            chosen.append(item)
    options = followup_options(answer)
    selected_actions = [
        item for item in options if item["id"] in (followup_ids or [])
    ] or options
    return Interpretation(
        summary=chosen[0]["statement"],
        findings=[item["statement"] for item in chosen],
        limitations=answer["limitations"],
        hypotheses=hypotheses or [],
        evidence=[
            EvidenceItem(
                claim=item["statement"],
                data_ref=f"answer.facts.{facts.index(item)}.value",
                value=item["value"],
            )
            for item in chosen
        ],
        # Legacy free-form suggestions are retained in inference history only.
        suggested_followups=[item["label"] for item in selected_actions],
        followup_actions=selected_actions,
        visualizations=views,
    )
