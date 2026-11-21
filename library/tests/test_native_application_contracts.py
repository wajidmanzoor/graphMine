"""Public/native parity, review without execution and representation isolation."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import test_native_extended
from test_native_extended import BINDING, canonical

native = test_native_extended.native


def stable(result):
    return {
        key: value
        for key, value in result.items()
        if key not in {"elapsed_seconds", "representations"}
    }


@pytest.mark.parametrize("operation", [
    "maximal-bicliques", "maximal-biclique-counting", "community-detection",
])
@pytest.mark.parametrize("explicit_unlimited", [False, True])
def test_calculations_exceed_old_candidate_cap_without_a_default_work_limit(
    native, operation, explicit_unlimited,
):
    if operation == "community-detection":
        graph = canonical(800, [(0, vertex) for vertex in range(1, 800)])
    else:
        # Isolates inflate the old clique-completion search, but this input has
        # exactly one nonempty maximal biclique: the single cross-partition edge.
        graph = canonical(200, [(0, 100)], sides=["left"] * 100 + ["right"] * 100)
    with pytest.raises(BINDING.NativeError, match="candidate budget exceeded"):
        native.run(operation, graph, device="cpu", budget={"max_candidates": 2_000_000})
    options = {"budget": {"max_candidates": None}} if explicit_unlimited else {}
    result = native.run(operation, graph, device="cpu", **options)
    assert result["budget"]["max_candidates"] is None
    assert result["complete"] is True
    if operation == "maximal-bicliques":
        assert result["result"]["bicliques"] == [{"left_vertices": [0], "right_vertices": [100]}]
        assert result["result"]["total_count"] == 1
    elif operation == "maximal-biclique-counting":
        assert result["ports"]["count"]["value"] == 1
    else:
        rows = result["result"]["community_by_vertex"]
        assert {row["vertex"] for row in rows} == set(range(800))
        assert result["result"]["community_count"] == 1


def test_complete_native_output_exceeds_the_former_default_limit(native):
    graph = canonical(100_001, [])
    with pytest.raises(BINDING.NativeError, match="output budget exceeded"):
        native.run("breadth-first-search", graph, device="cpu", parameters={"sources": [0]},
                   budget={"max_output_items": 100_000})
    result = native.run("breadth-first-search", graph, device="cpu", parameters={"sources": [0]})
    assert result["budget"] == {"max_candidates": None, "max_output_items": None, "timeout_seconds": None}
    assert len(result["result"]["distances"]) == 100_001
    assert result["complete"] is True


def test_public_api_without_python_algorithm_dependencies(native):
    root = Path(__file__).resolve().parents[2]
    program = """
import sys, json, importlib.abc
sys.path.insert(0, sys.argv[1])
class NoAlgorithms(importlib.abc.MetaPathFinder):
    def find_spec(self, name, *args):
        if name.split('.')[0] in {'networkx','numpy','scipy','cvxpy','igraph','gudhi','rapidfuzz','cugraph'} or name.startswith('graphmine.algorithms'):
            raise AssertionError('Python algorithm dependency imported: '+name)
sys.meta_path.insert(0, NoAlgorithms())
from graphmine import Graph, list_algorithms, list_families, run
from graphmine.workflows import execute_workflow
from graphmine.dispatch import native_library
assert list_algorithms() == native_library().catalog()['operations']
assert list_families() == native_library().catalog()['families']
graph = Graph.from_edges([(0, '0'), ('0', 'é'), ('é', 0)])
plan = {'version':1, 'device':'cpu', 'steps':[{'id':'count','operation':'triangle-counting','input':{'input':'g'}}]}
result = execute_workflow(plan, {'g':{'kind':'graph','data':graph.to_canonical()}})
assert result['status'] == 'completed', result
assert result['steps']['count']['result']['ports']['count']['value'] == 1
assert result['steps']['count']['result']['input_fingerprint'] == graph.fingerprint
print(json.dumps(run('triangle-counting', graph, device='cpu')))
"""
    completed = subprocess.run(
        [sys.executable, "-S", "-c", program, str(root / "python/graphmine")],
        env={
            **os.environ,
            "GRAPHMINE_NATIVE_LIBRARY": native.path,
            "CUDA_VISIBLE_DEVICES": "",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout)["backend"]["id"] == "cpp"


def test_validation_has_no_algorithm_execution(native):
    # Review only validates contracts and input records. A deliberately tiny
    # explicit work budget still applies when the caller requests execution.
    graph = canonical(2500, [])
    reviewed = native.validate("maximum-independent-set", graph)
    assert "result" not in reviewed and "ports" not in reviewed
    with pytest.raises(BINDING.NativeError, match="budget"):
        native.run(
            "maximum-independent-set", graph, device="cpu", budget={"max_candidates": 1}
        )
    with pytest.raises(BINDING.NativeError, match="Unknown|unknown"):
        native.validate(
            "node-lookup",
            graph,
            parameters={
                "vertex_filters": [
                    {"field": "attributes.unknown", "op": "eq", "value": 1}
                ]
            },
        )
    with pytest.raises(BINDING.NativeError):
        native.validate(
            "node-learning",
            parameters={"model_definition": {"architecture": "sgc", "epochs": False}},
            partial_parameters=True,
        )
    with pytest.raises(BINDING.NativeError):
        native.validate(
            "node-learning",
            parameters={
                "model_definition": {"architecture": "sgc", "secret_code": "x"}
            },
            partial_parameters=True,
        )


def test_native_backend_evidence_admission(native):
    graph = canonical(3, [(0, 1), (1, 2)])
    assert (
        native.run(
            "breadth-first-search",
            graph,
            parameters={"sources": [0]},
            allowed_backends=["cpp"],
        )["backend"]["id"]
        == "cpp"
    )
    for allowed in ([], ["libcugraph"], ["invented"]):
        with pytest.raises(BINDING.NativeError):
            native.run(
                "breadth-first-search",
                graph,
                parameters={"sources": [0]},
                device="cpu",
                allowed_backends=allowed,
            )


def test_cache_reuses_content_and_normalization_without_changing_budgets(native):
    native.request({"command": "representation_cache", "action": "clear"})
    graph = canonical(3, [(0, 1, 2), (0, 1, 3), (1, 2, 1)], directed=True)
    first = native.run(
        "single-source-shortest-paths", graph, parameters={"source": 0}, device="cpu"
    )
    second = native.run(
        "single-source-shortest-paths", graph, parameters={"source": 0}, device="cpu"
    )
    assert stable(first) == stable(second)
    assert not any(row["hit"] for row in first["representations"])
    assert all(row["hit"] for row in second["representations"])
    normalization = first["representations"][-1]["normalization"]
    assert normalization == {
        "projection_applied": False,
        "self_loops_removed": 0,
        "parallel_edges_collapsed": 1,
        "weights_cast": 3,
        "vertices": 3,
        "edges": 2,
    }
    assert second["representations"][-1]["normalization"] == normalization
    assert first["ports"]["distances"]["value"][2]["distance"] == 3
    rank = native.run("pagerank", graph, device="cpu")
    assert rank["representations"][0]["hit"]
    assert not rank["representations"][-1][
        "hit"
    ]  # summed weights versus minimum lengths
    for row in first["representations"]:
        assert first["input_fingerprint"] in row["key"]
        assert first["implementation_sha256"] in row["key"]
    graph["edges"][0]["weight"] = 5
    changed = native.run(
        "single-source-shortest-paths", graph, parameters={"source": 0}, device="cpu"
    )
    assert changed["input_fingerprint"] != first["input_fingerprint"]
    assert not any(row["hit"] for row in changed["representations"])
    assert changed["ports"]["distances"]["value"][2]["distance"] == 4
    with pytest.raises(BINDING.NativeError, match="budget"):
        native.run(
            "single-source-shortest-paths",
            graph,
            parameters={"source": 0},
            device="cpu",
            budget={"max_candidates": 1},
        )


def test_cache_bounded_eviction_disable_and_concurrent_identity(native):
    cache = lambda **options: native.request(
        {"command": "representation_cache", **options}
    )
    initial = cache()
    try:
        cache(action="clear")
        cache(action="configure", max_bytes=15000)
        for i in range(16):
            graph = canonical(3, [(0, 1)])
            graph["graph"]["id"] = str(i)
            native.run("node-lookup", graph, device="cpu")
        state = cache()
        assert state["accounted_bytes"] <= state["max_bytes"] and state["evictions"] > 0
        cache(action="configure", max_bytes=0)
        assert cache()["entries"] == 0
        cache(action="configure", max_bytes=initial["max_bytes"])
        graph = canonical(3, [(0, 1), (1, 2)])

        def execute(i):
            data = deepcopy(graph)
            data["vertices"][0]["id"] = f"v-{i}"
            data["edges"][0]["source"] = f"v-{i}"
            result = native.run("node-lookup", data, device="cpu")
            return result["input_fingerprint"], result["ports"]["vertices"]["value"][0]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(execute, range(32)))
        assert len({fingerprint for fingerprint, _ in results}) == 32
        assert [value for _, value in results] == [f"v-{i}" for i in range(32)]
    finally:
        cache(action="configure", max_bytes=initial["max_bytes"])
        cache(action="clear")
