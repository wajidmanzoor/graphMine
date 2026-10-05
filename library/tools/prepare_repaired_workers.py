#!/usr/bin/env python3
"""Build pinned, hash-checked GPU repairs as isolated GraphMine workers.

Upstream source stays in local build/cache directories. Use --fetch only when
the pinned Git objects or kPAR release archive are not available locally.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPAIRS = ROOT / "validation/algorithm_repairs"
WORKERS = {
    "acctd": (
        "acctd",
        "08_k_truss_decomposition/papers/2020_accelerating_truss_heterogeneous/code",
        "build/cuda-pkt-offload-opt",
    ),
    "mbe-gpu": (
        "mbe_gpu",
        "09_maximal_biclique_enumeration/papers/2023_efficient_mbe_gpus/code",
        "build/MBE_GPU",
    ),
    "cds": (
        "cds",
        "05_densest_subgraph/papers/2026_bound_tightened_dsd/code",
        "build/main",
    ),
    "kpar": ("kpar", "", "kpar"),
    "gamma-butterfly": (
        "gamma_butterfly",
        "23_butterfly_counting_bipartite/papers/2022_gamma_reuse/code",
        "sm",
    ),
    "gpu4gst": (
        "gpu4gst",
        "27_group_steiner_tree/papers/2025_gpu4gst/code",
        "TrimCDP-WB",
    ),
    "superfuser": (
        "superfuser",
        "28_influence_maximization/papers/2021_superfuser/code",
        "superfuser",
    ),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_commit(path, commit):
    return (
        path.is_dir()
        and subprocess.run(
            ["git", "-C", str(path), "cat-file", "-e", commit + "^{commit}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def fetch(path, url, commit):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "fetch", "--depth=1", url, commit], check=True
    )
    assert has_commit(path, commit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "library/repaired-workers"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Existing problems/ directory with pinned upstream Git checkouts",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch missing pinned sources into the local cache",
    )
    parser.add_argument(
        "--gpu",
        type=int,
        default=1,
        help="Physical GPU used by upstream architecture detection",
    )
    parser.add_argument("--arch", default="89")
    parser.add_argument("--backend", action="append", choices=WORKERS)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    roots = ([args.source_root.resolve()] if args.source_root else []) + [
        ROOT / "problems",
        ROOT.parent / "problems",
    ]
    records = (
        json.loads((output / "manifest.json").read_text())
        if (output / "manifest.json").exists()
        else {}
    )
    for backend in args.backend or WORKERS:
        repair, relative, executable = WORKERS[backend]
        folder = REPAIRS / repair
        metadata_file = folder / (
            "provenance.json"
            if backend in ["acctd", "mbe-gpu", "cds"]
            else "manifest.json"
        )
        metadata = json.loads(metadata_file.read_text())
        inputs = [metadata_file, folder / "repair.patch", folder / "build.py"]
        if (folder / "probe.cu").exists():
            inputs.append(folder / "probe.cu")
        fingerprint = hashlib.sha256(
            ("".join(sha(p) for p in inputs) + args.arch).encode()
        ).hexdigest()
        binary = output / ("graphmine-worker-" + backend)
        old = records.get(backend, {})
        if (
            old.get("fingerprint") == fingerprint
            and binary.exists()
            and old.get("sha256") == sha(binary)
        ):
            print(backend, "already prepared", flush=True)
            continue
        cache = output / ".cache" / backend
        work = output / ".build" / (backend + "-" + fingerprint[:16])
        command = [sys.executable, str(folder / "build.py")]
        if backend == "kpar":
            candidates = [
                ROOT / "validation/gpu_correctness_expansion/vendor/kpar/kPAR.zip",
                ROOT.parent
                / "validation/gpu_correctness_expansion/vendor/kpar/kPAR.zip",
                cache / "kPAR.zip",
            ]
            archive = next(
                (
                    p
                    for p in candidates
                    if p.is_file() and sha(p) == metadata["archive_sha256"]
                ),
                None,
            )
            if archive is None:
                if not args.fetch:
                    raise SystemExit(
                        "kPAR release archive is missing; rerun with --fetch"
                    )
                cache.mkdir(parents=True, exist_ok=True)
                archive = cache / "kPAR.zip"
                with urllib.request.urlopen(
                    metadata["archive_url"], timeout=120
                ) as response:
                    archive.write_bytes(response.read())
                assert sha(archive) == metadata["archive_sha256"], (
                    "kPAR archive hash mismatch"
                )
            command += [
                "--archive",
                str(archive),
                "--work",
                str(work),
                "--arch",
                "sm_" + args.arch,
            ]
        else:
            commit = metadata["commit"]
            source = next(
                (
                    root / relative
                    for root in roots
                    if has_commit(root / relative, commit)
                ),
                None,
            )
            if source is None:
                source = cache / "upstream"
                if not has_commit(source, commit):
                    if not args.fetch:
                        raise SystemExit(
                            f"{backend}: pinned checkout missing; pass --source-root or --fetch"
                        )
                    fetch(
                        source,
                        metadata.get("upstream_url", metadata.get("remote")),
                        commit,
                    )
            if backend == "mbe-gpu" and not has_commit(
                source / "src/third_party/cub", metadata["cub_commit"]
            ):
                if not args.fetch:
                    raise SystemExit(
                        "MBE-GPU: pinned CUB objects missing; rerun with --fetch"
                    )
                # Fetch into our own cache, never mutate a supplied checkout.
                cached = cache / "upstream"
                if not has_commit(cached, commit):
                    fetch(cached, metadata["upstream_url"], commit)
                fetch(
                    cached / "src/third_party/cub",
                    "https://github.com/NVIDIA/cub.git",
                    metadata["cub_commit"],
                )
                source = cached
            if backend in ["acctd", "mbe-gpu", "cds"]:
                command += ["--source-checkout", str(source), "--output", str(work)]
                if backend == "acctd":
                    command += ["--architecture", args.arch]
                else:
                    command += ["--gpu", str(args.gpu)]
                    command += (
                        ["--targets", "MBE_GPU"]
                        if backend == "mbe-gpu"
                        else ["--arch", args.arch]
                    )
            else:
                command += [
                    "--upstream",
                    str(source),
                    "--work",
                    str(work),
                    "--arch",
                    "sm_" + args.arch,
                ]
        if not (work / "build.json").exists():
            if work.exists():
                raise SystemExit(
                    f"Incomplete build retained at {work}; inspect it and choose a fresh output directory"
                )
            work.parent.mkdir(parents=True, exist_ok=True)
            print("Building", backend, flush=True)
            with (output / (backend + "-build.log")).open("w") as log:
                subprocess.run(
                    command,
                    env={**os.environ, "CUDA_VISIBLE_DEVICES": str(args.gpu)},
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
        built = work / executable
        build_record = json.loads((work / "build.json").read_text())
        if "binary_sha256" in build_record:
            expected = build_record["binary_sha256"]
        else:
            entry = build_record["binaries"][built.name]
            expected = entry["sha256"] if isinstance(entry, dict) else entry
        assert sha(built) == expected, "Build output hash mismatch"
        shutil.copy2(built, binary)
        binary.chmod(0o755)
        records[backend] = {
            "fingerprint": fingerprint,
            "sha256": sha(binary),
            "repair": repair,
            "patch_sha256": sha(folder / "repair.patch"),
            "build_record": str(work / "build.json"),
            "command": command,
        }
        (output / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
        print(backend, records[backend]["sha256"], flush=True)


if __name__ == "__main__":
    main()
