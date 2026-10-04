"""Review frozen routing outputs without regenerating or changing model weights.

Temporal-only fields have no effect on static operations, and a bounded read-only
inspection is a request for another routing stage, not a wrong computation.
Behavior uses the production blocker, where capability limitations outrank input
requests. Optional, hash-bound label audits produce a separate third score set.
Original scores, unmodified labels, and all review changes remain visible.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..models import RouteDecision, utc_now
from ..planning import resolve_route_scope, route_blocker
from .adapter_eval import read_suite, score_generation, semantic_intent, summarize
from .corpus import digest

VERSION = "routing-application-review-v2"
TEMPORAL_FIELDS = {"pattern_vertex_count", "pattern_edges", "time_unit", "time_window"}


def review_generation(case, result, catalog):
    strict = score_generation(case, result, catalog)
    review = deepcopy(strict)
    review["ignored_differences"] = []
    if not strict.get("decision"):
        return strict, review
    expected = RouteDecision.model_validate(case["expected"])
    temporal = expected.problem_id == "temporal_motif_mining"
    ignored = []
    for issue in review["issues"]:
        field = issue.partition(":")[0]
        if (
            not temporal and field in TEMPORAL_FIELDS
        ) or issue == "unnecessary inspection on a complete routing fixture":
            ignored.append(issue)
    review["issues"] = [issue for issue in review["issues"] if issue not in ignored]
    review["ignored_differences"] = ignored
    review["inspection_requested"] = bool(strict["decision"]["inspections"])
    # Scope resolution still comes from the application's actual implementation.
    from ..models import ApplicationIntent

    active = case["payload"].get("active_constraints")
    previous = ApplicationIntent.model_validate(active) if active else None
    decision = resolve_route_scope(
        catalog, RouteDecision.model_validate(strict["decision"]), previous
    )
    blocker = route_blocker(catalog, decision)
    behavior = (
        "execute"
        if blocker is None
        else "clarify"
        if blocker[0] == "needs_information"
        else "unsupported"
    )
    review["original_behavior"] = strict["behavior"]
    review["behavior"] = behavior
    review["behavior_correct"] = behavior == case["behavior"]
    review["unsafe_execution"] = behavior == "execute" and case["behavior"] != "execute"
    review["application_blocker"] = list(blocker) if blocker else None
    review["issues"] = [
        issue for issue in review["issues"] if not issue.startswith("behavior:")
    ]
    if not review["behavior_correct"]:
        review["issues"].append(
            f"behavior: expected {case['behavior']}, got {behavior}"
        )
    review["passed"] = not review["issues"]
    unit = case["payload"]["graph_context"].get("timestamp_unit")
    actual = semantic_intent(decision.intent, unit)
    target = semantic_intent(expected.intent, unit)
    fields = set(target) if temporal else set(target) - TEMPORAL_FIELDS
    review["semantic_requirements_correct"] = all(
        actual[k] == target[k] for k in fields
    )
    return strict, review


def audited_cases(suite, cases, path):
    """Bind explicit behavior-label corrections to immutable input evidence."""
    audit = json.loads(path.read_text())
    if audit["suite_plan_sha256"] != HistoryStore.digest(suite / "plan.json"):
        raise ValueError("Label audit belongs to a different suite")
    by_id = {case["id"]: case for case in cases}
    changes = {}
    for correction in audit["corrections"]:
        case_id = correction["id"]
        if case_id not in by_id or case_id in changes:
            raise ValueError("Unknown or duplicate label-audit case")
        case = by_id[case_id]
        if correction["case_sha256"] != digest(case):
            raise ValueError("Audited case inputs changed")
        if correction["original_behavior"] != case["behavior"]:
            raise ValueError("Label audit does not match the original behavior")
        behavior = correction["reviewed_behavior"]
        if behavior not in {"execute", "clarify", "unsupported"}:
            raise ValueError("Unknown reviewed behavior")
        if not correction["reason"].strip():
            raise ValueError("Every label correction needs an evidence-based reason")
        changes[case_id] = {**case, "behavior": behavior}
    return audit, changes


def review(suite: Path, results: list[Path], output: Path, *, label_audit=None):
    if output.exists():
        raise ValueError("Use a new review path; preserve prior reports")
    plan, cases, _ = read_suite(suite)
    catalog = Catalog(Settings.from_env())
    originals, reviewed, arms, evidence = [], [], [], {}
    audited = []
    audit, changes = (
        audited_cases(suite, cases, label_audit) if label_audit else (None, {})
    )
    for root in results:
        status = json.loads((root / "status.json").read_text())
        contract = json.loads((root / "contract.json").read_text())
        if status["phase"] != "completed":
            raise ValueError(f"Comparison is not complete: {root}")
        if contract["plan_sha256"] != HistoryStore.digest(suite / "plan.json"):
            raise ValueError("Comparisons must use the identical suite")
        for arm in contract["arms"]:
            if arm in arms:
                raise ValueError("Duplicate comparison arm")
            arms.append(arm)
            for case in cases:
                path = root / "calls" / f"{case['id']}--{arm}.json"
                row = json.loads(path.read_text())
                if (
                    row["id"] != case["id"]
                    or row["arm"] != arm
                    or row["case_sha256"] != digest(case)
                ):
                    raise ValueError("Saved response identity or case hash mismatch")
                strict, corrected = review_generation(case, row, catalog)
                originals.append({**row, "score": strict})
                reviewed.append({**row, "score": corrected})
                if audit is not None:
                    audited_case = changes.get(case["id"], case)
                    _, audited_score = review_generation(audited_case, row, catalog)
                    audited_score["label_changed"] = case["id"] in changes
                    audited.append(
                        {
                            **row,
                            "behavior": audited_case["behavior"],
                            "score": audited_score,
                        }
                    )
                evidence[str(path.resolve())] = HistoryStore.digest(path)
    report = {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "suite_plan_sha256": HistoryStore.digest(suite / "plan.json"),
        "review_source_sha256": HistoryStore.digest(Path(__file__)),
        "split": plan["split"],
        "cases_per_arm": len(cases),
        "strict_summary": summarize(originals, len(cases), arms),
        "application_review_summary": summarize(reviewed, len(cases), arms),
        "grading_changes": [
            "Non-temporal operations ignore temporal pattern/window fields in application_capability_errors and planning; redundant descriptions are tracked separately.",
            "A bounded inspection is allowed by the production prompt; record it without claiming the complete follow-up succeeded.",
            "Effective behavior uses production route_blocker, including capability-before-input priority and missing operation identity; no gold operation fallback.",
        ],
        "caution": "Grading corrections were defined after inspecting early test outputs. Original scores and raw outputs are preserved. This is not an untouched final benchmark or complete-agent validation.",
        "limitations": plan["limitations"],
        "reviewed_cases": [{k: r[k] for k in ("id", "arm", "score")} for r in reviewed],
        "raw_evidence_sha256": evidence,
        "deployed": False,
    }
    if audit is not None:
        report.update(
            label_audit=audit,
            label_audit_sha256=HistoryStore.digest(label_audit),
            audited_summary=summarize(audited, len(cases), arms),
            audited_cases=[
                {k: row[k] for k in ("id", "arm", "behavior", "score")}
                for row in audited
            ],
        )
    snapshot = output.with_name(output.stem + "-review-source.py")
    if snapshot.exists():
        raise ValueError("Preserve the existing review-source snapshot")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(Path(__file__).read_bytes())
    report["review_source_snapshot"] = str(snapshot.resolve())
    HistoryStore.write(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-audit", type=Path)
    args = parser.parse_args()
    report = review(args.suite, args.results, args.output, label_audit=args.label_audit)
    print(
        json.dumps(report.get("audited_summary", report["application_review_summary"]))
    )


if __name__ == "__main__":
    main()
