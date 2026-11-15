"""Views must describe saved witnesses, including inputs outside UI previews."""

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from graphmine_agent.analytics import AnalyticsError, AnalyticsService
from graphmine_agent.result_views import PROFILES, focus_graph, input_graph, result_view


def graph():
    return {
        "graph": {"id": "example", "directed": True},
        "vertices": [{"id": v} for v in [0, 1, "1", 2, 3, 4]],
        "edges": [
            {"id": "01", "source": 0, "target": 1, "weight": 1},
            {"id": "01-expensive", "source": 0, "target": 1, "weight": 9},
            {"id": "12", "source": 1, "target": 2, "weight": 2},
            {"id": "02-chord", "source": 0, "target": 2, "weight": 10},
            {"id": "23", "source": 2, "target": 3, "weight": 3},
            {"id": "text", "source": "1", "target": 3, "weight": 4},
        ],
    }


def result(operation, typ, value, **extra):
    return {
        "operation": operation,
        "ports": {"out": {"type": typ, "value": value, "complete": True}},
        **extra,
    }


def ids(g, kind):
    return [v["id"] for v in g[kind]]


def test_all_declared_native_operations_have_intentional_views():
    # The runtime's public output contract is independent of the view registry.
    source = Path(__file__).resolve().parents[2] / "python/graphmine/graphmine/ports.py"
    assignment = next(
        n
        for n in ast.parse(source.read_text()).body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "OUTPUT_PORTS" for t in n.targets)
    )
    OUTPUT_PORTS = ast.literal_eval(assignment.value)
    assert set(OUTPUT_PORTS) <= set(PROFILES)
    assert len(PROFILES) == 82
    assert all(p["preferred_ports"] and p["blocks"] for p in PROFILES.values())


def test_shortest_path_excludes_chords_parallel_alternatives_and_other_destinations():
    g = graph()
    rows = [
        {"vertex": v, "distance": d, "predecessor": p}
        for v, d, p in [(0, 0, None), (1, 1, 0), (2, 3, 1), (3, 6, 2), (4, None, None)]
    ]
    output = result("single-source-shortest-paths", "vertex_scores", rows)
    before = deepcopy((g, output))
    view, note, vertices, edges = focus_graph(g, output, "out", 2)
    assert vertices == [0, 1, 2] and edges == ["12", "01"]
    assert set(ids(view, "edges")) == {"01", "12"}
    assert "path" in note
    assert (g, output) == before
    unreachable = focus_graph(g, output, "out", 4)[0]
    assert unreachable["vertices"] == [] and unreachable["edges"] == []


def test_widest_path_uses_capacity_witness_and_missing_predecessors_do_not_invent_paths():
    rows = [
        {"vertex": 0, "predecessor": None, "reachable": True},
        {"vertex": 1, "predecessor": 0, "reachable": True},
    ]
    view = focus_graph(
        graph(), result("widest-paths", "widest_path_tree", rows), "out", 1
    )[0]
    assert ids(view, "edges") == ["01-expensive"]
    view, note, _, _ = focus_graph(
        graph(),
        result(
            "single-source-shortest-paths",
            "vertex_scores",
            [{"vertex": 1, "distance": 1}],
        ),
        "out",
        0,
    )
    assert view is None and "predecessor" in note
    assert (
        focus_graph(
            graph(),
            result(
                "many-source-shortest-paths",
                "table",
                [{"source": 0, "target": 2, "distance": 3}],
            ),
            "out",
        )[0]
        is None
    )


def test_densest_induces_only_returned_members_and_preserves_typed_ids():
    view, _, selected, _ = focus_graph(
        graph(), result("densest-subgraph", "vertex_set", ["1", 3]), "out"
    )
    assert selected == ["1", 3]
    assert ids(view, "edges") == ["text"]


@pytest.mark.parametrize(
    "typ,value,expected",
    [
        ("path_set", [{"vertices": [0, 1, 2], "edges": ["01", "12"]}], ["01", "12"]),
        ("edge_sequence_collection", [["12", "23"]], ["12", "23"]),
        (
            "temporal_path_table",
            [{"vertex": 2, "edges": ["01", "12"], "reachable": True}],
            ["01", "12"],
        ),
        ("walk_sample", [[0, 1, 2]], ["01", "12"]),
        (
            "temporal_occurrence_collection",
            [
                {
                    "vertices": [
                        {"query_vertex": "a", "data_vertex": 1},
                        {"query_vertex": "b", "data_vertex": 2},
                    ],
                    "edge_ids": ["12"],
                }
            ],
            ["12"],
        ),
    ],
)
def test_path_formats_show_recorded_connections_only(typ, value, expected):
    view = focus_graph(
        graph(),
        result("temporal-motifs" if "occurrence" in typ else "query-paths", typ, value),
        "out",
    )[0]
    assert ids(view, "edges") == expected


@pytest.mark.parametrize(
    "typ,value",
    [
        (
            "vertex_mappings",
            [
                [
                    {"query_vertex": 99, "data_vertex": 1},
                    {"query_vertex": 100, "data_vertex": 2},
                ]
            ],
        ),
        (
            "motif_instances",
            {
                "triangle": [
                    [
                        {"query_vertex": "a", "data_vertex": 1},
                        {"query_vertex": "b", "data_vertex": 2},
                    ]
                ]
            },
        ),
        ("graphlet_instances", {"g2": [[1, 2]]}),
    ],
)
def test_occurrence_formats_resolve_data_ids(typ, value):
    view = focus_graph(graph(), result("subgraph-isomorphism", typ, value), "out", 0)[0]
    assert ids(view, "vertices") == [1, 2] and ids(view, "edges") == ["12"]


def test_flow_uses_recorded_edge_ids_in_parallel_network():
    output = result(
        "max-flow-min-cut",
        "vertex_set",
        [0],
        result={
            "flows": [
                {"edge": "01-expensive", "source": 0, "target": 1, "flow": 2},
                {"edge": "01", "source": 0, "target": 1, "flow": 0},
            ]
        },
    )
    assert ids(focus_graph(graph(), output, "out")[0], "edges") == ["01-expensive"]


def test_context_uses_full_immediate_input_and_default_group_is_explicit():
    g = graph()
    g["vertices"] = [{"id": i} for i in range(700)]
    g["edges"] = [{"id": "far", "source": 650, "target": 699}]
    output = result(
        "maximal-cliques", "vertex_groups", [{"group": 0, "vertices": [650, 699]}]
    )
    record = {
        "id": "w",
        "revision": 3,
        "input_files": {"main": {"file_id": "original"}},
        "validation": {
            "plan": {
                "steps": [
                    {"id": "derived", "input": {"input": "main"}},
                    {"id": "mine", "input": {"step": "derived", "port": "graph"}},
                ]
            }
        },
    }
    service = SimpleNamespace(
        get=lambda _: record,
        _directory=lambda _: Path("/unused"),
        _saved=lambda _, step, **_options: {
            "result": output
            if step == "mine"
            else {"ports": {"graph": {"type": "graph", "value": g}}}
        },
    )
    assert input_graph(service, record, "mine") is g
    view = result_view(service, "w", "mine", "out")
    assert ids(view, "vertices") == [650, 699] and view["index"] == 0
    assert view["vertex_count"] == 2 and view["source_file_ids"] == ["original"]
    context = result_view(service, "w", "mine", "out", context=True)
    assert context["vertex_count"] == 700 and context["vertices_truncated"]
    assert context["selected_vertices"] == [650, 699]
    assert {650, 699}.issubset({v["id"] for v in context["vertices"]})
    assert [e["id"] for e in context["edges"]] == ["far"]


def test_lookup_table_uses_declared_vertex_field_and_preserves_id_type():
    graph = {"graph": {"directed": False}, "vertices": [{"id": "0"}, {"id": 0}], "edges": []}
    saved = {"operation": "node-lookup", "ports": {
        "rows": {"type": "table", "vertex_field": "id", "value": [{"id": "0", "name": "Ada"}]}
    }}
    focused, _, selected, _ = focus_graph(graph, saved, "rows", 0)
    assert selected == ["0"]
    assert focused["vertices"] == [{"id": "0"}]


@pytest.mark.parametrize(
    "typ,value",
    [
        ("scalar", 12),
        ("cross_graph_mapping", [{"source": 0, "target": 1}]),
        ("table", [{"motif": "triangle", "count": 12}]),
    ],
)
def test_counts_and_cross_graph_correspondences_do_not_fabricate_network(typ, value):
    assert focus_graph(graph(), result("motif-counting", typ, value), "out")[0] is None


def test_invalid_selection_and_predecessor_cycle_fail_closed():
    with pytest.raises(AnalyticsError):
        focus_graph(graph(), result("densest-subgraph", "vertex_set", [0]), "out", 1)
    rows = [{"vertex": 0, "predecessor": 1}, {"vertex": 1, "predecessor": 0}]
    with pytest.raises(AnalyticsError, match="cycle"):
        focus_graph(
            graph(),
            result("single-source-shortest-paths", "vertex_scores", rows),
            "out",
            1,
        )


def test_named_occurrence_pages_and_views_share_positions_without_mutating_results(
    monkeypatch, tmp_path,
):
    output = result(
        "graphlet-counting",
        "graphlet_instances",
        {"2": [[1, 2]], "10": [[0, 1]], "1": [["1", 3]]},
    )
    from test_analytics_group_views import indexed_fixture

    before = deepcopy(output)
    service = object.__new__(AnalyticsService)
    monkeypatch.setattr(
        service,
        "_indexed",
        lambda _, step=None, **_options: indexed_fixture(output, tmp_path, step),
    )
    summary = service.result_summary("w", limit=1)["steps"]["mine"]["result"]["ports"][
        "out"
    ]
    assert summary["value"] == [{"pattern": "1", "vertices": ["1", 3]}]
    assert summary["total_items"] == 3 and summary["presentation_only"]
    page = service.port_page("w", "mine", "out", 0, 2, search='pattern:"10"')
    assert page["positions"] == [1] and page["items"][0]["vertices"] == [0, 1]
    view = focus_graph(graph(), output, "out", page["positions"][0])[0]
    assert ids(view, "vertices") == [0, 1] and output == before
