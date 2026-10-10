#!/usr/bin/env python3
"""Check isolated CUDA kernels directly; large API/oracle checks run separately."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
from collections import deque
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flow_input(path, extreme):
    n = 256 if not extreme else 4
    arcs = {(u, u + 1): 3 for u in range(n - 1)}
    if extreme:
        arcs = {
            (0, 1): 250000000,
            (1, 3): 250000000,
            (0, 2): 250000000,
            (2, 3): 250000000,
        }
    else:
        arcs.update({(u + 1, u): 2 for u in range(n - 1)})
        arcs.update({(u, u + 2): 4 for u in range(n - 2)})
        arcs.update({(u, u + 3): 0 for u in range(n - 3)})
    edges = sorted(arcs)
    offsets = [sum(u < v for u, _ in edges) for v in range(n + 1)]
    values = [
        n,
        len(edges),
        *offsets,
        *(v for _, v in edges),
        *(arcs[e] for e in edges),
    ]
    path.write_bytes(struct.pack(f"{len(values)}i", *values))
    return n, edges, arcs


def certify_flow(text, n, edges, capacities):
    match = re.search(r"^GRAPHMINE_FLOW (.+)$", text, re.MULTILINE)
    assert match
    values = list(map(int, match[1].split()))
    assert len(values) == len(edges)
    balance = [0] * n
    residual = [[] for _ in range(n)]
    for edge, value in zip(edges, values, strict=True):
        u, v = edge
        capacity = capacities[edge]
        assert 0 <= value <= capacity
        balance[u] -= value
        balance[v] += value
        if value < capacity:
            residual[u].append(v)
        if value > 0:
            residual[v].append(u)
    assert all(x == 0 for x in balance[1:-1])
    seen = {0}
    queue = deque([0])
    while queue:
        for v in residual[queue.popleft()]:
            if v not in seen:
                seen.add(v)
                queue.append(v)
    assert n - 1 not in seen
    cut = sum(capacities[e] for e in edges if e[0] in seen and e[1] not in seen)
    assert cut == balance[-1] == -balance[0]
    return {"vertices": n, "arcs": len(edges), "flow": cut, "certificate_valid": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workers = args.gpu_build / "optimization-workers"
    files = [
        args.gpu_build / "native-source-hashes.txt",
        args.gpu_build / "libgraphmine_runtime.so",
        *sorted(workers.glob("graphmine-worker-*")),
        Path(__file__).resolve(),
    ]
    before = {str(p): sha(p) for p in files}
    catalog = json.loads(
        subprocess.check_output([args.gpu_build / "graphmine-native", "catalog"])
    )
    rows = []
    for device in (0, 1):
        for backend in ("ecl-maxflow", "hungarian-cuda"):
            for tool in ("memcheck", "initcheck"):
                for extreme in (False, True):
                    case = f"{backend}-{tool}-gpu-{device}-{'limit' if extreme else 'structure'}"
                    input_path = args.output / f"{case}.input"
                    if backend == "ecl-maxflow":
                        n, edges, capacities = flow_input(input_path, extreme)
                        argv = [str(input_path), "0", str(n - 1), "1"]
                    else:
                        n = 64
                        costs = [
                            [
                                999 if extreme or c != (r + 1) % n else 0
                                for c in range(n)
                            ]
                            for r in range(n)
                        ]
                        input_path.write_text(
                            str(n)
                            + "\n"
                            + "\n".join(" ".join(map(str, row)) for row in costs)
                            + "\n"
                        )
                        argv = [str(input_path)]
                    diagnostics = args.output / f"{case}.stderr.log"
                    command = [
                        "/usr/bin/compute-sanitizer",
                        "--tool",
                        tool,
                        "--error-exitcode",
                        "99",
                        "--log-file",
                        str(diagnostics),
                        str(workers / f"graphmine-worker-{backend}"),
                        *argv,
                    ]
                    process = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=False,
                        env={**os.environ, "CUDA_VISIBLE_DEVICES": str(device)},
                    )
                    log = diagnostics.read_text() + process.stderr
                    diagnostics.write_text(log)
                    output = args.output / f"{case}.stdout.log"
                    output.write_text(process.stdout)
                    assert (
                        process.returncode == 0 and "ERROR SUMMARY: 0 errors" in log
                    ), (case, log[-6000:])
                    if backend == "ecl-maxflow":
                        result = certify_flow(process.stdout, n, edges, capacities)
                    else:
                        match = re.search(
                            r"^GRAPHMINE_ASSIGNMENT (.+)$", process.stdout, re.MULTILINE
                        )
                        assert match
                        values = list(map(int, match[1].split()))
                        assert sorted(values) == list(range(n))
                        cost = sum(costs[r][c] for r, c in enumerate(values))
                        assert cost == (999 * n if extreme else 0)
                        result = {
                            "side_size": n,
                            "objective_value": cost,
                            "optimality_checked": True,
                        }
                    rows.append(
                        {
                            "case": case,
                            "passed": True,
                            "result": result,
                            "log_sha256": sha(diagnostics),
                            "output_sha256": sha(output),
                            "input_sha256": sha(input_path),
                        }
                    )
                    print(case + ": passed", flush=True)
    assert before == {str(p): sha(p) for p in files}
    record = {
        "passed": len(rows),
        "failed": 0,
        "cases": rows,
        "binary_files": before,
        "sanitizer_binary_sha256": sha(Path("/usr/bin/compute-sanitizer")),
        "scope": "Direct isolated CUDA worker kernels; independent flow certificates and known assignment optima",
        "build_unchanged_during_run": True,
        "implementation_sha256": catalog["implementation_sha256"],
    }
    (args.output / "summary.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
