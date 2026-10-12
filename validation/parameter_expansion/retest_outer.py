#!/usr/bin/env python3
"""Re-run the outer workspace's raw artifacts without replacing old evidence.

The pre-existing screen adapters expose results but retain upstream kernels.
These results are deliberately separate from the repaired library's sweep.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUTER = ROOT.parent
LEGACY = OUTER / "validation/gpu_correctness_expansion"
HERE = OUTER / "validation/parameter_expansion_outer"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child(name, gpu):
    sys.path.insert(0, str(LEGACY))
    import run
    import validate_extra
    import screen_candidates
    import screen_remaining
    modules = [run, validate_extra, screen_candidates, screen_remaining]
    folder = HERE / name
    folder.mkdir(parents=True, exist_ok=True)
    for directory in ["bin", "adapted/wbpr", "results"]:
        (folder / directory).mkdir(parents=True, exist_ok=True)
    for binary in (LEGACY / "bin").iterdir():
        target = folder / "bin" / binary.name
        if not target.exists():
            # gpu4gst's original screen rebuilds its device-selection adapter.
            if binary.name == "gpu4gst_device0":
                shutil.copy2(binary, target)
            else:
                target.symlink_to(binary)
    target = folder / "adapted/wbpr/maxflow"
    if not target.exists():
        target.symlink_to(LEGACY / "adapted/wbpr/maxflow")
    if name == "gamma_butterfly":
        ref = HERE / "graphminer_butterfly"
        shutil.copytree(ref / "datasets/graphminer_butterfly", folder / "datasets/graphminer_butterfly", dirs_exist_ok=True)
        shutil.copy2(ref / "results/graphminer_butterfly.json", folder / "results/graphminer_butterfly.json")

    def run_command(label, command, *, cwd=OUTER, timeout=120, kind="runs", stdin_path=None):
        directory = folder / kind
        directory.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": gpu, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "1"}
        start = time.monotonic()
        with (directory / (label + ".log")).open("w") as log, (Path(stdin_path) if stdin_path else Path("/dev/null")).open("rb") as inp:
            process = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env, stdin=inp,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            expired = False
            try:
                code = process.wait(timeout=min(timeout, 15) if kind == "runs" else timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                code, expired = 124, True
        record = {"command": list(map(str, command)), "cwd": str(cwd), "gpu": gpu,
                  "stdin_path": str(stdin_path) if stdin_path else None,
                  "exit_code": code, "timeout": expired, "elapsed_seconds": time.monotonic()-start,
                  "log": str((directory / (label + ".log")).relative_to(folder))}
        run.write_json(directory / (label + ".json"), record)
        return record, (directory / (label + ".log")).read_text(errors="replace")

    old_scc, old_flow = run.scc_cases, run.flow_cases
    def scc_cases():
        yield from old_scc()
        arcs = list(itertools.permutations(range(3), 2))
        for mask in range(64):
            yield f"all3_{mask}", 3, [e for i,e in enumerate(arcs) if mask >> i & 1]
        rng = random.Random(20261009)
        for i in range(64):
            n = rng.randint(4, 8)
            yield f"small_{i}", n, [e for e in itertools.permutations(range(n),2) if rng.random()<0.3]
    def flow_cases():
        yield from old_flow()
        rng = random.Random(20261009)
        for key,n,edges in list(scc_cases())[13:]:
            yield key,n,[(u,v,rng.randint(0,20)) for u,v in edges],0,n-1
    for module in modules:
        module.HERE = folder
        module.run_command = run_command
        module.scc_cases = scc_cases
        module.flow_cases = flow_cases
    functions = {
        "ecl_scc": lambda: run.validate(name), "ecl_flow": lambda: run.validate(name),
        "hungarian": lambda: run.validate(name), "gdlog_tc": validate_extra.reachability,
        "graphminer_butterfly": validate_extra.butterflies,
        "gim": lambda: validate_extra.influence(name), "superfuser": lambda: validate_extra.influence(name),
        "wbpr": screen_candidates.wbpr, "gamma_butterfly": screen_candidates.gamma,
        "gpusteiner": screen_candidates.gpusteiner, "kpar": screen_remaining.kpar,
        "graphbplus": lambda: screen_remaining.signed(name),
        "ecl_sgb": lambda: screen_remaining.signed(name),
        "gst_vlsi": screen_remaining.gst_vlsi, "gpu4gst": screen_remaining.gpu4gst,
    }
    if name == "gpu4gst":
        # The current outer source already contains an earlier device-0 repair.
        # Rebuild that source rather than reapplying stale textual anchors.
        def current_gpu4gst_source(original, destination, transform):
            text = original.read_text()
            if "run_gpu4gst" in text and "cudaSetDevice(0)" in text:
                return run.adapt(original, destination, lambda value: value)
            return run.adapt(original, destination, transform)
        screen_remaining.adapt = current_gpu4gst_source
    functions[name]()
    path = folder / "results" / (name + ".json")
    if not path.exists():
        run.write_json(path, {"backend": name, "status": "build_failed", "passed": 0, "total": 0})
    result = json.loads(path.read_text())
    result["scope_location"] = str(OUTER / "problems")
    result["gpu"] = gpu
    result["binaries"] = {str(p.resolve()): sha(p) for p in (folder / "bin").iterdir() if p.is_file()}
    result["screen_source_sha256"] = {str(Path(m.__file__)): sha(Path(m.__file__)) for m in modules}
    run.write_json(path, result)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend")
    p.add_argument("--gpu", default="0")
    args = p.parse_args()
    if args.backend:
        child(args.backend, args.gpu)
        return
    HERE.mkdir(parents=True, exist_ok=True)
    def launch(name, gpu):
        with (HERE / (name + ".log")).open("w") as log:
            proc = subprocess.run([sys.executable, __file__, "--backend", name, "--gpu", gpu],
                                  stdout=log, stderr=subprocess.STDOUT)
        path = HERE / name / "results" / (name + ".json")
        result = json.loads(path.read_text()) if path.exists() else {"backend": name, "status": "screen_error", "passed": 0, "total": 0}
        result["screen_exit_code"] = proc.returncode
        print(name, result["status"], result.get("passed"), result.get("total"), flush=True)
        return result
    # GAMMA consumes the same independently counted fixtures as GraphMiner.
    results = [launch("graphminer_butterfly", "0")]
    names = ["ecl_scc", "ecl_flow", "hungarian", "gdlog_tc", "gim", "superfuser", "wbpr",
             "gamma_butterfly", "gpusteiner", "kpar", "graphbplus", "ecl_sgb", "gst_vlsi", "gpu4gst"]
    def shard(i):
        return [launch(name, str(i)) for name in names[i::2]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for rows in pool.map(shard, [0,1]):
            results.extend(rows)
    summary = {"location": str(OUTER / "problems"), "results": results,
               "note": "Raw outer artifacts and their existing diagnostic adapters; separate from repaired inner-library results."}
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")


if __name__ == "__main__":
    main()
