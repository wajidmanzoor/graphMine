"""Offline evidence rechecks and paired development-workflow comparisons."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from ..catalog import Catalog
from ..history import HistoryStore
from ..models import utc_now
from .catalog_replay import (
    DIMENSIONS,
    MAX_REPORT_BYTES,
    VERSION,
    grade_capture,
    source_bindings,
    summarize_report,
)
from .catalog_suite import digest, load_suite


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, f"Duplicate JSON field: {key}")
        value[key] = item
    return value


def _constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def _has_fixture_marker(value):
    if isinstance(value, dict):
        return any(
            (
                key in {"test_double", "cpu_reference_fixture", "browser_test"}
                and bool(item)
            )
            or _has_fixture_marker(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_fixture_marker(item) for item in value)
    return False


def regrade_report(catalog, suite, report):
    """Validate coverage/evidence identities and ignore every saved grade."""
    _require(
        isinstance(report, dict) and report.get("version") == VERSION,
        "Unknown workflow report version",
    )
    _require(
        report.get("suite_sha256") == digest(suite),
        "Report belongs to a different suite",
    )
    _require(
        report.get("catalog_sha256") == suite["catalog_sha256"],
        "Report catalog binding differs",
    )
    _require(
        report.get("human_review") == "unreviewed"
        and report.get("training_eligible") is False
        and report.get("label_source") == suite["label_source"],
        "Development evidence cannot be relabeled as reviewed or training eligible",
    )
    _require(
        report.get("capture_kind") in {"live_agent", "cpu_fixture"},
        "Unknown capture kind",
    )
    _require(
        isinstance(report.get("profile"), dict)
        and isinstance(report.get("source_sha256"), dict),
        "Missing configuration or source bindings",
    )
    _require(
        isinstance(report.get("label"), str) and 0 < len(report["label"]) <= 100,
        "Invalid configuration label",
    )
    known = {case["id"]: case for case in suite["cases"]}
    selected = report.get("case_ids")
    _require(
        isinstance(selected, list)
        and selected
        and all(isinstance(value, str) for value in selected),
        "Missing case selection",
    )
    _require(
        len(selected) == len(set(selected)) and set(selected) <= known.keys(),
        "Duplicate or unknown selected cases",
    )
    repeats = report.get("repeats")
    _require(type(repeats) is int and 1 <= repeats <= 3, "Invalid repeat count")
    captures = report.get("captures")
    _require(
        isinstance(captures, list) and len(captures) <= len(selected) * repeats,
        "Too many or malformed trials",
    )
    graded = copy.deepcopy(report)
    seen, sessions = set(), set()
    for row in graded["captures"]:
        _require(isinstance(row, dict), "Malformed trial")
        case_id, trial = row.get("case_id"), row.get("trial")
        _require(
            isinstance(case_id, str) and case_id in selected,
            "Trial has an unknown case",
        )
        _require(
            type(trial) is int and 1 <= trial <= repeats,
            "Trial index is outside the selected repeats",
        )
        identity = (case_id, trial)
        _require(identity not in seen, "Duplicate case/trial identity")
        seen.add(identity)
        case = known[case_id]
        _require(
            row.get("case_sha256") == case["sha256"]
            and row.get("operation_id") == case["task"]["operation_id"]
            and row.get("problem_id") == case["task"]["problem_id"],
            "Trial case content or operation binding differs",
        )
        raw = {
            key: value
            for key, value in row.items()
            if key not in {"grade", "evidence_sha256"}
        }
        _require(
            row.get("evidence_sha256") == digest(raw), "Trial evidence hash mismatch"
        )
        session = row.get("session_id")
        _require(
            isinstance(session, str) and session and session not in sessions,
            "Trials must have distinct session identities",
        )
        sessions.add(session)
        latency = row.get("latency_seconds")
        _require(
            type(latency) in {int, float} and math.isfinite(latency) and latency >= 0,
            "Invalid trial duration",
        )
        providers = row.get("model_providers")
        _require(
            isinstance(providers, list)
            and all(value in {"llm", "offline_rules"} for value in providers),
            "Missing or unknown model provider evidence",
        )
        if report["capture_kind"] == "live_agent":
            _require(
                "offline_rules" not in providers and not _has_fixture_marker(raw),
                "CPU fixtures cannot be reported as live model/native evidence",
            )
        try:
            row["grade"] = grade_capture(catalog, case, row)
        except (AttributeError, KeyError, TypeError, ValueError, IndexError) as error:
            raise ValueError(f"Malformed trial {case_id}/{trial}: {error}") from error
    graded["summary"] = summarize_report(graded)
    graded["summary"]["selected_case_count"] = len(selected)
    graded["summary"]["suite_case_count"] = len(known)
    graded["summary"]["all_suite_cases_selected"] = set(selected) == known.keys()
    graded["recheck"] = {
        "at": utc_now().isoformat(),
        "checker_source_sha256": source_bindings(),
        "saved_grades_trusted": False,
        "evidence_authentication": "Content hashes detect mismatches; they do not authenticate the producer or model weights.",
        "model_inference": "not_run",
        "native_execution": "not_run",
    }
    return graded


def _load(path: Path):
    with path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    _require(len(raw) <= MAX_REPORT_BYTES, "Workflow report exceeds the 32 MiB limit")
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)


def recheck_report(settings, *, suite_path, report_path):
    catalog = Catalog(settings)
    suite = load_suite(catalog, suite_path)
    report = regrade_report(catalog, suite, _load(report_path))
    report["recheck"]["input_report_sha256"] = HistoryStore.digest(report_path)
    return report


def _paired(before, after):
    result = {
        "paired": 0,
        "improved": 0,
        "regressed": 0,
        "both_passed": 0,
        "both_failed": 0,
        "not_comparable": 0,
    }
    for first, second in zip(before, after, strict=True):
        if first is None or second is None:
            result["not_comparable"] += 1
            continue
        result["paired"] += 1
        key = (
            ("both_passed" if first else "improved")
            if second
            else ("regressed" if first else "both_failed")
        )
        result[key] += 1
    return result


def _latency(rows):
    values = sorted(row["latency_seconds"] for row in rows)
    return {
        "count": len(values),
        "p50_seconds": values[max(0, math.ceil(len(values) * 0.5) - 1)]
        if values
        else None,
        "p95_seconds": values[max(0, math.ceil(len(values) * 0.95) - 1)]
        if values
        else None,
        "scope": "Observed question-to-completion durations, including failures; no warmup or hardware normalization.",
    }


def _measurements(first, second, matched):
    comparisons = []
    for key in matched:
        before = (first[key]["grade"]["numerical"] or {}).get("measurements", {})
        after = (second[key]["grade"]["numerical"] or {}).get("measurements", {})
        if not before and not after:
            continue
        values = {}
        for name in sorted(before.keys() | after.keys()):
            a, b = before.get(name), after.get(name)
            values[name] = {
                "before": a,
                "after": b,
                "delta_after_minus_before": b - a
                if type(a) in {int, float} and type(b) in {int, float}
                else None,
            }
        comparisons.append({"case_id": key[0], "trial": key[1], "values": values})
    return comparisons


def compare_reports(settings, *, suite_path, before_path, after_path):
    before = recheck_report(settings, suite_path=suite_path, report_path=before_path)
    after = recheck_report(settings, suite_path=suite_path, report_path=after_path)
    _require(
        set(before["case_ids"]) == set(after["case_ids"])
        and before["repeats"] == after["repeats"],
        "Paired comparison requires identical case selection and repeats",
    )
    _require(
        before["capture_kind"] == after["capture_kind"],
        "CPU fixtures and live captures cannot be compared as model runs",
    )
    index = lambda report: {
        (row["case_id"], row["trial"]): row for row in report["captures"]
    }
    first, second = index(before), index(after)
    matched = sorted(first.keys() & second.keys())
    dimensions = {}
    for name in (*DIMENSIONS, "workflow_contract_passed"):
        value = lambda row, name=name: (
            row["grade"][name]
            if name == "workflow_contract_passed"
            else row["grade"]["dimensions"][name]
        )
        dimensions[name] = _paired(
            [value(first[key]) for key in matched],
            [value(second[key]) for key in matched],
        )
    changes = {}
    for category in ("profile", "source_sha256"):
        changes[category] = {
            key: {
                "before": before[category].get(key),
                "after": after[category].get(key),
            }
            for key in sorted(before[category].keys() | after[category].keys())
            if before[category].get(key) != after[category].get(key)
        }
    transitions = [
        {
            "case_id": key[0],
            "trial": key[1],
            "operation_id": first[key]["operation_id"],
            "before_passed": first[key]["grade"]["workflow_contract_passed"],
            "after_passed": second[key]["grade"]["workflow_contract_passed"],
            "after_issues": second[key]["grade"]["issues"],
        }
        for key in matched
        if first[key]["grade"]["workflow_contract_passed"]
        != second[key]["grade"]["workflow_contract_passed"]
    ]
    return {
        "version": "current-catalog-comparison-v1",
        "created_at": utc_now().isoformat(),
        "suite_sha256": before["suite_sha256"],
        "capture_kind": before["capture_kind"],
        "scope": "Paired unreviewed development contracts, not held-out accuracy or an isolated adapter effect. Declared model weights and precision are not verified by this harness.",
        "human_review": "unreviewed",
        "training_eligible": False,
        "before": {
            "label": before["label"],
            "sha256": HistoryStore.digest(before_path),
            "summary": before["summary"],
            "latency": _latency(before["captures"]),
        },
        "after": {
            "label": after["label"],
            "sha256": HistoryStore.digest(after_path),
            "summary": after["summary"],
            "latency": _latency(after["captures"]),
        },
        "complete": before["summary"]["complete"] and after["summary"]["complete"],
        "expected_pairs": len(before["case_ids"]) * before["repeats"],
        "matched_pairs": len(matched),
        "unmatched_before": [list(key) for key in sorted(first.keys() - second.keys())],
        "unmatched_after": [list(key) for key in sorted(second.keys() - first.keys())],
        "dimensions": dimensions,
        "changed_outcomes": transitions,
        "numerical_measurements": _measurements(first, second, matched),
        "changed_bindings": changes,
        "checker_source_sha256": source_bindings(),
        "model_inference": "not_run",
        "native_execution": "not_run",
    }


def write_new_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
