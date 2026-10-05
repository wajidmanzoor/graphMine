#!/usr/bin/env python3
"""Independent per-edge differential tests for the AccTD repair (no CPU fallback)."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import heapq
import json
import os
from pathlib import Path
import random
import signal
import struct
import subprocess
import time

import networkx as nx

HERE = Path(__file__).resolve().parent
SEED = 20261004


def edge_key(u, v):
    return (min(u, v), max(u, v))


def oracle(graph):
    """Serial triangle-hypergraph degeneracy; independent of AccTD's queues."""
    neighbors = {u: set(graph[u]) for u in graph}
    support = {edge_key(u, v): len(neighbors[u] & neighbors[v]) for u, v in graph.edges()}
    heap = [(value, edge) for edge, value in support.items()]
    heapq.heapify(heap)
    result, floor = {}, 0
    while heap:
        count, edge = heapq.heappop(heap)
        if support.get(edge) != count:
            continue
        del support[edge]
        floor = max(floor, count)
        result[edge] = floor + 2
        u, v = edge
        for w in neighbors[u] & neighbors[v]:
            for other in (edge_key(u, w), edge_key(v, w)):
                support[other] -= 1
                heapq.heappush(heap, (support[other], other))
        neighbors[u].remove(v)
        neighbors[v].remove(u)
    return result


def verify_oracle(graph, expected):
    """Compare every nontrivial k-truss with NetworkX's repeated pruning."""
    for k in range(2, max(expected.values(), default=2) + 2):
        wanted = {edge for edge, value in expected.items() if value >= k}
        actual = {edge_key(*edge) for edge in nx.k_truss(graph, k).edges()}
        if wanted != actual:
            raise AssertionError(f"Independent CPU oracles disagree at k={k}")


def write_graph(folder, graph):
    folder.mkdir(parents=True, exist_ok=True)
    assert set(graph) == set(range(len(graph)))
    rows = [sorted(graph[u]) for u in range(len(graph))]
    flat = [v for row in rows for v in row]
    degree = struct.pack(f"<{len(graph) + 3}I", 4, len(graph), len(flat), *map(len, rows))
    adjacency = struct.pack(f"<{len(flat)}I", *flat)
    (folder / "b_degree.bin").write_bytes(degree)
    (folder / "b_adj.bin").write_bytes(adjacency)
    return hashlib.sha256(degree + adjacency).hexdigest()


def read_graph(folder):
    raw = (folder / "b_degree.bin").read_bytes()
    size, n, m, *degree = struct.unpack(f"<{len(raw) // 4}I", raw)
    assert size == 4 and len(degree) == n and sum(degree) == m
    raw = (folder / "b_adj.bin").read_bytes()
    adjacency = struct.unpack(f"<{m}I", raw)
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    offset = 0
    for u, count in enumerate(degree):
        graph.add_edges_from((u, v) for v in adjacency[offset:offset + count])
        offset += count
    return graph


def named_graphs():
    for n in (0, 1, 2, 7, 32, 65):
        yield f"empty-{n}", nx.empty_graph(n)
    for n in (2, 3, 4, 7, 31, 32, 33, 64, 65, 127):
        yield f"path-{n}", nx.path_graph(n)
        yield f"star-{n}", nx.star_graph(n - 1)
        if n >= 3:
            yield f"cycle-{n}", nx.cycle_graph(n)
    for n in (3, 4, 5, 8, 16, 31, 32, 33, 64):
        yield f"clique-{n}", nx.complete_graph(n)
    for a, b in ((1, 31), (2, 3), (7, 13), (32, 33), (64, 65)):
        yield f"bipartite-{a}-{b}", nx.complete_bipartite_graph(a, b)
    yield "diamond", nx.diamond_graph()
    yield "petersen", nx.petersen_graph()
    yield "karate", nx.karate_club_graph()
    yield "grid", nx.convert_node_labels_to_integers(nx.grid_2d_graph(16, 16))
    for n in (4, 8, 32):
        yield f"windmill-{n}", nx.windmill_graph(n, 4)
        yield f"barbell-{n}", nx.barbell_graph(n, 5)
    for n in (32, 64, 128):
        graph = nx.Graph()
        graph.add_nodes_from(range(n))
        graph.add_edges_from((0, u) for u in range(1, n))
        graph.add_edges_from((1, u) for u in range(2, n))
        yield f"book-{n}", graph
    # Isolated vertices before, between and after triangle-bearing components.
    for n in (8, 32, 65, 129):
        graph = nx.empty_graph(n)
        graph.add_edges_from([(1, 2), (2, 3), (1, 3)])
        graph.add_edges_from((u, v) for u in range(n - 5, n - 1)
                            for v in range(u + 1, n - 1))
        yield f"isolates-{n}", graph


def cases(args):
    graphs = list(named_graphs())
    for path in sorted((HERE / "fixtures").glob("*.json")):
        data = json.loads(path.read_text())
        graph = nx.empty_graph(data["vertices"])
        graph.add_edges_from(data["edges"])
        graphs.append((path.stem, graph))
    if args.suite == "full":
        graphs.extend((f"atlas-{i}", g) for i, g in enumerate(nx.graph_atlas_g()))
    rng = random.Random(SEED)
    probabilities = (0.01, 0.04, 0.10, 0.25, 0.5, 0.8, 0.97)
    sizes = (8, 15, 31, 32, 33, 63, 64, 65, 96, 128)
    for i in range(args.random_cases):
        n = sizes[i % len(sizes)]
        p = probabilities[(i // len(sizes)) % len(probabilities)]
        graph = nx.gnp_random_graph(n, p, seed=SEED + i)
        graphs.append((f"random-{i}", graph))
        if i % 5 == 0:
            labels = list(range(n))
            rng.shuffle(labels)
            graphs.append((f"random-{i}-permuted", nx.relabel_nodes(graph, dict(enumerate(labels)))))
    if args.suite == "full":
        for i in range(20):
            graph = nx.barabasi_albert_graph(512 + 32 * i, 3 + i % 5, seed=SEED + i)
            graphs.append((f"scale-free-{i}", graph))
        for i in range(10):
            graph = nx.powerlaw_cluster_graph(256, 8, 0.7, seed=SEED + i)
            graphs.append((f"clustered-{i}", graph))
    return graphs


def run_case(args, name, graph, repeat=0, sanitizer=None):
    started = time.monotonic()
    folder = args.output / "cases" / f"{name}-r{repeat}"
    expected = oracle(graph)
    verify_oracle(graph, expected)
    digest = write_graph(folder, graph)
    output = folder / "edges.txt"
    output.unlink(missing_ok=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": args.gpu,
           "OMP_NUM_THREADS": str(args.threads[repeat % len(args.threads)]),
           "ACCTD_EDGE_OUTPUT": str(output)}
    command = [str(args.binary), str(folder), "org"]
    if sanitizer:
        command = ["compute-sanitizer", "--tool", sanitizer, "--error-exitcode", "99",
                   "--log-file", str(folder / f"{sanitizer}.log"), *command]
    record = {"case": name, "repeat": repeat, "vertices": len(graph),
              "edges": graph.number_of_edges(), "input_sha256": digest,
              "omp_threads": int(env["OMP_NUM_THREADS"]), "command": command,
              "sanitizer": sanitizer, "expected_histogram": dict(sorted(Counter(expected.values()).items()))}
    with (folder / "run.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=True)
        try:
            process.wait(timeout=args.timeout if not sanitizer else max(args.timeout, 120))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            record["timeout"] = True
    record["exit_code"] = process.returncode
    observed = {}
    try:
        for line in output.read_text().splitlines():
            u, v, truss = map(int, line.split())
            edge = edge_key(u, v)
            if edge in observed:
                raise ValueError(f"Duplicate edge {edge}")
            observed[edge] = truss
        record["observed_histogram"] = dict(sorted(Counter(observed.values()).items()))
        record["mismatches"] = [{"edge": list(edge), "expected": expected.get(edge),
                                 "observed": observed.get(edge)}
                                for edge in sorted(expected.keys() | observed.keys())
                                if expected.get(edge) != observed.get(edge)]
        record["passed"] = process.returncode == 0 and observed == expected
    except (OSError, ValueError) as error:
        record.update(passed=False, error=str(error))
    if sanitizer:
        text = (folder / f"{sanitizer}.log").read_text()
        record["sanitizer_clean"] = "ERROR SUMMARY: 0 errors" in text
        if sanitizer == "racecheck":
            record["sanitizer_clean"] = "0 hazards displayed" in text or "ERROR SUMMARY: 0 errors" in text
        record["passed"] &= record["sanitizer_clean"]
    record["seconds"] = round(time.monotonic() - started, 5)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--random-cases", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 4, 16])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--gpu", default="1")
    parser.add_argument("--only", help="Select case names containing this text")
    parser.add_argument("--sanitizer", choices=("memcheck", "initcheck", "racecheck", "synccheck"))
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    selected = [(name, graph) for name, graph in cases(args)
                if args.only is None or args.only in name]
    if not selected:
        parser.error("No cases selected")
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = [executor.submit(run_case, args, name, graph, repeat, args.sanitizer)
                   for name, graph in selected for repeat in range(args.repeats)]
        for future in as_completed(pending):
            record = future.result()
            records.append(record)
            if not record["passed"]:
                print("FAILED", record["case"], record.get("error", record.get("mismatches", [])[:3]), flush=True)
            if len(records) % 100 == 0:
                print(f"Checked {len(records)}/{len(pending)}; failures={sum(not r['passed'] for r in records)}", flush=True)
    records.sort(key=lambda r: (r["case"], r["repeat"]))
    report = {"seed": SEED, "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              "binary": str(args.binary), "networkx_version": nx.__version__,
              "gpu": args.gpu, "suite": args.suite,
              "total": len(records), "passed": sum(r["passed"] for r in records), "cases": records}
    (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Passed {report['passed']}/{report['total']}", flush=True)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
