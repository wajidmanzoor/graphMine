"""Readable, source-derived tables and bounded follow-up actions."""

from __future__ import annotations

from typing import Any

from .graph_context import identity


def result_status(operation: str, output: dict[str, Any]) -> list[dict[str, str]]:
    """Describe reported guarantees without inferring certainty from success."""
    status = []

    def add(label, detail, tone="neutral"):
        status.append({"label": label, "detail": detail, "tone": tone})

    if output.get("feasible") is False:
        add("No feasible solution", "No solution satisfies the supplied constraints.")
    elif output.get("approximate") is True or operation in {
        "personalized-pagerank",
        "influence-maximization",
    }:
        add(
            "Approximate result",
            "This method returns an approximation or sampled estimate; see its limitations.",
            "caution",
        )
    elif output.get("optimal") is True:
        add(
            "Optimal solution",
            "The solver reports an optimal solution for this objective.",
            "positive",
        )
    elif output.get("optimal") is False:
        add(
            "Optimality not certified",
            "The returned solution is not certified as globally optimal.",
            "caution",
        )

    # Top-k PageRank is a requested subset, not a failed enumeration.
    if operation != "personalized-pagerank" and isinstance(
        output.get("complete"), bool
    ):
        if output["complete"]:
            if any(
                field in output
                for field in (
                    "instances_complete",
                    "embeddings_complete",
                    "changed_instances_complete",
                )
            ):
                add(
                    "Computation complete",
                    "The computation is complete; the instance-list status is reported separately.",
                    "positive",
                )
            else:
                add(
                    "Complete result",
                    "The operation reports complete output.",
                    "positive",
                )
        else:
            add(
                "Partial result",
                "The operation did not return a complete result.",
                "caution",
            )
    for field in (
        "instances_complete",
        "embeddings_complete",
        "changed_instances_complete",
    ):
        if isinstance(output.get(field), bool):
            if output[field]:
                expected = {
                    "instances_complete": [
                        "triangles" if operation == "triangle-counting" else "instances"
                    ],
                    "embeddings_complete": ["embeddings"],
                    "changed_instances_complete": [
                        "deleted_triangles",
                        "inserted_triangles",
                    ],
                }[field]
                present = [isinstance(output.get(name), list) for name in expected]
                if all(present):
                    add(
                        "All instances returned",
                        "The operation reports that all matching instances were returned.",
                        "positive",
                    )
                elif any(present):
                    add(
                        "Limited instance list",
                        "Some optional instance lists were not returned.",
                        "caution",
                    )
                else:
                    add(
                        "Instance list not returned",
                        "The result does not include an individual instance list.",
                    )
            else:
                add(
                    "Limited instance list",
                    "The listed instances are a subset; they cannot establish every membership or absence.",
                    "caution",
                )
            break
    return status


def method_explanation(operation: str, parameters: dict[str, Any]) -> str:
    explanations = {
        "maximal-cliques": "Every pair of members in a group has a recorded connection. No other entity from the analysed graph can be added while keeping every pair connected; different groups can overlap.",
        "maximum-clique": "Every pair of members in the returned group has a recorded connection. The analysis searches for the largest such group; the result status states whether optimality was certified.",
        "community-detection": "The analysis groups entities using their connection patterns. Members of a group do not have to be connected to every other member, and connections can cross group boundaries.",
        "betweenness-centrality": "Higher scores identify entities that lie on more shortest routes between other pairs in this graph. Each link counts as one step; equal scores are ties.",
        "personalized-pagerank": "Scores describe proximity to the selected starting entity through outgoing, unweighted links. This profile returns the requested top ranks using a fixed restart probability of 0.2.",
        "triangle-counting": "Each match contains three distinct entities with a connection between every pair. A total count does not imply that every individual match was listed.",
        "densest-subgraph": "Density here is the number of internal undirected relationships divided by the number of group members. The objective does not fix the group size or use relationship weights.",
        "group-steiner-tree": "The analysis seeks a minimum-cost connected tree that reaches at least one member of every requested group. Intermediate entities may connect those groups; the result status reports whether a solution exists.",
        "influence-maximization": "The selected starting entities aim to spread activation under the independent-cascade model using the supplied probabilities. Reported spread is a sampled estimate, not an observed outcome.",
        "maximal-bicliques": "Each member on one side connects to every member on the other side. A member can belong to more than one returned group.",
        "maximal-biclique-counting": "The result counts maximal fully connected cross-group patterns. It does not list their individual members.",
        "butterfly-counting": "Each counted pattern contains two entities on each side and all four cross-group connections. The result is a total count, not a list of participants.",
        "temporal-motif-mining": "Each match follows the ordered events A to B, B to C, then A to C within the requested time window. Other event patterns are outside this operation's scope.",
        "quasi-cliques": "Every member must meet the requested minimum fraction of connections to the other members. This is a threshold for each member, rather than an average over the group. Returned groups also meet the requested minimum size.",
        "k-core": "A core number describes the largest remaining-partner threshold an entity survives when entities with too few partners are repeatedly removed. It is not simply the entity's original number of connections.",
        "k-truss": "An edge's truss number is the largest k for which it survives repeatedly removing edges in fewer than k−2 triangles. The computation uses an undirected graph with duplicate relationships and self-loops removed.",
        "dynamic-triangle-counting": "The result compares fully connected triplets before and after the supplied relationship changes. Added and removed triplets are counted separately; their difference is the net change.",
        "graph-motifs": "Each supplied pattern is counted separately. Patterns can overlap, so their counts should not be added to claim a number of distinct groups. The requested occurrence rule determines how different mappings of the same entities are counted.",
        "subgraph-isomorphism": "Each match maps distinct entities in the supplied pattern to distinct entities in your data while preserving the pattern's connections. The query and selected matching options determine which matches qualify.",
        "max-flow-min-cut": "Directed relationship capacities limit the flow from the chosen source to the destination. A minimum cut separates them with the smallest total capacity. These are capacities in the supplied model, not observations of real traffic.",
        "linear-assignment": "Each entity on one side is paired with exactly one entity on the other side, minimizing the total supplied cost. Every entity is used once in this complete, equal-size assignment profile.",
        "transitive-closure": "A reachable pair means a directed path exists from the first entity to the second, possibly through intermediates. Each entity also reaches itself. Reachability does not imply a direct relationship.",
    }
    if operation == "k-cliques" and isinstance(parameters.get("k"), int):
        return f"Each returned group contains exactly {parameters['k']} distinct entities, with a recorded connection between every pair. Different groups can share members."
    if operation == "densest-subgraph" and parameters.get("clique_order", 2) != 2:
        return f"Density is the number of fully connected groups of {parameters['clique_order']} entities inside the selected set, divided by the number of selected entities. Clique order does not fix the size of the selected set."
    if operation == "k-core" and isinstance(parameters.get("requested_k"), int):
        return f"Entities with fewer than {parameters['requested_k']} partners are repeatedly removed. Every remaining entity meets that threshold within the remaining graph."
    if operation == "connected-components":
        if parameters.get("connectivity_mode") == "strongly_connected":
            return "Every entity in a group can reach every other member by directed paths. A direct connection between each pair is not required. Different groups do not share members."
        return "Direction is ignored when grouping entities joined by paths. A direct connection between each pair is not required. Different groups do not share members."
    return explanations.get(operation, "")


def readable_fields(row: dict[str, Any]) -> dict[str, list[str]]:
    """Share column paths with clients without duplicating every result row."""
    result = {"Name": ["label"]}
    for name, title in (
        ("rank", "Rank"),
        ("score", "Connection score"),
        ("core_number", "Remaining-partner threshold"),
        ("assigned_to", "Assigned to"),
        ("assignment_cost", "Assignment cost"),
    ):
        if name in row:
            result[title] = [name]
    attrs = row.get("attributes", {})
    titles = {
        "string_id": "STRING ID",
        "participant_id": "Participant ID",
        "iata": "Airport code",
    }
    for name, value in attrs.items():
        if name in {"gene_name", "name", "display_name"} and str(value) == str(
            row["label"]
        ):
            continue
        # Complex records and adversarial notes remain inspectable in raw data,
        # not promoted into the primary answer table as instructions or prose.
        if name in {"import_note", "note", "description"} or isinstance(
            value, (dict, list)
        ):
            continue
        if len(result) >= 10:
            break
        title = titles.get(name, name.replace("_", " ").capitalize())
        if title in result or title == "Original ID":
            title = f"Attribute: {title}"
        result[title] = ["attributes", name]
    if not any(name in attrs for name in ("string_id", "participant_id", "iata")):
        result["Original ID"] = ["id"]
    return result


def readable_row(row: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for label, path in readable_fields(row).items():
        value = row
        for field in path:
            value = value[field]
        result[label] = value
    return result


def answer_tables(rows, groups, limit=1000):
    by_id = {identity(row["id"]): row for row in rows}
    members = [readable_row(row) for row in rows[:limit]]
    memberships = []
    total = sum(len(group["vertices"]) for group in groups)
    for group in groups:
        for identifier in group["vertices"]:
            if len(memberships) >= limit:
                break
            memberships.append(
                {"Group": group["label"], **readable_row(by_id[identity(identifier)])}
            )
        if len(memberships) >= limit:
            break
    columns = {}
    for row in rows:
        for label, path in readable_fields(row).items():
            if label not in columns and len(columns) < 15:
                columns[label] = path
        if len(columns) >= 15:
            break
    return {
        "members": members,
        "groups": memberships,
        "total_members": len(rows),
        "total_memberships": total,
        "truncated": len(rows) > len(members) or total > len(memberships),
        "columns": [{"label": label, "path": path} for label, path in columns.items()],
    }


def followup_options(answer):
    """Actions reference supplied answer views or requests through normal gates.

    No arbitrary code, model-authored capability claims or direct job submission.
    """
    if "steps" in answer:
        options = []
        for step_id, step in answer["steps"].items():
            for item in followup_options(step):
                if item["kind"] == "show_view":
                    options.append(
                        {
                            **item,
                            "id": f"{step_id}_{item['id']}",
                            "view_id": f"{step_id}_{item['view_id']}",
                        }
                    )
        return options[:3]
    noun = answer.get("entity_noun", "entities")
    options = []
    if answer["rows"]:
        options.append(
            {
                "id": "show_members",
                "label": f"Inspect the {noun} and their original attributes",
                "kind": "show_view",
                "view_id": "members",
            }
        )
    if answer["network"]["nodes"]:
        options.append(
            {
                "id": "show_connections",
                "label": "Explore connections in the answer",
                "kind": "show_view",
                "view_id": "network",
            }
        )
    if not options:
        options.append(
            {
                "id": "show_measurements",
                "label": "Inspect the computed result",
                "kind": "show_view",
                "view_id": "measurements",
            }
        )
    if answer["provenance"]["filters"]:
        options.append(
            {
                "id": "clear_scope",
                "label": "Repeat this question without the current filters",
                "kind": "ask",
                "request": "Repeat the same analysis using all records in this uploaded sample. Remove the current vertex and relationship filters; keep the other requirements unchanged.",
            }
        )
    elif answer["operation_id"] != "betweenness-centrality":
        options.append(
            {
                "id": "rank_connectors",
                "label": f"Which {noun} connect routes through this sample?",
                "kind": "ask",
                "request": f"Using the same sample and active filters, rank all {noun} by how often they lie between other pairs along routes with the fewest links. Count each link as one step, not as a weighted distance, and include original names and attributes.",
            }
        )
    return options[:3]
