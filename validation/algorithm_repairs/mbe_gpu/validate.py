#!/usr/bin/env python3
"""Differential tests for nonempty maximal biclique counts on an actual GPU."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import time

import networkx as nx

HERE = Path(__file__).resolve().parent
SEED = 20261004


@dataclass(frozen=True)
class Case:
    name: str
    left: int
    rows: tuple[tuple[int, ...], ...]
    known_count: int | None = None

    @property
    def text(self):
        return "".join(" ".join(map(str, row)) + "\n" for row in self.rows)


def case(name, left, rows, known=None):
    return Case(name, left, tuple(tuple(sorted(set(row))) for row in rows), known)


def intersection_oracle(graph):
    """Every nonzero intersection of row neighborhoods is one closed left side.

    Its matching right side is ALL rows containing it. Closing again gives the
    same left side, so distinct intersections are exactly the nonempty maximal
    bicliques. This enumerates sets, not the GPU's search/pruning procedure.
    """
    closed = set()
    for row in graph.rows:
        mask = sum(1 << u for u in row)
        additions = {mask} | {mask & previous for previous in closed}
        additions.discard(0)
        closed.update(additions)
        if len(closed) > 300_000:
            raise RuntimeError(f"Oracle resource limit exceeded: {graph.name}")
    return len(closed)


def clique_oracle(graph):
    """Independent reduction to maximal cliques; exclude either empty side."""
    left = set(range(graph.left))
    right = set(range(graph.left, graph.left + len(graph.rows)))
    completed = nx.Graph()
    completed.add_nodes_from(left | right)
    completed.add_edges_from(itertools.combinations(left, 2))
    completed.add_edges_from(itertools.combinations(right, 2))
    completed.add_edges_from((u, graph.left + v)
                             for v, row in enumerate(graph.rows) for u in row)
    return sum(bool(left.intersection(c)) and bool(right.intersection(c))
               for c in nx.find_cliques(completed))


def transpose(graph, name):
    rows = [[] for _ in range(graph.left)]
    for v, row in enumerate(graph.rows):
        for u in row:
            rows[u].append(v)
    return case(name, len(graph.rows), rows, graph.known_count)


def fixtures():
    expected = {"original-small": 7, "original-medium": 15,
                "medium-no-isolates": 15, "one-edge": 1,
                "one-edge-isolate": 1, "no-edges": 0, "overlap": 3}
    for name, count in expected.items():
        rows = [list(map(int, line.split()))
                for line in (HERE / "fixtures" / f"{name}.adj").read_text().splitlines()]
        left = max((u for row in rows for u in row), default=-1) + 1
        yield case(name, left, rows, count)


def named_cases():
    yield from fixtures()
    yield case("empty-file", 0, [], 0)
    for n in (1, 2, 31, 32, 33, 64, 65, 129):
        yield case(f"isolates-{n}", n, [[] for _ in range(n)], 0)
        yield case(f"matching-{n}", n, [[u] for u in range(n)], n)
    for n, m in ((1, 33), (33, 1), (2, 8), (8, 2), (31, 33), (33, 31),
                 (32, 65), (65, 32), (65, 65), (131, 137)):
        yield case(f"complete-{n}-{m}", n, [range(n)] * m, 1)
        yield case(f"complete-isolates-{n}-{m}", n + 3,
                   [[]] + [range(1, n + 1)] * m + [[]] * 3, 1)
    for n in (2, 3, 4, 5, 8, 12, 14, 16):
        yield case(f"crown-{n}", n,
                   [[u for u in range(n) if u != v] for v in range(n)], (1 << n) - 2)
    for n in (3, 8, 31, 32, 33, 65, 129):
        yield case(f"staircase-{n}", n, [range(v + 1) for v in range(n)], n)
        yield case(f"cycle-{n}", n, [[v, (v + 1) % n] for v in range(n)], 2 * n)
    yield case("many-identical-rows", 8, [range(6)] * 180 + [[7]] * 40 + [[]] * 9, 2)
    yield case("disjoint-complete-blocks", 128,
               [range((v // 8) * 8, (v // 8 + 1) * 8) for v in range(128)], 16)


def generate(suite, random_cases):
    yield from named_cases()
    if suite == "smoke":
        return
    for mask in range(1 << 9):
        rows = [[u for u in range(3) if mask & (1 << (v * 3 + u))] for v in range(3)]
        yield case(f"exhaustive-3x3-{mask:03d}", 3, rows)
    rng = random.Random(SEED)
    graphs = []
    for i in range(random_cases):
        n = rng.choice((1, 2, 3, 4, 5, 8, 12, 16))
        m = rng.choice((1, 2, 3, 4, 7, 13, 19, 32, 33, 48))
        p = rng.choice((0, .03, .1, .25, .5, .75, .9, .98, 1))
        graph = case(f"random-{i:03d}", n,
                     [[u for u in range(n) if rng.random() < p] for _ in range(m)])
        graphs.append(graph)
        yield graph
    for i, graph in enumerate(graphs[:60]):
        yield transpose(graph, f"transpose-{i:03d}")
        labels = list(range(graph.left + 3))
        rng.shuffle(labels)
        rows = [[labels[u] for u in row] for row in graph.rows] + [[], []]
        rng.shuffle(rows)
        yield case(f"relabel-isolates-{i:03d}", graph.left + 3, rows)
    for i in range(25):
        n, m, p = rng.choice((33, 65, 129)), rng.choice((32, 64, 128)), rng.choice((.01, .05, .1))
        yield case(f"larger-sparse-{i:02d}", n,
                   [[u for u in range(n) if rng.random() < p] for _ in range(m)])


def run_one(args, graph, expected, mode, order, trans, repeat, work):
    key = f"{graph.name}-s{mode}-o{order}-t{trans}-r{repeat}"
    directory = work / key
    directory.mkdir(parents=True, exist_ok=False)
    input_path = directory / "input.adj"
    input_path.write_text(graph.text)
    command = [str(args.binary.resolve()), "-i", str(input_path), "-s", str(mode),
               "-o", str(order), "-t", str(trans), "-m", str(args.bound_height),
               "-n", str(args.bound_size)]
    if not args.slow_input:
        command.append("-f")
    if args.sanitizer:
        command = ["compute-sanitizer", "--tool", args.sanitizer, "--error-exitcode", "91",
                   "--log-file", str(directory / "sanitizer.log")] + command
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu))
    start = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, env=env, start_new_session=True)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        # Upstream catches SIGTERM and prints a partial result with exit code 0.
        # Kill the process group and explicitly mark timeout as failure.
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
    (directory / "stdout.log").write_text(output)
    match = re.search(r",\s*(\d+)\s*,\s*([0-9.eE+-]+)\s*$", output)
    actual = int(match[1]) if match else None
    sanitizer_ok = True
    if args.sanitizer:
        log_path = directory / "sanitizer.log"
        log = log_path.read_text() if log_path.exists() else ""
        sanitizer_ok = ("ERROR SUMMARY: 0 errors" in log if args.sanitizer != "racecheck"
                        else bool(re.search(r"RACECHECK SUMMARY: 0 hazards displayed", log)))
    passed = not timed_out and process.returncode == 0 and sanitizer_ok and actual == expected + args.counter_offset
    return dict(case=graph.name, mode=mode, order=order, transpose=trans, repeat=repeat,
                left=graph.left, right=len(graph.rows), edges=sum(map(len, graph.rows)),
                input_sha256=hashlib.sha256(graph.text.encode()).hexdigest(), expected=expected,
                actual=actual, passed=passed, returncode=process.returncode, timeout=timed_out,
                sanitizer_ok=sanitizer_ok, seconds=round(time.monotonic() - start, 4),
                log=str(directory / "stdout.log"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=("smoke", "full"), default="full")
    parser.add_argument("--random-cases", type=int, default=300)
    parser.add_argument("--modes", type=int, nargs="+", default=[2, 0, 1])
    parser.add_argument("--orders", type=int, nargs="+", default=[1])
    parser.add_argument("--transposes", type=int, nargs="+", default=[0])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--gpu", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--only", default="", help="Regular expression on case names")
    parser.add_argument("--bound-height", type=int, default=20)
    parser.add_argument("--bound-size", type=int, default=1500)
    parser.add_argument("--slow-input", action="store_true")
    parser.add_argument("--counter-offset", type=int, default=0,
                        help="Expected artificial offset, only for a diagnostic counter-seeded build")
    parser.add_argument("--sanitizer", choices=("memcheck", "initcheck", "racecheck", "synccheck"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error("Output already exists; preserve prior evidence by using a fresh name")
    work = output.parent / (output.stem + "-runs")
    work.mkdir(exist_ok=False)
    graphs = [g for g in generate(args.suite, args.random_cases) if re.search(args.only, g.name)]
    if not graphs:
        parser.error("No cases selected")
    expected = {}
    oracle_crosschecks = 0
    for graph in graphs:
        count = intersection_oracle(graph)
        if graph.known_count is not None and count != graph.known_count:
            raise AssertionError((graph.name, count, graph.known_count))
        if graph.left + len(graph.rows) <= 42:
            other = clique_oracle(graph)
            if count != other:
                raise AssertionError((graph.name, count, other))
            oracle_crosschecks += 1
        expected[graph.name] = count
    jobs = [(g, m, o, t, r) for g in graphs for m in args.modes
            for o in args.orders for t in args.transposes for r in range(args.repeats)]
    print(f"{len(graphs)} graphs; {oracle_crosschecks} independent oracle cross-checks; {len(jobs)} GPU runs", flush=True)
    start = time.monotonic()
    records = []
    with output.with_suffix(".progress.jsonl").open("w") as progress, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, args, g, expected[g.name], m, o, t, r, work)
                   for g, m, o, t, r in jobs]
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            progress.write(json.dumps(record) + "\n")
            progress.flush()
            if not record["passed"]:
                print("FAIL " + json.dumps(record), flush=True)
            elif len(records) % 100 == 0:
                print(f"Completed {len(records)}/{len(jobs)}; failures={sum(not r['passed'] for r in records)}", flush=True)
    records.sort(key=lambda r: (r["case"], r["mode"], r["order"], r["transpose"], r["repeat"]))
    result = dict(seed=SEED, command_options={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  networkx_version=nx.__version__, graphs=len(graphs),
                  oracle_crosschecks=oracle_crosschecks, runs=len(records),
                  passed=sum(r["passed"] for r in records),
                  failed=sum(not r["passed"] for r in records),
                  seconds=round(time.monotonic() - start, 3), records=records)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("records", "command_options")}), flush=True)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
