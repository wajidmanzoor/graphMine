#!/usr/bin/env python3
"""Record native runtime source/binary/dependency evidence and migration scope.

This is a local evidence inventory, not yet the application's execution gate.
The supplied build directories must contain the completed native oracle runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def build_evidence(directory, source_root, dependency_hashes):
    directory = directory.resolve()
    catalog = json.loads(
        subprocess.check_output([directory / "graphmine-native", "catalog"], text=True)
    )
    inventory = (directory / "native-source-hashes.txt").read_text()
    assert (
        hashlib.sha256(inventory.encode()).hexdigest()
        == catalog["implementation_sha256"]
    )
    source_files = {}
    for line in inventory.splitlines():
        name, expected = line.rsplit(":", 1)
        path = (source_root / "library" / name).resolve()
        assert sha(path) == expected, f"Source changed since build: {path}"
        relative = path.relative_to(source_root.resolve())
        assert sha(ROOT / relative) == expected, (
            f"Repository source differs: {relative}"
        )
        source_files[str(relative)] = expected
    library = directory / "libgraphmine_runtime.so"
    dependencies = []
    linkage = subprocess.check_output(["ldd", library], text=True)
    assert "not found" not in linkage, linkage
    for line in linkage.splitlines():
        match = re.search(r"=> (/\S+)", line)
        if match:
            path = Path(match[1]).resolve()
            if str(path) not in dependency_hashes:
                dependency_hashes[str(path)] = sha(path)
            dependencies.append(str(path))
    binaries = {
        name: sha(directory / name)
        for name in (
            "libgraphmine_runtime.so",
            "graphmine-native",
            "graphmine_runtime_test",
            "graphmine_reference_test",
        )
    }
    cache = directory / "CMakeCache.txt"
    if not cache.exists():
        cache = directory.parent / "CMakeCache.txt"
    configuration = [
        line
        for line in cache.read_text().splitlines()
        if line.startswith(
            (
                "GRAPHMINE_",
                "CMAKE_BUILD_TYPE:",
                "CMAKE_CXX_COMPILER:",
                "CMAKE_CUDA_COMPILER:",
                "CMAKE_CXX_FLAGS:",
                "CMAKE_CUDA_FLAGS:",
            )
        )
    ]
    return {
        "build_directory": str(directory),
        "catalog": catalog,
        "source_files": source_files,
        "binaries": binaries,
        "native_dependencies": dependencies,
        "ldd": linkage,
        "build_configuration": configuration,
        "root_build_script_sha256": sha(source_root / "library/CMakeLists.txt")
        if cache.parent != directory
        else None,
    }


def xml_evidence(path, source_root, expected_count=None):
    suite = ET.parse(path).getroot().find("testsuite")
    count = int(suite.attrib["tests"])
    if expected_count is not None:
        assert count == expected_count
    assert count > 0
    assert all(int(suite.attrib[key]) == 0 for key in ("errors", "failures", "skipped"))
    meta = path.with_name(path.name + ".metadata.json")
    data = json.loads(meta.read_text())
    assert data["sources_unchanged_during_run"]
    assert data["collected_test_count"] == count
    for name, expected_hash in data["source_files"].items():
        source = Path(name)
        if not source.is_absolute():
            source = source_root / source
        assert sha(source) == expected_hash, name
    for key in ("native_binary", "native_library"):
        if key in data:
            assert sha(data[key]) == data[key + "_sha256"]
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha(path),
        "metadata_sha256": sha(meta),
        "passed": count,
    }


def audit(
    cpu_build,
    gpu_build,
    gpu_source_root,
    report_root,
    staged_app_root=None,
    working_gpu_build=None,
):
    report_root = report_root.resolve()
    dependencies = {}
    builds = {
        "cpu": build_evidence(cpu_build, ROOT, dependencies),
        "gpu": build_evidence(gpu_build, gpu_source_root, dependencies),
    }
    if working_gpu_build is not None:
        builds["working_ingestion_gpu"] = build_evidence(
            working_gpu_build, ROOT, dependencies
        )
    hardware = []
    for ordinal in (0, 1):
        request = {
            "command": "run",
            "operation": "breadth-first-search",
            "graph": {
                "graph": {
                    "id": "hardware-inventory",
                    "directed": False,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": [{"id": 0}],
                "edges": [],
            },
            "parameters": {"sources": [0]},
            "device": "gpu",
            "gpu_device": ordinal,
            "backend": "libcugraph",
        }
        response = json.loads(
            subprocess.check_output(
                [gpu_build / "graphmine-native", "request"],
                input=json.dumps(request),
                text=True,
            )
        )
        assert response["backend"]["hardware"]["device_ordinal"] == ordinal
        hardware.append(response["backend"])
    assert not any(
        name in builds["cpu"]["ldd"].lower()
        for name in ("python", "cuda", "cugraph", "cudf")
    )
    reports = {}
    expected = {
        "cpu": [
            ("contracts", "cpu", 20),
            ("bfs", "cpu", 4608),
            ("triangles", "cpp", 2048),
        ],
        "gpu-0": [("bfs", "gpu", 4608), ("triangles", "tot", 2048)],
        "gpu-1": [("bfs", "gpu", 4608), ("triangles", "wetric", 2048)],
        "reference-cpu": [
            ("contracts", "cpu", 28),
            ("paths", "cpu", 3645),
            ("forests", "cpu", 1458),
            ("connectivity", "cpu", 320),
            ("rank", "cpu", 706),
            ("similarity", "cpu", 1024),
        ],
    }
    for ordinal in (0, 1):
        expected[f"reference-gpu-{ordinal}"] = [
            ("contracts", "gpu", 30),
            ("paths", "gpu", 3645),
            ("forests", "gpu", 1458),
            ("connectivity", "gpu", 256),
            ("rank", "gpu", 514),
            ("similarity", "gpu", 128),
        ]
    for name, cases in expected.items():
        path = report_root / f"{name}.json"
        rows = json.loads(path.read_text())
        assert len(rows) == len(cases)
        for row, (suite, backend, count) in zip(rows, cases, strict=True):
            assert (
                row["suite"],
                row["backend"],
                row["passed_requests"],
                row["failed"],
            ) == (suite, backend, count, 0)
            if "gpu-" in name:
                assert row["gpu_device"] == int(name[-1])
            build = builds["gpu" if "gpu-" in name else "cpu"]
            assert (
                row["implementation_sha256"]
                == build["catalog"]["implementation_sha256"]
            )
        metadata_path = path.with_suffix(".json.metadata.json")
        metadata = json.loads(metadata_path.read_text())
        assert metadata["build_unchanged_during_run"]
        assert (
            metadata["implementation_sha256"]
            == build["catalog"]["implementation_sha256"]
        )
        for binary, digest in metadata["binary_files"].items():
            assert sha(binary) == digest, binary
        reports[name] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha(path),
            "metadata_sha256": sha(metadata_path),
            "results": rows,
        }
    reports["binding_ingestion"] = xml_evidence(
        report_root / "binding-ingestion.xml", ROOT, 30
    )
    native_uploads = staged_app_root is not None
    if native_uploads:
        reports["cudf_construction"] = xml_evidence(
            report_root / "cudf-construction.xml", ROOT, 64
        )
        for name, root in (("app-working", ROOT), ("app-staged", staged_app_root)):
            reports[name] = xml_evidence(report_root / f"{name}.xml", root)
            suite = ET.parse(report_root / f"{name}.xml").getroot().find("testsuite")
            names = {case.attrib["name"] for case in suite.findall("testcase")}
            assert {
                "test_upload_uses_cudf_and_preserves_original_bytes",
                "test_upload_endpoint_returns_graph_constructed_by_cpp",
                "test_unavailable_cudf_does_not_use_a_python_reader",
            } <= names
    installed_path = report_root / "installed-consumers.json"
    installed = json.loads(installed_path.read_text())
    assert installed["cpp_consumer"] and installed["c_consumer"]
    assert not installed["python_on_path"] and not installed["cuda_visible_devices"]
    assert (
        installed["implementation_sha256"]
        == builds["cpu"]["catalog"]["implementation_sha256"]
    )
    for path, expected_hash in installed["source_files"].items():
        assert sha(ROOT / path) == expected_hash, path
    for path, expected_hash in installed["binary_files"].items():
        assert sha(path) == expected_hash, path
    assert (
        sha(installed["installed_library"]["path"])
        == installed["installed_library"]["sha256"]
    )
    reports["installed_consumers"] = {
        "path": str(installed_path.relative_to(ROOT)),
        "sha256": sha(installed_path),
        "cpp_consumer": True,
        "c_consumer": True,
        "python_on_path": False,
    }
    taxonomy = json.loads(
        (ROOT / "library/manifests/problem_families.json").read_text()
    )
    problems = {row["id"]: row for row in taxonomy["problems"]}
    contracts = [
        json.loads(path.read_text())
        for path in sorted((ROOT / "problems").glob("[0-9][0-9]_*/problem.json"))
    ]
    assert {row["problem_id"] for row in contracts} == set(problems) - {
        "graph_record_queries"
    }
    references = json.loads(
        (ROOT / "catalog/python_analytics_coverage.json").read_text()
    )["operations"]
    assert all(
        card["family"] == problems[card["problem_id"]]["family"] for card in references
    )
    return {
        "schema_version": 1,
        "scope": "Native runtime migration checkpoint; not a complete architecture migration or application gate",
        "native_formal_problem_count": len(
            {
                row["problem_id"]
                for row in builds["cpu"]["catalog"]["operations"]
                if row["problem_id"] != "graph_record_queries"
            }
        ),
        "formal_problem_count": 70,
        "cpu_runtime_operations": [
            row["id"] for row in builds["cpu"]["catalog"]["operations"]
        ],
        "standalone_core_requires_python": False,
        "application_uses_native_runtime": False,
        "application_tabular_uploads_use_native_cudf": native_uploads,
        "application_algorithm_worker_uses_native_runtime": False,
        "remaining_native_profile_migration_required": True,
        "builds": builds,
        "reports": reports,
        "native_dependency_sha256": dependencies,
        "native_gpu_hardware": hardware,
        "wrapper_sha256": sha(ROOT / "python/graphmine/graphmine/native/__init__.py"),
        "family_catalog_sha256": sha(ROOT / "library/manifests/problem_families.json"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-build", type=Path, required=True)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--gpu-source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--report-root", type=Path, default=ROOT / "validation/native_runtime"
    )
    parser.add_argument("--staged-app-root", type=Path)
    parser.add_argument("--working-gpu-build", type=Path)
    args = parser.parse_args()
    result = audit(
        args.cpu_build,
        args.gpu_build,
        args.gpu_source_root,
        args.report_root,
        args.staged_app_root,
        args.working_gpu_build,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "native_formal_problem_count",
                    "formal_problem_count",
                    "standalone_core_requires_python",
                    "application_uses_native_runtime",
                    "application_tabular_uploads_use_native_cudf",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
