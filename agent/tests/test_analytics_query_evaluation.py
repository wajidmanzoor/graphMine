"""Authored evaluation fixtures; real workers for the reference execution gate."""

from copy import deepcopy

import pytest
from graphmine_agent.learning.analytics_queries import build_suite, evaluate, grade


def test_query_bundle_is_explicitly_development_only():
    suite = build_suite()
    assert len(suite["cases"]) == 20
    assert len({case["id"] for case in suite["cases"]}) == 20
    assert "not human labels" in suite["scope"]
    assert "training authorization" in suite["scope"]
    assert sum(case["slice"] == "dependent" for case in suite["cases"]) == 10
    for case in suite["cases"]:
        assert case["expected"]
        assert len({step["operation"] for step in case["plan"]["steps"]}) == len(
            case["plan"]["steps"]
        )


@pytest.mark.asyncio
async def test_twenty_authored_cases_through_actual_application_workers(settings):
    report = await evaluate(settings)
    assert report["model_accuracy_measured"] is False
    assert report["mode"] == "reference"
    assert report["passed"] == report["total"] == 20, report
    assert report["by_slice"] == {
        "dependent": {"passed": 10, "total": 10},
        "lookup": {"passed": 10, "total": 10},
    }
    assert all(row["planning"] is None for row in report["cases"])


def grading_fixture():
    plan = {
        "steps": [
            {
                "id": "lookup",
                "operation": "node-lookup",
                "parameters": {"vertices": [0]},
                "device": "cpu",
                "input": {"input": "main"},
                "bindings": {},
            },
            {
                "id": "sub",
                "operation": "query-subgraph",
                "parameters": {},
                "device": "cpu",
                "input": {"input": "main"},
                "bindings": {"vertices": {"step": "lookup", "port": "vertices"}},
            },
        ]
    }
    result = {
        "status": "completed",
        "complete": True,
        "steps": {
            "lookup": {
                "status": "completed",
                "result": {"ports": {"vertices": {"value": [0], "complete": True}}},
            }
        },
    }
    checks = [{"step": "lookup", "port": "vertices", "value": [0]}]
    return plan, result, checks


def test_grader_accepts_step_renaming_but_preserves_wiring():
    expected, result, checks = grading_fixture()
    actual = deepcopy(expected)
    actual["steps"][0]["id"] = "first"
    actual["steps"][1]["bindings"]["vertices"]["step"] = "first"
    result["steps"]["first"] = result["steps"].pop("lookup")
    assert grade(expected, actual, result, checks)["passed"]
    actual["steps"][1]["bindings"]["vertices"]["port"] = "rows"
    graded = grade(expected, actual, result, checks)
    assert graded["operations"] and graded["parameters"] and not graded["wiring"]
    assert not graded["passed"]


def test_grader_accepts_declared_defaults_but_not_changed_semantics():
    expected, result, checks = grading_fixture()
    actual = deepcopy(expected)
    actual["steps"][0]["parameters"]["limit"] = 10000
    defaults = {"node-lookup": {"limit": 10000}}
    assert grade(expected, actual, result, checks, defaults)["passed"]
    actual["steps"][0]["parameters"]["limit"] = 1
    assert not grade(expected, actual, result, checks, defaults)["passed"]


@pytest.mark.parametrize(
    "mutation",
    ["wrong_type", "truncated", "failed", "wrong_parameters", "extra_operation"],
)
def test_grader_rejects_false_success(mutation):
    expected, result, checks = grading_fixture()
    actual = deepcopy(expected)
    if mutation == "wrong_type":
        result["steps"]["lookup"]["result"]["ports"]["vertices"]["value"] = ["0"]
    elif mutation == "truncated":
        result["steps"]["lookup"]["result"]["ports"]["vertices"]["complete"] = False
    elif mutation == "failed":
        result["steps"]["lookup"]["status"] = "failed"
    elif mutation == "wrong_parameters":
        actual["steps"][0]["parameters"]["vertices"] = ["0"]
    else:
        actual["steps"].append(deepcopy(actual["steps"][0]))
    assert not grade(expected, actual, result, checks)["passed"]


@pytest.mark.asyncio
async def test_model_evaluation_does_not_silently_fall_back_to_reference(settings):
    with pytest.raises(ValueError, match="explicitly enabled model"):
        await evaluate(settings, mode="model")
