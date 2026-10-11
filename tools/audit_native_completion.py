#!/usr/bin/env python3
"""Inventory all formal contracts through the same evidence gate used by the app."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-library", required=True, type=Path)
    parser.add_argument("--gpu-library", required=True, type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "catalog/native_runtime_coverage.json"
    )
    args = parser.parse_args()
    builds = {}
    for name, library in (("cpu", args.cpu_library), ("gpu", args.gpu_library)):
        env = {
            **os.environ,
            "GRAPHMINE_NATIVE_LIBRARY": str(library.resolve()),
            "PYTHONPATH": str(ROOT / "python/graphmine"),
            "CUDA_VISIBLE_DEVICES": "",
        }
        caps = json.loads(
            subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    "import json,sys;from graphmine.evidence import capabilities;print(json.dumps(capabilities(sys.argv[1])))",
                    str(ROOT),
                ],
                env=env,
                cwd=ROOT,
            )
        )
        assert not caps["verification_issues"], caps["verification_issues"]
        assert len(caps["operations"]) == 80
        assert all(card["execution"]["cpu"] for card in caps["operations"])
        builds[name] = {
            "native_library": str(library.resolve()),
            "binary_sha256": sha(library),
            "implementation_sha256": caps["implementation_sha256"],
            "cpu_verified_operations": len(caps["operations"]),
            "gpu_verified_operations": sum(
                card["execution"]["gpu"] for card in caps["operations"]
            ),
            "operations": caps["operations"],
            "verification_issues": caps["verification_issues"],
        }
    cpu, gpu = builds["cpu"]["operations"], builds["gpu"]["operations"]
    assert {(c["id"], c["problem_id"], c["family"]) for c in cpu} == {
        (c["id"], c["problem_id"], c["family"]) for c in gpu
    }
    formal = {
        json.loads(path.read_text())["problem_id"]: path
        for path in (ROOT / "problems").glob("[0-9][0-9]_*/problem.json")
    }
    represented = {card["problem_id"] for card in cpu} - {"graph_record_queries"}
    assert len(formal) == 70 and set(formal) == represented
    inventory = []
    for problem, path in sorted(formal.items()):
        cards = [card for card in gpu if card["problem_id"] == problem]
        inventory.append(
            {
                "problem_id": problem,
                "contract": str(path.relative_to(ROOT)),
                "contract_sha256": sha(path),
                "family": cards[0]["family"],
                "native_cpu_operations": [card["id"] for card in cards],
                "native_gpu_operations": [
                    card["id"] for card in cards if card["execution"]["gpu"]
                ],
            }
        )
    report = {
        "schema_version": 2,
        "scope": "All formal contracts have documented native executable profiles; finite native oracle evidence does not prove every input or every literature variant. The application uses the separately hashed execution gate.",
        "native_formal_problem_count": len(represented),
        "formal_problem_count": len(formal),
        "native_operation_count": len(cpu),
        "native_gpu_operation_count": builds["gpu"]["gpu_verified_operations"],
        "cpu_runtime_operations": [card["id"] for card in cpu],
        "standalone_core_requires_python": False,
        "application_uses_native_runtime": True,
        "application_algorithm_worker_uses_native_runtime": True,
        "application_tabular_uploads_use_native_cudf": True,
        "remaining_native_profile_migration_required": False,
        "formal_problems": inventory,
        "builds": builds,
        "execution_gate": {
            "path": "catalog/native_execution_evidence.json",
            "sha256": sha(ROOT / "catalog/native_execution_evidence.json"),
        },
        "audit_source_sha256": sha(Path(__file__)),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "native_formal_problem_count",
                    "native_operation_count",
                    "native_gpu_operation_count",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
