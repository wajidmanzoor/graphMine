#!/usr/bin/env python3
"""Published Graphalytics references plus larger SNAP/synthetic native runs.

This is a correctness/latency study, not a certified LDBC benchmark submission.
PR uses convergence, so it is not compared with Graphalytics' fixed iterations.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python/graphmine"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def graph(name, vertices, edges, directed=False):
    return {
        "graph": {
            "id": name,
            "directed": directed,
            "allows_self_loops": True,
            "allows_parallel_edges": True,
        },
        "vertices": [{"id": vertex} for vertex in vertices],
        "edges": [
            {
                "id": i,
                "source": row[0],
                "target": row[1],
                **({"weight": row[2]} if len(row) > 2 else {}),
            }
            for i, row in enumerate(edges)
        ],
    }


def child(library, request, output):
    from graphmine.native import NativeLibrary

    started = time.perf_counter()
    lib = NativeLibrary(library)
    value = json.loads(Path(request).read_text())
    result = lib.request(value)
    elapsed = time.perf_counter() - started
    Path(output).write_text(json.dumps(result, separators=(",", ":"), allow_nan=False))
    print(
        json.dumps(
            {
                "elapsed_seconds_including_load_and_json": elapsed,
                "native_elapsed_seconds": result["elapsed_seconds"],
                "peak_process_rss_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * 1024,
                "backend": result["backend"],
                "implementation_sha256": result["implementation_sha256"],
            }
        ),
        flush=True,
    )


def run(args, name, document, operation, parameters, policy):
    library = (
        args.cpu_build if policy == "cpu" else args.gpu_build
    ) / "libgraphmine_runtime.so"
    request = args.output / f"{name}-{operation}-{policy}.request.json"
    output = args.output / f"{name}-{operation}-{policy}.result.json"
    request.write_text(
        json.dumps(
            {
                "command": "run",
                "operation": operation,
                "graph": document,
                "parameters": parameters,
                "device": "cpu" if policy == "cpu" else "gpu",
                "gpu_device": 0,
                "backend": "cpp" if policy == "cpu" else "libcugraph",
                "budget": {
                    "max_candidates": 100000000,
                    "max_output_items": 1000000,
                    "timeout_seconds": 240,
                },
            },
            separators=(",", ":"),
        )
    )
    environment = {
        **os.environ,
        "CUDA_VISIBLE_DEVICES": "" if policy == "cpu" else policy.removeprefix("gpu-"),
    }
    started = time.perf_counter()
    process = subprocess.Popen(
        [
            sys.executable,
            "-S",
            str(Path(__file__).resolve()),
            "--child",
            str(library),
            str(request),
            str(output),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    samples, peak = 0, 0
    while process.poll() is None:
        if time.perf_counter() - started > 300:
            process.kill()
            raise TimeoutError(
                f"Scale run exceeded deadline: {name}/{operation}/{policy}"
            )
        if policy != "cpu":
            sample = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in sample.stdout.splitlines():
                pid, used = [value.strip() for value in line.split(",")]
                if pid == str(process.pid) and used.isdecimal():
                    peak = max(peak, int(used) * 1024 * 1024)
            samples += 1
        time.sleep(0.1)
    raw, errors = process.communicate()
    if process.returncode:
        raise RuntimeError(f"{name}/{operation}/{policy}: {errors[-4000:]}")
    metrics = json.loads(raw)
    result = json.loads(output.read_text())
    assert result["complete"]
    metrics.update(
        dataset=name,
        operation=operation,
        device=policy,
        vertices=len(document["vertices"]),
        edges=len(document["edges"]),
        wall_seconds_including_process=time.perf_counter() - started,
        observed_peak_gpu_bytes=peak if samples else None,
        gpu_memory_samples=samples,
        gpu_memory_sampling_interval_seconds=0.1,
        request_sha256=sha(request),
        result_sha256=sha(output),
        native_library_sha256=sha(library),
    )
    return result, metrics


def distances(result, operation):
    payload = result["result"]
    rows = payload["distances"]
    return {row["vertex"]: row["distance"] for row in rows}


def components(result):
    return {frozenset(row["vertices"]) for row in result["ports"]["groups"]["value"]}


def published(args):
    records = []
    for directory in sorted(args.datasets.iterdir()):
        if not directory.is_dir():
            continue
        name = directory.name
        properties = {}
        for line in (directory / f"{name}.properties").read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                properties[key.strip()] = value.strip()
        vertices = [
            int(line.split()[0])
            for line in (directory / f"{name}.v").read_text().splitlines()
            if line.strip()
        ]
        edges = []
        for line in (directory / f"{name}.e").read_text().splitlines():
            row = line.split()
            if row:
                edges.append(
                    (
                        int(row[0]),
                        int(row[1]),
                        *([float(row[2])] if len(row) > 2 else []),
                    )
                )
        document = graph(
            name, vertices, edges, properties[f"graph.{name}.directed"] == "true"
        )
        for code, operation in [
            ("BFS", "breadth-first-search"),
            ("SSSP", "single-source-shortest-paths"),
            ("WCC", "connected-components"),
        ]:
            reference = directory / f"{name}-{code}"
            if not reference.exists():
                continue
            expected = {
                int(row[0]): row[1]
                for line in reference.read_text().splitlines()
                if (row := line.split())
            }
            parameters = {"connectivity_mode": "weakly_connected"}
            if code != "WCC":
                source = int(properties[f"graph.{name}.{code.lower()}.source-vertex"])
                parameters = (
                    {"sources": [source]} if code == "BFS" else {"source": source}
                )
            for policy in args.devices:
                result, metric = run(
                    args, name, document, operation, parameters, policy
                )
                if code == "WCC":
                    grouped = {}
                    for vertex, label in expected.items():
                        grouped.setdefault(label, set()).add(vertex)
                    assert components(result) == {
                        frozenset(group) for group in grouped.values()
                    }
                else:
                    observed = distances(result, operation)
                    assert set(observed) == set(expected)
                    for vertex, value in expected.items():
                        unreachable = value in ("infinity", "9223372036854775807")
                        assert (
                            observed[vertex] is None
                            if unreachable
                            else math.isclose(
                                observed[vertex],
                                float(value),
                                rel_tol=1e-10,
                                abs_tol=1e-12,
                            )
                        )
                metric.update(
                    passed=True,
                    oracle="published Graphalytics reference",
                    oracle_sha256=sha(reference),
                )
                records.append(metric)
                print(name, code, policy, "passed", flush=True)
    return records


def larger(args):
    import numpy as np
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components, dijkstra
    import networkx as nx

    datasets = []
    snap = args.datasets / "ca-CondMat.txt.gz"
    edges = set()
    with gzip.open(snap, "rt") as stream:
        for line in stream:
            if line.startswith("#"):
                continue
            u, v = map(int, line.split())
            edges.add(tuple(sorted((u, v))))
    vertices = sorted({v for pair in edges for v in pair})
    assert len(vertices) == 23133 and len(edges) == 93497
    datasets.append(graph("snap-ca-CondMat", vertices, sorted(edges)))
    rng = random.Random(30171011)
    n = args.synthetic_vertices
    pairs = {tuple(sorted((u, (u + 1) % n))) for u in range(n)}
    while len(pairs) < 5 * n:
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            pairs.add(tuple(sorted((u, v))))
    datasets.append(
        graph(
            f"synthetic-{n}",
            range(n),
            [(u, v, 1 + (u * 13 + v * 7) % 31) for u, v in sorted(pairs)],
        )
    )
    records = []
    for document in datasets:
        name, vertices = (
            document["graph"]["id"],
            [row["id"] for row in document["vertices"]],
        )
        index = {vertex: i for i, vertex in enumerate(vertices)}
        row, col, weights = [], [], []
        for edge in document["edges"]:
            u, v = index[edge["source"]], index[edge["target"]]
            row += [u, v]
            col += [v, u]
            weights += [edge.get("weight", 1)] * 2
        matrix = sp.csr_matrix(
            (weights, (row, col)), shape=(len(vertices), len(vertices))
        )
        source = vertices[0]
        _, labels = connected_components(matrix, directed=False)
        groups = {}
        for vertex, label in zip(vertices, labels, strict=True):
            groups.setdefault(int(label), set()).add(vertex)
        reference = {
            "breadth-first-search": dijkstra(
                matrix, directed=False, indices=0, unweighted=True
            ),
            "single-source-shortest-paths": dijkstra(matrix, directed=False, indices=0),
        }
        network = nx.Graph()
        network.add_nodes_from(vertices)
        network.add_edges_from(
            (edge["source"], edge["target"]) for edge in document["edges"]
        )
        network.remove_edges_from(list(nx.selfloop_edges(network)))
        rank = nx.pagerank(network, alpha=0.85, tol=1e-13, max_iter=1000, weight=None)
        parameters = {
            "breadth-first-search": {"sources": [source]},
            "single-source-shortest-paths": {
                "source": source,
            },
            "connected-components": {"connectivity_mode": "weakly_connected"},
            "pagerank": {
                "alpha": 0.85,
                "tolerance": 1e-10,
                "max_iterations": 1000,
            },
        }
        for operation, params in parameters.items():
            for policy in args.devices:
                result, metric = run(args, name, document, operation, params, policy)
                if operation == "connected-components":
                    assert components(result) == {
                        frozenset(group) for group in groups.values()
                    }
                elif operation == "pagerank":
                    got = {
                        row["vertex"]: row["score"]
                        for row in result["ports"]["scores"]["value"]
                    }
                    error = max(abs(got[v] - rank[v]) for v in vertices)
                    assert error < 2e-8 and abs(sum(got.values()) - 1) < 1e-6
                    metric["max_absolute_error"] = error
                else:
                    got = distances(result, operation)
                    assert set(got) == set(vertices)
                    for vertex, expected in zip(
                        vertices, reference[operation], strict=True
                    ):
                        assert (
                            got[vertex] is None
                            if np.isinf(expected)
                            else math.isclose(
                                got[vertex], expected, rel_tol=1e-12, abs_tol=1e-10
                            )
                        )
                metric.update(
                    passed=True, oracle="SciPy csgraph / independent NetworkX PageRank"
                )
                records.append(metric)
                print(name, operation, policy, "passed", flush=True)
    return records


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--cpu-build", type=Path, required=True)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--devices", nargs="+", default=["cpu", "gpu-0", "gpu-1"])
    parser.add_argument("--synthetic-vertices", type=int, default=100000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    before = {
        str(path): sha(path)
        for path in [
            Path(__file__),
            args.cpu_build / "libgraphmine_runtime.so",
            args.gpu_build / "libgraphmine_runtime.so",
        ]
    }
    rows = published(args) + larger(args)
    assert before == {path: sha(path) for path in before}
    report = {
        "scope": __doc__,
        "passed": len(rows),
        "failed": 0,
        "runs": rows,
        "source_and_binary_files": before,
        "datasets": json.loads((args.datasets / "sources.json").read_text()),
        "sources_unchanged_during_run": True,
        "gpu_memory_note": "Observed per-process samples, not an exact allocator high-water mark; the local planner model may occupy GPU 0 independently.",
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
