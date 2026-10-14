#!/usr/bin/env python3
"""Run native C++ oracles on CPU and both GPUs, retaining immutable snapshots."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_snapshot(build):
    inventory = (build / "native-source-hashes.txt").read_text()
    files = [
        ROOT / "library" / line.rsplit(":", 1)[0] for line in inventory.splitlines()
    ]
    files.append(Path(__file__))
    return {str(path.resolve().relative_to(ROOT)): sha(path) for path in files}


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def snapshot(build):
    files = [
        build / name
        for name in (
            "libgraphmine_runtime.so",
            "graphmine-native",
            "graphmine_runtime_test",
            "graphmine_reference_test",
            "graphmine_mining_test",
            "graphmine_structure_test",
            "graphmine_centrality_test",
            "graphmine_matching_test",
            "graphmine_flow_test",
            "graphmine_selection_test",
            "native-source-hashes.txt",
        )
    ]
    files += sorted((build / "optimization-workers").glob("graphmine-worker-*"))
    files += sorted((build.parent / "workers").glob("graphmine-worker-*"))
    files += sorted((build / "optimization-generated").glob("*.cu"))
    return {str(path.resolve()): sha(path) for path in files}


def validate(build, label, ordinal, output):
    before = snapshot(build)
    sources = source_snapshot(build)
    catalog = json.loads(
        subprocess.check_output([build / "graphmine-native", "catalog"])
    )
    cpu = label == "cpu"
    environment = dict(os.environ)
    if cpu:
        environment["CUDA_VISIBLE_DEVICES"] = ""
    device = "cpu" if cpu else "gpu"
    hardware = None
    if not cpu:
        request = {
            "command": "run",
            "operation": "breadth-first-search",
            "graph": {
                "graph": {
                    "id": "evidence-device",
                    "directed": False,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": [{"id": 0}],
                "edges": [],
            },
            "parameters": {"sources": [0]},
            "device": "gpu",
            "backend": "libcugraph",
            "gpu_device": ordinal,
        }
        result = json.loads(
            subprocess.check_output(
                [build / "graphmine-native", "request"],
                input=json.dumps(request),
                text=True,
                env=environment,
            )
        )
        hardware = result["backend"]["hardware"]
    suites = (
        [
            ("contracts", "cpu"),
            ("bfs", device),
            ("triangles", "cpp" if cpu else "tot" if ordinal == 0 else "wetric"),
        ]
        if cpu
        else [("bfs", device), ("triangles", "tot" if ordinal == 0 else "wetric")]
    )
    groups = [
        (label, "graphmine_runtime_test", suites),
        (
            f"reference-{label}",
            "graphmine_reference_test",
            [
                (suite, device)
                for suite in (
                    "contracts",
                    "paths",
                    "forests",
                    "connectivity",
                    "rank",
                    "similarity",
                )
            ],
        ),
    ]
    groups += [
        (
            f"structure-{label}",
            "graphmine_structure_test",
            [
                (s, "cpp" if cpu else "libcugraph")
                for s in (
                    ["contracts", "truss", "blocks", "boundaries"]
                    if cpu
                    else ["contracts", "truss", "boundaries"]
                )
            ],
        ),
        (
            f"centrality-{label}",
            "graphmine_centrality_test",
            [
                (s, "cpp" if cpu else "libcugraph")
                for s in (
                    ["contracts", "degree", "betweenness", "weighted", "boundaries"]
                    if cpu
                    else ["contracts", "betweenness", "boundaries"]
                )
            ],
        ),
    ]
    groups += [
        (
            f"matching-{label}",
            "graphmine_matching_test",
            [
                (s, "cpp" if cpu else "hungarian-cuda")
                for s in (
                    ["contracts", "general", "bipartite", "boundaries"]
                    if cpu
                    else ["contracts", "assignment", "boundaries"]
                )
            ],
        ),
        (
            f"flow-{label}",
            "graphmine_flow_test",
            [
                (s, "cpp" if cpu else "ecl-maxflow")
                for s in (
                    ["contracts", "edges", "vertices", "boundaries"]
                    if cpu
                    else ["contracts", "edges", "boundaries"]
                )
            ],
        ),
    ]
    groups.insert(
        0,
        (
            f"selection-{label}",
            "graphmine_selection_test",
            [
                (suite, "cpp" if cpu else "libcugraph")
                for suite in (
                    "contracts",
                    "independent",
                    "coloring",
                    "subgraphs",
                    "walks",
                    *(["sampling"] if cpu else []),
                    "probability",
                    "boundaries",
                    "large",
                )
            ],
        ),
    )  # Exercise newly migrated profiles before regressions.
    if cpu:
        groups.append(
            (
                "mining-cpu",
                "graphmine_mining_test",
                [
                    (s, "cpp")
                    for s in (
                        "contracts",
                        "maximal",
                        "maximum",
                        "fixed",
                        "core",
                        "optimization",
                        "boundaries",
                    )
                ],
            )
        )
    else:
        groups.append(
            (
                f"centrality-turbo-bc-{label}",
                "graphmine_centrality_test",
                [(s, "turbo-bc") for s in ("contracts", "betweenness", "boundaries")],
            )
        )
        for backend, algorithms in (
            ("rdmce", ["maximal"]),
            ("mce-gpu", ["maximal"]),
            ("g2-aimd", ["maximal"]),
            ("cuda-ms", ["maximum", "optimization"]),
            ("gpu-maximum-clique", ["maximum", "optimization"]),
            ("maximum-clique-on-gpu", ["maximum", "optimization"]),
            ("graphset", ["fixed"]),
            ("gamma", ["fixed"]),
            ("kcgpu", ["fixed"]),
            ("kcore-gpu", ["core"]),
            ("libcugraph", ["core"]),
        ):
            groups.append(
                (
                    f"mining-{backend}-{label}",
                    "graphmine_mining_test",
                    [(s, backend) for s in ["contracts", *algorithms, "boundaries"]],
                )
            )
    for report_name, executable, cases in groups:
        rows = []
        for suite, backend in cases:
            command = [str(build / executable), suite, backend, str(ordinal)]
            log_path = output / f"{report_name}-{suite}.log"
            with log_path.open("w") as log:
                process = subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=900
                    if not cpu
                    and executable in {"graphmine_matching_test", "graphmine_flow_test"}
                    else 300,
                    check=False,
                    env=environment,
                )
            log_text = log_path.read_text()
            if process.returncode:
                raise RuntimeError(
                    f"{command}: {process.returncode}\n{log_text[-8000:]}"
                )
            row = json.loads(log_text.strip().splitlines()[-1])
            assert row["failed"] == 0 and row["passed_requests"] > 0
            digest = catalog["implementation_sha256"]
            assert row.get("implementation_sha256", digest) == digest
            row["implementation_sha256"] = digest
            rows.append(row)
            print(
                f"{label}: {executable} {suite}: {row['passed_requests']} passed",
                flush=True,
            )
        assert before == snapshot(build), f"Native build changed during {report_name}"
        assert sources == source_snapshot(build), (
            f"Native sources changed during {report_name}"
        )
        path = output / f"{report_name}.json"
        path.write_text(json.dumps(rows, indent=2) + "\n")
        path.with_suffix(".json.metadata.json").write_text(
            json.dumps(
                {
                    "binary_files": before,
                    "build_unchanged_during_run": True,
                    "implementation_sha256": catalog["implementation_sha256"],
                    "native_library_sha256": before[
                        str((build / "libgraphmine_runtime.so").resolve())
                    ],
                    "sources_unchanged_during_run": True,
                    "source_files": sources,
                    "device": device,
                    "gpu_hardware": hardware,
                    "cuda_visible_devices": environment.get("CUDA_VISIBLE_DEVICES"),
                },
                indent=2,
            )
            + "\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-build", type=Path, required=True)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(validate, args.cpu_build.resolve(), "cpu", 0, args.output)
        ]
        futures += [
            pool.submit(validate, args.gpu_build.resolve(), f"gpu-{i}", i, args.output)
            for i in (0, 1)
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()


if __name__ == "__main__":
    main()
