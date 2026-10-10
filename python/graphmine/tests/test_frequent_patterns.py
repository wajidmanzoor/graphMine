"""Independent graph-universe and injection oracles; no BLISS or VF2 in references."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from fractions import Fraction
from functools import cache, lru_cache
from itertools import combinations, permutations, product

import networkx as nx
import pytest
from graphmine import Budget, Graph, GraphCollection, run
from graphmine.exceptions import GraphMineError, ResourceLimit
from graphmine.inputs import load_input
from graphmine.workflows import execute_workflow, validate_workflow

ATLAS = [
    (i, len(g), tuple(g.edges)) for i, g in enumerate(nx.graph_atlas_g()) if len(g) <= 5
]
PAIRS4 = tuple(combinations(range(4), 2))
ARCS3 = tuple((u, v) for u in range(3) for v in range(3) if u != v)


def graph(n, edges, *, directed=False, labels=None, ids=None, name="transaction"):
    ids = list(range(n)) if ids is None else ids
    data = Graph.from_edges(
        [(ids[u], ids[v]) for u, v in edges], vertices=ids, directed=directed
    ).to_canonical()
    data["graph"]["id"] = name
    if labels is not None:
        for row, label in zip(data["vertices"], labels, strict=True):
            row["label"] = label
            row["type"] = label
    return data


def collection(*graphs):
    values = [deepcopy(g) for g in graphs]
    for i, value in enumerate(values):
        value["graph"]["id"] = f"transaction-{i}"
    return {"dataset_id": "database", "graphs": list(values)}


def packed(data, vertex_field=None, edge_field=None):
    ids = {row["id"]: i for i, row in enumerate(data["vertices"])}
    labels = tuple(
        json.dumps(row.get(vertex_field), ensure_ascii=False) if vertex_field else "*"
        for row in data["vertices"]
    )
    matrix = [[None for _ in ids] for _ in ids]
    for edge in data["edges"]:
        u, v = ids[edge["source"]], ids[edge["target"]]
        token = (
            json.dumps(edge.get(edge_field), ensure_ascii=False) if edge_field else "*"
        )
        matrix[u][v] = token
        if not data["graph"]["directed"]:
            matrix[v][u] = token
    return labels, tuple(map(tuple, matrix))


@lru_cache(maxsize=32768)
def signature(packing):
    labels, matrix = packing
    return min(
        (
            tuple(labels[i] for i in order),
            tuple(
                "0" if matrix[i][j] is None else "1" + matrix[i][j]
                for i in order
                for j in order
            ),
        )
        for order in permutations(range(len(labels)))
    )


def embeddings(pattern, host, induced):
    plabels, pmatrix = pattern
    hlabels, hmatrix = host
    for assignment in permutations(range(len(hlabels)), len(plabels)):
        if any(plabels[i] != hlabels[j] for i, j in enumerate(assignment)):
            continue
        if all(
            (pmatrix[u][v] == hmatrix[assignment[u]][assignment[v]])
            if induced or pmatrix[u][v] is not None
            else True
            for u in range(len(plabels))
            for v in range(len(plabels))
        ):
            yield assignment


def connected(n, edges):
    if not n:
        return False
    reached = {0}
    for _ in range(n):
        for u, v in edges:
            if u in reached or v in reached:
                reached.update((u, v))
    return len(reached) == n


@cache
def universe(nmax, *, directed=False, labeled=False, connected_only=False, max_edges=3):
    # Generate all possible adjacency masks/labelings, not host-derived
    # candidates. Atlas fixtures supply an independently classified undirected
    # universe including disconnected graphs and arbitrary isolates.
    shapes = [
        (n, edges)
        for _, n, edges in ATLAS
        if 1 <= n <= nmax and len(edges) <= max_edges
    ]
    if directed:
        shapes = []
        for n in range(1, nmax + 1):
            arcs = [(u, v) for u in range(n) for v in range(n) if u != v]
            for size in range(min(max_edges, len(arcs)) + 1):
                shapes.extend((n, edges) for edges in combinations(arcs, size))
    result = {}
    for n, edges in shapes:
        if connected_only and not connected(n, edges):
            continue
        for labels in product(("A", "B"), repeat=n) if labeled else [None]:
            data = graph(n, edges, directed=directed, labels=labels)
            item = packed(data, "label" if labeled else None)
            result.setdefault(signature(item), (item, len(edges)))
    return result


def call(operation, data, **parameters):
    value = run(operation, data, parameters=parameters, device="cpu")
    assert value["backend"]["device"] == "cpu"
    assert value["backend"]["library"] == "igraph"
    assert value["quality"] == "exact" and value["complete"]
    return value


@pytest.mark.parametrize("induced", [False, True])
@pytest.mark.parametrize("atlas_id,n,edges", ATLAS)
def test_transaction_atlas_universe(atlas_id, n, edges, induced):
    source = graph(n, edges)
    # Repeated content with different IDs is a distinct transaction; repeated
    # embeddings within each transaction still contribute one support unit.
    complement = graph(
        n, [edge for edge in combinations(range(n), 2) if edge not in edges]
    )
    data = collection(source, source, complement)
    hosts = [packed(g) for g in data["graphs"]]
    expected = {}
    for key, (pattern, _) in universe(n).items():
        support = [
            f"transaction-{i}"
            for i, host in enumerate(hosts)
            if next(embeddings(pattern, host, induced), None) is not None
        ]
        if Fraction(len(support), 3) >= Fraction(1, 2):
            expected[key] = support
    result = call(
        "frequent-subgraphs",
        data,
        minimum_support_fraction=0.5,
        minimum_edges=0,
        maximum_edges=3,
        label_semantics="unlabeled",
        induced=induced,
        include_supporting_graph_ids=True,
    )
    actual = {}
    for row in result["result"]["patterns"]:
        key = signature(packed(row["pattern"]))
        assert key not in actual
        actual[key] = row["supporting_graph_ids"]
        assert row["support_graph_count"] == len(actual[key])
        assert row["support_fraction"] == len(actual[key]) / 3
    assert actual == expected


@pytest.mark.parametrize("induced", [False, True])
@pytest.mark.parametrize("mask", range(64))
def test_directed_transaction_universe(mask, induced):
    source = graph(
        3, [edge for i, edge in enumerate(ARCS3) if mask & (1 << i)], directed=True
    )
    host = packed(source)
    expected = {
        key
        for key, (pattern, _) in universe(3, directed=True, max_edges=6).items()
        if next(embeddings(pattern, host, induced), None) is not None
    }
    result = call(
        "frequent-subgraphs",
        collection(source),
        minimum_support_fraction=1,
        minimum_edges=0,
        maximum_edges=6,
        label_semantics="unlabeled",
        induced=induced,
    )
    actual = [signature(packed(p["pattern"])) for p in result["result"]["patterns"]]
    assert len(actual) == len(set(actual))
    assert set(actual) == expected


@pytest.mark.parametrize("induced", [False, True])
@pytest.mark.parametrize("label_mask", range(16))
@pytest.mark.parametrize("edge_mask", range(64))
def test_all_labeled_four_vertex_mni(edge_mask, label_mask, induced):
    labels = ["A" if label_mask & (1 << v) else "B" for v in range(4)]
    source = graph(
        4,
        [edge for i, edge in enumerate(PAIRS4) if edge_mask & (1 << i)],
        labels=labels,
        ids=[0, "0", 2**62 + 1, "last"],
    )
    host = packed(source, "label")
    expected = {}
    for key, (pattern, _) in universe(4, labeled=True, connected_only=True).items():
        images = [set() for _ in pattern[0]]
        for assignment in embeddings(pattern, host, induced):
            for i, vertex in enumerate(assignment):
                images[i].add(vertex)
        support = min(map(len, images))
        if support:
            expected[key] = support
    args = {
        "minimum_image_support": 1,
        "max_pattern_edges": 3,
        "output_mode": "patterns",
        "match_mode": "induced" if induced else "non_induced",
        "include_images": True,
    }
    result = call("single-graph-frequent-subgraphs", source, **args)
    actual = {}
    for row in result["result"]["patterns"]:
        pattern = packed(row["pattern"], "label")
        key = signature(pattern)
        assert key not in actual
        actual[key] = row["minimum_image_support"]
        images = [set() for _ in pattern[0]]
        for assignment in embeddings(pattern, host, induced):
            for i, vertex in enumerate(assignment):
                images[i].add(source["vertices"][vertex]["id"])
        assert [
            {"pattern_vertex": i, "count": len(values)}
            for i, values in enumerate(images)
        ] == row["image_counts"]
        assert [set(item["host_vertices"]) for item in row["images"]] == images
    assert actual == expected
    threshold = (edge_mask + label_mask) % 6 + 1
    count = call(
        "single-graph-frequent-subgraphs",
        source,
        **{
            **args,
            "minimum_image_support": threshold,
            "output_mode": "count",
            "include_images": False,
        },
    )
    assert count["result"]["frequent_pattern_count"] == sum(
        value >= threshold for value in expected.values()
    )
    assert count["result"]["patterns"] is None and "patterns" not in count["ports"]


@pytest.mark.parametrize(
    "semantics", ["unlabeled", "vertex_type", "edge_type", "vertex_and_edge_type"]
)
@pytest.mark.parametrize("induced", [False, True])
def test_type_semantics_missing_empty_types_and_canonical_reordering(
    semantics, induced
):
    source = graph(3, [(0, 1), (1, 2), (2, 0)], directed=True, labels=["", "A", "A"])
    del source["vertices"][0]["type"]
    source["edges"][0]["type"] = ""
    source["edges"][1]["type"] = "A"
    args = {
        "minimum_support_fraction": 1,
        "minimum_edges": 0,
        "maximum_edges": 3,
        "label_semantics": semantics,
        "induced": induced,
    }
    first = call("frequent-subgraphs", collection(source), **args)["result"]
    vertex_field = (
        "type" if semantics in ("vertex_type", "vertex_and_edge_type") else None
    )
    edge_field = "type" if semantics in ("edge_type", "vertex_and_edge_type") else None
    # A separately constructed labeled universe: every vertex subset and every
    # abstract typed adjacency matrix, followed by independent injections.
    domain = [None, "", "A"]
    host = packed(source, vertex_field, edge_field)
    expected = set()
    for n in range(1, 4):
        pairs = [(u, v) for u in range(n) for v in range(n) if u != v]
        for size in range(min(3, len(pairs)) + 1):
            for edges in combinations(pairs, size):
                for values in product(domain, repeat=n) if vertex_field else [None]:
                    for edge_values in (
                        product(domain, repeat=size) if edge_field else [None]
                    ):
                        candidate = graph(n, edges, directed=True)
                        if values is not None:
                            for row, value in zip(candidate["vertices"], values):
                                if value is not None:
                                    row["type"] = value
                        if edge_values is not None:
                            for row, value in zip(candidate["edges"], edge_values):
                                if value is not None:
                                    row["type"] = value
                        pattern = packed(candidate, vertex_field, edge_field)
                        if next(embeddings(pattern, host, induced), None) is not None:
                            expected.add(signature(pattern))
    actual = [
        signature(packed(row["pattern"], vertex_field, edge_field))
        for row in first["patterns"]
    ]
    assert set(actual) == expected and len(actual) == len(expected)
    for permutation in permutations(range(3)):
        renamed = deepcopy(source)
        identifiers = {i: ("vertex-" + str(permutation[i])) for i in range(3)}
        for row in renamed["vertices"]:
            row["id"] = identifiers[row["id"]]
        for i, row in enumerate(renamed["edges"]):
            row.update(
                id=f"new-edge-{i}",
                source=identifiers[row["source"]],
                target=identifiers[row["target"]],
                weight=i + 5,
            )
        random.Random(sum(permutation) + permutation[0]).shuffle(renamed["vertices"])
        renamed["edges"].reverse()
        other = call("frequent-subgraphs", collection(renamed), **args)["result"]
        assert other == first


def test_collection_validation_ownership_and_namespaces():
    a = graph(1, [], ids=[0])
    b = graph(1, [], ids=["0"])
    raw = collection(a, b)
    value = GraphCollection(raw)
    before = value.to_canonical()
    raw["graphs"][0]["vertices"][0]["id"] = "changed"
    exposed = value.to_canonical()
    exposed["graphs"].clear()
    assert value.to_canonical() == before and value.graph_count == 2
    assert value.graphs[0].node_ids == (0,) and value.graphs[1].node_ids == ("0",)
    assert GraphCollection(before).fingerprint == value.fingerprint
    with pytest.raises(GraphMineError, match="requires graph"):
        load_input(value, "graph")
    for invalid in [
        None,
        {},
        {"dataset_id": "", "graphs": []},
        {"dataset_id": "x", "graphs": {}},
        {"dataset_id": "x", "graphs": [a, a]},
        collection(a, graph(1, [], directed=True)),
    ]:
        with pytest.raises(GraphMineError):
            GraphCollection(invalid)


def test_empty_patterns_isolates_and_decimal_support_boundary():
    assert (
        call(
            "frequent-subgraphs",
            collection(),
            minimum_support_fraction=1,
            maximum_edges=0,
            minimum_edges=0,
            minimum_vertices=0,
        )["result"]["patterns"]
        == []
    )
    data = collection(graph(0, []), graph(1, []), graph(3, []))
    result = call(
        "frequent-subgraphs",
        data,
        minimum_support_fraction=0.3333333333333333,
        maximum_edges=0,
        minimum_edges=0,
        minimum_vertices=0,
    )["result"]
    assert {
        p["vertex_count"]: p["support_graph_count"] for p in result["patterns"]
    } == {0: 3, 1: 2, 2: 1, 3: 1}
    result = call(
        "frequent-subgraphs",
        data,
        minimum_support_fraction=0.3333333333333334,
        maximum_edges=0,
        minimum_edges=0,
        minimum_vertices=0,
    )["result"]
    assert {
        p["vertex_count"]: p["support_graph_count"] for p in result["patterns"]
    } == {0: 3, 1: 2}
    result = call(
        "frequent-subgraphs",
        collection(graph(5, [])),
        minimum_support_fraction=1,
        maximum_edges=0,
        minimum_edges=0,
        minimum_vertices=2,
        maximum_vertices=4,
    )["result"]
    assert {p["vertex_count"] for p in result["patterns"]} == {2, 3, 4}
    empty = call(
        "single-graph-frequent-subgraphs",
        graph(0, []),
        minimum_image_support=1,
        max_pattern_edges=1,
    )
    assert empty["result"]["frequent_pattern_count"] == 0


@pytest.mark.parametrize("size", [7, 8])
def test_patterns_above_six_edges(size):
    source = graph(
        size, [(v, (v + 1) % size) for v in range(size)], labels=["A"] * size
    )
    transaction = call(
        "frequent-subgraphs",
        collection(source),
        minimum_support_fraction=1,
        minimum_edges=size,
        maximum_edges=size,
        minimum_vertices=size,
    )
    assert len(transaction["result"]["patterns"]) == 1
    mined = call(
        "single-graph-frequent-subgraphs",
        source,
        minimum_image_support=size,
        max_pattern_edges=size,
        output_mode="patterns",
    )
    assert any(
        p["edge_count"] == size and p["minimum_image_support"] == size
        for p in mined["result"]["patterns"]
    )


def test_loop_parallel_labels_and_parameter_contracts():
    source = graph(2, [(0, 1)], labels=["A", "A"])
    duplicate = deepcopy(source)
    duplicate["graph"]["allows_parallel_edges"] = True
    duplicate["edges"].append(
        {"id": "duplicate", "source": 1, "target": 0, "type": "different"}
    )
    args = {"minimum_support_fraction": 1, "maximum_edges": 1}
    with pytest.raises(GraphMineError, match="Parallel"):
        run("frequent-subgraphs", collection(duplicate), device="cpu", parameters=args)
    with pytest.raises(GraphMineError, match="different selected types"):
        run(
            "frequent-subgraphs",
            collection(duplicate),
            device="cpu",
            parameters={**args, "parallel_edges": "collapse"},
        )
    result = call(
        "frequent-subgraphs",
        collection(duplicate),
        **args,
        label_semantics="unlabeled",
        parallel_edges="collapse",
    )
    assert len(result["result"]["patterns"]) == 1
    mni = {"minimum_image_support": 1, "max_pattern_edges": 1}
    assert (
        call(
            "single-graph-frequent-subgraphs",
            duplicate,
            **mni,
            parallel_edges="collapse",
        )["result"]["frequent_pattern_count"]
        == 2
    )
    loop = deepcopy(source)
    loop["graph"]["allows_self_loops"] = True
    loop["edges"].append({"id": "loop", "source": 0, "target": 0})
    for operation, data, parameters in [
        ("frequent-subgraphs", collection(loop), args),
        ("single-graph-frequent-subgraphs", loop, mni),
    ]:
        with pytest.raises(GraphMineError, match="self-loops"):
            run(operation, data, device="cpu", parameters=parameters)
    assert (
        call("frequent-subgraphs", collection(loop), **args, self_loops="drop")[
            "result"
        ]
        == call("frequent-subgraphs", collection(source), **args)["result"]
    )
    for invalid in [
        {"maximum_edges": 0},
        {"minimum_support_fraction": 0},
        {"minimum_support_fraction": 2},
        {"minimum_vertices": 3, "maximum_vertices": 2},
        {"maximum_edges": True},
        {"closed_only": True},
    ]:
        with pytest.raises(GraphMineError):
            run(
                "frequent-subgraphs",
                collection(source),
                device="cpu",
                parameters={**args, **invalid},
            )
    for invalid in [
        {"include_images": True},
        {"minimum_image_support": 0},
        {"max_pattern_edges": 0},
        {"vertex_label_field": "missing"},
    ]:
        with pytest.raises(GraphMineError):
            run(
                "single-graph-frequent-subgraphs",
                source,
                device="cpu",
                parameters={**mni, **invalid},
            )
    for invalid_graph in [
        graph(2, [(0, 1)]),
        graph(2, [(0, 1)], directed=True, labels=["A", "A"]),
    ]:
        with pytest.raises(GraphMineError):
            run(
                "single-graph-frequent-subgraphs",
                invalid_graph,
                device="cpu",
                parameters=mni,
            )
    assert (
        call(
            "single-graph-frequent-subgraphs", source, **mni, vertex_label_field="type"
        )["result"]["frequent_pattern_count"]
        == 2
    )


@pytest.mark.parametrize("kind", ["work", "output"])
@pytest.mark.parametrize(
    "operation", ["frequent-subgraphs", "single-graph-frequent-subgraphs"]
)
def test_exhaustion_never_claims_completion(kind, operation):
    source = graph(3, [(0, 1), (1, 2)], labels=["A"] * 3)
    parameters = (
        {"minimum_support_fraction": 1, "maximum_edges": 2}
        if operation == "frequent-subgraphs"
        else {
            "minimum_image_support": 1,
            "max_pattern_edges": 2,
            "output_mode": "patterns",
        }
    )
    budget = Budget(max_candidates=1) if kind == "work" else Budget(max_output_items=1)
    with pytest.raises(ResourceLimit):
        run(
            operation,
            collection(source) if operation == "frequent-subgraphs" else source,
            device="cpu",
            parameters=parameters,
            budget=budget,
        )


def test_pattern_graph_workflow_and_count_only_rejection():
    source = graph(3, [(0, 1), (1, 2)], labels=["A"] * 3)
    inputs = {"database": {"kind": "graph_collection", "data": collection(source)}}
    plan = {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "mine",
                "operation": "frequent-subgraphs",
                "input": {"input": "database"},
                "parameters": {
                    "minimum_support_fraction": 1,
                    "minimum_edges": 2,
                    "maximum_edges": 2,
                },
            },
            {
                "id": "degrees",
                "operation": "degree-centrality",
                "input": {
                    "step": "mine",
                    "port": "patterns",
                    "select": {"kind": "pattern_graph", "index": 0},
                },
            },
        ],
    }
    validate_workflow(plan, inputs)
    completed = execute_workflow(plan, inputs)
    assert all(step["status"] == "completed" for step in completed["steps"].values())
    mining = completed["steps"]["mine"]["result"]
    degrees = completed["steps"]["degrees"]["result"]
    assert (
        degrees["graph_fingerprint"]
        == Graph(mining["result"]["patterns"][0]["pattern"]).fingerprint
    )
    assert degrees["graph_fingerprint"] != mining["input_fingerprint"]
    assert sorted(row["score"] for row in degrees["ports"]["scores"]["value"]) == [
        0.5,
        0.5,
        1,
    ]
    for index in [-1, True, "0"]:
        invalid = deepcopy(plan)
        invalid["steps"][1]["input"]["select"]["index"] = index
        with pytest.raises(GraphMineError):
            validate_workflow(invalid, inputs)
    plan["steps"][0] = {
        "id": "mine",
        "operation": "single-graph-frequent-subgraphs",
        "input": {"input": "host"},
        "parameters": {"minimum_image_support": 1, "max_pattern_edges": 2},
    }
    count_only = execute_workflow(plan, {"host": {"kind": "graph", "data": source}})
    assert count_only["steps"]["mine"]["status"] == "completed"
    assert count_only["steps"]["degrees"]["status"] == "failed"
