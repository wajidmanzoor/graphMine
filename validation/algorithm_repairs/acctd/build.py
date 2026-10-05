#!/usr/bin/env python3
"""Build the AccTD repair from a clean archive of the recorded upstream commit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", type=Path, required=True,
                        help="Local upstream Git checkout; its worktree is never modified")
    parser.add_argument("--output", type=Path, required=True, help="New build directory")
    parser.add_argument("--architecture", default="89")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--poison-allocations", action="store_true",
                        help="Fill every managed allocation with 0xa5 to expose reliance on zeroed memory")
    parser.add_argument("--force-recount", action="store_true",
                        help="Exercise the adaptive triangle-recount update path on small test graphs")
    args = parser.parse_args()
    provenance = json.loads((HERE / "provenance.json").read_text())
    patch = HERE / "repair.patch"
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == provenance["patch_sha256"]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    archive = output / "upstream.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "-C", str(args.source_checkout.resolve()), "archive",
                        provenance["commit"], "LICENSE", "opt-truss-decomp-offload",
                        "dependencies/libpopcnt", "dependencies/moderngpu/src"],
                       stdout=stream, check=True)
    with tarfile.open(archive) as snapshot:
        snapshot.extractall(source, filter="data")
    # Give git apply an isolated repository root; otherwise it discovers the
    # enclosing GraphMine checkout and silently skips these relative paths.
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
    for name, expected in provenance["patched_source_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Patched source hash mismatch: {name}")
    if args.poison_allocations:
        header = source / "opt-truss-decomp-offload/util/cuda/cuda_util.h"
        text = header.read_text()
        anchor = "    checkCudaErrors(cudaMallocManaged((void **) addr, malloc_bytes));"
        assert text.count(anchor) == 1
        text = text.replace(anchor, anchor + "\n    checkCudaErrors(cudaMemset(*addr, 0xa5, malloc_bytes));")
        header.write_text(text)
    if args.force_recount:
        kernel = source / "opt-truss-decomp-offload/pkt_cuda_experimental.cu"
        text = kernel.read_text()
        anchor = "if (estimated_tc_time > estimated_peel_time) {"
        assert text.count(anchor) == 1
        kernel.write_text(text.replace(anchor, "if (false) { // Validation: force triangle recount"))
    build = output / "build"
    commands = [
        ["cmake", "-S", str(source / "opt-truss-decomp-offload"), "-B", str(build),
         "-DCMAKE_BUILD_TYPE=Release", "-DUSE_JEMALLOC=OFF", "-DPLAYGROUND=OFF",
         f"-DUSER_CC_CAP={args.architecture}"],
        ["cmake", "--build", str(build), "--target", "cuda-pkt-offload-opt",
         "--parallel", str(args.jobs)],
    ]
    for label, command in zip(("configure", "build"), commands):
        with (output / f"{label}.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = build / "cuda-pkt-offload-opt"
    result = {"upstream_commit": provenance["commit"], "patch_sha256": provenance["patch_sha256"],
              "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "architecture": args.architecture, "poison_allocations": args.poison_allocations,
              "force_recount": args.force_recount,
              "commands": commands, "binary": str(binary),
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    (output / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(binary)


if __name__ == "__main__":
    main()
