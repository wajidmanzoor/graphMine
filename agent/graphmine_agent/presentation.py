"""Readable, source-derived tables and bounded follow-up actions."""

from __future__ import annotations

from typing import Any

from .graph_context import identity


def readable_row(row: dict[str, Any]) -> dict[str, Any]:
    result = {"Name": row["label"]}
    for name, title in (
        ("rank", "Rank"),
        ("score", "Connection score"),
        ("core_number", "Remaining-partner threshold"),
        ("assigned_to", "Assigned to"),
        ("assignment_cost", "Assignment cost"),
    ):
        if name in row:
            result[title] = row[name]
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
        result[titles.get(name, name.replace("_", " ").capitalize())] = value
    if not any(name in attrs for name in ("string_id", "participant_id", "iata")):
        result["Original ID"] = row["id"]
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
    return {
        "members": members,
        "groups": memberships,
        "total_members": len(rows),
        "total_memberships": total,
        "truncated": len(rows) > len(members) or total > len(memberships),
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
