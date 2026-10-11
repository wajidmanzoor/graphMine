"""Native record algebra checked against vertex/edge injection universes."""

from __future__ import annotations

import itertools
from fractions import Fraction

import pytest
import test_native_extended
from test_native_extended import BINDING, canonical, run

native = test_native_extended.native


def records():
    data = canonical(4, [])
    data["graph"].update(directed=True, attributes={})
    data["vertices"] = [
        {
            "id": 0,
            "label": "Alice",
            "attributes": {"branch": "east", "active": True, "tags": ["vip", 1]},
        },
        {"id": "0", "label": "Bob", "attributes": {"branch": "west", "active": 1}},
        {
            "id": 2**60 + 1,
            "label": "Cara",
            "attributes": {"branch": "east", "active": False},
        },
        {"id": "isolate", "attributes": {"branch": None, "active": None}},
    ]
    data["edges"] = [
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
    ]
    return data


@pytest.mark.parametrize(
    "field,op,value,expected",
    [
        ("id", "eq", 0, [0]),
        ("id", "eq", "0", ["0"]),
        ("id", "in", [], []),
        ("id", "in", [0, 2**60 + 1], [0, 2**60 + 1]),
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
        ("attributes.absent", "exists", False, [0, "0", 2**60 + 1, "isolate"]),
    ],
)
def test_native_record_filters(native, field, op, value, expected):
    result = run(
        native,
        "node-lookup",
        records(),
        vertex_filters=[{"field": field, "op": op, "value": value}],
    )
    assert result["ports"]["vertices"]["value"] == expected
    assert result["ports"]["count"]["value"] == len(expected)


def path_universe(data, source, target, direction, maximum):
    if source == target:
        return {((source,), ())}
    interior = [v["id"] for v in data["vertices"] if v["id"] not in (source, target)]
    output = set()
    for hops in range(1, min(maximum, len(data["vertices"]) - 1) + 1):
        for inside in itertools.permutations(interior, hops - 1):
            vertices = (source, *inside, target)
            choices = [
                [
                    edge["id"]
                    for edge in data["edges"]
                    if (
                        (
                            (
                                not data["graph"]["directed"]
                                or direction in ("out", "both")
                            )
                            and edge["source"] == u
                            and edge["target"] == v
                        )
                        or (
                            (
                                not data["graph"]["directed"]
                                or direction in ("in", "both")
                            )
                            and edge["source"] == v
                            and edge["target"] == u
                        )
                    )
                ]
                for u, v in itertools.pairwise(vertices)
            ]
            output.update((vertices, edges) for edges in itertools.product(*choices))
    return output


def test_native_query_paths_exhaustive_injections(native):
    pairs = list(itertools.permutations(range(3), 2))
    for mask in range(64):
        data = canonical(
            3, [edge for i, edge in enumerate(pairs) if mask >> i & 1], directed=True
        )
        for direction, source, target, mode in itertools.product(
            ("out", "in", "both"), range(3), range(3), ("shortest", "all_simple")
        ):
            expected = path_universe(data, source, target, direction, 2)
            if mode == "shortest" and expected:
                shortest = min(len(vs) for vs, _ in expected)
                expected = {(vs, es) for vs, es in expected if len(vs) == shortest}
            result = run(
                native,
                "query-paths",
                data,
                source=source,
                target=target,
                direction=direction,
                max_hops=2,
                mode=mode,
            )
            assert {
                (tuple(r["vertices"]), tuple(r["edges"]))
                for r in result["result"]["rows"]
            } == expected
            assert result["ports"]["count"]["value"] == len(expected)
    data = records()
    for direction, directed in itertools.product(("out", "in", "both"), (False, True)):
        data["graph"]["directed"] = directed
        expected = path_universe(data, 0, 2**60 + 1, direction, 3)
        result = run(
            native,
            "query-paths",
            data,
            source=0,
            target=2**60 + 1,
            direction=direction,
            mode="all_simple",
        )
        assert {
            (tuple(r["vertices"]), tuple(r["edges"])) for r in result["result"]["rows"]
        } == expected


def test_native_query_neighbors_and_intersections(native):
    data = records()
    for direction, directed in itertools.product(("out", "in", "both"), (False, True)):
        data["graph"]["directed"] = directed
        ids = [v["id"] for v in data["vertices"]]
        neighbors = {}
        for source in ids:
            neighbors[source] = {
                e["target"]
                for e in data["edges"]
                if e["source"] == source
                and (not directed or direction in ("out", "both"))
            } | {
                e["source"]
                for e in data["edges"]
                if e["target"] == source
                and (not directed or direction in ("in", "both"))
            }
            for hops in (0, 1, 2):
                expected = {}
                for target in ids:
                    paths = path_universe(data, source, target, direction, hops)
                    if paths:
                        expected[target] = min(len(es) for _, es in paths)
                result = run(
                    native,
                    "neighbors",
                    data,
                    entity=source,
                    direction=direction,
                    hops=hops,
                    include_seed=True,
                )
                assert {
                    r["vertex"]: r["distance"] for r in result["result"]["rows"]
                } == expected
        for source, target in itertools.product(ids, repeat=2):
            result = run(
                native,
                "common-neighbors",
                data,
                source=source,
                target=target,
                direction=direction,
            )
            assert (
                set(result["ports"]["vertices"]["value"])
                == neighbors[source] & neighbors[target]
            )


def test_native_record_joins_aggregates_and_empty_scopes(native):
    data = records()
    joined = run(
        native,
        "edge-filter",
        data,
        source_filters=[{"field": "attributes.branch", "op": "eq", "value": "east"}],
        target_filters=[{"field": "attributes.branch", "op": "eq", "value": "west"}],
    )
    assert joined["result"]["rows"] == data["edges"][:2]
    for direction, expected in (
        ("out", [3, 2, 0, 0]),
        ("in", [2, 2, 1, 0]),
        ("both", [4, 4, 1, 0]),
    ):
        result = run(
            native, "graph-aggregate", data, group_by="vertex", direction=direction
        )
        assert [r["value"] for r in result["result"]["rows"]] == expected
    for metric, expected in (
        ("count", 5),
        ("sum", Fraction(3, 2)),
        ("avg", Fraction(3, 10)),
        ("min", Fraction(1, 10)),
        ("max", Fraction(1, 2)),
    ):
        result = run(
            native,
            "graph-aggregate",
            data,
            metric=metric,
            **({"field": "weight"} if metric != "count" else {}),
        )
        row = result["result"]["rows"][0]
        assert (
            Fraction(
                int(row["exact_value"]["numerator"]),
                int(row["exact_value"]["denominator"]),
            )
            == expected
        )
        assert row["rounded"] == (Fraction(row["value"]) != expected)
    result = run(
        native,
        "graph-aggregate",
        data,
        metric="sum",
        field="attributes.amount",
        group_by="source",
        filters=[{"field": "attributes.kind", "op": "eq", "value": "sale"}],
    )
    assert {r["group"]: r["value"] for r in result["result"]["rows"]} == {
        0: 2**61 + 3,
        "0": 5,
    }
    empty = canonical(0, [])
    for metric in ("count", "sum", "avg", "min", "max"):
        row = run(
            native,
            "graph-aggregate",
            empty,
            metric=metric,
            **({"field": "weight"} if metric != "count" else {}),
        )["result"]["rows"][0]
        assert row["value"] == (0 if metric in ("count", "sum") else None)
    assert (
        run(
            native,
            "node-lookup",
            empty,
            vertex_filters=[{"field": "attributes.amount", "op": "gt", "value": 7}],
        )["result"]["rows"]
        == []
    )


@pytest.mark.parametrize(
    "mode,parameters,vertex_ids,edge_ids",
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
        ("neighborhood", {"entity": 0, "hops": 1, "edge_ids": ["loop"]}, [0], ["loop"]),
    ],
)
def test_native_query_subgraphs_preserve_records(
    native, mode, parameters, vertex_ids, edge_ids
):
    data = records()
    result = run(native, "query-subgraph", data, mode=mode, **parameters)
    derived = result["result"]["graph"]
    assert derived["vertices"] == [v for v in data["vertices"] if v["id"] in vertex_ids]
    assert derived["edges"] == [e for e in data["edges"] if e["id"] in edge_ids]
    assert derived["graph"]["attributes"] == {}
    assert result["ports"]["graph"]["graph_fingerprint"] != result["input_fingerprint"]
    assert derived["graph"]["id"] == "query:" + result["input_fingerprint"]


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("node-lookup", {"vertices": ["unknown"]}),
        (
            "node-lookup",
            {
                "vertex_filters": [
                    {"field": "attributes.unknown", "op": "eq", "value": 1}
                ]
            },
        ),
        (
            "node-lookup",
            {"vertex_filters": [{"field": "id", "op": "eq", "value": 0.0}]},
        ),
        ("edge-filter", {"edge_ids": [False]}),
        ("neighbors", {"entity": 0, "hops": -1}),
        ("query-subgraph", {"mode": "vertices"}),
        ("query-subgraph", {"mode": "edges", "direction": "in"}),
        ("query-subgraph", {"mode": "neighborhood", "entity": 0, "vertices": [0]}),
        ("graph-aggregate", {"metric": "sum"}),
        ("graph-aggregate", {"metric": "count", "field": "weight"}),
        ("graph-aggregate", {"direction": "both"}),
        ("graph-aggregate", {"group_by": "attributes.absent"}),
    ],
)
def test_native_record_query_contract_errors(native, operation, parameters):
    with pytest.raises(BINDING.NativeError):
        run(native, operation, records(), **parameters)


def test_native_query_collection_completeness_and_budget(native):
    data = records()
    for operation, parameters in (
        ("node-lookup", {}),
        ("edge-filter", {}),
        ("neighbors", {"entity": 0, "hops": 2}),
        ("query-paths", {"source": 0, "target": 2**60 + 1}),
        ("graph-aggregate", {"group_by": "vertex"}),
    ):
        result = run(native, operation, data, result_limit=1, **parameters)
        assert not result["complete"]
        assert result["ports"]["count"]["complete"]
        assert result["ports"]["count"]["value"] > 1
        assert all(
            not port["complete"]
            for name, port in result["ports"].items()
            if name != "count"
        )
    with pytest.raises(BINDING.NativeError, match="budget"):
        native.run(
            "query-paths",
            data,
            parameters={"source": 0, "target": "0"},
            device="cpu",
            budget={"max_candidates": 1},
        )
