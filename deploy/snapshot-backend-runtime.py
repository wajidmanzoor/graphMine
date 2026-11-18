#!/usr/bin/env python3
"""Copy verified native bytes into a new detached release checkout.

No rebuild, binary patch, benchmark or dependency installation occurs. The only
tracked change in the snapshot is relocation of verified worker/library paths
in the correctness manifest. Commit that relocation before deploying it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def copy_verified(source, destination, digest):
    if sha(source) != digest:
        raise ValueError(f"Source changed: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha(destination) != digest:
            raise ValueError(f"Snapshot source differs: {destination}")
    else:
        shutil.copy2(source, destination)
    if sha(destination) != digest:
        raise ValueError(f"Copy verification failed: {destination}")


def launcher(path, *, native):
    executable = "library/build/runtime/graphmine-native" if native else "library/build/graphmine"
    workers = "library/build/runtime/verified-workers" if native else "library/build/workers"
    text = f'''#!/usr/bin/env bash
set -euo pipefail
release_root="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
export GRAPHMINE_RUNTIME_REPOSITORY="$release_root"
export GRAPHMINE_NATIVE_LIBRARY="$release_root/library/build/runtime/libgraphmine_runtime.so"
export GRAPHMINE_WORKER_DIR="$release_root/{workers}"
export LD_LIBRARY_PATH="$release_root/library/build/runtime${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
export PYTHONPATH="${{PYTHONPATH:+$PYTHONPATH:}}$release_root/agent:$release_root/python/graphmine"
exec "$release_root/{executable}" "$@"
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    subprocess.run(["bash", "-n", path], check=True)


def snapshot(source, destination):
    source, destination = source.resolve(), destination.absolute()
    if destination.exists():
        raise ValueError("A runtime snapshot must use a new destination")
    if subprocess.check_output(["git", "-C", source, "status", "--porcelain"], text=True).strip():
        raise ValueError("Commit source changes before snapshotting a release")
    commit = subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip()
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="")
    catalog = json.loads(subprocess.check_output([source / "library/build/runtime/graphmine-native", "catalog"], env=environment))
    implementation = catalog["implementation_sha256"]
    evidence = json.loads((source / "catalog/native_execution_evidence.json").read_text())
    current = next(b for b in evidence["builds"] if b["implementation_sha256"] == implementation)
    library = source / "library/build/runtime/libgraphmine_runtime.so"
    if sha(library) != current["binary_sha256"]:
        raise ValueError("The current library does not match correctness evidence")
    subprocess.run(["git", "-C", source, "worktree", "add", "--detach", destination, commit], check=True)
    for name, digest in current["sources"].items():
        copy_verified(source / name, destination / name, digest)
    binary_hashes = {}
    for name in ("library/build/graphmine", "library/build/runtime/graphmine-native", "library/build/runtime/native-source-hashes.txt"):
        digest = sha(source / name)
        copy_verified(source / name, destination / name, digest)
        binary_hashes[name] = digest
    real = library.resolve()
    relative = real.relative_to(source)
    copy_verified(real, destination / relative, current["binary_sha256"])
    binary_hashes[str(relative)] = current["binary_sha256"]
    for alias in library.parent.glob("libgraphmine_runtime.so*"):
        if alias.is_symlink():
            target = os.readlink(alias)
            if Path(target).is_absolute() or "/" in target:
                raise ValueError("Runtime aliases must remain within their directory")
            (destination / alias.relative_to(source)).symlink_to(target)
    relocated, merged = {}, {}
    for name, digest in current["workers"].items():
        relative = Path(name).relative_to(source)
        target = destination / relative
        copy_verified(Path(name), target, digest)
        relocated[str(target)] = digest
        binary_hashes[str(relative)] = digest
        # The native optimization ABI and the classic CLI have different worker
        # builds with identical names. Keep both; native calls select their own.
        if target.name not in merged or "optimization-workers" in relative.parts:
            merged[target.name] = target
    directory = destination / "library/build/runtime/verified-workers"
    directory.mkdir(parents=True)
    for name, target in merged.items():
        (directory / name).symlink_to(os.path.relpath(target, directory))
    current["workers"] = relocated
    current["native_library"] = str(destination / "library/build/runtime/libgraphmine_runtime.so")
    (destination / "catalog/native_execution_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    launcher(destination / "bin/graphmine", native=False)
    launcher(destination / "bin/graphmine-native", native=True)
    for name in ("bin/graphmine", "bin/graphmine-native"):
        binary_hashes[name] = sha(destination / name)
    loaded = json.loads(subprocess.check_output([destination / "bin/graphmine-native", "catalog"], env=environment))
    if loaded["implementation_sha256"] != implementation:
        raise ValueError("Relocated native launcher loaded a different implementation")
    linkage = subprocess.check_output(["ldd", destination / "library/build/runtime/graphmine-native"], text=True,
        env=dict(environment, LD_LIBRARY_PATH=str(destination / "library/build/runtime")))
    match = re.search(r"libgraphmine_runtime\.so[^ ]* => (/\S+)", linkage)
    if not match or Path(match[1]).resolve() != (destination / real.relative_to(source)).resolve():
        raise ValueError("Native executable still resolves a development library")
    return dict(source_commit=commit, runtime_checkout=str(destination), implementation_sha256=implementation,
                native_library_sha256=current["binary_sha256"], artifact_hashes=binary_hashes,
                worker_links={name: str(target) for name, target in merged.items()},
                source_inventory_count=len(current["sources"]), native_worker_count=len(relocated),
                relocation_only=True, correctness_reports_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = snapshot(args.source, args.destination)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in {"artifact_hashes", "worker_links"}}, indent=2))


if __name__ == "__main__":
    main()
