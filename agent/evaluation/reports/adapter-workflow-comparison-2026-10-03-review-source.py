"""Summarize complete matched application runs without changing their grades."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from ..history import HistoryStore
from ..models import utc_now
from .corpus import digest


def complete_rows(report):
    if not report.get("finished_at"):
        raise ValueError("Application report is unfinished")
    cases = {case["id"]: case for case in report["cases"]}
    if (
        not cases
        or len(cases) != len(report["cases"])
        or any(not case["steps"] for case in cases.values())
    ):
        raise ValueError("Expected distinct, nonempty workflow cases")
    if report["cases_sha256"] != digest(report["cases"]):
        raise ValueError("Application case manifest changed")
    repeats = report["repeats"]
    if not isinstance(repeats, int) or not 1 <= repeats <= 3:
        raise ValueError("Invalid workflow repeat count")
    expected = {
        (case_id, repetition, index)
        for case_id, case in cases.items()
        for repetition in range(1, repeats + 1)
        for index in range(1, len(case["steps"]) + 1)
    }
    rows, trials_seen, workflows_passed = {}, set(), 0
    for trial in report["trials"]:
        case_id = trial.get("case_id", trial.get("id"))
        repetition = trial["repetition"]
        trial_key = (case_id, repetition)
        if case_id not in cases or trial_key in trials_seen:
            raise ValueError("Unknown or duplicate workflow trial")
        trials_seen.add(trial_key)
        case = cases[case_id]
        queries = (
            case["queries"]
            if "queries" in case
            else [step["query"] for step in case["steps"]]
        )
        if len(queries) != len(case["steps"]):
            raise ValueError("Missing workflow questions")
        if trial["expected_steps"] != len(queries) or len(trial["steps"]) != len(
            queries
        ):
            raise ValueError("Incomplete workflow trial")
        for step in trial["steps"]:
            key = (case_id, repetition, step["index"])
            if key not in expected or key in rows:
                raise ValueError("Unknown or duplicate workflow turn")
            if step["query"] != queries[step["index"] - 1]:
                raise ValueError("Workflow question differs from its case contract")
            if not isinstance(step["passed"], bool) or step["passed"] != (
                not step["issues"]
            ):
                raise ValueError("Step grade and issues disagree")
            seconds = step["elapsed_seconds"]
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError("Invalid recorded turn duration")
            rows[key] = {**step, "history_path": trial["history_path"]}
        workflows_passed += all(step["passed"] for step in trial["steps"])
    if set(rows) != expected or len(trials_seen) != len(cases) * repeats:
        raise ValueError("Application report does not cover every expected turn")
    if (
        report["total"] != len(rows)
        or report.get("expected_total", len(rows)) != len(rows)
        or report["passed"] != sum(row["passed"] for row in rows.values())
        or report["workflows_passed"] != workflows_passed
    ):
        raise ValueError("Application totals disagree with the complete trials")
    return rows


def stage_evidence(root, arm, row):
    history = Path(row["history_path"]).resolve()
    allowed = (root / f"{arm}-runtime" / "history").resolve()
    if not history.is_relative_to(allowed):
        raise ValueError("Workflow history escaped its isolated arm store")
    requests = []
    for path in sorted((history / "events").glob("*.json")):
        event = json.loads(path.read_text())
        if event.get("turn_id") != row["turn_id"] or event["type"] != "llm.request":
            continue
        request = event["data"]["request"]
        schema = request.get("response_format", {}).get("json_schema", {}).get("name")
        schema = schema or request.get("response_schema", {}).get("title")
        requests.append(
            {"path": str(path), "sha256": HistoryStore.digest(path), "schema": schema}
        )
    return {
        "requests": requests,
        "routing_call_recorded": any(
            row["schema"] == "RouteDecision" for row in requests
        ),
        "note": "Stage participation is evidence for investigation, not automatic attribution of the failure to that stage. Empty history is missing evidence.",
    }


def review(roots, output):
    if output.exists():
        raise ValueError("Preserve earlier application comparison reports")
    arms, baseline, reports, protocols, evidence = {}, None, {}, {}, {}
    for root in roots:
        status = json.loads((root / "status.json").read_text())
        protocol = json.loads((root / "protocol.json").read_text())
        if (
            status["phase"] != "completed"
            or status["completed_arms"] != protocol["arms"]
        ):
            raise ValueError("Every requested arm must finish before review")
        for arm in protocol["arms"]:
            if arm in arms:
                raise ValueError("Duplicate application arm")
            path = root / f"{arm}.json"
            report = json.loads(path.read_text())
            rows = complete_rows(report)
            contract = {
                "wrapper_source_sha256": protocol["source_sha256"],
                **{
                    name: report.get(name)
                    for name in (
                        "mode",
                        "corpus_sha256",
                        "cases_sha256",
                        "repeats",
                        "source_sha256",
                        "protocol_sha256",
                        "replay_contract_sha256",
                        "inference_profile",
                    )
                },
                **{
                    name: protocol[name]
                    for name in (
                        "suite_plan_sha256",
                        "adapter_sha256",
                        "routing_only",
                        "route_context_budget",
                        "route_completion_budget",
                        "other_stages_model",
                        "llm_plan_reasoning_effort",
                        "llm_analyst_reasoning_effort",
                        "final_holdout",
                    )
                },
            }
            if baseline is not None and contract != baseline:
                raise ValueError(
                    "Application arms have different case or inference contracts"
                )
            baseline = contract
            arms[arm] = rows
            protocols[arm] = protocol
            failures = []
            for identity, row in rows.items():
                if not row["passed"]:
                    failures.append(
                        {
                            "identity": list(identity),
                            "query": row["query"],
                            "issues": row["issues"],
                            "turn_id": row["turn_id"],
                            "stages": stage_evidence(root, arm, row),
                        }
                    )
            reports[arm] = {
                "passed": report["passed"],
                "total": report["total"],
                "workflows_passed": report["workflows_passed"],
                "workflows_total": len(report["cases"]) * report["repeats"],
                "median_turn_seconds": statistics.median(
                    row["elapsed_seconds"] for row in rows.values()
                ),
                "maximum_turn_seconds": max(
                    row["elapsed_seconds"] for row in rows.values()
                ),
                "recorded_route_completion_budget": (
                    report.get("inference_profile", {}).get("llm_route_max_tokens")
                    if arm == "serving_fp8"
                    else protocol["route_completion_budget"]
                ),
                "failures": failures,
            }
            for item in [path, root / "protocol.json", root / "status.json"]:
                evidence[str(item.resolve())] = HistoryStore.digest(item)
    if not {"base_nf4", "adapter_nf4"}.issubset(arms):
        raise ValueError("A complete matched local pair is required")
    if protocols["base_nf4"]["native_gpu"] != protocols["adapter_nf4"]["native_gpu"]:
        raise ValueError("Matched local arms used different native GPUs")
    if protocols["base_nf4"].get("local_route_environment") != protocols[
        "adapter_nf4"
    ].get("local_route_environment"):
        raise ValueError("Matched local routing environments differ")
    paired, improvements, regressions = Counter(), [], []
    for identity, original in arms["base_nf4"].items():
        updated = arms["adapter_nf4"][identity]
        label = (
            "both_pass"
            if original["passed"] and updated["passed"]
            else "improved"
            if updated["passed"]
            else "regressed"
            if original["passed"]
            else "both_fail"
        )
        paired[label] += 1
        if label == "improved":
            improvements.append(list(identity))
        elif label == "regressed":
            regressions.append(list(identity))
    result = {
        "version": "adapter-application-comparison-v1",
        "created_at": utc_now().isoformat(),
        "complete": True,
        "contract": baseline,
        "by_arm": reports,
        "paired_nf4": dict(paired),
        "improvements": improvements,
        "regressions": regressions,
        "protocols": protocols,
        "evidence_sha256": evidence,
        "review_source_sha256": HistoryStore.digest(Path(__file__)),
        "caution": "Preserves the original workflow grades; no regeneration or post-hoc regrading. Stage participation alone does not establish causality. Turn times include every model stage and native work; the serving FP8 reference can have different GPU sharing and precision. A development comparison does not establish untouched general accuracy or novice usability.",
        "deployment_changed": False,
    }
    snapshot = output.with_name(output.stem + "-review-source.py")
    if snapshot.exists():
        raise ValueError("Preserve earlier review-source snapshot")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(Path(__file__).read_bytes())
    result["review_source_snapshot"] = str(snapshot.resolve())
    HistoryStore.write(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = review(args.results, args.output)
    print(json.dumps({"by_arm": result["by_arm"], "paired_nf4": result["paired_nf4"]}))


if __name__ == "__main__":
    main()
