#!/usr/bin/env python3
"""Verify repaired original mining depth/storage limits with CUDA sanitizers."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    binary = args.gpu_build / "graphmine-native"
    files = [
        binary,
        args.gpu_build / "libgraphmine_runtime.so",
        args.gpu_build / "native-source-hashes.txt",
        Path(__file__).resolve(),
    ]
    before = {str(p): sha(p) for p in files}
    catalog = json.loads(subprocess.check_output([binary, "catalog"]))
    rows = []
    for device in (0, 1):
        for backend, n, k, sanitizer, rejected in (
            ("kcgpu", 514, 3, "memcheck", False),
            ("gamma", 12, 7, "racecheck", False),
            ("kcgpu", 1002, 3, None, True),
            ("kcgpu", 514, 10, None, True),
        ):
            graph = {
                "graph": {
                    "id": f"K{n}",
                    "directed": False,
                    "allows_self_loops": False,
                    "allows_parallel_edges": False,
                },
                "vertices": [{"id": v} for v in range(n)],
                "edges": [
                    {"id": i, "source": u, "target": v}
                    for i, (u, v) in enumerate(itertools.combinations(range(n), 2))
                ],
            }
            request = {
                "command": "run",
                "operation": "k-cliques",
                "backend": backend,
                "device": "gpu",
                "gpu_device": device,
                "graph": graph,
                "parameters": {"k": k},
                "budget": {"timeout_seconds": 120, "max_candidates": 20000000},
            }
            raw = json.dumps(request, separators=(",", ":"))
            label = f"{backend}-K{n}-k{k}-gpu-{device}"
            diagnostics = args.output / f"{label}.stderr.log"
            diagnostics.write_text("")
            command = [str(binary), "request"]
            if sanitizer:
                command = [
                    "/usr/bin/compute-sanitizer",
                    "--tool",
                    sanitizer,
                    "--error-exitcode",
                    "99",
                    "--log-file",
                    str(diagnostics),
                    *command,
                ]
            result = subprocess.run(
                command,
                input=raw,
                text=True,
                capture_output=True,
                timeout=180,
                check=False,
            )
            log_text = diagnostics.read_text() + result.stderr
            diagnostics.write_text(log_text)
            (args.output / f"{label}.stdout.json").write_text(result.stdout)
            response = json.loads(result.stdout)
            if rejected:
                assert (
                    result.returncode == 2
                    and response["error"]["code"] == "unsupported_input"
                ), (label, response)
            else:
                assert result.returncode == 0, (label, result.stderr)
                assert response["result"]["count"] == math.comb(n, k), (label, response)
                assert response["backend"]["hardware"]["device_ordinal"] == device
                if sanitizer == "memcheck":
                    assert "ERROR SUMMARY: 0 errors" in log_text, log_text
                else:
                    assert "RACECHECK SUMMARY: 0 hazards" in log_text, log_text
            rows.append(
                {
                    "case": label,
                    "passed": True,
                    "sanitizer": sanitizer,
                    "expected_rejection": rejected,
                    "request_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "response": response,
                    "log_sha256": sha(args.output / f"{label}.stderr.log"),
                }
            )
            print(label, "passed", flush=True)
    assert before == {str(p): sha(p) for p in files}
    result = {
        "passed": len(rows),
        "failed": 0,
        "implementation_sha256": catalog["implementation_sha256"],
        "binary_files": before,
        "build_unchanged_during_run": True,
        "sanitizer_binary_sha256": sha(Path("/usr/bin/compute-sanitizer")),
        "cases": rows,
    }
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
