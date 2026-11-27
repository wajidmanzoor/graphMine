#!/usr/bin/env python3
"""Inventory W1–W24 live prerequisites without sending model requests.

Exit 2 means live measurement is blocked. This preflight does not replace the
author's run_tento.py or its quality scorers.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
METRICS = {
    "W1": "Review sentiment accuracy", "W2": "Genre accuracy",
    "W3": "One minus relative error of negative-review counts",
    "W4": "Precision against reference-model athlete judgments",
    "W5": "Mean genre and reference-year accuracy", "W6": None,
    "W7": "Negative-review precision at five", "W8": "Pairwise movie-ranking accuracy",
    "W9": "MPAA rating-set F1", "W10": "Airport-country pair F1",
    "W11": "Negative-review ID F1", "W12": "End-airport F1 against reference model",
    "W13": "Reachable-airport F1", "W14": "Route F1", "W15": "Reply-path state F1",
    "W16": "Friendship-structure predicate accuracy", "W17": None,
    "W18": "Airport-country accuracy", "W19": None, "W20": None,
    "W21": "Company country and central-member accuracy", "W22": "Description-image pair F1",
    "W23": "Image-pair F1", "W24": None,
}
TRUTH = {
    "W1": ["export/review.csv"], "W2": ["export/movie.csv"],
    "W3": ["export/review.csv", "export/movie.csv", "export/person.csv", "export/worked_on.csv"],
    "W4": ["reference/W4.json"], "W5": ["export/movie.csv", "reference/W5_year.json"],
    "W7": ["export/review.csv"], "W8": ["export/review.csv", "export/movie.csv", "export/person.csv", "export/worked_on.csv"],
    "W10": ["export/airport.csv"], "W11": ["export/review.csv"], "W12": ["reference/W12.json"],
    "W13": ["export/airport.csv", "export/flight.csv"], "W14": ["export/flight.csv"],
    "W15": ["export/ldbc_w15_truth.csv"], "W16": ["export/ldbc_knows.csv"],
    "W18": ["export/airport.csv"], "W21": ["export/ldbc_w21_truth.csv"],
}


def declarations(path):
    # Read metadata without importing the scorer (which loads external truth)
    # or the workload's generated queries and native runner.
    tree = ast.parse(path.read_text())
    return {node.targets[0].id: node.value for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}


def fields(node):
    return {ast.literal_eval(key): value for key, value in zip(node.keys, node.values) if key is not None}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(path):
    return path.is_file() and path.stat().st_size > 0


def inventory(source, data_root, model_id):
    paper = source / "ladybug/scripts/paper"
    declared = declarations(paper / "workload.py")
    workload, models = fields(declared["WORKLOAD"]), fields(declared["MODELS"])
    lock = json.loads((ROOT / "agent/graphmine_agent/semantic_engine.lock.json").read_text())
    # Clearing a future lock cannot silently activate an unverified runner.
    blockers = [*lock["live_blockers"], *lock["integration_blockers"],
                "verified_local_qwen_runner_adapter_required", "live_planner_admission_unverified"]
    model_ids = {name: ast.literal_eval(fields(value)["model"]) for name, value in models.items()}
    target_aliases = [name for name, value in model_ids.items() if value == model_id]
    if not target_aliases:
        blockers.append("local_model_missing_from_paper_runner")
    records = []
    for number in range(1, 25):
        name = f"W{number}"
        spec = fields(workload[name])
        database = ast.literal_eval(spec["db"])
        db_path = data_root / "demo" / database
        missing = [] if present(db_path) else [str(db_path)]
        truth_paths = [data_root / "paper_eval" / path for path in TRUTH.get(name, [])]
        if name in {"W22", "W23"}:
            truth_paths.append(data_root / "ecomm_sf500/products.json")
        if name == "W24":
            truth_paths.append(data_root / "vg100/gt.json")
        missing_truth = [str(path) for path in truth_paths if not present(path)]
        local_blockers = list(blockers)
        if missing:
            local_blockers.append("workload_database_missing")
        if missing_truth:
            local_blockers.append("quality_reference_missing")
        if name == "W22":
            vector = source / "ladybug/extension/vector/build/libvector.lbug_extension"
            if not present(vector):
                missing.append(str(vector))
                local_blockers.append("vector_extension_missing")
        if number >= 22:
            local_blockers.extend(["image_assets_unverified", "model_image_input_unverified"])
        records.append({
            "query": name, "feature": ast.literal_eval(spec["feature"]),
            "status": "blocked", "execution_started": False, "database": database,
            "database_present": present(db_path), "missing_inputs": missing,
            "required_native_functions": ast.literal_eval(spec["needs"]) if "needs" in spec else [],
            "requires_explicit_query_selection": ast.literal_eval(spec["test"]) if "test" in spec else False,
            "blockers": local_blockers, "duration_seconds": None, "usage": None,
            "provider_requests_sent": 0, "effective_settings": None,
            "requested_cache_policy": "fresh database copy; answers off" if name != "W24" else
                "fresh database copy; answers enabled within W24's multi-statement run",
            "quality": {"metric": METRICS[name], "score": None, "missing_inputs": missing_truth,
                        "status": "not_measured" if METRICS[name] else "not_scored_by_paper_systems_table",
                        "optional_metric": "Annotated-object recall (separate ablation scorer)" if name == "W24" else None},
        })
    commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": "blocked",
        "kind": "live_acceptance_prerequisites", "engine_commit": commit, "engine_lock": lock,
        "source_matches_lock": commit == lock["commit"],
        "runner": {"path": str(paper / "run_tento.py"), "sha256": digest(paper / "run_tento.py"),
                   "workload_sha256": digest(paper / "workload.py"), "quality_scorer_sha256": digest(paper / "make_eval_table.py"),
                   "target_aliases": target_aliases, "existing_model_ids": model_ids,
                   "invoked": False, "required_queries": [f"W{i}" for i in range(1, 25)]},
        "model": {"configured_id": model_id, "loaded_version": None, "verified_live": False},
        "data_root": str(data_root), "requested_settings": {"thinking": "off", "strict_json": True, "temperature": 0},
        "effective_live_settings": None, "provider_requests_sent": 0,
        "completed_workloads": 0, "failed_workloads": 0, "blocked_workloads": 24,
        "live_flow": {"status": "blocked", "input_version": None, "output_version": None, "blockers": blockers},
        "workloads": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "third_party/tento")
    parser.add_argument("--data-root", type=Path, default=Path.home() / "lbug_data")
    parser.add_argument("--model-id", required=True, help="Configured ID; does not establish the loaded model version")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.source.resolve(), args.data_root.resolve(), args.model_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Blocked: {report['blocked_workloads']}/24 workloads; 0 provider requests. Report: {args.output}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
