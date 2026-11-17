"""The baseline must measure failures honestly without changing product behavior."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lane_baseline", ROOT / "tools/evaluate_lane_baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def test_frozen_cases_cover_the_nine_lanes_and_actual_graphs():
    suite, graphs = baseline.load_suite(baseline.SUITE)
    assert len(suite["cases"]) == 60
    assert {case["expected"]["lane"] for case in suite["cases"]} == baseline.LANES
    assert len(graphs["demo"]["vertices"]) == 8
    assert len(graphs["demo"]["edges"]) == 10
    assert len(graphs["yelp"]["vertices"]) == 20
    assert len(graphs["yelp"]["edges"]) == 69
    assert graphs["yelp"]["graph"]["directed"] is True
    assert graphs["yelp_undirected"]["graph"]["directed"] is False
    assert "side" not in graphs["yelp"]["vertices"][0]["attributes"]
    assert {vertex["attributes"]["side"] for vertex in graphs["yelp_undirected"]["vertices"]} == {"left", "right"}
    for case in suite["cases"]:
        if case.get("reference"):
            assert case["checks"]
        if case.get("previous"):
            assert case["previous_checks"]


def test_changed_fixture_is_rejected_before_model_use(tmp_path):
    suite, _ = baseline.load_suite(baseline.SUITE)
    for fixture in suite["fixtures"].values():
        fixture["path"] = "graph.json"
    (tmp_path / "graph.json").write_text("{}")
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(suite))
    with pytest.raises(ValueError, match="Fixture changed"):
        baseline.load_suite(path)


def test_measurements_include_answer_calls_and_do_not_capture_prompts():
    measured = baseline.Measurements()
    for stage in ("route", "plan", "answer"):
        measured.model_call("session", stage=stage, request={"model": "local", "messages": ["private prompt"]},
                            response={"usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}},
                            output={"intent": "calculate", "operations": ["triangle-counting"]}, outcome="ok", seconds=1)
    rows = measured.calls["session"]
    assert baseline.usage_totals(rows) == {
        "model_calls": 3, "model_samples": 3, "by_stage": {"route": 1, "plan": 1, "answer": 1},
        "tokens": {"prompt_tokens": 60, "completion_tokens": 15, "total_tokens": 75},
        "known_tokens": {"prompt_tokens": 60, "completion_tokens": 15, "total_tokens": 75},
        "calls_missing_usage": 0}
    assert "private prompt" not in json.dumps(rows)


def test_parallel_choices_count_samples_separately_from_http_requests():
    measured = baseline.Measurements()
    measured.model_call("session", stage="candidates", request={"model": "local", "n": 5},
                        response={"usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}},
                        output=[], outcome="ok", seconds=1)
    usage = baseline.usage_totals(measured.calls["session"])
    assert usage["model_calls"] == 1 and usage["model_samples"] == 5
    assert usage["tokens"]["total_tokens"] == 50


def test_high_calibration_counts_wrong_parameters_and_low_likelihood_honestly(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from calibrate_option_scores import fit
    suite = {"cases": [{"id": str(i), "expected": {"operations": [["k-core"]]},
                        "reference": {"parameters": {"requested_k": 3}}} for i in range(7)]}
    def result(index, k):
        return {"id": str(index), "response": {"options": [{"id": "option_1", "operations": ["k-core"], "parameters": {"requested_k": k},
            "score": .9, "match_evidence": {"votes": 5, "operation_logprobs": [{}] * 5, "missing_parameters": []}}]}}
    report = {"model": "test", "server": "http://test", "catalog_sha256": "test", "cases": [result(i, 3 if i < 6 else 4) for i in range(7)]}
    fitted = fit(report, suite)
    assert fitted["high"]["precision"] == 6 / 7 and fitted["high"]["threshold"] == .9
    report["cases"][5] = result(5, 4)
    assert fit(report, suite)["high"]["threshold"] > 1  # No misleading High band.
    report["cases"][5] = result(5, 3)
    for case in report["cases"]:
        case["response"]["options"][0]["match_evidence"]["operation_logprobs"] = []
    assert fit(report, suite)["high"]["count"] == 0


def test_failed_call_with_unknown_usage_is_not_reported_as_zero_tokens():
    rows = [{"stage": "route", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
            {"stage": "plan", "usage": None, "outcome": "planner_timeout"}]
    result = baseline.usage_totals(rows)
    assert result["model_calls"] == 2
    assert result["calls_missing_usage"] == 1
    assert result["tokens"]["total_tokens"] is None
    assert result["known_tokens"]["total_tokens"] == 12
    assert baseline.usage_totals([])["tokens"]["total_tokens"] == 0


@pytest.mark.parametrize("expected_lane", ["lookup", "options", "describe_input"])
def test_calculation_cannot_masquerade_as_a_missing_lane(expected_lane):
    case = {"expected": {"lane": expected_lane, "operations": [["triangle-counting"]], "property": "edges_count", "value": 3},
            "checks": [{"operation": "triangle-counting", "port": "count", "kind": "equal", "value": 1}]}
    response = {"status": "ready", "plan": {"steps": [{"operation": "triangle-counting"}]}}
    saved = {"status": "completed", "complete": True, "steps": {"answer": {"status": "completed", "result": {
        "operation": "triangle-counting", "ports": {"count": {"complete": True, "value": 1}}}}}}
    result = baseline.grade(case, response, [], saved)
    assert result["lane_chosen"] == "calculate"
    assert result["execution_completed"] and result["result_checks"][0]["passed"]
    assert not result["success"]


def test_rejected_selection_is_a_measured_failure_with_no_invented_model_call():
    case = {"expected": {"lane": "calculate", "operations": [["triangle-counting"]]}}
    result = baseline.grade(case, {}, [], error={"type": "ValidationError"})
    assert result["lane_chosen"] == "unclassified"
    assert not result["success"]
    assert baseline.usage_totals([])["model_calls"] == 0


def test_grounding_measurement_uses_current_tool_events_not_the_checked_flag():
    from types import SimpleNamespace
    source = {'id': 'f1', 'kind': 'fact', 'ref': 'input:loaded', 'text': 'Ann has 3 connections.', 'turn_id': 'now', 'tool': 'input'}
    response = {'turn_id': 'now', 'answer': {'text': source['text'],
        'citations': [{key: source[key] for key in ('id', 'kind', 'ref')}], 'grounding': {'checked': True}}}
    event = SimpleNamespace(type='workflow.evidence', payload={'turn_id': 'now', 'sources': [source]})
    assert baseline.check_grounding(response, [event], 'describe_input')['passed']
    assert not baseline.check_grounding(response, [], 'describe_input')['passed']
    response['answer']['text'] = 'Bob has 3 connections.'
    assert not baseline.check_grounding(response, [event], 'describe_input')['passed']


def test_explanation_needs_the_requested_saved_fact():
    case = {"expected": {"lane": "explain", "operations": [[]], "fact_patterns": [r"\b33 bicliques\b"]}}
    response = {"status": "answered", "answer": {"workflow_id": "saved", "facts": [{"statement": "Returned 33 bicliques."}]}}
    assert baseline.grade(case, response, [])["success"]
    response["answer"]["facts"] = [{"statement": "The result is exact."}]
    assert not baseline.grade(case, response, [])["success"]


@pytest.mark.parametrize("complete,values,passed", [(True, [0], True), (True, ["0"], False), (False, [0], False)])
def test_result_checks_preserve_typed_ids_and_reject_incomplete_ports(complete, values, passed):
    check = {"port": "vertices", "kind": "set", "value": [0]}
    result = {"ports": {"vertices": {"value": values, "complete": complete}}}
    assert baseline.check_port(check, result) is passed


def test_biclique_oracle_allows_orientation_but_not_missing_members():
    check = {"port": "bicliques", "kind": "bicliques", "value": [{"left_vertices": [0, 1], "right_vertices": ["0"]}]}
    result = {"ports": {"bicliques": {"complete": True, "value": [{"left_vertices": ["0"], "right_vertices": [1, 0]}]}}}
    assert baseline.check_port(check, result)
    incomplete = deepcopy(result)
    incomplete["ports"]["bicliques"]["value"][0]["right_vertices"] = [1]
    assert not baseline.check_port(check, incomplete)


def test_options_require_two_distinct_choices_without_execution():
    case = {"expected": {"lane": "options", "operations": [["maximal-cliques"]]}}
    response = {"status": "options", "options": [
        {"operation": "maximal-cliques", "parameters": {}},
        {"operation": "maximum-clique", "parameters": {}}]}
    assert baseline.grade(case, response, [])["success"]
    response["options"][1] = deepcopy(response["options"][0])
    assert not baseline.grade(case, response, [])["success"]
