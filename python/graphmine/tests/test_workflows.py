"""Dependent results checked against independent peeling and linear algebra."""

from copy import deepcopy
from itertools import combinations

import networkx as nx
import numpy as np
import pytest
from graphmine import Graph, list_algorithms, run
from graphmine.exceptions import GraphMineError
from graphmine.workflows import execute_workflow, validate_workflow


def inputs(graph=None):
    graph = graph or Graph.from_edges([(0, "0"), ("0", 2), (2, 0), (2, 3)])
    return {"main": {"kind": "graph", "data": graph.to_canonical()}}


def workflow():
    return {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "core",
                "operation": "k-core",
                "input": {"input": "main"},
                "parameters": {"requested_k": 2},
            },
            {
                "id": "sub",
                "operation": "induced-subgraph",
                "parameters": {"mode": "induced"},
                "input": {"input": "main"},
                "bindings": {"vertices_or_seeds": {"step": "core", "port": "vertices"}},
            },
            {
                "id": "rank",
                "operation": "pagerank",
                "input": {"step": "sub", "port": "graph"},
            },
        ],
    }


CASES = [
    (i, len(g), list(g.edges)) for i, g in enumerate(nx.graph_atlas_g()) if len(g) <= 6
]


@pytest.mark.parametrize("operation", ["k-cliques", "triangle-counting"])
@pytest.mark.parametrize("case,n,edges", [case for case in CASES if case[1] <= 5])
def test_requested_listing_completeness_separate_from_exact_count(
    operation, case, n, edges
):
    graph = Graph.from_edges(edges, vertices=range(n))
    edge_set = {frozenset(edge) for edge in edges}
    expected = {
        frozenset(group)
        for group in combinations(range(n), 3)
        if all(frozenset(edge) in edge_set for edge in combinations(group, 2))
    }
    parameters = {
        "result_limit": 1,
        **(
            {"k": 3, "mode": "enumerate"}
            if operation == "k-cliques"
            else {"mode": "enumerate"}
        ),
    }
    result = run(operation, graph, parameters=parameters, device="cpu")
    assert result["ports"]["count"]["value"] == len(expected)
    assert result["ports"]["count"]["complete"]
    rows = result["ports"]["groups"]["value"]
    assert {frozenset(row["vertices"]) for row in rows} <= expected
    assert len(rows) == min(1, len(expected))
    assert (
        result["complete"]
        == result["ports"]["groups"]["complete"]
        == (len(expected) <= 1)
    )
    if operation == "k-cliques":
        counted = run(
            operation, graph, parameters={"k": 3, "mode": "count"}, device="cpu"
        )
        assert counted["complete"]
        assert not counted["ports"]["groups"]["complete"]


@pytest.mark.parametrize("case,n,edges", CASES)
def test_derived_core_pagerank(case, n, edges):
    graph = Graph.from_edges(edges, vertices=range(n))
    result = execute_workflow(workflow(), inputs(graph))
    assert result["status"] == "completed", result
    assert result["complete"]
    selected = set(range(n))
    while True:
        keep = {
            v
            for v in selected
            if sum(v in e and set(e) <= selected for e in edges) >= 2
        }
        if keep == selected:
            break
        selected = keep
    assert result["steps"]["core"]["result"]["ports"]["vertices"]["value"] == sorted(
        selected
    )
    derived = result["steps"]["sub"]["result"]["ports"]["graph"]
    assert {v["id"] for v in derived["value"]["vertices"]} == selected
    assert {
        frozenset((e["source"], e["target"])) for e in derived["value"]["edges"]
    } == {frozenset(e) for e in edges if set(e) <= selected}
    assert (
        result["steps"]["rank"]["result"]["input_fingerprint"]
        == derived["graph_fingerprint"]
    )
    rows = result["steps"]["rank"]["result"]["ports"]["scores"]["value"]
    if not selected:
        assert rows == []
    else:
        vertices = sorted(selected)
        matrix = np.array(
            [
                [int((u, v) in edges or (v, u) in edges) for v in vertices]
                for u in vertices
            ],
            dtype=float,
        )
        transition = matrix / matrix.sum(axis=1)[:, None]
        expected = np.linalg.solve(
            np.eye(len(vertices)) - 0.85 * transition.T,
            np.full(len(vertices), 0.15 / len(vertices)),
        )
        assert [r["score"] for r in rows] == pytest.approx(expected, abs=1e-8)


def test_cards_and_forward_references():
    assert len(list_algorithms()) == 82
    assert all(c["output_ports"] for c in list_algorithms())
    plan = workflow()
    plan["steps"].reverse()
    assert validate_workflow(plan, inputs())["order"] == ["core", "sub", "rank"]
    result = execute_workflow(plan, inputs())
    assert result["steps"]["sub"]["result"]["result"]["graph"]["vertices"] == [
        {"id": 0},
        {"id": "0"},
        {"id": 2},
    ]


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(version=True),
        lambda p: p.update(device=[]),
        lambda p: p.update(steps=[]),
        lambda p: p.update(code="print(1)"),
        lambda p: p["steps"][0].update(operation="invented"),
        lambda p: p["steps"][0].update(id="../escape"),
        lambda p: p["steps"][1].update(id="core"),
        lambda p: p["steps"][1]["bindings"]["vertices_or_seeds"].update(step=[]),
        lambda p: p["steps"][0].update(input={"input": "missing"}),
        lambda p: p["steps"][0].update(input={"input": "main", "step": "sub"}),
        lambda p: p["steps"][0].update(input={"step": "core", "port": "vertices"}),
        lambda p: p["steps"][1]["bindings"]["vertices_or_seeds"].update(port="missing"),
        lambda p: p["steps"][1]["bindings"]["vertices_or_seeds"].update(
            select={"kind": "eval", "code": "1"}
        ),
        lambda p: p["steps"][1].update(parameters={"vertices_or_seeds": [0]}),
        lambda p: p["steps"][0].update(parameters={"requested_k": True}),
        lambda p: p["steps"][0].update(parameters={"requested_k": float("nan")}),
        lambda p: p["steps"][0].update(budget={"max_candidates": 0}),
        lambda p: p["steps"][0].update(device="gpu"),
    ],
)
def test_invalid_plans_fail_before_execution(change):
    plan = workflow()
    change(plan)
    with pytest.raises(GraphMineError):
        validate_workflow(plan, inputs())


def test_cycle_and_input_kind():
    plan = workflow()
    plan["steps"][0]["input"] = {"step": "sub", "port": "graph"}
    with pytest.raises(GraphMineError, match="cycle"):
        validate_workflow(plan, inputs())
    bad = inputs()
    bad["main"]["kind"] = []
    with pytest.raises(GraphMineError, match="kind"):
        validate_workflow(workflow(), bad)


def test_namespace_mismatch_and_blocked_dependents():
    data = inputs()
    data["other"] = inputs(Graph.from_edges([(0, "0")], vertices=[0, "0", 2, 3]))[
        "main"
    ]
    plan = workflow()
    plan["steps"][1]["input"] = {"input": "other"}
    result = execute_workflow(plan, data)
    assert result["steps"]["core"]["status"] == "completed"
    assert "different input graph" in result["steps"]["sub"]["error"]["message"]
    assert result["steps"]["rank"]["status"] == "blocked"
    assert not result["complete"]


@pytest.mark.parametrize("mode,limit", [("count", None), ("enumerate", 1)])
def test_incomplete_and_count_only_collections_rejected(mode, limit):
    plan = workflow()
    plan["steps"][0].update(
        operation="k-cliques", parameters={"k": 2, "mode": mode, "result_limit": limit}
    )
    plan["steps"][1]["bindings"]["vertices_or_seeds"] = {
        "step": "core",
        "port": "groups",
        "select": {"kind": "flatten_groups"},
    }
    result = execute_workflow(plan, inputs())
    assert result["steps"]["sub"]["status"] == "failed"
    assert result["steps"]["rank"]["status"] == "blocked"


def test_missing_conditional_port():
    plan = workflow()
    plan["steps"][0]["parameters"] = {}
    result = execute_workflow(plan, inputs())
    assert "did not produce" in result["steps"]["sub"]["error"]["message"]


def test_score_selector_and_vertex_id_binding():
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "degree",
                "operation": "degree-centrality",
                "input": {"input": "main"},
            },
            {
                "id": "distance",
                "operation": "single-source-shortest-paths",
                "input": {"input": "main"},
                "bindings": {
                    "source": {
                        "step": "degree",
                        "port": "scores",
                        "select": {"kind": "top_vertex"},
                    }
                },
            },
            {
                "id": "sub",
                "operation": "induced-subgraph",
                "parameters": {"mode": "induced"},
                "input": {"input": "main"},
                "bindings": {
                    "vertices_or_seeds": {
                        "step": "distance",
                        "port": "distances",
                        "select": {"kind": "top_vertices", "k": 2, "descending": False},
                    }
                },
            },
        ],
    }
    result = execute_workflow(plan, inputs())
    assert result["status"] == "completed", result
    assert result["steps"]["distance"]["result"]["parameters"]["source"] == 2
    assert {
        v["id"] for v in result["steps"]["sub"]["result"]["result"]["graph"]["vertices"]
    } == {0, 2}


def test_resume_corruption_parameters_inputs_and_source_invalidation(monkeypatch):
    plan, data = workflow(), inputs()
    first = execute_workflow(plan, data)
    second = execute_workflow(plan, data, resume=first["steps"])
    assert all(r["reused"] for r in second["steps"].values())
    broken = deepcopy(first["steps"])
    broken["core"]["result"]["ports"]["vertices"]["value"] = [3]
    result = execute_workflow(plan, data, resume=broken)
    assert not result["steps"]["core"]["reused"]
    assert result["steps"]["sub"]["reused"]  # recomputation restores identical input
    plan["steps"][0]["parameters"]["requested_k"] = 1
    result = execute_workflow(plan, data, resume=first["steps"])
    assert not any(r["reused"] for r in result["steps"].values())
    changed = inputs(Graph.from_edges([(0, "0"), ("0", 2)], vertices=[0, "0", 2, 3]))
    result = execute_workflow(workflow(), changed, resume=first["steps"])
    assert not any(r["reused"] for r in result["steps"].values())
    monkeypatch.setattr("graphmine.workflows.implementation_hash", lambda: "changed")
    result = execute_workflow(workflow(), data, resume=first["steps"])
    assert not any(r["reused"] for r in result["steps"].values())


def test_gpu_variant_and_edge_id_bindings_are_checked():
    plan = workflow()
    plan["device"] = "gpu"
    with pytest.raises(
        GraphMineError,
        match="No compiled GPU profile|Explicit induced selection uses native CPU",
    ):
        validate_workflow(plan, inputs())
    plan = workflow()
    plan["steps"][1] = {
        "id": "cycles",
        "operation": "bounded-paths-cycles",
        "input": {"input": "main"},
        "parameters": {"task": "cycle_through_edge", "max_hops": 4},
        "bindings": {
            "anchor_edge": {
                "step": "core",
                "port": "vertices",
                "select": {"kind": "vertex", "index": 0},
            }
        },
    }
    plan["steps"].pop()
    with pytest.raises(GraphMineError, match="Incompatible binding"):
        validate_workflow(plan, inputs())


def test_independent_steps_continue_after_failure_and_emit_status():
    plan = workflow()
    plan["steps"][0]["budget"] = {"max_output_items": 1}
    plan["steps"].append(
        {
            "id": "independent",
            "operation": "triangle-counting",
            "input": {"input": "main"},
        }
    )
    events = []
    result = execute_workflow(plan, inputs(), emit=events.append)
    assert result["steps"]["core"]["status"] == "failed"
    assert result["steps"]["rank"]["status"] == "blocked"
    assert result["steps"]["independent"]["result"]["ports"]["count"]["value"] == 1
    assert [e["step"] for e in events if e["event"] == "step_finished"] == result[
        "order"
    ]
