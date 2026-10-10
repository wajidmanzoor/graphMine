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
        )
    }
    return {
        "build_directory": str(directory),
        "catalog": catalog,
        "source_files": source_files,
        "binaries": binaries,
        "native_dependencies": dependencies,
        "ldd": linkage,
    }


def audit(cpu_build, gpu_build, gpu_source_root, report_root):
    dependencies = {}
    builds = {
        "cpu": build_evidence(cpu_build, ROOT, dependencies),
        "gpu": build_evidence(gpu_build, gpu_source_root, dependencies),
    }
    assert not any(
        name in builds["cpu"]["ldd"].lower()
        for name in ("python", "cuda", "cugraph", "cudf")
    )
    reports = {}
    expected = {
        "cpu": [
            ("contracts", "cpu", 13),
            ("bfs", "cpu", 4608),
            ("triangles", "cpp", 2048),
        ],
        "gpu-0": [("bfs", "gpu", 4608), ("triangles", "tot", 2048)],
        "gpu-1": [("bfs", "gpu", 4608), ("triangles", "wetric", 2048)],
    }
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
            if name.startswith("gpu-"):
                assert row["gpu_device"] == int(name[-1])
        reports[name] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha(path),
            "results": rows,
        }
    xml = report_root / "binding-ingestion.xml"
    suite = ET.parse(xml).getroot().find("testsuite")
    assert int(suite.attrib["tests"]) == 19
    assert all(int(suite.attrib[key]) == 0 for key in ("errors", "failures", "skipped"))
    meta = xml.with_name(xml.name + ".metadata.json")
    data = json.loads(meta.read_text())
    assert data["sources_unchanged_during_run"]
    for path, expected_hash in data["source_files"].items():
        assert sha(path) == expected_hash, path
    reports["binding_ingestion"] = {
        "path": str(xml.relative_to(ROOT)),
        "sha256": sha(xml),
        "metadata_sha256": sha(meta),
        "passed": 19,
    }
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
        "native_formal_problem_count": 2,
        "formal_problem_count": 70,
        "cpu_runtime_operations": [
            row["id"] for row in builds["cpu"]["catalog"]["operations"]
        ],
        "standalone_core_requires_python": False,
        "application_uses_native_runtime": False,
        "remaining_native_profile_migration_required": True,
        "builds": builds,
        "reports": reports,
        "native_dependency_sha256": dependencies,
        "wrapper_sha256": sha(ROOT / "python/graphmine/graphmine/native/__init__.py"),
        "family_catalog_sha256": sha(ROOT / "library/manifests/problem_families.json"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-build", type=Path, required=True)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--gpu-source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.cpu_build,
        args.gpu_build,
        args.gpu_source_root,
        ROOT / "validation/native_runtime",
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
                )
            }
        )
    )


if __name__ == "__main__":
    main()
