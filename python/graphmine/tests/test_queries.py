"""Record queries checked against independent path injections and explicit rows."""

from fractions import Fraction
from itertools import pairwise, permutations, product

import pytest
from graphmine import Budget, Graph, list_algorithms, run
from graphmine.exceptions import GraphMineError, ResourceLimit, UnsupportedOperation
from graphmine.workflows import execute_workflow, validate_workflow


def query(operation, graph, **parameters):
    return run(operation, graph, parameters=parameters, device="cpu")


def records():
    return Graph(
        {
            "graph": {
                "id": "payments",
                "directed": True,
                "allows_self_loops": True,
                "allows_parallel_edges": True,
            },
            "vertices": [
                {
                    "id": 0,
                    "label": "Alice",
                    "attributes": {
                        "branch": "east",
                        "active": True,
                        "tags": ["vip", 1],
                    },
                },
                {
                    "id": "0",
                    "label": "Bob",
                    "attributes": {"branch": "west", "active": 1},
                },
                {
                    "id": 2**60 + 1,
                    "label": "Cara",
                    "attributes": {"branch": "east", "active": False},
                },
                {"id": "isolate", "attributes": {"branch": None, "active": None}},
            ],
            "edges": [
                {
                    "id": 0,
                    "source": 0,
                    "target": "0",
                    "weight": 0.1,
                    "attributes": {"amount": 2**60 + 1, "kind": "sale"},
                },
                {
                    "id": "0",
                    "source": 0,
                    "target": "0",
                    "weight": 0.2,
                    "attributes": {"amount": 2**60 + 2, "kind": "sale"},
                },
                {
                    "id": "return",
                    "source": "0",
                    "target": 0,
                    "weight": 0.3,
                    "attributes": {"amount": -3, "kind": "refund"},
                },
                {
                    "id": "next",
                    "source": "0",
                    "target": 2**60 + 1,
                    "weight": 0.4,
                    "attributes": {"amount": 5, "kind": "sale"},
                },
                {
                    "id": "loop",
                    "source": 0,
                    "target": 0,
                    "weight": 0.5,
                    "attributes": {"amount": 7, "kind": "internal"},
                },
            ],
        }
    )


@pytest.mark.parametrize(
    "field,op,value,expected",
    [
        ("id", "eq", 0, [0]),
        ("id", "eq", "0", ["0"]),
        ("id", "in", [0, 2**60 + 1], [0, 2**60 + 1]),
        ("id", "in", [], []),
        ("attributes.branch", "eq", "east", [0, 2**60 + 1]),
        ("attributes.branch", "ne", "east", ["0", "isolate"]),
        ("attributes.active", "eq", True, [0]),
        ("attributes.active", "eq", 1, ["0"]),
        ("attributes.active", "eq", None, ["isolate"]),
        ("label", "exists", False, ["isolate"]),
        ("label", "not_in", ["Alice"], ["0", 2**60 + 1]),
        ("label", "contains", "ar", [2**60 + 1]),
        ("attributes.tags", "contains", "vip", [0]),
        ("attributes.tags", "contains", True, []),
        ("attributes.never_present", "exists", False, [0, "0", 2**60 + 1, "isolate"]),
    ],
)
def test_record_predicates_preserve_types_and_missingness(field, op, value, expected):
    result = query(
        "node-lookup",
        records(),
        vertex_filters=[{"field": field, "op": op, "value": value}],
    )
    assert result["ports"]["vertices"]["value"] == expected
    assert result["ports"]["count"]["value"] == len(expected)
    assert result["backend"]["library"] == "python"
    assert result["complete"]


@pytest.mark.parametrize(
    "op,value,expected",
    [
        ("gt", 2**60 + 1, ["0"]),
        ("gte", 2**60 + 1, [0, "0"]),
        ("lt", 0, ["return"]),
        ("lte", 5, ["return", "next"]),
    ],
)
def test_numeric_filter_does_not_round_large_values(op, value, expected):
    result = query(
        "edge-filter",
        records(),
        edge_filters=[{"field": "attributes.amount", "op": op, "value": value}],
    )
    assert result["ports"]["edges"]["value"] == expected


def test_endpoint_filters_and_parallel_records_are_lossless():
    graph = records()
    result = query(
        "edge-filter",
        graph,
        source_filters=[{"field": "label", "op": "eq", "value": "Alice"}],
        target_filters=[{"field": "id", "op": "eq", "value": "0"}],
    )
    assert result["ports"]["edges"]["value"] == [0, "0"]
    assert result["result"]["rows"] == graph.to_canonical()["edges"][:2]
    result["result"]["rows"][0]["attributes"]["amount"] = 99
    assert (
        query("edge-filter", graph)["result"]["rows"][0]["attributes"]["amount"]
        == 2**60 + 1
    )
    copied = graph.to_canonical()
    copied["edges"][0]["source"] = "isolate"
    assert query("neighbors", graph, entity=0)["ports"]["vertices"]["value"] == ["0"]
    assert query("node-lookup", graph, vertices=[])["result"]["rows"] == []


def directed_graph(mask):
    pairs = [(u, v) for u in range(3) for v in range(3) if u != v]
    edges = [pair for i, pair in enumerate(pairs) if mask & (1 << i)]
    return Graph.from_edges(edges, vertices=range(3), directed=True), edges


def oracle_paths(graph, source, target, direction, hops):
    # Independent complete vertex-injection universe, then edge assignments.
    records = graph.to_canonical()["edges"]
    if source == target:
        return [((source,), ())]
    result = []
    candidates = [v for v in graph.node_ids if v not in {source, target}]
    for length in range(1, min(hops, graph.vertex_count - 1) + 1):
        for middle in permutations(candidates, length - 1):
            vertices = (source, *middle, target)
            choices = []
            for u, v in pairwise(vertices):
                choices.append(
                    [
                        edge["id"]
                        for edge in records
                        if (
                            (not graph.directed or direction in {"out", "both"})
                            and edge["source"] == u
                            and edge["target"] == v
                        )
                        or (
                            (not graph.directed or direction in {"in", "both"})
                            and edge["source"] == v
                            and edge["target"] == u
                        )
                    ]
                )
            result.extend((vertices, assignment) for assignment in product(*choices))
    return result


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("direction", ["out", "in", "both"])
@pytest.mark.parametrize("mode", ["shortest", "all_simple"])
def test_every_small_directed_path_by_injection(mask, direction, mode):
    graph, _ = directed_graph(mask)
    for source, target in product(range(3), repeat=2):
        expected = oracle_paths(graph, source, target, direction, 2)
        if mode == "shortest" and expected:
            shortest = min(len(vertices) for vertices, _ in expected)
            expected = [
                (vertices, edges)
                for vertices, edges in expected
                if len(vertices) == shortest
            ]
        result = query(
            "query-paths",
            graph,
            source=source,
            target=target,
            direction=direction,
            max_hops=2,
            mode=mode,
        )
        actual = {
            (tuple(row["vertices"]), tuple(row["edges"]))
            for row in result["result"]["rows"]
        }
        assert actual == set(expected)
        assert result["ports"]["count"]["value"] == len(expected)


@pytest.mark.parametrize("mask", range(64))
@pytest.mark.parametrize("direction", ["out", "in", "both"])
def test_neighbors_and_common_neighbors_from_path_universe(mask, direction):
    graph, _ = directed_graph(mask)
    for source in range(3):
        one_hop = {
            v
            for v in range(3)
            if v != source and oracle_paths(graph, source, v, direction, 1)
        }
        two_hop = {
            v
            for v in range(3)
            if v != source and oracle_paths(graph, source, v, direction, 2)
        }
        assert (
            set(
                query("neighbors", graph, entity=source, direction=direction)["ports"][
                    "vertices"
                ]["value"]
            )
            == one_hop
        )
        assert (
            set(
                query("neighbors", graph, entity=source, direction=direction, hops=2)[
                    "ports"
                ]["vertices"]["value"]
            )
            == two_hop
        )
        for target in range(3):
            other_neighbors = {
                v
                for v in range(3)
                if v != target and oracle_paths(graph, target, v, direction, 1)
            }
            assert (
                set(
                    query(
                        "common-neighbors",
                        graph,
                        source=source,
                        target=target,
                        direction=direction,
                    )["ports"]["vertices"]["value"]
                )
                == one_hop & other_neighbors
            )


@pytest.mark.parametrize("direction", ["out", "in", "both"])
@pytest.mark.parametrize("mode", ["shortest", "all_simple"])
@pytest.mark.parametrize("directed", [True, False])
def test_paths_with_parallel_edges_loops_filters_and_typed_ids(
    direction, mode, directed
):
    data = records().to_canonical()
    data["graph"]["directed"] = directed
    graph = Graph(data)
    expected = oracle_paths(graph, 0, 2**60 + 1, direction, 5)
    if mode == "shortest" and expected:
        minimum = min(len(vertices) for vertices, _ in expected)
        expected = [(v, e) for v, e in expected if len(v) == minimum]
    result = query(
        "query-paths",
        graph,
        source=0,
        target=2**60 + 1,
        direction=direction,
        mode=mode,
        max_hops=5,
    )
    assert {
        (tuple(row["vertices"]), tuple(row["edges"]))
        for row in result["result"]["rows"]
    } == set(expected)
    rejected = query(
        "query-paths",
        graph,
        source=0,
        target=2**60 + 1,
        direction=direction,
        edge_filters=[{"field": "attributes.kind", "op": "eq", "value": "internal"}],
    )
    assert rejected["result"]["rows"] == []


@pytest.mark.parametrize(
    "direction,expected",
    [
        ("out", {0: 3, "0": 2, 2**60 + 1: 0, "isolate": 0}),
        ("in", {0: 2, "0": 2, 2**60 + 1: 1, "isolate": 0}),
        ("both", {0: 4, "0": 4, 2**60 + 1: 1, "isolate": 0}),
    ],
)
def test_per_vertex_aggregation_counts_distinct_records_including_loops(
    direction, expected
):
    result = query("graph-aggregate", records(), group_by="vertex", direction=direction)
    assert {row["vertex"]: row["value"] for row in result["result"]["rows"]} == expected
    assert result["ports"]["scores"]["complete"]


@pytest.mark.parametrize(
    "metric,expected",
    [
        ("count", Fraction(5)),
        ("sum", Fraction(3, 2)),
        ("avg", Fraction(3, 10)),
        ("min", Fraction(1, 10)),
        ("max", Fraction(1, 2)),
    ],
)
def test_exact_decimal_aggregates(metric, expected):
    result = query(
        "graph-aggregate",
        records(),
        metric=metric,
        **({"field": "weight"} if metric != "count" else {}),
    )
    row = result["result"]["rows"][0]
    assert Fraction(**row["exact_value"]) == expected
    assert row["rounded"] == (Fraction(row["value"]) != expected)


def test_grouped_filters_empty_aggregates_and_lossless_integer_sums():
    result = query(
        "graph-aggregate",
        records(),
        metric="sum",
        field="attributes.amount",
        group_by="source",
        filters=[{"field": "attributes.kind", "op": "eq", "value": "sale"}],
    )
    assert {row["group"]: row["value"] for row in result["result"]["rows"]} == {
        0: 2**61 + 3,
        "0": 5,
    }
    empty = Graph.from_edges([])
    for metric in ("count", "sum", "avg", "min", "max"):
        row = query(
            "graph-aggregate",
            empty,
            metric=metric,
            **({"field": "weight"} if metric != "count" else {}),
        )["result"]["rows"][0]
        assert row["value"] == (0 if metric in {"count", "sum"} else None)
    assert query("node-lookup", empty)["result"]["rows"] == []
    assert query("edge-filter", empty)["result"]["rows"] == []
    assert (
        query("query-subgraph", empty, vertices=[])["result"]["graph"]["vertices"] == []
    )


@pytest.mark.parametrize(
    "mode,params,vertex_ids,edge_ids",
    [
        (
            "vertices",
            {"vertices": [0, "0", "isolate"]},
            [0, "0", "isolate"],
            [0, "0", "return", "loop"],
        ),
        ("edges", {"edge_ids": ["0"]}, [0, "0"], ["0"]),
        ("edges", {"edge_ids": []}, [], []),
        (
            "neighborhood",
            {"entity": 0, "hops": 1},
            [0, "0"],
            [0, "0", "return", "loop"],
        ),
        ("neighborhood", {"entity": 0, "hops": 0}, [0], ["loop"]),
    ],
)
def test_subgraphs_keep_the_original_records(mode, params, vertex_ids, edge_ids):
    graph = records()
    result = query("query-subgraph", graph, mode=mode, **params)
    original = graph.to_canonical()
    derived = result["ports"]["graph"]["value"]
    assert derived["vertices"] == [
        row for row in original["vertices"] if row["id"] in vertex_ids
    ]
    assert derived["edges"] == [
        row for row in original["edges"] if row["id"] in edge_ids
    ]
    assert derived["graph"]["directed"] == original["graph"]["directed"]
    assert result["ports"]["graph"]["source_graph_fingerprint"] == graph.fingerprint
    assert result["ports"]["graph"]["graph_fingerprint"] == Graph(derived).fingerprint


def inputs(graph):
    return {"main": {"kind": "graph", "data": graph.to_canonical()}}


def workflow(operation, parameters, second=None):
    steps = [
        {
            "id": "query",
            "operation": operation,
            "input": {"input": "main"},
            "parameters": parameters,
        }
    ]
    if second:
        steps.append(second)
    return {"version": 1, "device": "cpu", "steps": steps}


def test_query_edge_binding_and_lineage_into_dependent_calculation():
    graph = records()
    plan = workflow(
        "edge-filter",
        {"edge_ids": [0, "0"]},
        {
            "id": "sub",
            "operation": "query-subgraph",
            "input": {"input": "main"},
            "parameters": {"mode": "edges"},
            "bindings": {"edge_ids": {"step": "query", "port": "edges"}},
        },
    )
    result = execute_workflow(plan, inputs(graph))
    assert result["status"] == "completed"
    assert [
        row["id"]
        for row in result["steps"]["sub"]["result"]["ports"]["graph"]["value"]["edges"]
    ] == [0, "0"]
    different = graph.to_canonical()
    different["graph"]["id"] = "another-dataset"
    both = {**inputs(graph), "other": {"kind": "graph", "data": different}}
    plan["steps"][1]["input"] = {"input": "other"}
    result = execute_workflow(plan, both)
    assert result["steps"]["sub"]["status"] == "failed"
    assert "different input graph" in result["steps"]["sub"]["error"]["message"]


@pytest.mark.parametrize(
    "operation,parameters,port",
    [
        ("node-lookup", {}, "vertices"),
        ("edge-filter", {}, "edges"),
        ("neighbors", {"entity": 0, "hops": 2}, "vertices"),
        ("query-paths", {"source": 0, "target": 2**60 + 1}, "edges"),
        ("graph-aggregate", {"group_by": "vertex"}, "scores"),
    ],
)
def test_capped_collection_cannot_feed_a_dependent_step(operation, parameters, port):
    graph = records()
    source = query(operation, graph, **parameters, result_limit=1)
    assert not source["complete"]
    assert not source["ports"][port]["complete"]
    assert source["ports"]["count"]["complete"]
    reference = {"step": "query", "port": port}
    if port == "scores":
        reference["select"] = {"kind": "top_vertices", "k": 1}
    child = {
        "id": "sub",
        "operation": "query-subgraph",
        "input": {"input": "main"},
        "parameters": {"mode": "edges" if port == "edges" else "vertices"},
        "bindings": {"edge_ids" if port == "edges" else "vertices": reference},
    }
    result = execute_workflow(
        workflow(operation, {**parameters, "result_limit": 1}, child), inputs(graph)
    )
    assert result["steps"]["sub"]["status"] == "failed"
    assert "incomplete" in result["steps"]["sub"]["error"]["message"].lower()


def test_top_vertex_selection_uses_exact_aggregate_not_rounded_display():
    graph = Graph(
        {
            "graph": {
                "id": "precision",
                "directed": True,
                "allows_self_loops": False,
                "allows_parallel_edges": True,
            },
            "vertices": [{"id": v} for v in [0, 1, 2]],
            "edges": [
                {"id": i, "source": u, "target": 2, "weight": w}
                for i, (u, w) in enumerate(
                    [(0, 2**60), (0, 2**60 + 1), (1, 2**60), (1, 2**60 + 3)]
                )
            ],
        }
    )
    plan = workflow(
        "graph-aggregate",
        {"group_by": "vertex", "metric": "avg", "field": "weight"},
        {
            "id": "chosen",
            "operation": "node-lookup",
            "input": {"input": "main"},
            "bindings": {
                "vertices": {
                    "step": "query",
                    "port": "scores",
                    "select": {"kind": "top_vertices", "k": 1},
                }
            },
        },
    )
    result = execute_workflow(plan, inputs(graph))
    assert result["status"] == "completed"
    assert result["steps"]["chosen"]["result"]["ports"]["vertices"]["value"] == [1]


@pytest.mark.parametrize(
    "operation,parameters",
    [
        (
            "node-lookup",
            {
                "vertex_filters": [
                    {"field": "attributes.missing", "op": "eq", "value": 1}
                ]
            },
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "id", "op": "eq", "value": True}]},
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "id", "op": "eq", "value": 0.0}]},
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "label", "op": "regex", "value": ".*"}]},
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "label", "op": "exists", "value": 1}]},
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "label", "op": "in", "value": "Alice"}]},
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "label", "op": "eq", "value": {}}]},
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "__class__", "op": "eq", "value": "object"}]},
        ),
        ("node-lookup", {"sql": "SELECT * FROM vertices"}),
        ("node-lookup", {"vertices": [True]}),
        ("neighbors", {"entity": "missing"}),
        ("neighbors", {"entity": 0, "hops": -1}),
        ("query-paths", {"source": 0, "target": "0", "mode": "weighted"}),
        ("graph-aggregate", {"metric": "sum"}),
        ("graph-aggregate", {"metric": "count", "field": "weight"}),
        ("graph-aggregate", {"group_by": "missing"}),
        ("query-subgraph", {}),
        ("query-subgraph", {"mode": "neighborhood"}),
        ("edge-filter", {"edge_ids": ["absent"]}),
    ],
)
def test_invalid_queries_rejected_before_queueing(operation, parameters):
    graph = records()
    with pytest.raises(GraphMineError):
        query(operation, graph, **parameters)
    with pytest.raises(GraphMineError):
        validate_workflow(workflow(operation, parameters), inputs(graph))


def test_derived_input_fields_revalidated_on_actual_records():
    graph = records()
    plan = workflow(
        "query-subgraph",
        {"vertices": ["isolate"]},
        {
            "id": "lookup",
            "operation": "node-lookup",
            "input": {"step": "query", "port": "graph"},
            "parameters": {
                "vertex_filters": [
                    {"field": "attributes.tags", "op": "contains", "value": "vip"}
                ]
            },
        },
    )
    result = execute_workflow(plan, inputs(graph))
    assert result["steps"]["lookup"]["status"] == "failed"
    assert "Unknown vertices field" in result["steps"]["lookup"]["error"]["message"]


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("node-lookup", {}),
        ("edge-filter", {}),
        ("neighbors", {"entity": 0}),
        ("query-paths", {"source": 0, "target": "0"}),
        ("graph-aggregate", {}),
        ("query-subgraph", {"vertices": [0]}),
    ],
)
def test_queries_obey_work_limits_and_never_claim_gpu(operation, parameters):
    with pytest.raises(ResourceLimit):
        run(
            operation,
            records(),
            parameters=parameters,
            device="cpu",
            budget=Budget(max_candidates=1),
        )
    with pytest.raises(UnsupportedOperation):
        run(operation, records(), parameters=parameters, device="gpu")


def test_query_cards_are_declared_with_nested_filter_schemas():
    cards = [card for card in list_algorithms() if card["family"] == "query"]
    assert len(cards) == 7
    assert all(card["library"] == "python" for card in cards)
    for card in cards:
        assert card["output_ports"]
        for name, parameter in card["parameters"].items():
            if "filters" in name:
                assert (
                    parameter["json_schema"]["items"]["additionalProperties"] is False
                )


def test_query_results_and_cards_cannot_mutate_later_defaults_or_schemas():
    result = query("node-lookup", records())
    result["parameters"]["vertex_filters"].append(
        {"field": "id", "op": "eq", "value": 0}
    )
    assert len(query("node-lookup", records())["result"]["rows"]) == 4
    card = next(card for card in list_algorithms() if card["id"] == "node-lookup")
    card["parameters"]["vertex_filters"]["json_schema"]["items"]["properties"]["op"][
        "enum"
    ].append("execute")
    with pytest.raises(GraphMineError, match="Unknown filter operator"):
        query(
            "node-lookup",
            records(),
            vertex_filters=[{"field": "id", "op": "execute", "value": 0}],
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {"scope": "vertices", "metric": "sum", "field": "attributes.branch"},
        {"scope": "vertices", "metric": "avg", "field": "attributes.active"},
        {"scope": "vertices", "group_by": "label"},
        {"scope": "vertices", "group_by": "attributes.tags"},
    ],
)
def test_invalid_aggregate_records_rejected_during_preflight(parameters):
    with pytest.raises(GraphMineError):
        validate_workflow(workflow("graph-aggregate", parameters), inputs(records()))


def test_vertex_record_filter_precedes_vertex_grouping():
    result = query(
        "graph-aggregate",
        records(),
        scope="vertices",
        group_by="vertex",
        filters=[{"field": "id", "op": "eq", "value": "0"}],
    )
    assert [(row["vertex"], row["value"]) for row in result["result"]["rows"]] == [
        ("0", 1)
    ]


def test_neighborhood_edge_scope_controls_reachability_not_only_output():
    graph = records()
    result = query(
        "query-subgraph",
        graph,
        mode="neighborhood",
        entity=0,
        hops=3,
        edge_ids=["next"],
    )
    assert result["ports"]["vertices"]["value"] == [0]
    assert result["ports"]["edges"]["value"] == []
    result = query(
        "query-subgraph",
        graph,
        mode="neighborhood",
        entity=0,
        hops=3,
        edge_ids=["0", "next"],
    )
    assert result["ports"]["vertices"]["value"] == [0, "0", 2**60 + 1]
    assert result["ports"]["edges"]["value"] == ["0", "next"]


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("query-subgraph", {"vertices": [0], "entity": "0"}),
        ("query-subgraph", {"vertices": [0], "hops": 3}),
        ("query-subgraph", {"mode": "edges", "direction": "in"}),
        ("query-subgraph", {"mode": "neighborhood", "entity": 0, "vertices": [0]}),
        ("graph-aggregate", {"group_by": "source", "direction": "in"}),
        (
            "graph-aggregate",
            {"scope": "vertices", "group_by": "vertex", "direction": "in"},
        ),
    ],
)
def test_irrelevant_mode_parameters_are_rejected_not_ignored(operation, parameters):
    with pytest.raises(GraphMineError):
        validate_workflow(workflow(operation, parameters), inputs(records()))


def test_empty_record_scopes_do_not_invent_field_values_or_fail_queries():
    empty = Graph.from_edges([])
    result = query(
        "node-lookup",
        empty,
        vertex_filters=[{"field": "attributes.amount", "op": "gte", "value": 100}],
    )
    assert result["result"]["rows"] == [] and result["complete"]
    result = query("graph-aggregate", empty, metric="avg", field="attributes.amount")
    assert result["result"]["rows"][0]["value"] is None


def test_empty_query_extraction_can_feed_a_domain_aggregate():
    plan = workflow(
        "query-subgraph",
        {"vertices": []},
        {
            "id": "sum",
            "operation": "graph-aggregate",
            "input": {"step": "query", "port": "graph"},
            "parameters": {"metric": "sum", "field": "attributes.amount"},
        },
    )
    result = execute_workflow(plan, inputs(records()))
    assert result["status"] == "completed", result
    assert result["steps"]["sum"]["result"]["result"]["rows"][0]["value"] == 0
