"""Review queues recheck evidence and never promote evaluation data to training."""

from __future__ import annotations

import copy
import socket
import subprocess

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning import failure_candidates as collector
from graphmine_agent.learning.catalog_compare import write_new_report
from graphmine_agent.learning.catalog_suite import digest
from test_catalog_compare import rehash
from test_catalog_replay import capture_fixture


@pytest.fixture
def captured(settings, catalog, tmp_path, monkeypatch):
    return capture_fixture(
        settings, catalog, tmp_path, monkeypatch, case_ids=["k-cliques--supported"]
    )


def forbidden(*args, **kwargs):
    raise AssertionError("Collection cannot run a process or connect to a model")


def test_passing_evidence_does_not_create_candidates_from_saved_failure_flags(
    settings, tmp_path, monkeypatch, captured
):
    report, _ = captured
    report["captures"][0]["grade"] = {"workflow_contract_passed": False}
    report["summary"] = {"workflow_contract_passes": 0}
    path = tmp_path / "stale-grades.json"
    write_new_report(path, report)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = collector.collect_failures(
        settings, workflow_suite=tmp_path / "suite.json", workflow_reports=[path]
    )
    assert result["candidate_count"] == 0
    assert result["sources"][0]["summary"]["workflow_contract_passes"] == 1


def test_corrupt_output_is_rechecked_deduplicated_and_kept_out_of_training(
    settings, tmp_path, monkeypatch, captured
):
    report, _ = captured
    row = report["captures"][0]
    row["outcome"]["result"]["payload"]["output"]["count"] = 999
    rehash(row)  # Preserve intentionally stale passing grades.
    first, copied = tmp_path / "first.json", tmp_path / "copied.json"
    write_new_report(first, report)
    copied.write_bytes(first.read_bytes())
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = collector.collect_failures(
        settings,
        workflow_suite=tmp_path / "suite.json",
        workflow_reports=[first, copied, first],
    )
    assert result["candidate_count"] == 1 and len(result["sources"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source_kind"] == "cpu_fixture"
    assert candidate["review_status"] == "unreviewed"
    assert (
        candidate["training_eligible"] is False and candidate["corrected_label"] is None
    )
    assert "numerical_checks" in candidate["issues"]
    assert len(candidate["evidence"]) == 1
    assert candidate["query"] == candidate["reference_task"]["question"]
    assert result["training_started"] is result["training_eligible"] is False
    assert result["model_inference"] == result["native_execution"] == "not_run"
    assert not list(tmp_path.rglob("train.jsonl"))


def test_changed_evidence_without_updated_hash_is_rejected(
    settings, tmp_path, captured
):
    report, _ = captured
    report["captures"][0]["outcome"]["response"]["message"] = "changed"
    path = tmp_path / "changed.json"
    write_new_report(path, report)
    with pytest.raises(ValueError, match="evidence hash"):
        collector.collect_failures(
            settings, workflow_suite=tmp_path / "suite.json", workflow_reports=[path]
        )


@pytest.fixture
def archived(tmp_path, monkeypatch):
    task = {"query": "Which group?", "behavior": "clarify", "operation_id": None}
    case = {
        "id": "clarification",
        "source_id": "source",
        "graph_id": "graph",
        "split": "development",
        "steps": [task, copy.deepcopy(task)],
    }
    manifest = {
        "cases": [case],
        "sources": {"source": {"title": "CPU fixture source", "split": "development"}},
    }
    corpus = tmp_path / "corpus"
    HistoryStore.write(corpus / "manifest.json", manifest)
    graph = {"graph": {"directed": False}, "vertices": [], "edges": []}
    monkeypatch.setattr(
        collector, "load_realworld", lambda path: (manifest, {"graph": graph})
    )
    cases = [dict(case, queries=["Which group?", "Which group?"])]
    report = {
        "mode": "real-world-evaluation-v3",
        "corpus_sha256": HistoryStore.digest(corpus / "manifest.json"),
        "training_started": False,
        "training_export_allowed": False,
        "cases": cases,
        "cases_sha256": digest(cases),
        "repeats": 1,
        "finished_at": "2026-10-07T00:00:00Z",
        "passed": 2,
        "total": 2,
        "workflows_passed": 1,
        "trials": [
            {
                "case_id": case["id"],
                "repetition": 1,
                "expected_steps": 2,
                "history_path": str(tmp_path / "archived-history"),
                "steps": [
                    {
                        "index": index,
                        "query": "Which group?",
                        "passed": True,
                        "issues": [],
                        "elapsed_seconds": 1,
                        "observed": {
                            "response": {
                                "planning_status": "ready",
                                "plan": {},
                                "message": "Need clique rules",
                            }
                        },
                    }
                    for index in (1, 2)
                ],
            }
        ],
    }
    path = tmp_path / "archived.json"
    HistoryStore.write(path, report)
    comparison = {
        "version": "adapter-application-comparison-v1",
        "complete": True,
        "contract": {"final_holdout": False},
        "evidence_sha256": {str(path): HistoryStore.digest(path)},
    }
    comparison_path = tmp_path / "comparison.json"
    HistoryStore.write(comparison_path, comparison)
    return corpus, comparison_path, path, manifest, report, comparison


def test_archived_failures_preserve_context_and_separate_presentation(
    settings, archived, monkeypatch
):
    corpus, comparison, path, *_ = archived
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = collector.collect_failures(
        settings, corpus=corpus, comparison=comparison, archived_reports=[path]
    )
    assert result["candidate_count"] == 4
    assert result["counts_by_kind"] == {
        "archived_workflow_contract": 2,
        "archived_presentation_compatibility": 2,
    }
    for candidate in result["candidates"]:
        assert candidate["source_kind"] == "archived_application_observation"
        assert candidate["evidence"][0]["historical_passed"] is True
        assert candidate["evidence"][0]["rechecked_issues"]
        assert candidate["training_eligible"] is False
    contracts = [
        row
        for row in result["candidates"]
        if row["kind"] == "archived_workflow_contract"
    ]
    assert sorted(len(row["conversation"]) for row in contracts) == [1, 2]


@pytest.mark.parametrize(
    "defect",
    [
        "hash",
        "corpus",
        "holdout_report",
        "holdout_case",
        "contract",
        "missing_turn",
        "duplicate_turn",
    ],
)
def test_archived_unbound_or_held_out_evidence_is_rejected(settings, archived, defect):
    corpus, comparison_path, path, _manifest, report, comparison = archived
    if defect == "hash":
        comparison["evidence_sha256"][str(path)] = "changed"
    elif defect == "corpus":
        report["corpus_sha256"] = "changed"
    elif defect == "holdout_report":
        comparison["contract"]["final_holdout"] = True
    elif defect == "holdout_case":
        report["cases"][0]["split"] = "holdout"
    elif defect == "contract":
        report["cases"][0]["source_id"] = "changed"
    elif defect == "missing_turn":
        report["trials"][0]["steps"].pop()
    elif defect == "duplicate_turn":
        report["trials"][0]["steps"][1] = copy.deepcopy(report["trials"][0]["steps"][0])
    report["cases_sha256"] = digest(report["cases"])
    HistoryStore.write(path, report)
    if defect != "hash":
        comparison["evidence_sha256"][str(path)] = HistoryStore.digest(path)
    HistoryStore.write(comparison_path, comparison)
    with pytest.raises(ValueError):
        collector.collect_failures(
            settings, corpus=corpus, comparison=comparison_path, archived_reports=[path]
        )
