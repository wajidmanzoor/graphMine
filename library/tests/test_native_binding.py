"""Test transport/ingestion boundaries; graph algorithms run in the native core."""

from __future__ import annotations

import concurrent.futures
import csv
import ctypes
import ctypes.util
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "python/graphmine/graphmine/native/__init__.py"
spec = importlib.util.spec_from_file_location("tested_native_binding", WRAPPER)
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)
CPU = Path(os.environ.get("GRAPHMINE_NATIVE_CPU_BUILD", "/tmp/graphmine-native-cpu"))
GPU = Path(os.environ.get("GRAPHMINE_NATIVE_GPU_BUILD", "/tmp/graphmine-native-gpu"))
ORIGINAL = Path(
    os.environ.get(
        "GRAPHMINE_NATIVE_ORIGINAL_BUILD", "/tmp/graphmine-native-staged-build/runtime"
    )
)


@pytest.fixture(scope="session", autouse=True)
def record_evidence(request):
    files = [WRAPPER, Path(__file__), ROOT / "library/manifests/problem_families.json"]
    files += list((ROOT / "library/runtime").rglob("*.cpp"))
    files += list((ROOT / "library/runtime").rglob("*.hpp"))
    files += list((ROOT / "library/runtime").rglob("*.in"))
    files += [ROOT / "library/runtime/CMakeLists.txt"]
    for directory in {CPU, GPU, ORIGINAL}:
        files += [
            directory / "libgraphmine_runtime.so",
            directory / "graphmine-native",
            directory / "native-source-hashes.txt",
        ]

    def snapshot():
        return {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)
        }

    before = snapshot()
    yield
    unchanged = before == snapshot()
    report = getattr(request.config.option, "xmlpath", None)
    if report:
        Path(str(report) + ".metadata.json").write_text(
            json.dumps(
                {
                    "scope": "Native C ABI/Python parity and libcudf ingestion; no application migration claim",
                    "source_files": before,
                    "sources_unchanged_during_run": unchanged,
                    "collected_test_count": len(request.session.items),
                },
                indent=2,
            )
            + "\n"
        )
    assert unchanged, "Native/binding inputs changed during verification"


def test_default_native_constructor_uses_explicit_installation(monkeypatch):
    monkeypatch.setenv("GRAPHMINE_NATIVE_LIBRARY", str(CPU / "libgraphmine_runtime.so"))
    implicit = binding.NativeLibrary()
    explicit = binding.NativeLibrary(CPU / "libgraphmine_runtime.so")
    assert implicit.catalog() == explicit.catalog()
    assert Path(implicit.path).samefile(explicit.path)


def graph():
    return {
        "graph": {
            "id": "binding-check",
            "directed": True,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": v} for v in [0, "0", 9007199254740993, "isolated"]],
        "edges": [
            {"id": 0, "source": 0, "target": "0"},
            {"id": 1, "source": "0", "target": 9007199254740993},
        ],
    }


def library(path=CPU):
    return binding.NativeLibrary(path / "libgraphmine_runtime.so")


def without_timing(value):
    return {
        k: v
        for k, v in value.items()
        if k not in {"elapsed_seconds", "representations"}
    }


def test_native_catalog_and_python_families_are_identical():
    lib = library()
    native = json.loads(subprocess.check_output([CPU / "graphmine-native", "catalog"]))
    assert lib.catalog() == native
    assert lib.list_families() == native["families"]
    assert lib.list_algorithms() == native["operations"]
    problems = {row["id"]: row for row in native["problems"]}
    assert len(problems) == 71
    for card in lib.list_algorithms():
        assert card["family"] == problems[card["problem_id"]]["family"]
        assert card in lib.family(card["family"]).list_algorithms()
    lib.list_algorithms()[0]["family"] = "tampered"
    assert lib.list_algorithms() == native["operations"]
    with pytest.raises(AttributeError):
        _ = lib.family("traversal").triangle_counting


def test_cpp_cli_python_binding_and_family_method_return_same_results(tmp_path):
    lib = library()
    parameters = {"sources": [0]}
    direct = lib.run(
        "breadth-first-search", graph(), parameters=parameters, device="cpu"
    )
    family = lib.family("traversal").breadth_first_search(
        graph(), parameters=parameters, device="cpu"
    )
    request = {
        "command": "run",
        "operation": "breadth-first-search",
        "graph": graph(),
        "parameters": parameters,
        "device": "cpu",
    }
    process = subprocess.run(
        [CPU / "graphmine-native", "request"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env={"PATH": str(tmp_path), "CUDA_VISIBLE_DEVICES": ""},
        check=True,
    )
    assert without_timing(direct) == without_timing(json.loads(process.stdout))
    assert without_timing(family) == without_timing(direct)
    assert [r["distance"] for r in direct["result"]["distances"]] == [0, 1, 2, None]
    assert direct["backend"]["python_runtime_required"] is False


def test_wrapper_import_and_execution_without_installed_python_packages():
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from graphmine.native import NativeLibrary
library = NativeLibrary(sys.argv[2])
assert library.catalog()['python_runtime_required'] is False
assert not {'networkx','numpy','cugraph','cudf'} & set(sys.modules)
print(len(library.list_algorithms()))
"""
    process = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            script,
            str(ROOT / "python/graphmine"),
            str(CPU / "libgraphmine_runtime.so"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert int(process.stdout.strip()) == len(library().list_algorithms())


@pytest.mark.parametrize(
    ("operation", "parameters", "undirected"),
    [
        ("single-source-shortest-paths", {"source": 0}, False),
        ("many-source-shortest-paths", {"origins": [0, "0"]}, False),
        ("spanning-tree-forest", {"objective": "maximum"}, True),
        ("connected-components", {"connectivity_mode": "strongly_connected"}, False),
        ("topological-sort", {}, False),
        ("pagerank", {"weight_mode": "edge_weight"}, False),
        ("betweenness-centrality", {"weight_mode": "edge_weight"}, False),
        ("degree-centrality", {"direction_mode": "both"}, False),
        ("personalized-pagerank", {"seed_vertices": [0], "top_k": 1}, False),
        ("link-prediction", {"scoring_measure": "resource_allocation"}, True),
        ("maximal-cliques", {"result_limit": 1}, True),
        ("maximum-clique", {"return_all_ties": True}, True),
        ("k-cliques", {"k": 2, "mode": "enumerate"}, True),
        ("k-core", {"requested_k": 0}, True),
        ("k-truss", {"requested_k": 3}, True),
        ("biconnected-components", {}, True),
        ("maximum-independent-set", {}, True),
        ("minimum-vertex-cover", {"mode": "decision", "k": 0}, True),
        ("maximal-independent-set", {"random_seed": 19}, True),
        ("vertex-coloring", {"distance": 2, "random_seed": 19}, True),
        (
            "random-walks",
            {"start_vertices": [0, "0", 0], "length": 4, "random_seed": 19},
            False,
        ),
        (
            "random-walks",
            {
                "start_vertices": [0],
                "length": 4,
                "walk_model": "node2vec",
                "p": 0.5,
                "q": 2,
                "random_seed": 19,
            },
            False,
        ),
        (
            "neighborhood-sampling",
            {"seeds": [0, "0"], "fanouts": [-1, 2], "random_seed": 19},
            False,
        ),
        ("induced-subgraph", {"mode": "induced", "vertices_or_seeds": [0, "0"]}, False),
        (
            "induced-subgraph",
            {
                "mode": "ego",
                "vertices_or_seeds": [9007199254740993],
                "radius": 1,
                "direction_mode": "incoming",
            },
            False,
        ),
    ],
)
def test_migrated_families_match_native_cli(
    operation, parameters, undirected, tmp_path
):
    lib = library()
    data = graph()
    data["graph"]["directed"] = not undirected
    card = next(row for row in lib.list_algorithms() if row["id"] == operation)
    method = getattr(lib.family(card["family"]), operation.replace("-", "_"))
    wrapped = method(data, parameters=parameters, device="cpu")
    process = subprocess.run(
        [CPU / "graphmine-native", "request"],
        input=json.dumps(
            {
                "command": "run",
                "operation": operation,
                "graph": data,
                "parameters": parameters,
                "device": "cpu",
            }
        ),
        text=True,
        capture_output=True,
        env={"PATH": str(tmp_path), "CUDA_VISIBLE_DEVICES": ""},
        check=True,
    )
    assert without_timing(wrapped) == without_timing(json.loads(process.stdout))
    assert wrapped["family"] == card["family"]
    assert wrapped["backend"]["python_runtime_required"] is False


@pytest.mark.parametrize("gpu_device", [0, 1])
@pytest.mark.parametrize(
    ("operation", "parameters", "undirected"),
    [
        ("maximal-independent-set", {"random_seed": 19}, True),
        ("vertex-coloring", {"distance": 1, "random_seed": 19}, True),
        ("vertex-coloring", {"distance": 2, "random_seed": 19}, True),
        (
            "random-walks",
            {"start_vertices": [0, "0", 0], "length": 4, "random_seed": 19},
            False,
        ),
        (
            "random-walks",
            {
                "start_vertices": [0],
                "length": 4,
                "walk_model": "weighted",
                "random_seed": 19,
            },
            False,
        ),
        (
            "induced-subgraph",
            {
                "mode": "ego",
                "vertices_or_seeds": [9007199254740993],
                "radius": 1,
                "direction_mode": "incoming",
            },
            False,
        ),
    ],
)
def test_native_selection_gpu_matches_cli_and_restores_device(
    operation, parameters, undirected, gpu_device, tmp_path
):
    lib = library(ORIGINAL)
    data = graph()
    data["graph"]["directed"] = not undirected
    runtime = ctypes.CDLL(ctypes.util.find_library("cudart"))
    runtime.cudaSetDevice.argtypes = [ctypes.c_int]
    runtime.cudaGetDevice.argtypes = [ctypes.POINTER(ctypes.c_int)]
    assert runtime.cudaSetDevice(1 - gpu_device) == 0
    card = next(row for row in lib.list_algorithms() if row["id"] == operation)
    wrapped = getattr(lib.family(card["family"]), operation.replace("-", "_"))(
        data, parameters=parameters, device="gpu", gpu_device=gpu_device
    )
    after = ctypes.c_int()
    assert runtime.cudaGetDevice(ctypes.byref(after)) == 0
    assert after.value == 1 - gpu_device
    direct = json.loads(
        subprocess.check_output(
            [ORIGINAL / "graphmine-native", "request"],
            input=json.dumps(
                {
                    "command": "run",
                    "operation": operation,
                    "graph": data,
                    "parameters": parameters,
                    "device": "gpu",
                    "gpu_device": gpu_device,
                }
            ),
            text=True,
            env={"PATH": str(tmp_path)},
        )
    )
    assert without_timing(direct) == without_timing(wrapped)
    assert wrapped["backend"]["id"] == "libcugraph"
    assert wrapped["backend"]["hardware"]["device_ordinal"] == gpu_device


@pytest.mark.parametrize("gpu_device", [0, 1])
def test_native_selection_auto_preserves_unsupported_gpu_semantics(gpu_device):
    lib = library(ORIGINAL)
    for operation, parameters in [
        (
            "random-walks",
            {
                "start_vertices": [0],
                "length": 4,
                "walk_model": "node2vec",
                "p": 0.5,
                "random_seed": 19,
            },
        ),
        ("induced-subgraph", {"mode": "induced", "vertices_or_seeds": [0, "0"]}),
        ("neighborhood-sampling", {"seeds": [0], "fanouts": [-1], "random_seed": 19}),
    ]:
        with pytest.raises(binding.NativeError) as error:
            lib.run(
                operation,
                graph(),
                parameters=parameters,
                device="gpu",
                gpu_device=gpu_device,
            )
        assert error.value.code in {"unsupported_input", "backend_unavailable"}
        automatic = lib.run(
            operation,
            graph(),
            parameters=parameters,
            device="auto",
            gpu_device=gpu_device,
        )
        cpu = library().run(operation, graph(), parameters=parameters, device="cpu")
        assert automatic["backend"]["id"] == "cpp"
        assert automatic["backend"]["selection_reason"]
        assert automatic["result"] == cpu["result"]
        assert automatic["parameters"] == cpu["parameters"]


def test_native_subgraph_port_chains_with_derived_fingerprint():
    lib = library()
    original = graph()
    output = lib.run(
        "induced-subgraph",
        original,
        parameters={"mode": "induced", "vertices_or_seeds": [0, "0"]},
        device="cpu",
    )
    port = output["ports"]["graph"]
    result = lib.family("traversal").breadth_first_search(
        port["value"], parameters={"sources": [0]}, device="cpu"
    )
    assert port["input_fingerprint"] == output["input_fingerprint"]
    assert port["graph_fingerprint"] != output["input_fingerprint"]
    assert result["input_fingerprint"] == port["graph_fingerprint"]
    assert [row["distance"] for row in result["result"]["distances"]] == [0, 1]
    assert port["value"]["vertices"] == [{"id": 0}, {"id": "0"}]


@pytest.mark.parametrize(
    "literal",
    ["18446744073709551616", "18446744073709551617", "-9223372036854775809"],
)
def test_cli_validates_original_graph_numeric_tokens(tmp_path, literal):
    data = graph()
    data["vertices"][0]["attributes"] = {"value": "replace_number"}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data).replace('"replace_number"', literal))
    parameters = tmp_path / "params.json"
    parameters.write_text('{"sources":[0]}')
    process = subprocess.run(
        [
            CPU / "graphmine-native",
            "run",
            "breadth-first-search",
            path,
            "--parameters",
            parameters,
            "--device",
            "cpu",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 2
    error = json.loads(process.stderr)["error"]
    assert error["code"] == "invalid_input"
    assert "integer range" in error["message"]


def test_concurrent_binding_calls_keep_results_and_memory_ownership_separate():
    lib = library()

    def run(source):
        return lib.run(
            "breadth-first-search",
            graph(),
            parameters={"sources": [source]},
            device="cpu",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, [0, "0", "isolated"] * 20))
    for i, result in enumerate(results):
        expected = ([0, 1, 2, None], [None, 0, 1, None], [None, None, None, 0])[i % 3]
        assert [r["distance"] for r in result["result"]["distances"]] == expected


@pytest.mark.parametrize("invalid", [True, 0.0, "missing", 2**63, ""])
def test_native_errors_cross_the_binding_without_coercion(invalid):
    with pytest.raises(binding.NativeError) as caught:
        library().run(
            "breadth-first-search",
            graph(),
            parameters={"sources": [invalid]},
            device="cpu",
        )
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("gpu_device", [0, 1])
def test_native_cugraph_keeps_long_paths_and_explicit_device(gpu_device):
    result = library(GPU).run(
        "breadth-first-search",
        graph(),
        parameters={"sources": [0]},
        device="gpu",
        gpu_device=gpu_device,
    )
    assert [r["distance"] for r in result["result"]["distances"]] == [0, 1, 2, None]
    assert result["backend"]["id"] == "libcugraph"
    assert result["backend"]["hardware"]["device_ordinal"] == gpu_device


@pytest.mark.parametrize("gpu_device", [0, 1])
@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_cudf_csv_roundtrip_preserves_text_and_header_mapping(
    tmp_path, gpu_device, line_ending
):
    path = tmp_path / "entities.csv"
    expected = [
        {"id": "001", "note": "NA", "amount": "9007199254740993"},
        {"id": "a,b", "note": 'two "quotes"', "amount": "0.1"},
        {"id": "long\nname", "note": "", "amount": "-0.2"},
        {"id": "علی", "note": "hello", "amount": ""},
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["id", "note", "amount"], lineterminator=line_ending
        )
        writer.writeheader()
        writer.writerows(expected)
    result = library(GPU).read_csv(
        path, columns=["note", "amount", "id"], gpu_device=gpu_device
    )
    assert result["table"]["rows"] == expected
    assert result["complete"]
    assert result["provenance"]["reader"] == "libcudf"
    assert result["provenance"]["gpu_device"] == gpu_device


def test_cudf_empty_table_and_rejection_boundaries(tmp_path):
    lib = library(GPU)
    path = tmp_path / "table.csv"
    path.write_text("id,value\n")
    assert lib.read_csv(path, columns=["id", "value"])["table"]["rows"] == []
    path.write_text("id,value\nA,1\nB,2\n")
    with pytest.raises(binding.NativeError, match="row limit"):
        lib.read_csv(path, columns=["id", "value"], max_rows=1)
    with pytest.raises(binding.NativeError, match="column"):
        lib.read_csv(path, columns=["id"])
    with pytest.raises(binding.NativeError, match="column"):
        lib.read_csv(path, columns=["id", "wrong"])
    with pytest.raises(binding.NativeError):
        lib.read_csv(path, columns=["id", "id"])
    with pytest.raises(binding.NativeError):
        lib.read_csv(path, columns=["id", "value"], gpu_device=True)


def test_cudf_reader_refuses_cpu_only_build(tmp_path):
    with pytest.raises(binding.NativeError) as caught:
        library().read_csv(tmp_path / "anything.csv", columns=["id"])
    assert caught.value.code == "backend_unavailable"


@pytest.mark.parametrize("shape", ["triangle", "cycle"])
@pytest.mark.parametrize("gpu_device", [0, 1])
@pytest.mark.parametrize(
    ("operation", "backend", "parameters", "field", "expected"),
    [("triangle-counting", b, {}, "count", 1) for b in ("tot", "wetric")]
    + [("maximal-cliques", b, {}, "count", 2) for b in ("rdmce", "mce-gpu", "g2-aimd")]
    + [
        ("maximum-clique", b, {}, "maximum_size", 3)
        for b in ("cuda-ms", "gpu-maximum-clique", "maximum-clique-on-gpu")
    ]
    + [("k-cliques", b, {"k": 3}, "count", 1) for b in ("graphset", "gamma", "kcgpu")]
    + [
        ("k-core", b, {}, "core_numbers", [2, 2, 2, 0])
        for b in ("kcore-gpu", "libcugraph")
    ],
)
def test_original_cuda_backends_keep_cli_json_and_restore_device(
    operation, backend, parameters, field, expected, gpu_device, shape
):
    lib = library(ORIGINAL)
    runtime = ctypes.CDLL(ctypes.util.find_library("cudart"))
    runtime.cudaGetDevice.argtypes = [ctypes.POINTER(ctypes.c_int)]
    runtime.cudaSetDevice.argtypes = [ctypes.c_int]
    before = ctypes.c_int()
    assert runtime.cudaSetDevice(1 - gpu_device) == 0
    assert runtime.cudaGetDevice(ctypes.byref(before)) == 0
    selected = gpu_device
    value = graph()
    value["graph"]["directed"] = False
    value["edges"].append({"id": 2, "source": 9007199254740993, "target": 0})
    if shape == "cycle":
        value["vertices"] = [{"id": i} for i in range(5)]
        value["edges"] = [
            {"id": i, "source": i, "target": (i + 1) % 5} for i in range(5)
        ]
        expected = {
            "triangle-counting": 0,
            "maximal-cliques": 5,
            "maximum-clique": 2,
            "k-cliques": 0,
            "k-core": [2] * 5,
        }[operation]
    result = lib.run(
        operation,
        value,
        parameters=parameters,
        device="gpu",
        backend=backend,
        gpu_device=selected,
    )
    after = ctypes.c_int()
    assert runtime.cudaGetDevice(ctypes.byref(after)) == 0
    assert after.value == before.value
    actual = (
        [row["core_number"] for row in result["result"]["vertices"]]
        if field == "core_numbers"
        else result["result"][field]
    )
    assert actual == expected
    assert result["backend"]["hardware"]["device_ordinal"] == selected
    request = {
        "command": "run",
        "operation": operation,
        "parameters": parameters,
        "graph": value,
        "device": "gpu",
        "backend": backend,
        "gpu_device": selected,
    }
    process = subprocess.run(
        [ORIGINAL / "graphmine-native", "request"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=True,
    )
    # This must parse the entire stdout: upstream timing diagnostics previously
    # corrupted it even though the C++ count itself was correct.
    cli = json.loads(process.stdout)
    assert cli["backend"]["id"] == backend
    assert without_timing(cli) == without_timing(result)


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_graphset_and_gamma_can_share_a_host_process_across_devices(order):
    lib = library(ORIGINAL)
    value = graph()
    value["graph"]["directed"] = False
    value["vertices"] = [{"id": v} for v in range(12)]
    value["edges"] = [
        {"id": f"{u}-{v}", "source": u, "target": v}
        for u in range(12)
        for v in range(u + 1, 12)
    ]
    for backend, k, expected in [("graphset", 6, 924), ("gamma", 7, 792)]:
        for device in order:
            result = lib.run(
                "k-cliques",
                value,
                parameters={"k": k},
                device="gpu",
                backend=backend,
                gpu_device=device,
            )
            assert result["result"]["count"] == expected
            assert result["backend"]["hardware"]["device_ordinal"] == device


@pytest.mark.parametrize("backend", ["libcugraph", "turbo-bc"])
@pytest.mark.parametrize("gpu_device", [0, 1])
@pytest.mark.parametrize("normalized", [False, True])
def test_native_betweenness_backends_match_cli_and_restore_device(
    backend, gpu_device, normalized
):
    lib = library(ORIGINAL)
    value = graph()
    value["graph"]["directed"] = False
    runtime = ctypes.CDLL(ctypes.util.find_library("cudart"))
    runtime.cudaSetDevice.argtypes = [ctypes.c_int]
    runtime.cudaGetDevice.argtypes = [ctypes.POINTER(ctypes.c_int)]
    assert runtime.cudaSetDevice(1 - gpu_device) == 0
    result = lib.family("centrality").betweenness_centrality(
        value,
        parameters={"normalized": normalized},
        backend=backend,
        device="gpu",
        gpu_device=gpu_device,
    )
    after = ctypes.c_int()
    assert runtime.cudaGetDevice(ctypes.byref(after)) == 0
    assert after.value == 1 - gpu_device
    assert [row["score"] for row in result["result"]["vertices"]] == pytest.approx(
        [0, 1 / 3 if normalized else 1, 0, 0]
    )
    request = {
        "command": "run",
        "operation": "betweenness-centrality",
        "graph": value,
        "parameters": {"normalized": normalized},
        "backend": backend,
        "device": "gpu",
        "gpu_device": gpu_device,
    }
    direct = json.loads(
        subprocess.check_output(
            [ORIGINAL / "graphmine-native", "request"],
            input=json.dumps(request),
            text=True,
        )
    )
    assert without_timing(result) == without_timing(direct)


@pytest.mark.parametrize("backend", ["libcugraph", "turbo-bc"])
@pytest.mark.parametrize("gpu_device", [0, 1])
def test_native_betweenness_path_overflow_selects_cpu_before_execution(
    backend, gpu_device
):
    lib = library(ORIGINAL)
    value = graph()
    value["graph"]["directed"] = False
    value["vertices"] = [{"id": v} for v in range(66)]
    value["edges"] = [
        {"id": f"{layer}-{a}-{b}", "source": 2 * layer + a, "target": 2 * layer + 2 + b}
        for layer in range(32)
        for a in range(2)
        for b in range(2)
    ]
    with pytest.raises(binding.NativeError) as error:
        lib.run(
            "betweenness-centrality",
            value,
            backend=backend,
            device="gpu",
            gpu_device=gpu_device,
        )
    assert error.value.code == "unsupported_input"
    result = lib.run("betweenness-centrality", value, gpu_device=gpu_device)
    assert result["backend"]["id"] == "cpp"
    assert result["quality"] == "exact"


def optimization_graph(operation):
    value = graph()
    if operation == "bipartite-matching":
        value["graph"]["directed"] = False
        value["vertices"] = [
            {"id": identifier, "attributes": {"side": "left" if i < 2 else "right"}}
            for i, identifier in enumerate([0, "0", 9007199254740993, "right"])
        ]
        value["edges"] = [
            {
                "id": str(i),
                "source": [0, "0"][i // 2],
                "target": [9007199254740993, "right"][i % 2],
                "weight": weight,
            }
            for i, weight in enumerate([4, 1, 2, 5])
        ]
        return (
            value,
            {
                "objective": "minimum_cost",
                "weight_mode": "edge_weight",
                "perfect_matching_required": True,
            },
            "matching",
            "objective_value",
            3,
        )
    for edge in value["edges"]:
        edge["weight"] = 2
    if operation == "weighted-matching":
        value["graph"]["directed"] = False
        return value, {}, "matching", "objective_value", 2
    return value, {"source": 0, "sink": 9007199254740993}, "flow", "max_flow_value", 2


@pytest.mark.parametrize(
    "operation,backend,gpu_device",
    [
        ("weighted-matching", "cpp", 0),
        ("bipartite-matching", "cpp", 0),
        ("max-flow-min-cut", "cpp", 0),
        ("bipartite-matching", "hungarian-cuda", 0),
        ("bipartite-matching", "hungarian-cuda", 1),
        ("max-flow-min-cut", "ecl-maxflow", 0),
        ("max-flow-min-cut", "ecl-maxflow", 1),
    ],
)
def test_native_optimization_family_wrapper_matches_cli(operation, backend, gpu_device):
    build = CPU if backend == "cpp" else ORIGINAL
    lib = library(build)
    value, parameters, family, key, expected = optimization_graph(operation)
    selected = getattr(lib.family(family), operation.replace("-", "_"))
    result = selected(
        value,
        parameters=parameters,
        device="cpu" if backend == "cpp" else "gpu",
        backend=backend,
        gpu_device=gpu_device,
    )
    assert result["result"][key] == expected
    assert result["quality"] == "exact"
    request = {
        "command": "run",
        "operation": operation,
        "graph": value,
        "parameters": parameters,
        "backend": backend,
        "gpu_device": gpu_device,
        "device": "cpu" if backend == "cpp" else "gpu",
    }
    direct = json.loads(
        subprocess.check_output(
            [build / "graphmine-native", "request"],
            input=json.dumps(request),
            text=True,
        )
    )
    assert without_timing(result) == without_timing(direct)


def test_native_flow_vertex_capacities_preserve_typed_identity():
    value, parameters, *_ = optimization_graph("max-flow-min-cut")
    parameters["vertex_capacities"] = [
        {"vertex": 0, "capacity": 1},
        {"vertex": "0", "capacity": 0.5},
    ]
    result = (
        library(CPU)
        .family("flow")
        .max_flow_min_cut(value, parameters=parameters, device="cpu")
    )
    assert result["result"]["min_cut_vertices"] == ["0"]
    assert result["result"]["max_flow_value"] == 0.5
    assert result["parameters"]["vertex_capacities"] == parameters["vertex_capacities"]


@pytest.mark.parametrize(
    "operation,backend,script,code",
    [
        (
            "max-flow-min-cut",
            "ecl-maxflow",
            "echo GRAPHMINE_FLOW 1 0",
            "correctness_mismatch",
        ),
        (
            "bipartite-matching",
            "hungarian-cuda",
            "echo GRAPHMINE_ASSIGNMENT 0 1",
            "correctness_mismatch",
        ),
        ("max-flow-min-cut", "ecl-maxflow", "exit 7", "backend_failure"),
        ("bipartite-matching", "hungarian-cuda", "exit 7", "backend_failure"),
    ],
)
def test_native_cuda_worker_failure_has_no_silent_fallback(
    tmp_path, monkeypatch, operation, backend, script, code
):
    worker = tmp_path / f"graphmine-worker-{backend}"
    worker.write_text("#!/bin/sh\n" + script + "\n")
    worker.chmod(0o755)
    monkeypatch.setenv("GRAPHMINE_WORKER_DIR", str(tmp_path))
    value, parameters, *_ = optimization_graph(operation)
    with pytest.raises(binding.NativeError) as error:
        library(ORIGINAL).run(operation, value, parameters=parameters, device="auto")
    assert error.value.code == code


def test_native_cuda_worker_deadline_kills_and_reaps_process(tmp_path, monkeypatch):
    import time

    worker = tmp_path / "graphmine-worker-ecl-maxflow"
    pid_file = tmp_path / "pid"
    worker.write_text(f"#!/bin/sh\necho $$ > '{pid_file}'\nexec /bin/sleep 30\n")
    worker.chmod(0o755)
    monkeypatch.setenv("GRAPHMINE_WORKER_DIR", str(tmp_path))
    value, parameters, *_ = optimization_graph("max-flow-min-cut")
    start = time.monotonic()
    with pytest.raises(binding.NativeError) as error:
        library(ORIGINAL).run(
            "max-flow-min-cut",
            value,
            parameters=parameters,
            device="gpu",
            backend="ecl-maxflow",
            budget={"timeout_seconds": 0.2},
        )
    assert error.value.code == "resource_limit"
    assert time.monotonic() - start < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
