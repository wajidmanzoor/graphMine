import json

from graphmine_agent.analytics_context import (
    matched_entities,
    resolve_selection,
    summarize_port,
    summarize_result,
)
from graphmine_agent.analytics_planning import PlanningSelection

CLIQUES = {
    "type": "vertex_groups",
    "complete": True,
    "value": [
        {"group": 0, "vertices": ["a", "b"]},
        {"group": 1, "vertices": ["a", "b", "c", "d"]},
        {"group": 2, "vertices": ["c", "d", "e"]},
    ],
}


def saved(*ports):
    return {
        "order": ["core"],
        "steps": {
            "core": {
                "status": "completed",
                "result": {
                    "operation": "maximal-cliques",
                    "complete": True,
                    "quality": "exact",
                    "ports": dict(ports),
                },
            }
        },
    }


def test_port_summaries_keep_the_facts_a_follow_up_needs():
    groups = summarize_port(CLIQUES)
    assert groups["items"] == 3
    assert groups["largest"][0] == {"index": 1, "group": 1, "size": 4}
    assert groups["largest_members"] == ["a", "b", "c", "d"]
    partition = summarize_port(
        {
            "type": "vertex_partition",
            "value": [
                {"vertex": v, "part": p} for v, p in zip("abcde", [0, 0, 1, 0, 1])
            ],
        }
    )
    assert partition["parts"] == 2
    assert partition["largest_parts"][0] == {"part": 0, "size": 3}
    scores = summarize_port(
        {
            "type": "vertex_scores",
            "score_field": "rank",
            "value": [{"vertex": "a", "rank": 0.1}, {"vertex": "b", "rank": 0.7}],
        }
    )
    assert scores["highest"][0]["vertex"] == "b"
    assert summarize_port({"type": "scalar", "value": 7})["value"] == 7


def test_result_summaries_shrink_to_fit_the_budget():
    huge = {
        "type": "vertex_groups",
        "value": [
            {"group": i, "vertices": [f"v{i}-{j}" for j in range(300)]}
            for i in range(50)
        ],
    }
    full = summarize_result(saved(("cliques", huge)))
    small = summarize_result(saved(("cliques", huge)), budget=600)
    assert len(json.dumps(small)) <= 600 < len(json.dumps(full))
    assert small[0]["operation"] == "maximal-cliques"


def test_selection_is_resolved_from_the_saved_result():
    selection = PlanningSelection(
        workflow_id="w", step="core", port="cliques", index=2, label="Clique 3"
    )
    resolved = resolve_selection(saved(("cliques", CLIQUES)), selection)
    assert resolved["vertices"] == ["c", "d", "e"] and resolved["size"] == 3
    assert resolved["binding_selection"] == {"kind": "group_vertices", "index": 2}
    assert (
        resolve_selection(
            saved(("cliques", CLIQUES)), selection.model_copy(update={"index": 9})
        )
        is None
    )


def test_entities_are_found_across_the_full_input_not_only_samples():
    vertices = [{"id": i, "label": f"person-{i}"} for i in range(5000)]
    vertices.append({"id": "acct-77", "attributes": {"name": "Valjean"}})
    inputs = {"main": {"data": {"vertices": vertices, "edges": []}}}
    found = matched_entities("Who is connected to Valjean and person-4321?", inputs)
    assert {row["id"] for row in found} == {"acct-77", 4321}
    # Short IDs need to be named as vertices; plain numbers are not entities.
    assert matched_entities("Find groups of 3", inputs) == []
    assert [row["id"] for row in matched_entities("Start at vertex 3", inputs)] == [3]
