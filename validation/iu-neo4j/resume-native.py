"""Run the remaining oracle groups after shared-GPU memory contention.

Completed reports are retained unchanged. This script uses the same native
executables, independent oracles, source snapshots and report format as
tools/validate_native_runtime.py, and records itself in each new snapshot.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_native_runtime import sha, snapshot, source_snapshot

build = ROOT / "library/build/runtime"
output = Path(__file__).parent / "native-refresh"
before = snapshot(build)
sources = source_snapshot(build)
sources[str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__))
catalog = json.loads(subprocess.check_output([build / "graphmine-native", "catalog"]))
request = {"command": "run", "problem": "breadth-first-search", "graph": {
    "graph": {"id": "evidence-device", "directed": False, "allows_self_loops": False, "allows_parallel_edges": False},
    "vertices": [{"id": 0}], "edges": []}, "parameters": {"sources": [0]},
    "device": "gpu", "backend": "libcugraph", "gpu_device": 0}
hardware = json.loads(subprocess.check_output([build / "graphmine-native", "request"],
    input=json.dumps(request), text=True))["backend"]["hardware"]
assert hardware["uuid"] == "GPU-f9f2c156-0de4-a1f3-0c8a-a77ca24d10f7"
for backend, suite in [("gamma", "fixed"), ("kcgpu", "fixed"), ("kcore-gpu", "core"), ("libcugraph", "core")]:
    name = f"mining-{backend}-gpu-1"
    rows = []
    for case in ["contracts", suite, "boundaries"]:
        log_path = output / f"{name}-{case}.log"
        with log_path.open("w") as log:
            result = subprocess.run([build / "graphmine_mining_test", case, backend, "0"],
                                    stdout=log, stderr=subprocess.STDOUT, timeout=300)
        assert result.returncode == 0, f"{backend}/{case} failed; inspect {log_path}"
        row = json.loads(log_path.read_text().strip().splitlines()[-1])
        assert row["failed"] == 0 and row["passed_requests"] > 0
        assert row.get("implementation_sha256", catalog["implementation_sha256"]) == catalog["implementation_sha256"]
        row["implementation_sha256"] = catalog["implementation_sha256"]
        rows.append(row)
        print(f"{backend}/{case}: {row['passed_requests']} passed", flush=True)
    after = source_snapshot(build)
    after[str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__))
    assert before == snapshot(build) and sources == after
    (output / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")
    metadata = {"binary_files": before, "build_unchanged_during_run": True,
        "implementation_sha256": catalog["implementation_sha256"],
        "native_library_sha256": before[str((build / "libgraphmine_runtime.so").resolve())],
        "sources_unchanged_during_run": True, "source_files": sources,
        "device": "gpu", "gpu_hardware": hardware, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")}
    (output / f"{name}.json.metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
