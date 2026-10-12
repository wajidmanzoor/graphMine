"""Evidence corruption, incomplete-run accounting, and paired regression checks."""

from __future__ import annotations

import argparse
import copy
import json
import socket
import subprocess

import pytest
from graphmine_agent.learning import catalog_compare as compare
from graphmine_agent.learning.catalog_suite import build_suite, digest
from graphmine_agent.learning.cli import add_parser, run_learning
from test_catalog_replay import capture_fixture


def rehash(row):
    row["evidence_sha256"] = digest(
        {
            key: value
            for key, value in row.items()
            if key not in {"grade", "evidence_sha256"}
        }
    )


@pytest.fixture
def captured(settings, catalog, tmp_path, monkeypatch):
    selected = [
        case["id"]
        for case in build_suite(catalog)["cases"]
        if case["tags"] == ["supported"]
        and case["task"]["operation_id"] in {"k-cliques", "connected-components"}
    ]
    return capture_fixture(settings, catalog, tmp_path, monkeypatch, case_ids=selected)


def test_saved_grades_are_ignored_and_recheck_has_no_execution(
    settings, catalog, tmp_path, monkeypatch, captured
):
    report, suite = captured
    for row in report["captures"]:
        row["grade"] = {"workflow_contract_passed": False, "invented": True}
    report["summary"] = {"workflow_contract_passes": 10000}
    compare.write_new_report(tmp_path / "edited-grades.json", report)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Offline rechecking must not execute or open network connections"
        )

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    checked = compare.recheck_report(
        settings,
        suite_path=tmp_path / "suite.json",
        report_path=tmp_path / "edited-grades.json",
    )
    assert checked["summary"]["workflow_contract_passes"] == 2
    assert checked["summary"]["complete"] is True
    assert checked["summary"]["suite_case_count"] == 46
    assert checked["summary"]["all_suite_cases_selected"] is False
    assert checked["recheck"]["saved_grades_trusted"] is False
    assert checked["recheck"]["model_inference"] == "not_run"
    assert report["captures"][0]["grade"].get("invented") is True
    assert suite["training_eligible"] is False


@pytest.mark.parametrize(
    "change",
    [
        "evidence",
        "suite",
        "catalog",
        "case",
        "trial",
        "duplicate",
        "unknown",
        "review",
        "training",
        "selected_duplicate",
        "session",
        "latency",
        "malformed",
    ],
)
def test_invalid_report_evidence_is_rejected(catalog, captured, change):
    report, suite = captured
    row = report["captures"][0]
    if change == "evidence":
        row["outcome"]["response"]["message"] = "changed"
    elif change == "suite":
        report["suite_sha256"] = "wrong"
    elif change == "catalog":
        report["catalog_sha256"] = "wrong"
    elif change == "case":
        row["case_sha256"] = "wrong"
    elif change == "trial":
        row["trial"] = True
    elif change == "duplicate":
        report["captures"][1] = copy.deepcopy(row)
    elif change == "unknown":
        row["case_id"] = "not-selected"
    elif change == "review":
        report["human_review"] = "approved"
    elif change == "training":
        report["training_eligible"] = True
    elif change == "selected_duplicate":
        report["case_ids"].append(report["case_ids"][0])
    elif change == "session":
        row["session_id"] = report["captures"][1]["session_id"]
        rehash(row)
    elif change == "latency":
        row["latency_seconds"] = -1
        rehash(row)
    elif change == "malformed":
        row["inputs"] = []
        rehash(row)
    with pytest.raises(ValueError):
        compare.regrade_report(catalog, suite, report)


def test_removed_trials_and_unfinished_runs_do_not_become_perfect_scores(
    catalog, captured
):
    report, suite = captured
    report["captures"].pop()
    checked = compare.regrade_report(catalog, suite, report)
    assert checked["summary"]["complete"] is False
    assert checked["summary"]["missing_trials"] == 1
    assert checked["summary"]["expected_trials"] == 2
    assert checked["summary"]["workflow_contract_passes"] == 1
    report["finished_at"] = None
    report["case_ids"].pop()
    checked = compare.regrade_report(catalog, suite, report)
    assert checked["summary"]["missing_trials"] == 0
    assert checked["summary"]["complete"] is False


@pytest.mark.parametrize("hide_provider", [False, True])
def test_cpu_capture_cannot_be_relabeled_as_live(catalog, captured, hide_provider):
    report, suite = captured
    report["capture_kind"] = "live_agent"
    if hide_provider:
        for row in report["captures"]:
            row["model_providers"] = ["llm"]
            rehash(row)
    with pytest.raises(ValueError, match="CPU fixtures"):
        compare.regrade_report(catalog, suite, report)


def test_paired_comparison_regrades_reorders_and_reports_regression(
    settings, tmp_path, captured
):
    report, _ = captured
    before = tmp_path / "capture.json"
    row = next(row for row in report["captures"] if row["operation_id"] == "k-cliques")
    row["outcome"]["result"]["payload"]["output"]["count"] = 999
    rehash(row)
    report["captures"].reverse()
    report["profile"]["routing_model"] = "changed-declaration-only"
    report["label"] = "Deliberately corrupted CPU fixture"
    after = tmp_path / "corrupted.json"
    compare.write_new_report(after, report)
    result = compare.compare_reports(
        settings,
        suite_path=tmp_path / "suite.json",
        before_path=before,
        after_path=after,
    )
    assert result["complete"] is True
    assert result["matched_pairs"] == result["expected_pairs"] == 2
    assert result["dimensions"]["numerical_checks"] == {
        "paired": 2,
        "improved": 0,
        "regressed": 1,
        "both_passed": 1,
        "both_failed": 0,
        "not_comparable": 0,
    }
    assert result["dimensions"]["workflow_contract_passed"]["regressed"] == 1
    assert result["changed_outcomes"][0]["case_id"] == row["case_id"]
    assert "routing_model" in result["changed_bindings"]["profile"]
    assert result["after"]["summary"]["by_operation"]["k-cliques"]["passed"] == 0
    assert result["after"]["latency"]["count"] == 2
    assert result["training_eligible"] is False


def test_partial_comparison_preserves_missing_pairs(settings, tmp_path, captured):
    report, _ = captured
    report["captures"].pop()
    compare.write_new_report(tmp_path / "partial.json", report)
    result = compare.compare_reports(
        settings,
        suite_path=tmp_path / "suite.json",
        before_path=tmp_path / "capture.json",
        after_path=tmp_path / "partial.json",
    )
    assert result["complete"] is False
    assert result["expected_pairs"] == 2
    assert result["matched_pairs"] == 1
    assert len(result["unmatched_before"]) == 1
    assert result["after"]["summary"]["missing_trials"] == 1
    report["case_ids"].pop()
    compare.write_new_report(tmp_path / "different-selection.json", report)
    with pytest.raises(ValueError, match="identical case selection"):
        compare.compare_reports(
            settings,
            suite_path=tmp_path / "suite.json",
            before_path=tmp_path / "capture.json",
            after_path=tmp_path / "different-selection.json",
        )


def test_comparison_keeps_pagerank_error_separate_from_contract_passes(
    settings, catalog, tmp_path, monkeypatch
):
    selected = [
        case["id"]
        for case in build_suite(catalog)["cases"]
        if case["task"]["operation_id"] == "personalized-pagerank"
    ]
    report, _ = capture_fixture(
        settings, catalog, tmp_path, monkeypatch, case_ids=selected
    )
    row = report["captures"][0]
    for ranked in row["outcome"]["result"]["payload"]["output"]["ranked_vertices"]:
        ranked["score"] = 0.2
    rehash(row)
    after_path = tmp_path / "less-accurate.json"
    compare.write_new_report(after_path, report)
    result = compare.compare_reports(
        settings,
        suite_path=tmp_path / "suite.json",
        before_path=tmp_path / "capture.json",
        after_path=after_path,
    )
    assert result["dimensions"]["numerical_checks"]["both_passed"] == 1
    assert result["dimensions"]["exact_numerical"]["paired"] == 0
    measured = result["numerical_measurements"][0]["values"]
    assert (
        measured["maximum_returned_score_absolute_error"]["delta_after_minus_before"]
        > 0.2
    )
    assert measured["error_acceptance_threshold"]["after"] is None


@pytest.mark.parametrize(
    "raw", ['{"version":1,"version":2}', '{"value":NaN}', '{"value":Infinity}']
)
def test_ambiguous_json_is_rejected(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        compare._load(path)


def test_report_size_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "MAX_REPORT_BYTES", 16)
    path = tmp_path / "oversized.json"
    path.write_text(json.dumps({"text": "x" * 100}))
    with pytest.raises(ValueError, match="limit"):
        compare._load(path)


def test_cli_offline_reports_preserve_inputs_and_report_incomplete_exit(
    settings, tmp_path, captured, capsys
):
    report, _ = captured
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers())
    checked = tmp_path / "checked.json"
    args = parser.parse_args(
        [
            "learning",
            "recheck-current-catalog",
            str(tmp_path / "suite.json"),
            "--report",
            str(tmp_path / "capture.json"),
            "--output",
            str(checked),
        ]
    )
    assert run_learning(args, settings) == 0
    assert json.loads(capsys.readouterr().out)["captured_trials"] == 2
    original_bytes = checked.read_bytes()
    with pytest.raises(SystemExit, match="File exists"):
        run_learning(args, settings)
    assert checked.read_bytes() == original_bytes
    report["captures"].pop()
    compare.write_new_report(tmp_path / "partial.json", report)
    args = parser.parse_args(
        [
            "learning",
            "compare-current-catalog",
            str(tmp_path / "suite.json"),
            "--before",
            str(tmp_path / "capture.json"),
            "--after",
            str(tmp_path / "partial.json"),
            "--output",
            str(tmp_path / "comparison.json"),
        ]
    )
    assert run_learning(args, settings) == 1
    assert json.loads(capsys.readouterr().out)["complete"] is False
