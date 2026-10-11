#!/usr/bin/env python3
"""Install the CPU core and verify C/C++ algorithm calls without a Python PATH."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-build", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--consumer-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = ROOT / "library/examples/native_runtime"
    subprocess.run(
        ["cmake", "--install", args.cpu_build, "--prefix", args.prefix], check=True
    )
    subprocess.run(
        [
            "cmake",
            "-S",
            source,
            "-B",
            args.consumer_build,
            f"-DCMAKE_PREFIX_PATH={args.prefix}",
        ],
        check=True,
    )
    subprocess.run(["cmake", "--build", args.consumer_build, "-j", "2"], check=True)
    environment = {
        "PATH": str(args.consumer_build / "empty-path"),
        "CUDA_VISIBLE_DEVICES": "",
    }
    results = {}
    for name in ("cpp_consumer", "c_consumer"):
        results[name] = json.loads(
            subprocess.check_output(
                [args.consumer_build / name], env=environment, timeout=20
            )
        )
        assert results[name]["backend"]["id"] == "cpp"
        assert results[name]["backend"]["python_runtime_required"] is False
    cpp, c = results["cpp_consumer"], results["c_consumer"]
    assert cpp["result"]["maximum_size"] == 3
    assert [row["vertices"] for row in cpp["result"]["groups"]] == [[0, 1, 2]]
    assert [row["core_number"] for row in c["result"]["vertices"]] == [2, 2, 2, 0]
    assert c["result"]["selected_vertices"] == [0, 1, 2]
    assert cpp["implementation_sha256"] == c["implementation_sha256"]
    library = args.prefix / "lib/libgraphmine_runtime.so"
    linkage = subprocess.check_output(["ldd", library], text=True)
    assert "not found" not in linkage
    # ICU's libicudata is a Unicode data library, not a CUDA dependency.
    assert not re.search(r"\blib(?:python|cuda(?:rt)?|cugraph|cudf)[^\s]*\.so", linkage)
    record = {
        "cpp_consumer": True,
        "c_consumer": True,
        "python_on_path": False,
        "cuda_visible_devices": "",
        "cpu_ldd": linkage,
        "scope": "Installed standalone C/C++ algorithm calls on a triangle plus isolated vertex",
        "results": results,
        "source_files": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [*sorted(source.iterdir()), Path(__file__)]
            if p.is_file()
        },
        "binary_files": {
            str(args.consumer_build / name): sha(args.consumer_build / name)
            for name in results
        },
        "installed_library": {"path": str(library), "sha256": sha(library)},
        "implementation_sha256": cpp["implementation_sha256"],
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print("Installed C and C++ algorithm consumers passed without Python or CUDA")


if __name__ == "__main__":
    main()
