#!/usr/bin/env python3
"""Measure authenticated API upload, planning, native execution and full retrieval.

Run after validate_native_scale.py; compare values with its independently checked
SNAP results. Each case runs in a fresh process for meaningful RSS accounting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.getenv("GRAPHMINE_APPLICATION_SOURCE", str(ROOT / "agent")))
sys.path.insert(0, str(APP))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def single(args):
    from fastapi.testclient import TestClient
    from graphmine_agent.api import create_app
    from graphmine_agent.config import Settings

    request_path = (
        args.native_results / f"snap-ca-CondMat-{args.operation}-cpu.request.json"
    )
    expected_path = (
        args.native_results / f"snap-ca-CondMat-{args.operation}-cpu.result.json"
    )
    request, expected = (
        json.loads(request_path.read_text()),
        json.loads(expected_path.read_text()),
    )
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="graphmine-api-scale-") as directory:
        settings = replace(
            Settings.from_env(ROOT),
            data_root=Path(directory),
            api_token="local-scale-check",
            native_runtime_library=args.library.resolve(),
            llm_enabled=False,
            graph_gpu_uuid=args.gpu,
            analytics_gpu_uuids=(args.gpu,) if args.gpu else (),
            llm_gpu_uuid=None,
            job_timeout_seconds=180,
            max_upload_bytes=64 * 1024 * 1024,
        )
        headers = {"Authorization": "Bearer local-scale-check"}
        with TestClient(create_app(settings)) as client:
            session = client.post("/api/sessions", headers=headers, json={}).json()[
                "id"
            ]
            uploaded = client.post(
                f"/api/sessions/{session}/files",
                headers=headers,
                data={"role": "graph"},
                files={
                    "file": (
                        "snap.json",
                        json.dumps(request["graph"]).encode(),
                        "application/json",
                    )
                },
            )
            assert uploaded.status_code == 201, uploaded.text[:1000]
            upload_done = time.perf_counter()
            plan = {
                "version": 1,
                "device": "gpu" if args.gpu else "cpu",
                "steps": [
                    {
                        "id": "answer",
                        "operation": args.operation,
                        "input": {"input": "main"},
                        "parameters": request["parameters"],
                        "budget": {
                            "max_output_items": 1000000,
                            "max_candidates": 100000000,
                            "timeout_seconds": 120,
                        },
                    }
                ],
            }
            created = client.post(
                f"/api/sessions/{session}/workflows",
                headers=headers,
                json={
                    "mode": "normal",
                    "inputs": {"main": {"file_id": uploaded.json()["id"]}},
                    "plan": plan,
                    "evaluation_id": "external-scale/snap",
                },
            )
            assert created.status_code == 201, created.text[:1000]
            create_done = time.perf_counter()
            workflow = created.json()["id"]
            while time.perf_counter() - start < 180:
                record = client.get(
                    f"/api/workflows/{workflow}", headers=headers
                ).json()
                if record["status"] in ("completed", "failed", "cancelled"):
                    break
                time.sleep(0.05)
            assert record["status"] == "completed", record
            execution_done = time.perf_counter()
            response = client.get(f"/api/workflows/{workflow}/result", headers=headers)
            assert response.status_code == 200, response.text[:1000]
            result = response.json()
            actual = result["steps"]["answer"]["result"]
            assert result["complete"] and actual["complete"]
            if args.gpu:
                assert actual["backend"]["hardware"]["uuid"] == args.gpu
            else:
                assert actual["backend"]["device"] == "cpu"
            if args.operation == "pagerank":
                wanted = {
                    row["vertex"]: row["score"]
                    for row in expected["ports"]["scores"]["value"]
                }
                observed = {
                    row["vertex"]: row["score"]
                    for row in actual["ports"]["scores"]["value"]
                }
                assert observed.keys() == wanted.keys()
                error = max(abs(observed[key] - wanted[key]) for key in wanted)
                assert error < 2e-8
                port = "scores"
            else:
                observed = actual["ports"]["distances"]["value"]
                wanted = expected["ports"]["distances"]["value"]
                assert [
                    {k: v for k, v in row.items() if k != "predecessor"}
                    for row in observed
                ] == [
                    {k: v for k, v in row.items() if k != "predecessor"}
                    for row in wanted
                ]
                distances = {row["vertex"]: row["distance"] for row in observed}
                edges = {(e["source"], e["target"]) for e in request["graph"]["edges"]}
                if not request["graph"]["graph"]["directed"]:
                    edges |= {(v, u) for u, v in edges}
                for row in observed:
                    if row["distance"] is not None and row["distance"] > 0:
                        assert (row["predecessor"], row["vertex"]) in edges
                        assert distances[row["predecessor"]] == row["distance"] - 1
                error = 0
                port = "distances"
            page = client.get(
                f"/api/workflows/{workflow}/steps/answer/ports/{port}?offset=1000&limit=7",
                headers=headers,
            )
            assert page.status_code == 200, page.text[:1000]
            retrieval_done = time.perf_counter()
            measured = {
                "dataset": "SNAP ca-CondMat",
                "vertices": len(request["graph"]["vertices"]),
                "edges": len(request["graph"]["edges"]),
                "operation": args.operation,
                "backend": actual["backend"],
                "allocation": record["allocation"],
                "upload_seconds": upload_done - start,
                "validation_and_submission_seconds": create_done - upload_done,
                "execution_and_poll_seconds": execution_done - create_done,
                "full_retrieval_and_page_seconds": retrieval_done - execution_done,
                "total_seconds": retrieval_done - start,
                "full_result_bytes": len(response.content),
                "api_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * 1024,
                "largest_worker_peak_rss_bytes": resource.getrusage(
                    resource.RUSAGE_CHILDREN
                ).ru_maxrss
                * 1024,
                "reference_sha256": sha(expected_path),
                "input_request_sha256": sha(request_path),
                "max_absolute_error_against_independently_checked_native_reference": error,
                "passed": True,
            }
    print(json.dumps(measured))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-results", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--gpus", default="")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="store_true")
    parser.add_argument("--operation")
    parser.add_argument("--gpu")
    args = parser.parse_args()
    if args.case:
        single(args)
        return
    files = list((APP / "graphmine_agent").rglob("*.py")) + [
        Path(__file__),
        args.library,
        ROOT / "catalog/native_execution_evidence.json",
    ]
    before = {str(p): sha(p) for p in files}
    rows = []
    for operation in ("breadth-first-search", "pagerank"):
        for gpu in [None, *filter(None, args.gpus.split(","))]:
            command = [
                sys.executable,
                str(Path(__file__)),
                "--case",
                "--native-results",
                str(args.native_results),
                "--library",
                str(args.library),
                "--operation",
                operation,
            ]
            if gpu:
                command.extend(["--gpu", gpu])
            value = subprocess.check_output(
                command,
                text=True,
                cwd=ROOT,
                env={
                    **os.environ,
                    "GRAPHMINE_NATIVE_LIBRARY": str(args.library.resolve()),
                },
                timeout=200,
            )
            rows.append(json.loads(value))
            print(operation, gpu or "cpu", rows[-1]["total_seconds"], flush=True)
    assert before == {str(p): sha(p) for p in files}, (
        "Application changed during scale run"
    )
    report = {
        "scope": "Authenticated HTTP API in a fresh in-process server per case; native child workers; full input, result and page retrieval; no LLM latency included; reference values already checked independently by validate_native_scale.py",
        "passed": len(rows),
        "failed": 0,
        "runs": rows,
        "source_and_binary_files": before,
        "sources_unchanged_during_run": True,
        "memory_note": "Linux getrusage high-water RSS, separately for API process and largest completed child. GPU memory samples are in scale.json. Timings include source/dependency evidence checks and concurrent local model residency.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
