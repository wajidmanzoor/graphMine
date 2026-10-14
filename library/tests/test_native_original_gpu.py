"""Exercise every restored CUDA adapter through the public native runtime.

The oracles use NetworkX or direct subset/event enumeration. Device provenance,
profile rejection, typed identifiers, and planner admission are checked as well
as the mathematical result. No backend substitutes CPU execution silently.
"""

import importlib.util
import itertools
import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path

import networkx as nx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_native_binding", ROOT / "python/graphmine/graphmine/native/__init__.py"
)
BINDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BINDING)
POLICY = os.environ.get("GRAPHMINE_EVIDENCE_DEVICE", "cpu")
ORDINAL = int(os.environ.get("GRAPHMINE_TEST_GPU", "0"))


@pytest.fixture(scope="module")
def native(request):
    lib = BINDING.NativeLibrary(
        Path(os.environ["GRAPHMINE_NATIVE_CPU_BUILD"]) / "libgraphmine_runtime.so"
    )
    transport = lib.request

    def observe(value):
        result = transport(value)
        if value.get("command") == "run":
            backend = result["backend"]
            assert backend["device"] == POLICY
            assert backend["python_runtime_required"] is False
            key = result["operation"] + ":" + backend["id"]
            counts = request.session.native_observed_operations
            counts[key] = counts.get(key, 0) + 1
            if POLICY == "gpu":
                assert backend["hardware"]["uuid"]
                request.session.native_gpu_hardware = backend["hardware"]
        return result

    lib.request = observe
    return lib


def graph(n, edges, directed=False, left=None):
    vertices = [{"id": i} for i in range(n)]
    if left is not None:
        for v in vertices:
            v["attributes"] = {"side": "left" if v["id"] in left else "right"}
    rows = []
    for i, edge in enumerate(edges):
        u, v, *weight = edge
        rows.append({"id": f"e{i}", "source": u, "target": v})
        if weight:
            rows[-1]["weight"] = weight[0]
    return {
        "graph": {
            "id": "original-runtime-oracle",
            "directed": directed,
            "allows_self_loops": True,
            "allows_parallel_edges": True,
        },
        "vertices": vertices,
        "edges": rows,
    }


def call(native, op, backend, data, **params):
    selected = backend if POLICY == "gpu" else "cpp"
    result = native.run(
        op, data, parameters=params, backend=selected, device=POLICY, gpu_device=ORDINAL
    )
    assert result["backend"]["id"] == selected
    return result


def fraction(row):
    return Fraction(int(row["numerator"]), int(row["denominator"]))


@pytest.mark.parametrize("backend", ["tot", "wetric"])
def test_triangle_backends_on_each_device(native, backend):
    for edges in [
        [],
        [(0, 1), (1, 2), (0, 2)],
        list(itertools.combinations(range(5), 2)),
    ]:
        reference = nx.Graph(edges)
        reference.add_nodes_from(range(6))
        result = call(native, "triangle-counting", backend, graph(6, edges))
        assert (
            result["ports"]["count"]["value"]
            == sum(nx.triangles(reference).values()) // 3
        )


@pytest.mark.parametrize(
    "backend",
    ["gleiden", "parallel-louvain", "parallel-leiden", "parallel-leiden-plus"],
)
def test_community_gpu_partition_and_modularity(native, backend):
    for edges in [
        [],
        [(0, 1)],
        [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4), (4, 5), (5, 3)],
    ]:
        data = graph(7, edges)
        for resolution in [1] if backend == "gleiden" else [0.5, 1, 1.75]:
            result = call(
                native, "community-detection", backend, data, resolution=resolution
            )
            groups = [set(row["vertices"]) for row in result["result"]["groups"]]
            assert set.union(*groups) == set(range(7))
            assert sum(map(len, groups)) == 7
            g = nx.Graph()
            g.add_nodes_from(range(7))
            g.add_edges_from(edges)
            expected = (
                nx.community.modularity(g, groups, resolution=resolution)
                if edges
                else 0
            )
            assert float(
                fraction(result["result"]["quality_score_exact"])
            ) == pytest.approx(expected)
            if edges and POLICY == "gpu":
                assert result["quality"] == "heuristic"
                assert result["result"]["optimal"] is False


def test_quasi_cliques_subset_oracle(native):
    edges = [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3), (3, 4)]
    for gamma in [0.5, 0.8, 1]:
        qualifying = []
        g = nx.Graph(edges)
        g.add_nodes_from(range(6))
        for k in range(2, 7):
            for nodes in itertools.combinations(range(6), k):
                if all(
                    g.subgraph(nodes).degree(v) >= Fraction(str(gamma)) * (k - 1)
                    for v in nodes
                ):
                    qualifying.append(frozenset(nodes))
        expected = {s for s in qualifying if not any(s < t for t in qualifying)}
        result = call(
            native,
            "quasi-cliques",
            "cuqc",
            graph(6, edges),
            gamma=gamma,
            minimum_size=2,
        )
        assert {
            frozenset(r["vertices"]) for r in result["result"]["quasi_cliques"]
        } == expected


@pytest.mark.parametrize(
    "op,backend",
    [("maximal-bicliques", "cumbe"), ("maximal-biclique-counting", "mbe-gpu")],
)
def test_biclique_enumeration_and_count(native, op, backend):
    left, right = {0, 1, 2}, {3, 4, 5}
    for edges in [[], [(0, 3), (0, 4), (1, 3), (1, 4), (2, 4), (2, 5)]]:
        expected = set()
        for a in range(1, 8):
            l = frozenset(i for i in left if a & (1 << i))
            r = frozenset(v for v in right if all((u, v) in edges for u in l))
            if r and all(any((u, v) not in edges for v in r) for u in left - l):
                expected.add((l, r))
        params = (
            {"left_partition": sorted(left), "right_partition": sorted(right)}
            if op == "maximal-bicliques"
            else {}
        )
        result = call(native, op, backend, graph(6, edges, left=left), **params)[
            "result"
        ]
        assert result["total_count"] == len(expected)
        if op == "maximal-bicliques":
            assert {
                (frozenset(r["left_vertices"]), frozenset(r["right_vertices"]))
                for r in result["bicliques"]
            } == expected


def test_dynamic_triangle_batch_oracle(native):
    data = graph(4, [(0, 1), (1, 2), (0, 2), (1, 3), (2, 3)])
    for listing in [False, True]:
        result = call(
            native,
            "dynamic-triangle-counting",
            "edtc",
            data,
            updates=[
                {"kind": "delete_edge", "source": 0, "target": 1},
                {"kind": "insert_edge", "source": 0, "target": 3},
            ],
            list_changed_instances=listing,
        )["result"]
        assert result["deleted_triangle_count"] == 1
        assert result["inserted_triangle_count"] == 1
        assert result["net_triangle_change"] == 0
        assert (
            result["initial_global_triangle_count"]
            == result["final_global_triangle_count"]
            == 2
        )
        if listing:
            assert result["deleted_triangles"] == [{"vertices": [0, 1, 2]}]
            assert result["inserted_triangles"] == [{"vertices": [0, 2, 3]}]


@pytest.mark.parametrize(
    "backend,induced", [("graphminer", True), ("graphset", False), ("dumato", True)]
)
def test_gpu_motif_counts(native, backend, induced):
    data = graph(5, [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3), (3, 4)])
    motif = graph(3, [(0, 1), (1, 2), (0, 2)])
    for identity, expected in [
        ("all_embeddings", 12),
        ("unique_vertex_set_and_mapping_class", 2),
    ]:
        result = call(
            native,
            "motif-counting",
            backend,
            data,
            motifs=[motif],
            induced=induced,
            occurrence_identity=identity,
            list_instances=True,
        )["result"]
        assert result["count_by_motif"][motif["graph"]["id"]] == expected


def test_gmatch_embeddings(native):
    data = graph(5, [(0, 1), (0, 2), (1, 2), (2, 3)])
    query = graph(3, [(0, 1), (1, 2), (0, 2)])
    result = call(native, "subgraph-isomorphism", "gmatch", data, query_graph=query)[
        "result"
    ]
    assert result["returned_count"] == 6
    assert result["complete"] is True


def test_cli_keeps_kernel_diagnostics_out_of_json():
    backend = "gmatch" if POLICY == "gpu" else "cpp"
    request = {
        "command": "run",
        "operation": "subgraph-isomorphism",
        "graph": graph(4, [(0, 1), (0, 2), (1, 2), (2, 3)]),
        "parameters": {"query_graph": graph(3, [(0, 1), (0, 2), (1, 2)])},
        "device": POLICY,
        "backend": backend,
        "gpu_device": ORDINAL,
    }
    process = subprocess.run(
        [
            str(Path(os.environ["GRAPHMINE_NATIVE_CPU_BUILD"]) / "graphmine-native"),
            "request",
        ],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["backend"]["id"] == backend
    assert result["result"]["returned_count"] == 6


def test_dynamic_triangles_preserve_typed_ids(native):
    data = graph(4, [(0, 1), (1, 2), (0, 2), (2, 3)])
    ids = [0, "0", 9007199254740993, "last"]
    for vertex in data["vertices"]:
        vertex["id"] = ids[vertex["id"]]
    for edge in data["edges"]:
        edge["source"], edge["target"] = ids[edge["source"]], ids[edge["target"]]
    result = call(
        native,
        "dynamic-triangle-counting",
        "edtc",
        data,
        updates=[
            {"kind": "delete_edge", "source": 0, "target": "0"},
            {"kind": "insert_edge", "source": 0, "target": "last"},
        ],
        list_changed_instances=True,
    )["result"]
    assert {frozenset(r["vertices"]) for r in result["deleted_triangles"]} == {
        frozenset(ids[:3])
    }
    assert {frozenset(r["vertices"]) for r in result["inserted_triangles"]} == {
        frozenset([ids[0], ids[2], ids[3]])
    }


@pytest.mark.parametrize("backend", ["everest", "mayura"])
def test_temporal_gpu_event_identity(native, backend):
    data = graph(4, [(0, 1), (1, 2), (0, 2), (0, 2), (2, 3)], directed=True)
    for edge, timestamp in zip(data["edges"], [100, 101, 102, 103, 104], strict=True):
        edge["timestamp"] = timestamp
    motif = graph(3, [(0, 1), (1, 2), (0, 2)], directed=True)
    result = call(
        native,
        "temporal-motifs",
        backend,
        data,
        temporal_motif={"graph": motif},
        maximum_duration_seconds=3,
        list_instances=True,
    )["result"]
    assert result["occurrence_count"] == 2
    assert {tuple(row["edge_ids"]) for row in result["instances"]} == {
        ("e0", "e1", "e2"),
        ("e0", "e1", "e3"),
    }


def test_ecl_components_and_gdlog_reachability(native):
    edges = [(0, 1), (1, 0), (1, 2), (2, 3), (3, 2)]
    data = graph(5, edges, directed=True)
    g = nx.DiGraph(edges)
    g.add_nodes_from(range(5))
    for mode, oracle in [
        ("weakly_connected", nx.weakly_connected_components),
        ("strongly_connected", nx.strongly_connected_components),
    ]:
        result = call(
            native, "connected-components", "ecl-scc", data, connectivity_mode=mode
        )["result"]
        assert {frozenset(r["vertices"]) for r in result["groups"]} == {
            frozenset(c) for c in oracle(g)
        }
    result = call(native, "transitive-closure", "gdlog", data)["result"]
    assert {(r["source"], r["target"]) for r in result["pairs"]} == set(
        nx.transitive_closure(g, reflexive=True).edges
    )


@pytest.mark.parametrize("backend", ["graphminer", "gamma-butterfly"])
def test_butterfly_count_and_participation(native, backend):
    edges = list(itertools.product(range(3), range(3, 6)))
    result = call(
        native,
        "butterfly-counting",
        backend,
        graph(7, edges, left={0, 1, 2}),
        mode="per_vertex",
    )["result"]
    assert result["butterfly_count"] == 9
    assert [row["count"] for row in result["vertices"]] == [6] * 6 + [0]


def test_acctd_edge_truss_oracle(native):
    edges = list(itertools.combinations(range(4), 2)) + [(3, 4)]
    result = call(native, "k-truss", "acctd", graph(6, edges))["result"]
    g = nx.Graph(edges)
    g.add_nodes_from(range(6))
    expected = {tuple(sorted(e)): 2 for e in g.edges}
    for k in range(3, 7):
        for edge in nx.k_truss(g, k).edges:
            expected[tuple(sorted(edge))] = k
    assert {
        (r["source"], r["target"]): r["truss_number"] for r in result["edges"]
    } == expected


def test_cds_exact_fractional_density(native):
    edges = [(0, 1), (1, 2)]
    result = call(native, "densest-subgraph", "cds", graph(4, edges))["result"]
    assert fraction(result["density_exact"]) == Fraction(2, 3)


def test_gpu4gst_cost_and_groups(native):
    data = graph(5, [(0, 1, 2), (1, 3, 3), (0, 2, 1), (2, 3, 10)])
    result = call(native, "group-steiner-tree", "gpu4gst", data, groups=[[0], [3]])[
        "result"
    ]
    assert result["feasible"] and result["optimal"]
    assert fraction(result["tree_weight_exact"]) == 5


def test_kpar_explicit_approximation(native):
    data = graph(4, [(0, 1), (1, 2), (2, 3), (3, 0)], directed=True)
    result = call(
        native,
        "personalized-pagerank",
        "kpar",
        data,
        seed_vertices=[0],
        restart_probability=0.2,
        solution_quality="approximate",
        epsilon=0.01,
        top_k=2,
    )
    scores = {row["vertex"]: row["score"] for row in result["ports"]["scores"]["value"]}
    expected = nx.pagerank(
        nx.DiGraph([(0, 1), (1, 2), (2, 3), (3, 0)]),
        alpha=0.8,
        personalization={0: 1},
        tol=1e-13,
        max_iter=1000,
    )
    assert scores.keys() == expected.keys()
    assert max(abs(scores[v] - expected[v]) for v in scores) < 0.1
    assert result["ports"]["scores"]["complete"]
    assert len(result["result"]["ranking"]) == 2
    if POLICY == "gpu":
        assert result["quality"] == "approximate"
        assert result["result"]["error_bound_certified"] is False


def test_superfuser_declared_heuristic(native):
    for p in [0, 1]:
        data = graph(3, [(0, 1, p), (1, 2, p), (2, 0, p)], directed=True)
        result = call(
            native,
            "influence-maximization",
            "superfuser",
            data,
            diffusion_model="independent_cascade",
            seed_set_size=1,
            solution_quality="heuristic",
            sample_count=64,
        )
        assert result["ports"]["spread"]["value"] == (1 if p == 0 else 3)
        if POLICY == "gpu":
            assert result["quality"] == "heuristic"
            assert result["result"]["optimal"] is False
            assert result["result"]["guarantee_met"] is False


@pytest.mark.parametrize(
    "operation,backend,params",
    [
        ("community-detection", "gleiden", {"solution_quality": "exact"}),
        (
            "community-detection",
            "parallel-leiden",
            {"quality_function": "constant_potts_model"},
        ),
        ("community-detection", "gleiden", {"resolution": 2}),
        ("quasi-cliques", "cuqc", {"gamma": 0.4, "minimum_size": 2}),
        ("personalized-pagerank", "kpar", {"seed_vertices": [0]}),
        (
            "influence-maximization",
            "superfuser",
            {"seed_set_size": 1, "diffusion_model": "independent_cascade"},
        ),
    ],
)
def test_gpu_rejects_incompatible_quality(native, operation, backend, params):
    # No CUDA launch should be required to reject incompatible semantics.
    if POLICY == "cpu":
        return
    with pytest.raises(BINDING.NativeError) as caught:
        native.run(
            operation,
            graph(3, [(0, 1), (1, 2)]),
            parameters=params,
            device="gpu",
            backend=backend,
            gpu_device=ORDINAL,
        )
    assert caught.value.code == "unsupported_input"


def test_gpu_validation_checks_community_quality(native):
    if POLICY == "cpu":
        return
    request = {
        "command": "validate",
        "operation": "community-detection",
        "graph": graph(3, [(0, 1), (1, 2)]),
        "device": "gpu",
        "parameters": {"solution_quality": "exact"},
    }
    with pytest.raises(BINDING.NativeError) as caught:
        native.request(request)
    assert caught.value.code == "unsupported_input"
    request["parameters"]["solution_quality"] = "heuristic"
    assert native.request(request)["operation"] == "community-detection"


def test_catalog_restores_all_original_choices(native):
    expected = {
        "community-detection": {
            "gleiden",
            "parallel-louvain",
            "parallel-leiden",
            "parallel-leiden-plus",
        },
        "quasi-cliques": {"cuqc"},
        "maximal-bicliques": {"cumbe"},
        "dynamic-triangle-counting": {"edtc"},
        "maximal-biclique-counting": {"mbe-gpu"},
        "motif-counting": {"graphminer", "graphset", "dumato"},
        "subgraph-isomorphism": {"gmatch"},
        "temporal-motifs": {"everest", "mayura"},
        "connected-components": {"ecl-scc"},
        "transitive-closure": {"gdlog"},
        "butterfly-counting": {"graphminer", "gamma-butterfly"},
        "k-truss": {"acctd"},
        "densest-subgraph": {"cds"},
        "personalized-pagerank": {"kpar"},
        "group-steiner-tree": {"gpu4gst"},
        "influence-maximization": {"superfuser"},
    }
    cards = {c["id"]: c for c in native.catalog()["operations"]}
    assert sum(map(len, expected.values())) == 23
    for op, backends in expected.items():
        actual = {
            b["id"]
            for b in cards[op]["backends"]
            if b["device"] == "gpu" and (b["compiled"] or POLICY == "cpu")
        }
        assert backends <= actual
