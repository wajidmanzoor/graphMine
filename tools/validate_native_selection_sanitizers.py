#!/usr/bin/env python3
"""Verify native selection GPU boundaries under CUDA memory/init checking."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.gpu_build = args.gpu_build.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    files = [
        args.gpu_build / name
        for name in (
            "graphmine_selection_test",
            "graphmine-native",
            "libgraphmine_runtime.so",
            "native-source-hashes.txt",
        )
    ] + [Path(__file__).resolve()]
    before = {str(path): sha(path) for path in files}
    catalog = json.loads(
        subprocess.check_output([args.gpu_build / "graphmine-native", "catalog"])
    )
    rows = []
    for device in (0, 1):
        for tool in ("memcheck", "initcheck"):
            case = f"libcugraph-{tool}-gpu-{device}"
            diagnostics = args.output / f"{case}.stderr.log"
            command = [
                "/usr/bin/compute-sanitizer",
                "--tool",
                tool,
                "--error-exitcode",
                "99",
                "--log-file",
                str(diagnostics),
                str(args.gpu_build / "graphmine_selection_test"),
                "large",
                "libcugraph",
                str(device),
            ]
            process = subprocess.run(
                command, capture_output=True, text=True, timeout=180, check=False
            )
            log = diagnostics.read_text() + process.stderr
            diagnostics.write_text(log)
            output = args.output / f"{case}.stdout.json"
            output.write_text(process.stdout)
            assert process.returncode == 0 and "ERROR SUMMARY: 0 errors" in log, (
                case,
                log[-5000:],
            )
            result = json.loads(process.stdout)
            assert result["passed_requests"] == 11 and result["failed"] == 0
            assert result["implementation_sha256"] == catalog["implementation_sha256"]
            rows.append(
                {
                    "case": case,
                    "passed": True,
                    "result": result,
                    "log_sha256": sha(diagnostics),
                    "output_sha256": sha(output),
                }
            )
            print(case + ": passed", flush=True)
    assert before == {str(path): sha(path) for path in files}
    record = {
        "passed": len(rows),
        "failed": 0,
        "cases": rows,
        "binary_files": before,
        "sanitizer_binary_sha256": sha(Path("/usr/bin/compute-sanitizer")),
        "build_unchanged_during_run": True,
        "implementation_sha256": catalog["implementation_sha256"],
    }
    (args.output / "summary.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
