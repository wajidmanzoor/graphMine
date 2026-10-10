import json
import os
import subprocess
import sys

import pytest
from graphmine import Budget, Graph, list_algorithms, run
from graphmine.exceptions import GraphMineError, ResourceLimit, UnsupportedOperation


def test_public_catalog_stays_callable_after_loading_families():
    assert list_algorithms() == list_algorithms()
    assert len({card["id"] for card in list_algorithms()}) == len(list_algorithms())


def test_typed_ids_and_isolates_survive_every_boundary():
    ids = [0, "0", 2**62 + 1, "isolated"]
    graph = Graph.from_edges([(0, "0"), ("0", 2**62 + 1)], vertices=ids)
    result = run(
        "breadth-first-search", graph, parameters={"sources": [0]}, device="cpu"
    )
    result = json.loads(json.dumps(result, allow_nan=False))
    assert [(r["vertex"], r["distance"]) for r in result["result"]["distances"]] == [
        (0, 0),
        ("0", 1),
        (2**62 + 1, 2),
        ("isolated", None),
    ]
    copied = graph.to_canonical()
    copied["vertices"][0]["id"] = "changed"
    assert graph.node_ids == tuple(ids)


@pytest.mark.parametrize("bad_id", [True, False, 1.0, None, "", []])
def test_id_coercion_is_rejected(bad_id):
    with pytest.raises(GraphMineError):
        Graph.from_edges([], vertices=[bad_id])


def test_unknown_parameters_are_not_silently_ignored():
    with pytest.raises(GraphMineError, match="Unsupported parameters"):
        run(
            "k-cliques",
            Graph.from_edges([]),
            parameters={"k": 3, "gamma": 0.8},
            device="cpu",
        )


def test_count_only_and_truncated_memberships_are_not_complete_ports():
    graph = Graph.from_edges([(u, v) for u in range(5) for v in range(u + 1, 5)])
    count = run("k-cliques", graph, parameters={"k": 3}, device="cpu")
    partial = run(
        "k-cliques",
        graph,
        parameters={"k": 3, "mode": "enumerate", "result_limit": 2},
        device="cpu",
    )
    assert count["result"]["count"] == partial["result"]["count"] == 10
    assert count["ports"]["count"]["complete"]
    assert partial["ports"]["count"]["complete"]
    assert not count["ports"]["groups"]["complete"]
    assert not partial["ports"]["groups"]["complete"]
    assert len(partial["ports"]["groups"]["value"]) == 2


def test_clique_parameter_is_not_limited_to_five_or_six():
    graph = Graph.from_edges([(u, v) for u in range(8) for v in range(u + 1, 8)])
    assert (
        run("k-cliques", graph, parameters={"k": 7}, device="cpu")["result"]["count"]
        == 8
    )
    assert (
        run("k-cliques", graph, parameters={"k": 8}, device="cpu")["result"]["count"]
        == 1
    )
    assert (
        run("k-cliques", graph, parameters={"k": 9}, device="cpu")["result"]["count"]
        == 0
    )


def test_resource_limit_is_a_failure_not_a_false_complete_result():
    graph = Graph.from_edges([(u, v) for u in range(7) for v in range(u + 1, 7)])
    with pytest.raises(ResourceLimit):
        run(
            "k-cliques",
            graph,
            parameters={"k": 4},
            device="cpu",
            budget=Budget(max_candidates=2),
        )


def test_cpu_only_does_not_dispatch_cuda_even_with_backend_auto_config():
    # NetworkX can import installed plugin modules during initialization. Import
    # is not GPU execution. Reject every CUDA backend load and hide all devices.
    script = """
import networkx as nx
import json
original = nx.utils.backends._load_backend
def reject_cuda(name):
    if name == 'cugraph':
        raise AssertionError('CPU-only request attempted CUDA dispatch')
    return original(name)
nx.utils.backends._load_backend = reject_cuda
from graphmine import Graph,run
r=run('triangle-counting',Graph.from_edges([(0,1),(1,2),(2,0)]),device='cpu')
print(json.dumps({'device':r['backend']['device'],'count':r['result']['count']}))
"""
    environment = {
        **os.environ,
        "CUDA_VISIBLE_DEVICES": "",
        "NX_CUGRAPH_AUTOCONFIG": "True",
    }
    process = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {"device": "cpu", "count": 1}


def test_device_conflicts_and_unsupported_gpu_parameters_fail():
    graph = Graph.from_edges([(0, 1)])
    with pytest.raises(GraphMineError, match="conflicts"):
        run("pagerank", graph, device="cpu", backend="cugraph")
    with pytest.raises(UnsupportedOperation, match="unweighted"):
        run(
            "betweenness-centrality",
            graph,
            parameters={"weight_mode": "edge_weight"},
            device="gpu",
        )


def test_directed_input_requires_explicit_projection_for_undirected_algorithm():
    with pytest.raises(GraphMineError, match="undirected"):
        run("maximum-clique", Graph.from_edges([(0, 1)], directed=True), device="cpu")
