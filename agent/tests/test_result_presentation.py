from __future__ import annotations

import pytest
from graphmine_agent.answers import answer_interpretation, build_answer
from graphmine_agent.models import ApplicationIntent, ExecutionPlan
from graphmine_agent.presentation import (
    answer_tables,
    method_explanation,
    result_status,
)
from graphmine_agent.visualization import answer_visualizations


@pytest.mark.parametrize(
    ("operation", "output", "labels"),
    [
        ("maximum-clique", {}, []),
        ("maximum-clique", {"optimal": False}, ["Optimality not certified"]),
        ("maximum-clique", {"optimal": True}, ["Optimal solution"]),
        ("maximal-cliques", {"complete": False}, ["Partial result"]),
        ("maximal-cliques", {"complete": True}, ["Complete result"]),
        (
            "triangle-counting",
            {"instances_complete": True},
            ["Instance list not returned"],
        ),
        (
            "triangle-counting",
            {"instances_complete": True, "triangles": []},
            ["All instances returned"],
        ),
        (
            "subgraph-isomorphism",
            {"embeddings_complete": True},
            ["Instance list not returned"],
        ),
        (
            "dynamic-triangle-counting",
            {"changed_instances_complete": True, "inserted_triangles": []},
            ["Limited instance list"],
        ),
        (
            "triangle-counting",
            {"complete": True, "instances_complete": False},
            ["Computation complete", "Limited instance list"],
        ),
        (
            "personalized-pagerank",
            {"complete": False, "approximate": True},
            ["Approximate result"],
        ),
        ("influence-maximization", {"guarantee_met": False}, ["Approximate result"]),
        (
            "group-steiner-tree",
            {"feasible": False, "optimal": True},
            ["No feasible solution"],
        ),
    ],
)
def test_status_uses_only_reported_guarantees_and_preserves_partial_lists(
    operation, output, labels
):
    assert [item["label"] for item in result_status(operation, output)] == labels


@pytest.mark.parametrize("complete", [True, False])
def test_group_explanation_counts_distinct_members_and_survives_model_selection(
    complete,
):
    graph = {
        "graph": {"id": "overlap", "directed": False},
        "vertices": [
            {"id": value, "label": label, "type": "employee"}
            for value, label in [(0, "Ava"), (1, "Ben"), ("1", "Chen"), (3, "Divya")]
        ],
        "edges": [
            {"id": i, "source": a, "target": b}
            for i, (a, b) in enumerate([(0, 1), (0, "1"), (1, "1"), (1, 3), ("1", 3)])
        ],
    }
    plan = ExecutionPlan(
        session_id="session",
        graph_id="graph",
        operation_id="maximal-cliques",
        problem_id="maximal_clique_enumeration",
        application_intent=ApplicationIntent(
            objective="Find full collaboration groups"
        ),
    )
    answer = build_answer(
        graph,
        plan,
        {"output": {"cliques": [[0, 1, "1"], [1, "1", 3]], "complete": complete}},
        source_hash="source-hash",
    )
    comparison = next(
        fact for fact in answer["facts"] if fact["kind"] == "group_comparison"
    )
    assert comparison["value"] == {
        "returned_groups": 2,
        "smallest_group": 3,
        "largest_group": 3,
        "unique_members": 4,
        "members_in_multiple_groups": 2,
    }
    assert "Across these returned groups" in comparison["statement"]
    assert (
        "4 distinct employees; 2 belong to more than one group"
        in comparison["statement"]
    )
    interpretation = answer_interpretation(
        answer, answer_visualizations(answer), fact_ids=["fact_0"]
    )
    assert comparison["statement"] in interpretation.findings
    assert answer["provenance"]["source_vertices"] == 4
    assert answer["provenance"]["source_edges"] == 5
    assert "different groups can overlap" in answer["method_explanation"]
    assert answer["result_status"][0]["label"] == (
        "Complete result" if complete else "Partial result"
    )


def test_filter_scope_retains_original_counts_without_claiming_missing_data():
    graph = {
        "graph": {"id": "sample", "directed": False},
        "vertices": [{"id": i, "attributes": {"selected": i < 3}} for i in range(4)],
        "edges": [
            {"id": i, "source": a, "target": b}
            for i, (a, b) in enumerate([(0, 1), (1, 2), (0, 2), (2, 3)])
        ],
    }
    plan = ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id="maximal-cliques",
        problem_id="maximal_clique_enumeration",
        application_intent=ApplicationIntent(
            filters=[
                {
                    "target": "vertices",
                    "field": "attributes.selected",
                    "operator": "eq",
                    "value": True,
                }
            ]
        ),
    )
    answer = build_answer(
        graph,
        plan,
        {"output": {"cliques": [[0, 1, 2]], "complete": True}},
        source_hash="h",
    )
    assert answer["provenance"]["input_vertices"] == 3
    assert answer["provenance"]["input_edges"] == 3
    assert answer["provenance"]["source_vertices"] == 4
    assert answer["provenance"]["source_edges"] == 4


def test_every_executable_operation_has_a_readable_method(catalog):
    for operation in catalog.manifest_operations:
        assert method_explanation(operation, {"k": 3}), operation


def test_approved_undirected_projection_is_visible_even_when_narrator_omits_it():
    graph = {
        "graph": {"id": "directed", "directed": True},
        "vertices": [{"id": 0}, {"id": 1}],
        "edges": [{"id": 0, "source": 0, "target": 1}],
    }
    plan = ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id="maximal-cliques",
        problem_id="maximal_clique_enumeration",
        allow_directed_projection=True,
    )
    answer = build_answer(
        graph,
        plan,
        {"output": {"cliques": [[0, 1]], "complete": True}},
        source_hash="h",
    )
    interpretation = answer_interpretation(
        answer, answer_visualizations(answer), fact_ids=["fact_0"]
    )
    assert any("directions were ignored" in item for item in interpretation.findings)
    assert answer["network"]["directed"] is True


def test_complete_count_does_not_hide_a_partial_instance_list():
    graph = {
        "graph": {"id": "triangles", "directed": False},
        "vertices": [{"id": i} for i in range(4)],
        "edges": [
            {"id": i, "source": a, "target": b}
            for i, (a, b) in enumerate([(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)])
        ],
    }
    plan = ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id="triangle-counting",
        problem_id="triangle_counting",
    )
    answer = build_answer(
        graph,
        plan,
        {
            "output": {
                "global_triangle_count": 2,
                "triangles": [[0, 1, 2]],
                "complete": True,
                "instances_complete": False,
            }
        },
        source_hash="h",
    )
    assert answer["facts"][0]["value"] == 2
    assert "Limited instance list" in [
        item["label"] for item in answer["result_status"]
    ]
    assert any("incomplete" in limitation for limitation in answer["limitations"])
    assert {row["id"] for row in answer["rows"]} == {0, 1, 2}


def test_pattern_counts_have_views_and_do_not_invent_missing_memberships():
    graph = {
        "graph": {"id": "patterns", "directed": False},
        "vertices": [{"id": i, "label": f"Person {i}"} for i in range(4)],
        "edges": [
            {"id": i, "source": a, "target": b}
            for i, (a, b) in enumerate([(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)])
        ],
    }
    plan = ExecutionPlan(
        session_id="s",
        graph_id="g",
        operation_id="graph-motifs",
        problem_id="graph_motif_counting",
    )
    output = {
        "motifs": [
            {
                "motif_id": "triangle",
                "count": 2,
                "instances_complete": False,
                "instances": [
                    [{"motif_vertex": i, "data_vertex": i} for i in range(3)]
                ],
            },
            {"motif_id": "relationship", "count": 5, "instances_complete": True},
        ]
    }
    answer = build_answer(graph, plan, {"output": output}, source_hash="h")
    assert answer["pattern_rows"] == [
        {
            "Pattern": "triangle",
            "Matches": 2,
            "Listed matches": 1,
            "Instance list": "Partial list",
        },
        {
            "Pattern": "relationship",
            "Matches": 5,
            "Listed matches": 0,
            "Instance list": "Not returned",
        },
    ]
    assert len(answer["groups"]) == 1
    assert {row["id"] for row in answer["rows"]} == {0, 1, 2}
    assert len(answer["limitations"]) == 2
    views = answer_visualizations(answer)
    assert {view.id for view in views} >= {"pattern_counts", "patterns", "members"}
    interpretation = answer_interpretation(answer, views)
    assert any("triangle: 2 matches" in item for item in interpretation.findings)
    assert any("relationship: 5 matches" in item for item in interpretation.findings)


def test_table_projection_includes_later_columns_without_copying_every_row():
    rows = [
        {
            "id": i,
            "key": str(i),
            "label": f"Entity {i}",
            "score": i,
            "attributes": {"score": -i},
        }
        for i in range(1001)
    ]
    rows[-1]["attributes"]["source.with.dot"] = "late attribute"
    rows[-1]["attributes"]["note"] = "untrusted note"
    tables = answer_tables(rows, [{"label": "Group 1", "vertices": list(range(1001))}])
    assert len(tables["members"]) == len(tables["groups"]) == 1000
    assert tables["total_members"] == tables["total_memberships"] == 1001
    assert {
        "label": "Source.with.dot",
        "path": ["attributes", "source.with.dot"],
    } in tables["columns"]
    assert all(column["path"] != ["attributes", "note"] for column in tables["columns"])
    assert tables["members"][1]["Connection score"] == 1
    assert tables["members"][1]["Score"] == -1
