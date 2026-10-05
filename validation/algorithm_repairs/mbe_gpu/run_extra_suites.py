#!/usr/bin/env python3
"""Run the additional MBE-GPU repair suites, after validate.py's full sweep."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True,
                        help="build.py output directory containing build/MBE_GPU")
    parser.add_argument("--poison-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=1)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    normal = args.build.resolve() / "build/MBE_GPU"
    unpruned = args.build.resolve() / "build/MBE_GPU_NOPRUNE"
    poison = args.poison_build.resolve() / "build/MBE_GPU"
    poison_metadata = json.loads((args.poison_build / "build.json").read_text())
    if not poison_metadata["poison_scratch"] or poison_metadata["counter_seed"] != 4294967296:
        parser.error("The diagnostic build must use --poison-scratch --counter-seed 4294967296")
    selected = "^(original-small|original-medium|overlap|one-edge-isolate|crown-8|staircase-33)$"
    suites = [
        ("options", normal, ["--only", selected, "--orders", "0", "1", "2",
                             "--transposes", "0", "1", "2"]),
        ("slow-input", normal, ["--only", selected, "--orders", "0", "1", "2",
                                "--transposes", "0", "1", "2", "--slow-input"]),
        ("poison-counter", poison, ["--counter-offset", "4294967296", "--repeats", "3"]),
        ("forced-split", normal, ["--modes", "2", "--bound-height", "2",
                                  "--bound-size", "4", "--repeats", "3"]),
        ("unpruned", unpruned, []),
    ]
    sanitizer_selected = "^(empty-file|no-edges|one-edge-isolate|original-small|original-medium|overlap|crown-8|staircase-33)$"
    for tool in ("memcheck", "initcheck", "synccheck", "racecheck"):
        suites.append((tool, normal, ["--only", sanitizer_selected, "--sanitizer", tool,
                                      "--workers", "1", "--timeout", "90"]))
        suites.append((f"split-{tool}", normal,
                       ["--only", "^(original-small|original-medium|crown-8|staircase-33)$",
                        "--modes", "2", "--bound-height", "2", "--bound-size", "4",
                        "--sanitizer", tool, "--workers", "1", "--timeout", "90"]))
    records = []
    for name, binary, options in suites:
        command = [sys.executable, str(HERE / "validate.py"), "--binary", str(binary),
                   "--output", str(output / f"{name}.json"), "--suite", "smoke",
                   "--workers", "2", "--gpu", str(args.gpu), *options]
        print(f"Starting {name}", flush=True)
        result = subprocess.run(command)
        records.append(dict(suite=name, command=command, returncode=result.returncode))
        (output / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
