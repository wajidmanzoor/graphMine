"""Full correspondence enumeration and independently replayed edit witnesses."""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction
from itertools import combinations, permutations, product

import networkx as nx
import pytest
from graphmine import Budget, Graph, run
from graphmine.exceptions import GraphMineError, ResourceLimit
from graphmine.workflows import execute_workflow, validate_workflow

ATLAS = [
    (i, len(g), tuple(g.edges)) for i, g in enumerate(nx.graph_atlas_g()) if len(g) <= 4
]
ARCS = tuple((u, v) for u in range(3) for v in range(3) if u != v)
COSTS = {
    name: Fraction(1)
    for name in (
        "vertex_insertion",
        "vertex_deletion",
        "edge_insertion",
        "edge_deletion",
        "edge_substitution",
    )
}


def graph(n, edges, *, directed=False, labels=None, edge_labels=None, ids=None):
    ids = list(range(n)) if ids is None else ids
    data = Graph.from_edges(
        [(ids[u], ids[v]) for u, v in edges], vertices=ids, directed=directed
    ).to_canonical()
    if labels is not None:
        for vertex, label in zip(data["vertices"], labels, strict=True):
            vertex["label"] = label
    if edge_labels is not None:
        for edge, label in zip(data["edges"], edge_labels, strict=True):
            edge["type"] = label
    return data


def all_mappings(na, nb):
    for size in range(min(na, nb) + 1):
        for sources in combinations(range(na), size):
            for targets in permutations(range(nb), size):
                yield dict(zip(sources, targets, strict=True))


def labels(record, fields, ignore):
    return (
        "*"
        if ignore
        else json.dumps(
            {key: record[key] for key in fields if key in record}, sort_keys=True
        )
    )


def adjacency(data):
    ids = {row["id"]: i for i, row in enumerate(data["vertices"])}
    result = {}
    for edge in data["edges"]:
        endpoints = ids[edge["source"]], ids[edge["target"]]
        if not data["graph"]["directed"]:
            endpoints = tuple(sorted(endpoints))
        result[endpoints] = edge
    return result


def reference(
    a,
    b,
    *,
    ignore=False,
    costs=None,
    vertex_fields=("label", "type"),
    edge_fields=("type",),
):
    costs = {**COSTS, **{k: Fraction(str(v)) for k, v in (costs or {}).items()}}
    first, second = adjacency(a), adjacency(b)
    na, nb = len(a["vertices"]), len(b["vertices"])
    best, mcs_induced, mcs_noninduced = None, 0, 0
    for mapping in all_mappings(na, nb):
        image_edges = {}
        cost = (na - len(mapping)) * costs["vertex_deletion"] + (
            nb - len(mapping)
        ) * costs["vertex_insertion"]
        eligible = True
        for u, v in mapping.items():
            if labels(a["vertices"][u], vertex_fields, ignore) != labels(
                b["vertices"][v], vertex_fields, ignore
            ):
                cost += costs["vertex_deletion"] + costs["vertex_insertion"]
                eligible = False
        induced = eligible
        for (u, v), edge in first.items():
            if u not in mapping or v not in mapping:
                cost += costs["edge_deletion"]
                continue
            endpoints = mapping[u], mapping[v]
            if not a["graph"]["directed"]:
                endpoints = tuple(sorted(endpoints))
            image_edges[endpoints] = edge
            if endpoints not in second:
                cost += costs["edge_deletion"]
                induced = False
            elif labels(edge, edge_fields, ignore) != labels(
                second[endpoints], edge_fields, ignore
            ):
                cost += min(
                    costs["edge_substitution"],
                    costs["edge_insertion"] + costs["edge_deletion"],
                )
                induced = False
        images = set(mapping.values())
        for endpoints in second:
            if endpoints not in image_edges:
                cost += costs["edge_insertion"]
                if set(endpoints) <= images:
                    induced = False
        best = cost if best is None else min(best, cost)
        if induced:
            mcs_induced = max(mcs_induced, len(mapping))
        if eligible:
            mcs_noninduced = max(mcs_noninduced, len(mapping))
    return best, mcs_induced, mcs_noninduced


def replay(
    result,
    costs=None,
    *,
    ignore=False,
    vertex_fields=("label", "type"),
    edge_fields=("type",),
):
    """Apply each operation, checking live endpoints, cost rules and final data."""
    costs = {**COSTS, **{k: Fraction(str(v)) for k, v in (costs or {}).items()}}
    result = result["result"]
    source, target = result["normalized_source"], result["normalized_target"]
    vertex_records = {r["id"]: r for r in source["vertices"]}
    vertices = {
        r["vertex_handle"]: deepcopy(vertex_records[r["vertex"]])
        for r in result["source_vertex_handles"]
    }
    handles = {row["id"]: key for key, row in vertices.items()}
    edge_records = {r["id"]: r for r in source["edges"]}
    edges = {
        r["edge_handle"]: deepcopy(edge_records[r["edge"]])
        for r in result["source_edge_handles"]
    }
    for edge in edges.values():
        edge["source"], edge["target"] = (
            handles[edge["source"]],
            handles[edge["target"]],
        )
    total = Fraction()
    for step in result["edit_path"]:
        kind = step["operation"]
        if kind == "edge_deletion":
            assert step["edge_handle"] in edges
            del edges[step["edge_handle"]]
            expected = costs[kind]
        elif kind == "vertex_deletion":
            key = step["vertex_handle"]
            assert key in vertices
            assert all(key not in (e["source"], e["target"]) for e in edges.values())
            del vertices[key]
            expected = costs[kind]
        elif kind == "vertex_insertion":
            key = step["vertex_handle"]
            assert key not in vertices
            vertices[key] = deepcopy(step["vertex_record"])
            expected = costs[kind]
        elif kind == "vertex_substitution":
            key = step["vertex_handle"]
            before, after = vertices[key], step["vertex_record"]
            expected = (
                Fraction()
                if labels(before, vertex_fields, ignore)
                == labels(after, vertex_fields, ignore)
                else costs["vertex_insertion"] + costs["vertex_deletion"]
            )
            vertices[key] = deepcopy(after)
        elif kind in ("edge_substitution", "edge_insertion"):
            key, after = step["edge_handle"], step["edge_record"]
            assert after["source"] in vertices and after["target"] in vertices
            if kind == "edge_substitution":
                before = edges[key]
                old = before["source"], before["target"]
                new = after["source"], after["target"]
                assert (
                    old == new if source["graph"]["directed"] else set(old) == set(new)
                )
                expected = (
                    Fraction()
                    if labels(before, edge_fields, ignore)
                    == labels(after, edge_fields, ignore)
                    else costs[kind]
                )
            else:
                assert key not in edges
                expected = costs[kind]
            edges[key] = deepcopy(after)
        else:
            raise AssertionError(f"Unknown edit operation: {kind}")
        cost = Fraction(step["cost_numerator"], step["cost_denominator"])
        assert cost == expected
        total += cost
    for edge in edges.values():
        edge["source"], edge["target"] = (
            vertices[edge["source"]]["id"],
            vertices[edge["target"]]["id"],
        )
    assert {json.dumps(r, sort_keys=True) for r in vertices.values()} == {
        json.dumps(r, sort_keys=True) for r in target["vertices"]
    }
    assert {json.dumps(r, sort_keys=True) for r in edges.values()} == {
        json.dumps(r, sort_keys=True) for r in target["edges"]
    }
    assert len(vertices) == len(target["vertices"]) and len(edges) == len(
        target["edges"]
    )
    correspondence = result["vertex_correspondence"]
    sources = [
        r["graph_a_vertex"] for r in correspondence if r["graph_a_vertex"] is not None
    ]
    targets = [
        r["graph_b_vertex"] for r in correspondence if r["graph_b_vertex"] is not None
    ]
    assert len(sources) == len(set(sources)) == len(source["vertices"])
    assert len(targets) == len(set(targets)) == len(target["vertices"])
    assert set(sources) == {v["id"] for v in source["vertices"]}
    assert set(targets) == {v["id"] for v in target["vertices"]}
    for row in correspondence:
        assert row["graph_a_vertex"] is not None or row["graph_b_vertex"] is not None
        if row["graph_a_vertex"] is not None:
            slot = handles[row["graph_a_vertex"]]
            if row["graph_b_vertex"] is None:
                assert slot not in vertices
            else:
                assert vertices[slot]["id"] == row["graph_b_vertex"]
    assert total == Fraction(
        result["task_result"]["distance_numerator"],
        result["task_result"]["distance_denominator"],
    )
    return total


def common_witness(
    result,
    a,
    b,
    *,
    induced,
    ignore=False,
    vertex_fields=("label", "type"),
    edge_fields=("type",),
):
    result = result["result"]
    common = result["task_result"]["subgraph"]
    mapping = {
        r["graph_a_vertex"]: r["graph_b_vertex"]
        for r in result["vertex_correspondence"]
    }
    assert (
        len(mapping)
        == len(set(mapping.values()))
        == result["task_result"]["vertex_count"]
    )
    av, bv = ({v["id"]: v for v in data["vertices"]} for data in (a, b))
    for u, v in mapping.items():
        assert labels(av[u], vertex_fields, ignore) == labels(
            bv[v], vertex_fields, ignore
        )
    assert {v["id"] for v in common["vertices"]} == set(mapping)

    def edge_map(data):
        return {
            (e["source"], e["target"])
            if data["graph"]["directed"]
            else frozenset((e["source"], e["target"])): e
            for e in data["edges"]
        }

    ae, be, ce = map(edge_map, (a, b, common))
    for edge in common["edges"]:
        u, v = edge["source"], edge["target"]
        first = (u, v) if a["graph"]["directed"] else frozenset((u, v))
        second = (
            (mapping[u], mapping[v])
            if b["graph"]["directed"]
            else frozenset((mapping[u], mapping[v]))
        )
        assert first in ae and second in be
        assert labels(ae[first], edge_fields, ignore) == labels(
            be[second], edge_fields, ignore
        )
    if induced:
        for u, v in permutations(mapping, 2):
            first = (u, v) if a["graph"]["directed"] else frozenset((u, v))
            second = (
                (mapping[u], mapping[v])
                if b["graph"]["directed"]
                else frozenset((mapping[u], mapping[v]))
            )
            assert (first in ae) == (second in be) == (first in ce)


def call(operation, a, b, **parameters):
    result = run(
        operation, a, device="cpu", parameters={"other_graph": b, **parameters}
    )
    assert (
        result["complete"]
        and result["result"]["optimal"]
        and result["quality"] == "exact"
    )
    assert (
        result["backend"]["device"] == "cpu"
        and result["backend"]["library"] == "networkx"
    )
    return result


@pytest.mark.parametrize("a_fixture,b_fixture", tuple(product(ATLAS, repeat=2)))
def test_all_atlas_pairs_through_four_vertices(a_fixture, b_fixture):
    _, na, ea = a_fixture
    _, nb, eb = b_fixture
    a, b = graph(na, ea), graph(nb, eb)
    expected, induced_size, noninduced_size = reference(a, b)
    result = call("graph-edit-distance", a, b)
    assert replay(result) == expected
    for induced, size in ((True, induced_size), (False, noninduced_size)):
        common = call("maximum-common-subgraph", a, b, induced=induced)
        assert common["result"]["task_result"]["vertex_count"] == size
        common_witness(common, a, b, induced=induced)


@pytest.mark.parametrize("amask,bmask", tuple(product(range(64), repeat=2)))
def test_all_three_vertex_directed_pairs_with_categories(amask, bmask):
    # All adjacency pairs, with deterministic varied labels and asymmetric
    # decimal costs; both label policies appear throughout the full grid.
    graphs = []
    for mask in (amask, bmask):
        edges = [edge for bit, edge in enumerate(ARCS) if mask & (1 << bit)]
        graphs.append(
            graph(
                3,
                edges,
                directed=True,
                labels=["A" if mask & (1 << i) else "B" for i in range(3)],
                edge_labels=["x" if (u + 2 * v + mask) % 3 else "y" for u, v in edges],
                ids=[0, "0", 2**62 + 1],
            )
        )
    a, b = graphs
    ignore = (amask + bmask) % 3 == 0
    costs = {
        "vertex_insertion": 0.3,
        "vertex_deletion": 0.2,
        "edge_insertion": 0.4,
        "edge_deletion": 0.1,
        "edge_substitution": 0.25,
    }
    expected, induced_size, noninduced_size = reference(
        a, b, ignore=ignore, costs=costs
    )
    policy = "ignore_labels" if ignore else "exact"
    result = call(
        "graph-edit-distance", a, b, label_match_policy=policy, edit_costs=costs
    )
    assert replay(result, costs, ignore=ignore) == expected
    for induced, size in ((True, induced_size), (False, noninduced_size)):
        common = call(
            "maximum-common-subgraph", a, b, induced=induced, label_match_policy=policy
        )
        assert common["result"]["task_result"]["vertex_count"] == size
        common_witness(common, a, b, induced=induced, ignore=ignore)


@pytest.mark.parametrize("amask,bmask", tuple(product(range(8), repeat=2)))
@pytest.mark.parametrize(
    "costs",
    [
        {key: 0 for key in COSTS},
        {
            "vertex_insertion": 0,
            "edge_substitution": 5,
            "edge_deletion": 0.2,
            "edge_insertion": 0.1,
        },
        {
            "vertex_deletion": 2**60 + 1,
            "vertex_insertion": 2**60 + 3,
            "edge_insertion": 2**60 + 5,
        },
    ],
)
def test_labeled_paths_zero_costs_edge_replacements_and_large_integer_costs(
    amask, bmask, costs
):
    a = graph(
        3,
        [(0, 1), (1, 2)],
        labels=["A" if amask & (1 << i) else "B" for i in range(3)],
        edge_labels=["x", "y"],
    )
    b = graph(
        3,
        [(0, 1), (1, 2), (2, 0)],
        labels=["A" if bmask & (1 << i) else "B" for i in range(3)],
        edge_labels=["y", "x", "x"],
    )
    expected, _, _ = reference(a, b, costs=costs)
    result = call("graph-edit-distance", a, b, edit_costs=costs)
    assert replay(result, costs) == expected


def test_rational_cost_port_does_not_implicitly_round_a_downstream_parameter():
    a = graph(1, [], labels=["A"])
    b = graph(1, [], labels=["B"])
    result = call("graph-edit-distance", a, b, edit_costs={"vertex_insertion": 1e-200})
    port = result["ports"]["distance"]
    assert port["type"] == "rational_scalar"
    assert port["value"]["display"] == 1 and not port["value"]["display_is_exact"]
    assert Fraction(
        port["value"]["numerator"], port["value"]["denominator"]
    ) == 1 + Fraction(1, 10**200)
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "edit",
                "operation": "graph-edit-distance",
                "input": {"input": "a"},
                "bindings": {"other_graph": {"input": "b"}},
            },
            {
                "id": "cliques",
                "operation": "k-cliques",
                "input": {"input": "a"},
                "bindings": {"k": {"step": "edit", "port": "distance"}},
            },
        ],
    }
    with pytest.raises(GraphMineError):
        validate_workflow(
            plan, {"a": {"kind": "graph", "data": a}, "b": {"kind": "graph", "data": b}}
        )


def test_tiny_costs_remain_distinct_from_rounded_display():
    a = graph(3, [(0, 1), (1, 2)], labels=["A"] * 3, edge_labels=["x", "x"])
    b = graph(
        4, [(0, 1), (1, 2), (2, 3)], labels=["A"] * 4, edge_labels=["y", "x", "y"]
    )
    costs = {"edge_substitution": 1e-200, "edge_insertion": 0}
    result = call("graph-edit-distance", a, b, edit_costs=costs)
    expected, _, _ = reference(a, b, costs=costs)
    assert expected == 1 + Fraction(1, 10**200)
    assert result["result"]["task_result"]["distance"] == 1
    assert replay(result, costs) == expected


def test_id_reidentification_collisions_and_ignored_attributes():
    a = graph(
        3,
        [(0, 1), (1, 2)],
        directed=True,
        ids=[0, "0", 9007199254740993],
        labels=["A", "B", "C"],
    )
    b = graph(
        3,
        [(0, 1), (1, 2)],
        directed=True,
        ids=[9007199254740993, 0, "0"],
        labels=["A", "B", "C"],
    )
    for e in a["edges"]:
        e.update(weight=123, timestamp="ignored", attributes={"private": "irrelevant"})
    b["edges"][0]["id"], b["edges"][1]["id"] = a["edges"][1]["id"], a["edges"][0]["id"]
    a["vertices"][0]["attributes"] = {"other": 77}
    result = call("graph-edit-distance", a, b)
    assert replay(result) == 0
    assert len(result["result"]["vertex_correspondence"]) == 3
    assert (
        result["diagnostics"]["method"] == "NetworkX VF2 zero-cost isomorphism"
        or result["diagnostics"]["method"] == "NetworkX label matching"
    )
    assert "weight" not in result["result"]["normalized_source"]["edges"][0]
    assert "attributes" not in result["result"]["normalized_source"]["vertices"][0]


def test_disjoint_labels_and_vertex_objective_do_not_turn_into_edge_objective():
    a = graph(4, [], labels=["A"] * 4)
    b = graph(4, list(combinations(range(4), 2)), labels=["B"] * 4)
    assert replay(call("graph-edit-distance", a, b)) == 14
    assert (
        call("maximum-common-subgraph", a, b)["result"]["task_result"]["vertex_count"]
        == 0
    )
    result = call(
        "maximum-common-subgraph",
        a,
        b,
        induced=False,
        label_match_policy="ignore_labels",
    )
    assert result["result"]["task_result"]["vertex_count"] == 4
    assert result["result"]["task_result"]["edge_count"] == 0
    assert (
        call("maximum-common-subgraph", a, b, label_match_policy="ignore_labels")[
            "result"
        ]["task_result"]["vertex_count"]
        == 1
    )


@pytest.mark.parametrize("fields", [[], ["label"], ["type"], ["type", "label"]])
def test_missing_empty_and_selected_categories(fields):
    a = graph(3, [(0, 1), (1, 2)])
    b = deepcopy(a)
    a["vertices"][0]["label"] = ""
    a["vertices"][1]["type"] = "C"
    b["vertices"][2]["label"] = ""
    b["vertices"][1]["type"] = "D"
    a["edges"][0]["type"] = ""
    expected, size, _ = reference(a, b, vertex_fields=fields)
    result = call("graph-edit-distance", a, b, vertex_label_fields=fields)
    assert replay(result, vertex_fields=fields) == expected
    common = call("maximum-common-subgraph", a, b, vertex_label_fields=fields)
    assert common["result"]["task_result"]["vertex_count"] == size
    common_witness(common, a, b, induced=True, vertex_fields=fields)


def test_normalization_parameter_rejection_and_budgets():
    a = graph(2, [(0, 1)], labels=["A", "B"], edge_labels=["x"])
    source = deepcopy(a)
    source["graph"].update(allows_self_loops=True, allows_parallel_edges=True)
    source["edges"].extend(
        [
            {"id": "loop", "source": 0, "target": 0},
            {"id": "duplicate", "source": 1, "target": 0, "type": "x"},
        ]
    )
    for operation in ("graph-edit-distance", "maximum-common-subgraph"):
        with pytest.raises(GraphMineError, match="Parallel"):
            call(operation, source, a)
        result = call(operation, source, a, parallel_edges="collapse")
        if operation == "graph-edit-distance":
            assert replay(result) == 0
        else:
            assert result["result"]["task_result"]["vertex_count"] == 2
        with pytest.raises(GraphMineError, match="self-loops"):
            call(operation, source, a, parallel_edges="collapse", self_loops="reject")
        conflict = deepcopy(source)
        conflict["edges"][-1]["type"] = "different"
        with pytest.raises(GraphMineError, match="different selected"):
            call(operation, conflict, a, parallel_edges="collapse")
        call(
            operation,
            conflict,
            a,
            parallel_edges="collapse",
            label_match_policy="ignore_labels",
        )
        with pytest.raises(GraphMineError, match="same direction"):
            call(operation, a, graph(2, [(0, 1)], directed=True))
        for invalid in (
            {"vertex_label_fields": ["weight"]},
            {"vertex_label_fields": ["label", "label"]},
            {"vertex_label_fields": [{}]},
            {"edge_label_fields": ["label"]},
            {"time_budget_seconds": 1},
            {"solution_quality": "approximate"},
            {"label_match_policy": "custom_predicate"},
        ):
            with pytest.raises(GraphMineError):
                call(operation, a, a, **invalid)
        for budget in (Budget(max_candidates=1), Budget(max_output_items=1)):
            with pytest.raises(ResourceLimit):
                run(
                    operation,
                    a,
                    parameters={"other_graph": a},
                    device="cpu",
                    budget=budget,
                )
    for invalid in (
        {"vertex_substitution": 1},
        {"edge_substitution": -1},
        {"vertex_insertion": True},
        {"typo": 0},
        {"edge_deletion": None},
    ):
        with pytest.raises(GraphMineError):
            call("graph-edit-distance", a, a, edit_costs=invalid)


def test_larger_exact_cases_have_no_small_vertex_ceiling():
    a = graph(12, [], labels=["A"] * 6 + ["B"] * 6)
    b = graph(15, [], labels=["A"] * 7 + ["B"] * 8)
    assert replay(call("graph-edit-distance", a, b)) == 3
    assert (
        call("maximum-common-subgraph", a, b)["result"]["task_result"]["vertex_count"]
        == 12
    )
    ring = graph(9, [(i, (i + 1) % 9) for i in range(9)])
    assert replay(call("graph-edit-distance", ring, ring)) == 0
    assert (
        call("maximum-common-subgraph", ring, ring)["result"]["task_result"][
            "vertex_count"
        ]
        == 9
    )


def test_common_graph_is_a_real_downstream_input():
    a = graph(3, [(0, 1), (1, 2)])
    b = graph(3, [(0, 1), (1, 2), (2, 0)])
    inputs = {"a": {"kind": "graph", "data": a}, "b": {"kind": "graph", "data": b}}
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "compare",
                "operation": "maximum-common-subgraph",
                "input": {"input": "a"},
                "bindings": {"other_graph": {"input": "b"}},
            },
            {
                "id": "degree",
                "operation": "degree-centrality",
                "input": {"step": "compare", "port": "graph"},
            },
        ],
    }
    result = execute_workflow(plan, inputs)
    assert result["status"] == "completed"
    common = result["steps"]["compare"]["result"]
    degree = result["steps"]["degree"]["result"]
    assert [row["score"] for row in degree["ports"]["scores"]["value"]] == [1, 1]
    assert (
        degree["graph_fingerprint"]
        == Graph(common["ports"]["graph"]["value"]).fingerprint
    )
    assert degree["graph_fingerprint"] != common["graph_fingerprint"]


@pytest.mark.parametrize("changed_parent", ["a", "b"])
def test_common_graph_keeps_both_parent_namespaces(changed_parent):
    a = graph(3, [(0, 1), (1, 2)])
    b = graph(3, [(0, 1), (1, 2), (2, 0)])
    values = {"a": a, "b": b, "a2": deepcopy(a), "b2": deepcopy(b)}
    values[f"{changed_parent}2"]["graph"]["id"] = "another-dataset"
    inputs = {key: {"kind": "graph", "data": value} for key, value in values.items()}
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": name,
                "operation": "maximum-common-subgraph",
                "input": {"input": source},
                "bindings": {"other_graph": {"input": target}},
            }
            for name, source, target in (("first", "a", "b"), ("second", "a2", "b2"))
        ]
        + [
            {
                "id": "degree",
                "operation": "degree-centrality",
                "input": {"step": "first", "port": "graph"},
            },
            {
                "id": "distance",
                "operation": "single-source-shortest-paths",
                "input": {"step": "second", "port": "graph"},
                "bindings": {
                    "source": {
                        "step": "degree",
                        "port": "scores",
                        "select": {"kind": "top_vertex"},
                    }
                },
            },
        ],
    }
    result = execute_workflow(plan, inputs)
    first = result["steps"]["first"]["result"]["ports"]["graph"]
    second = result["steps"]["second"]["result"]["ports"]["graph"]
    assert first["value"]["vertices"] == second["value"]["vertices"]
    assert first["value"]["edges"] == second["value"]["edges"]
    assert first["graph_fingerprint"] != second["graph_fingerprint"]
    assert (
        call("maximum-common-subgraph", a, b)["ports"]["graph"]["graph_fingerprint"]
        == first["graph_fingerprint"]
    )
    assert result["steps"]["degree"]["status"] == "completed"
    assert result["steps"]["distance"]["status"] == "failed"
    assert "different input graph" in result["steps"]["distance"]["error"]["message"]
