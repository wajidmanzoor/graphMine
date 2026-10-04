from __future__ import annotations

from copy import deepcopy

import pytest
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.adapter_workflow_review import complete_rows, review
from graphmine_agent.learning.corpus import digest


def application_report(history):
    cases = [{"id": "scope", "steps": [{"query": "Use 2026"}, {"query": "Use 2025"}]}]
    return {
        "mode": "test",
        "cases": cases,
        "cases_sha256": digest(cases),
        "repeats": 1,
        "finished_at": "2026-10-03T20:00:00Z",
        "passed": 1,
        "total": 2,
        "workflows_passed": 0,
        "trials": [
            {
                "id": "scope",
                "repetition": 1,
                "expected_steps": 2,
                "history_path": str(history),
                "steps": [
                    {
                        "index": 1,
                        "query": "Use 2026",
                        "passed": True,
                        "issues": [],
                        "elapsed_seconds": 2,
                        "turn_id": "turn-a",
                    },
                    {
                        "index": 2,
                        "query": "Use 2025",
                        "passed": False,
                        "issues": ["wrong year"],
                        "elapsed_seconds": 4,
                        "turn_id": "turn-b",
                    },
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "defect",
    [
        "unfinished",
        "missing_step",
        "wrong_query",
        "duplicate_trial",
        "changed_case",
        "wrong_total",
        "grade_conflict",
    ],
)
def test_partial_or_inconsistent_application_reports_cannot_be_summarized(
    tmp_path, defect
):
    report = application_report(tmp_path)
    if defect == "unfinished":
        report["finished_at"] = None
    elif defect == "missing_step":
        report["trials"][0]["steps"].pop()
    elif defect == "wrong_query":
        report["trials"][0]["steps"][0]["query"] = "A different question"
    elif defect == "duplicate_trial":
        report["trials"].append(deepcopy(report["trials"][0]))
    elif defect == "changed_case":
        report["cases"][0]["steps"][0]["query"] = "Changed contract"
    elif defect == "wrong_total":
        report["passed"] = 2
    elif defect == "grade_conflict":
        report["trials"][0]["steps"][1]["passed"] = True
    with pytest.raises(ValueError):
        complete_rows(report)


def test_screened_real_questions_use_the_reviewed_query_sequence(tmp_path):
    report = application_report(tmp_path)
    case = report["cases"][0]
    case["queries"] = ["Use 2026", "Use 2025"]
    case["steps"] = [{"query": "original task one"}, {"query": "original task two"}]
    report["cases_sha256"] = digest(report["cases"])
    report["trials"][0]["case_id"] = report["trials"][0].pop("id")
    assert len(complete_rows(report)) == 2


def prepared_run(root):
    arms = ["base_nf4", "adapter_nf4"]
    protocol = {
        "arms": arms,
        "suite_plan_sha256": "suite",
        "adapter_sha256": "adapter",
        "source_sha256": "wrapper",
        "routing_only": True,
        "route_context_budget": 16384,
        "route_completion_budget": 2400,
        "other_stages_model": "fixed",
        "llm_plan_reasoning_effort": "medium",
        "llm_analyst_reasoning_effort": "medium",
        "final_holdout": False,
        "native_gpu": "same-gpu",
        "local_route_environment": {"quantization": "same"},
    }
    HistoryStore.write(root / "protocol.json", protocol)
    HistoryStore.write(
        root / "status.json", {"phase": "completed", "completed_arms": arms}
    )
    for arm in arms:
        history = root / f"{arm}-runtime/history/session"
        report = application_report(history)
        if arm == "adapter_nf4":
            report.update(passed=2, workflows_passed=1)
            report["trials"][0]["steps"][1].update(passed=True, issues=[])
        else:
            HistoryStore.write(
                history / "events/request.json",
                {
                    "type": "llm.request",
                    "turn_id": "turn-b",
                    "data": {
                        "request": {"response_schema": {"title": "RouteDecision"}}
                    },
                },
            )
        HistoryStore.write(root / f"{arm}.json", report)
    return protocol


def test_complete_pair_preserves_grades_and_records_failure_stage_evidence(tmp_path):
    root = tmp_path / "run"
    prepared_run(root)
    output = tmp_path / "comparison.json"
    result = review([root], output)
    assert result["paired_nf4"] == {"both_pass": 1, "improved": 1}
    assert result["improvements"] == [["scope", 1, 2]]
    assert not result["regressions"]
    assert result["by_arm"]["base_nf4"]["failures"][0]["stages"][
        "routing_call_recorded"
    ]
    assert result["by_arm"]["adapter_nf4"]["passed"] == 2
    assert result["by_arm"]["base_nf4"]["median_turn_seconds"] == 3
    with pytest.raises(ValueError, match="Preserve"):
        review([root], output)


def test_running_parent_is_rejected_even_if_arm_reports_look_complete(tmp_path):
    root = tmp_path / "run"
    prepared_run(root)
    HistoryStore.write(
        root / "status.json", {"phase": "evaluating", "completed_arms": ["base_nf4"]}
    )
    with pytest.raises(ValueError, match="Every requested arm"):
        review([root], tmp_path / "comparison.json")


def test_changed_inference_contract_cannot_be_presented_as_a_matched_pair(tmp_path):
    roots = [tmp_path / "base", tmp_path / "adapter"]
    for root, arm in zip(roots, ["base_nf4", "adapter_nf4"], strict=True):
        protocol = prepared_run(root)
        protocol["arms"] = [arm]
        if arm == "adapter_nf4":
            protocol["other_stages_model"] = "a different planning model"
        HistoryStore.write(root / "protocol.json", protocol)
        HistoryStore.write(
            root / "status.json", {"phase": "completed", "completed_arms": [arm]}
        )
    with pytest.raises(ValueError, match="different case or inference contracts"):
        review(roots, tmp_path / "comparison.json")
