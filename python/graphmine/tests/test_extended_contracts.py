from itertools import combinations, permutations, product

import pytest
from graphmine import Graph, list_algorithms, run
from graphmine.exceptions import GraphMineError, UnsupportedOperation


def execute(operation, graph, **args):
    return run(operation, graph, device="cpu", parameters=args)


@pytest.mark.parametrize("supplied", [False, [], "", 0])
def test_invalid_argument_containers_cannot_turn_into_defaults(supplied):
    with pytest.raises(GraphMineError, match="parameters must be an object"):
        run(
            "pagerank",
            Graph.from_edges([], vertices=[0]),
            device="cpu",
            parameters=supplied,
        )


def test_graph_port_has_derived_fingerprint_and_original_lineage():
    graph = Graph.from_edges([(0, "0"), ("0", 2**62 + 1)])
    result = execute(
        "induced-subgraph", graph, mode="induced", vertices_or_seeds=[0, "0"]
    )
    port = result["ports"]["graph"]
    assert port["graph_fingerprint"] == Graph(port["value"]).fingerprint
    assert port["graph_fingerprint"] != graph.fingerprint
    assert port["source_graph_fingerprint"] == graph.fingerprint
    assert result["ports"]["vertices"]["graph_fingerprint"] == graph.fingerprint


def test_scipy_provenance_and_explicit_backend_selection():
    graph = Graph.from_edges([(0, 1)])
    result = run(
        "densest-k-subgraph", graph, device="cpu", backend="scipy", parameters={"k": 2}
    )
    assert result["backend"]["id"] == "scipy"
    assert result["backend"]["version"] == result["backend"]["dependencies"]["scipy"]
    with pytest.raises(UnsupportedOperation):
        run("densest-k-subgraph", graph, backend="networkx", parameters={"k": 2})
    with pytest.raises(GraphMineError):
        run(
            "densest-k-subgraph",
            graph,
            device="gpu",
            backend="scipy",
            parameters={"k": 2},
        )


def test_higher_clique_orders_are_not_replaced_by_edge_density():
    edges = list(combinations(range(7), 2)) + list(product(range(7, 19), range(19, 31)))
    graph = Graph.from_edges(edges)
    ordinary = execute("densest-subgraph", graph, clique_order=2)["result"]
    higher = execute("densest-subgraph", graph, clique_order=6)["result"]
    assert set(ordinary["vertices"]) == set(range(7, 31))
    assert set(higher["vertices"]) == set(range(7))
    assert higher["clique_count"] == 7 and higher["density"] == 1
    empty = execute("densest-subgraph", graph, clique_order=1000)["result"]
    assert empty["clique_count"] == 0 and empty["density"] == 0


def test_density_large_integer_weights_keep_exact_ratio_ordering():
    graph = Graph.from_edges([(0, 1, 2**80), (2, 3, 2**80 + 1)])
    result = execute("densest-subgraph", graph, weight_mode="edge_weight")
    assert set(result["result"]["vertices"]) == {2, 3}
    assert result["result"]["induced_edge_value"] == 2**80 + 1
    assert result["diagnostics"]["density_fraction"] == {
        "numerator": 2**80 + 1,
        "denominator": 2,
    }
    with pytest.raises(GraphMineError, match="float64"):
        execute("densest-k-subgraph", graph, k=2, weight_mode="edge_weight")


def test_quasi_clique_bounds_and_non_maximal_listing():
    graph = Graph.from_edges(combinations(range(5), 2))
    result = execute(
        "quasi-cliques",
        graph,
        gamma=1,
        minimum_size=2,
        maximum_size=3,
        maximal_only=False,
    )["result"]
    assert result["count"] == 20
    maximal = execute("quasi-cliques", graph, gamma=1, minimum_size=2, maximum_size=3)[
        "result"
    ]
    assert maximal["count"] == 10 and all(
        r["size"] == 3 for r in maximal["quasi_cliques"]
    )


def test_count_ports_remain_complete_when_instance_lists_are_truncated():
    graph = Graph.from_edges(combinations(range(4), 2))
    query = Graph.from_edges([(0, 1), (1, 2)])
    result = execute(
        "motif-counting",
        graph,
        motifs=[query.to_canonical()],
        list_instances=True,
        result_limit_per_motif=1,
    )
    assert result["result"]["count_by_motif"] == {"graph": 12}
    assert result["complete"] and result["ports"]["counts"]["complete"]
    assert not result["ports"]["instances"]["complete"]
    listed = execute(
        "subgraph-isomorphism", graph, query_graph=query.to_canonical(), result_limit=1
    )
    assert not listed["complete"] and not listed["ports"]["matches"]["complete"]
    graphlets = execute(
        "graphlet-counting",
        graph,
        graphlet_sizes=[2, 3],
        list_instances=True,
        result_limit_per_graphlet=1,
    )
    assert graphlets["complete"] and not graphlets["ports"]["instances"]["complete"]
    assert graphlets["result"]["count_by_graphlet"]["atlas-3"] == 6


@pytest.mark.parametrize("size", [5, 6, 7])
def test_atlas_graphlet_extension_through_seven_vertices(size):
    graph = Graph.from_edges(combinations(range(size), 2))
    result = execute(
        "graphlet-counting", graph, graphlet_sizes=[size], include_orbit_counts=True
    )["result"]
    counts = result["count_by_graphlet"]
    assert sum(counts.values()) == 1
    key = next(key for key, count in counts.items() if count)
    assert len(result["graphlet_dictionary"][key]["edges"]) == size * (size - 1) // 2
    assert all(
        sum(row["counts"].values()) == 1 for row in result["orbit_counts_by_vertex"]
    )


def test_multigraph_matching_has_injective_edge_predicates_and_preserves_loops():
    data = Graph.from_edges(
        [(0, "0"), ("0", "end")], vertices=[0, "0", "end"]
    ).to_canonical()
    data["graph"].update(allows_parallel_edges=True, allows_self_loops=True)
    data["vertices"][0]["label"] = "start"
    data["vertices"][1]["label"] = "start"
    data["edges"][0]["type"] = "red"
    data["edges"][1]["type"] = "red"
    data["edges"] += [
        {"id": "blue", "source": 0, "target": "0", "type": "blue"},
        {"id": "loop", "source": 0, "target": 0, "type": "loop"},
    ]
    query = Graph.from_edges([("a", "b")]).to_canonical()
    query["graph"].update(allows_parallel_edges=True, allows_self_loops=True)
    query["vertices"][0]["label"] = "start"
    query["edges"][0]["type"] = "red"
    query["edges"] += [
        {"id": "b", "source": "a", "target": "b", "type": "blue"},
        {"id": "l", "source": "a", "target": "a", "type": "loop"},
    ]
    parameters = {
        "query_graph": query,
        "vertex_predicates": [
            {"field": "label", "operator": "eq_query", "query_vertex": "a"}
        ],
        "edge_predicates": [{"field": "type", "operator": "eq_query"}],
    }
    for induced in (False, True):
        result = execute(
            "subgraph-isomorphism", Graph(data), induced=induced, **parameters
        )["result"]
        assert result["matches"] == [
            [
                {"query_vertex": "a", "data_vertex": 0},
                {"query_vertex": "b", "data_vertex": "0"},
            ]
        ]
    # Two red pattern edges may not both use the single red data edge.
    query["edges"][1]["type"] = "red"
    assert (
        execute("subgraph-isomorphism", Graph(data), **parameters)["result"]["matches"]
        == []
    )


@pytest.mark.parametrize("mask", range(64))
def test_directed_pattern_embeddings_in_all_three_vertex_digraphs(mask):
    possible = [(u, v) for u in range(3) for v in range(3) if u != v]
    edges = {e for i, e in enumerate(possible) if mask >> i & 1}
    graph = Graph.from_edges(edges, vertices=range(3), directed=True)
    for query_edges in ({(0, 1), (1, 2)}, {(0, 1), (1, 2), (2, 0)}):
        query = Graph.from_edges(query_edges, vertices=range(3), directed=True)
        for induced in (False, True):
            expected = {
                p
                for p in permutations(range(3))
                if all((p[u], p[v]) in edges for u, v in query_edges)
                and (not induced or {(p[u], p[v]) for u, v in query_edges} == edges)
            }
            result = execute(
                "subgraph-isomorphism",
                graph,
                query_graph=query.to_canonical(),
                induced=induced,
            )["result"]
            assert {
                tuple(r["data_vertex"] for r in rows) for rows in result["matches"]
            } == expected


def test_empty_queries_and_graph_boundaries():
    graph, empty = Graph.from_edges([(0, 1)]), Graph.from_edges([], vertices=[])
    result = execute("subgraph-isomorphism", graph, query_graph=empty.to_canonical())[
        "result"
    ]
    assert result["matches"] == [[]] and result["complete"]
    result = execute("community-detection", empty, solution_quality="exact")["result"]
    assert result["community_count"] == 0 and result["quality_score"] == 0
    with pytest.raises(GraphMineError):
        execute("densest-subgraph", empty)


def test_parallel_matching_returns_the_id_of_the_best_edge():
    data = Graph.from_edges([("l", "r", 4)]).to_canonical()
    data["graph"]["allows_parallel_edges"] = True
    data["vertices"][0]["attributes"] = {"side": "left"}
    data["vertices"][1]["attributes"] = {"side": "right"}
    data["edges"].append({"id": "cheap", "source": "l", "target": "r", "weight": -2})
    result = execute(
        "bipartite-matching",
        Graph(data),
        objective="minimum_cost",
        weight_mode="edge_weight",
    )["result"]
    assert result["matching_edges"] == ["cheap"] and result["objective_value"] == -2


def test_new_algorithms_never_claim_an_unsupported_gpu_path():
    from graphmine.backends.cugraph import supports

    operations = {
        "densest-subgraph",
        "densest-k-subgraph",
        "quasi-cliques",
        "motif-counting",
        "graphlet-counting",
        "subgraph-isomorphism",
        "maximal-bicliques",
        "butterfly-counting",
        "bipartite-matching",
        "community-detection",
        "balanced-partitioning",
        "signed-balance",
    }
    assert operations <= {card["id"] for card in list_algorithms()}
    assert all(not supports(op, {})[0] for op in operations)


def test_oversized_integer_gpu_weight_fails_without_conversion_overflow(monkeypatch):
    from graphmine.backends import cugraph

    monkeypatch.setattr(cugraph, "installed", lambda: True)
    graph = Graph.from_edges([(0, 1, 10**500)])
    with pytest.raises(UnsupportedOperation):
        cugraph.prepare("single-source-shortest-paths", {}, graph)
