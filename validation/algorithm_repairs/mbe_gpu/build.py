#!/usr/bin/env python3
"""Rebuild the MBE-GPU repair from pinned local Git objects, without downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(checkout, commit, destination, tar_path, paths=()):
    destination.mkdir(parents=True, exist_ok=True)
    with tar_path.open("wb") as stream:
        subprocess.run(["git", "-C", str(checkout), "archive", commit, *paths],
                       stdout=stream, check=True)
    with tarfile.open(tar_path) as snapshot:
        snapshot.extractall(destination, filter="data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--targets", nargs="+", default=["MBE_GPU", "MBE_GPU_NOPRUNE"])
    parser.add_argument("--counter-seed", type=int, default=0,
                        help="Diagnostic build only: start the device counter at this value")
    parser.add_argument("--poison-scratch", action="store_true",
                        help="Diagnostic build only: fill scratch buffers with 0xa5 instead of zero")
    args = parser.parse_args()
    provenance = json.loads((HERE / "provenance.json").read_text())
    patch = HERE / "repair.patch"
    if digest(patch) != provenance["patch_sha256"]:
        raise RuntimeError("Repair patch hash mismatch")
    checkout = args.source_checkout.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    archive(checkout, provenance["commit"], source, output / "upstream.tar", ("src",))
    archive(checkout / "src/third_party/cub", provenance["cub_commit"],
            source / "src/third_party/cub", output / "cub.tar")
    # Avoid git apply discovering the surrounding GraphMine repository.
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
    for name, expected in provenance["patched_source_sha256"].items():
        if digest(source / name) != expected:
            raise RuntimeError(f"Patched source mismatch: {name}")
    # Retain optimized code, with line information for sanitizer diagnostics.
    cmake = source / "src/CMakeLists.txt"
    text = cmake.read_text()
    anchor = "set(CUDA_NVCC_FLAGS -gencode ${CudaArch};-O3;-w)"
    assert text.count(anchor) == 1
    cmake.write_text(text.replace(anchor, "set(CUDA_NVCC_FLAGS -gencode ${CudaArch};-O3;-w;-lineinfo)"))
    kernel = source / "src/IterFinderGpu.cu"
    text = kernel.read_text()
    if args.counter_seed:
        if not 0 < args.counter_seed < (1 << 64):
            parser.error("Counter seed must be a positive uint64")
        anchor = "gpuErrchk(cudaMemset(dev_mb_, 0, sizeof(unsigned long long)));"
        assert text.count(anchor) == 3
        replacement = (f"const unsigned long long validation_counter_seed = {args.counter_seed}ULL;\n"
                       "  gpuErrchk(cudaMemcpy(dev_mb_, &validation_counter_seed, sizeof(validation_counter_seed), cudaMemcpyHostToDevice));")
        text = text.replace(anchor, replacement)
    if args.poison_scratch:
        anchor = "cudaMemset(dev_global_buffer_, 0, g_size * sizeof(int))"
        assert text.count(anchor) == 3
        text = text.replace(anchor, "cudaMemset(dev_global_buffer_, 0xa5, g_size * sizeof(int))")
    kernel.write_text(text)
    build = output / "build"
    commands = [["cmake", "-S", str(source / "src"), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release"],
                ["cmake", "--build", str(build), "--target", *args.targets, "--parallel", str(args.jobs)]]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu))
    for label, command in zip(("configure", "build"), commands):
        with (output / f"{label}.log").open("w") as stream:
            subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = dict(upstream_commit=provenance["commit"], cub_commit=provenance["cub_commit"],
                  patch_sha256=digest(patch), upstream_archive_sha256=digest(output / "upstream.tar"),
                  cub_archive_sha256=digest(output / "cub.tar"), commands=commands,
                  lineinfo=True, counter_seed=args.counter_seed, poison_scratch=args.poison_scratch,
                  gpu=args.gpu,
                  compiled_source_sha256={name: digest(source / name) for name in provenance["patched_source_sha256"]},
                  binaries={name: {"path": str(build / name), "sha256": digest(build / name)} for name in args.targets})
    (output / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["binaries"]), flush=True)


if __name__ == "__main__":
    main()
