"""Separate answer-contract checks; not a substitute for visual/user review."""

from __future__ import annotations

import re

from ..graph_context import field_value
from ..models import FollowupAction
from ..presentation import answer_tables, followup_options
from .oracles import selected_graph

JARGON = re.compile(
    r"\b(?:cliques?|betweenness|k-core|Bron.Kerbosch|mce-gpu)\b", re.IGNORECASE
)


def check_presentation(graph, task, outcome):
    issues = []
    response = outcome.get("response", {})
    if task["behavior"] == "clarify" and JARGON.search(response.get("message", "")):
        issues.append("Clarification requires graph-mining vocabulary")
    if task["behavior"] != "execute" or not outcome.get("result"):
        return issues
    result = outcome["result"]
    answer = result.get("answer", {})
    interpretation = result.get("interpretation") or {}
    if not answer or not interpretation:
        return ["Missing materialized answer/presentation"]
    facts = {f["statement"] for f in answer.get("facts", [])}
    if (
        interpretation.get("summary") not in facts
        or not set(interpretation.get("findings", [])) <= facts
    ):
        issues.append("Displayed factual text is outside the computed fact set")
    if interpretation.get("limitations") != answer.get("limitations"):
        issues.append("Displayed limitations differ from server-owned context")
    display = " ".join(
        [
            interpretation.get("summary", ""),
            *interpretation.get("limitations", []),
            *interpretation.get("suggested_followups", []),
        ]
    )
    if JARGON.search(display) or "Assumption:" in display:
        issues.append("Primary answer exposes technical or unverified planner notes")
    types = {v.get("type") for v in graph["vertices"]}
    if types in ({"protein"}, {"participant"}) and "entities" in interpretation.get(
        "summary", ""
    ):
        issues.append("Primary answer omits the known application vocabulary")
    if answer.get("tables") != answer_tables(
        answer.get("rows", []), answer.get("groups", [])
    ):
        issues.append(
            "Readable table membership or attributes disagree with the answer"
        )
    allowed = {
        x["id"]: FollowupAction.model_validate(x).model_dump(mode="json")
        for x in followup_options(answer)
    }
    views = {x["id"] for x in interpretation.get("visualizations", [])}
    actions = interpretation.get("followup_actions", [])
    if not actions:
        issues.append("No executable/view follow-up actions")
    for action in actions:
        if action != allowed.get(action.get("id")):
            issues.append("Follow-up is not a supported source-bound action")
        elif action["kind"] == "show_view" and action["view_id"] not in views:
            issues.append("Follow-up references an unavailable view")
    evidence = answer.get("provenance", {}).get("filter_evidence", [])
    if len(evidence) != len(task["filters"]):
        issues.append("Missing exact-field filter evidence")
    for condition, row in zip(task["filters"], evidence):
        selected = selected_graph(graph, [condition])
        target = condition["target"]
        if (
            row.get("filter") != condition
            or row.get("matched_records") != len(selected[target])
            or row.get("source_records") != len(graph[target])
        ):
            issues.append("Filter evidence names the wrong predicate or count")
        numeric = []
        for record in graph[target]:
            try:
                value = field_value(record, condition["field"])
            except KeyError:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric.append(value)
        profile = row.get("field_statistics", {})
        if numeric and (
            profile.get("minimum") != min(numeric)
            or profile.get("maximum") != max(numeric)
        ):
            issues.append("Filter statistics belong to a different column")
    return issues
