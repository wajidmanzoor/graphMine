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
    return {k: v for k, v in value.items() if k != "elapsed_seconds"}


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
        ("personalized-pagerank", {"seed_vertices": [0], "top_k": 1}, False),
        ("link-prediction", {"scoring_measure": "resource_allocation"}, True),
        ("maximal-cliques", {"result_limit": 1}, True),
        ("maximum-clique", {"return_all_ties": True}, True),
        ("k-cliques", {"k": 2, "mode": "enumerate"}, True),
        ("k-core", {"requested_k": 0}, True),
        ("maximum-independent-set", {}, True),
        ("minimum-vertex-cover", {"mode": "decision", "k": 0}, True),
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
