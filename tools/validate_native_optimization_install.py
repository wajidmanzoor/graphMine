#!/usr/bin/env python3
"""Verify installed CUDA workers through standalone CLI and thin C ABI binding."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cmake", "--install", args.gpu_build, "--prefix", args.prefix], check=True
    )
    cli = args.prefix / "bin/graphmine-native"
    library = args.prefix / "lib/libgraphmine_runtime.so"
    worker_dir = args.prefix / "libexec/graphmine"
    spec = importlib.util.spec_from_file_location(
        "native", ROOT / "python/graphmine/graphmine/native/__init__.py"
    )
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    api = wrapper.NativeLibrary(library)
    rows = []
    for device in (0, 1):
        for operation, backend in (
            ("max-flow-min-cut", "ecl-maxflow"),
            ("bipartite-matching", "hungarian-cuda"),
        ):
            matching = operation == "bipartite-matching"
            vertices = [
                {"id": v, "attributes": {"side": "left" if i < 2 else "right"}}
                for i, v in enumerate([0, "0", 9007199254740993, "r"])
            ]
            edges = [
                {
                    "id": i,
                    "source": vertices[u]["id"],
                    "target": vertices[v]["id"],
                    "weight": w,
                }
                for i, (u, v, w) in enumerate(
                    [(0, 2, 4), (0, 3, 1), (1, 2, 2), (1, 3, 5)]
                    if matching
                    else [(0, 1, 3), (1, 2, 2), (0, 2, 1)]
                )
            ]
            graph = {
                "graph": {
                    "id": "installed",
                    "directed": not matching,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": vertices,
                "edges": edges,
            }
            parameters = (
                {
                    "objective": "minimum_cost",
                    "weight_mode": "edge_weight",
                    "perfect_matching_required": True,
                }
                if matching
                else {"source": 0, "sink": 9007199254740993}
            )
            request = {
                "command": "run",
                "operation": operation,
                "graph": graph,
                "parameters": parameters,
                "backend": backend,
                "device": "gpu",
                "gpu_device": device,
            }
            env = {**os.environ, "PATH": str(args.prefix / "empty-path")}
            env.pop("GRAPHMINE_WORKER_DIR", None)
            trace = args.output.parent / f"installed-{backend}-gpu-{device}.execve.log"
            direct = json.loads(
                subprocess.check_output(
                    [
                        "/usr/bin/strace",
                        "-f",
                        "-e",
                        "trace=execve",
                        "-o",
                        trace,
                        cli,
                        "request",
                    ],
                    input=json.dumps(request),
                    text=True,
                    env=env,
                    timeout=30,
                )
            )
            executions = [
                line for line in trace.read_text().splitlines() if "execve(" in line
            ]
            assert len(executions) == 2, executions
            assert (
                str(args.prefix) in executions[1]
                and f"graphmine-worker-{backend}" in executions[1]
            )
            assert (
                "optimization-workers" not in executions[1]
                and "python" not in executions[1].lower()
            )
            response = api.run(
                operation,
                graph,
                parameters=parameters,
                device="gpu",
                backend=backend,
                gpu_device=device,
            )
            # Separate processes have different cache hit counters and timings.
            telemetry = {"elapsed_seconds", "representations"}
            assert {k: v for k, v in response.items() if k not in telemetry} == {
                k: v for k, v in direct.items() if k not in telemetry
            }
            assert response["backend"]["hardware"]["device_ordinal"] == device
            assert (
                response["result"]["objective_value" if matching else "max_flow_value"]
                == 3
            )
            rows.append(
                {
                    "operation": operation,
                    "backend": backend,
                    "device": device,
                    "result": direct,
                    "execve_log": str(trace),
                    "execve_sha256": sha(trace),
                }
            )
    files = [cli, library, *sorted(worker_dir.glob("graphmine-worker-*"))]
    record = {
        "passed": len(rows),
        "failed": 0,
        "standalone_cli_python_on_path": False,
        "installed_workers_observed_in_execve": True,
        "wrapper_cli_parity": True,
        "binary_files": {str(p): sha(p) for p in files},
        "results": rows,
        "implementation_sha256": api.catalog()["implementation_sha256"],
        "source_files": {
            str(Path(__file__).relative_to(ROOT)): sha(Path(__file__)),
            "python/graphmine/graphmine/native/__init__.py": sha(
                ROOT / "python/graphmine/graphmine/native/__init__.py"
            ),
        },
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print("Installed CUDA flow/assignment and wrapper parity passed on both GPUs")


if __name__ == "__main__":
    main()
