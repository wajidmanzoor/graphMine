from __future__ import annotations

import json
from copy import deepcopy

import pytest
from graphmine_agent.catalog import Catalog
from graphmine_agent.config import Settings
from graphmine_agent.history import HistoryStore
from graphmine_agent.learning.adapter_eval import (
    routing_schema,
    score_generation,
    score_route,
    semantic_intent,
    summarize,
)
from graphmine_agent.learning.adapter_review import audited_cases, review_generation
from graphmine_agent.learning.corpus import digest, generate_corpus
from graphmine_agent.models import ApplicationIntent


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return generate_corpus(
        tmp_path_factory.mktemp("adapter-check") / "corpus", graphs_per_family=1
    )


@pytest.fixture(scope="module")
def catalog():
    return Catalog(Settings.from_env())


def make_case(example):
    return {
        "id": example["id"],
        "family": example["family"],
        "behavior": example["task"]["behavior"],
        "operation_id": example["task"]["operation_id"],
        "expected": example["gold_route"],
        "payload": {"graph_context": {}, "active_constraints": None},
    }


def test_all_gold_routes_pass_but_bad_json_cannot(corpus, catalog):
    for example in corpus["examples"]:
        case = make_case(example)
        score = score_route(case, json.dumps(example["gold_route"]), catalog)
        assert score["passed"], (example["id"], score)
        assert not score_route(case, '{"supported": true}', catalog)["passed"]


def test_wrong_attribute_and_false_empty_refusal_fail(corpus, catalog):
    example = next(
        e for e in corpus["examples"] if "score is exactly 0.999" in e["task"]["query"]
    )
    case, decision = make_case(example), deepcopy(example["gold_route"])
    decision["intent"]["filters"][0]["field"] = "attributes.ascore"
    assert any(
        "filters:" in i
        for i in score_route(case, json.dumps(decision), catalog)["issues"]
    )
    decision = deepcopy(example["gold_route"])
    decision.update(supported=False, operation_id=None)
    assert not score_route(case, json.dumps(decision), catalog)["passed"]


def test_weighting_is_never_dropped_to_pass(corpus, catalog):
    example = next(
        e
        for e in corpus["examples"]
        if e["task"]["reason"] == "filter_and_weight_required"
    )
    case, decision = make_case(example), deepcopy(example["gold_route"])
    decision.update(supported=True, operation_id=example["task"]["operation_id"])
    score = score_route(case, json.dumps(decision), catalog)
    assert score["passed"] and score["capability_errors"]
    assert not score["raw_route_matches"]
    decision["intent"].update(
        requires_edge_weights=False, weight_attribute=None, weight_usage=None
    )
    assert not score_route(case, json.dumps(decision), catalog)["passed"]


def test_scope_inheritance_and_clearing_are_graded(corpus, catalog):
    example = next(e for e in corpus["examples"] if e["task"]["filters"])
    case, decision = make_case(example), deepcopy(example["gold_route"])
    case["payload"]["active_constraints"] = deepcopy(decision["intent"])
    decision["intent"].update(filter_mode="inherit", filters=[])
    assert score_route(case, json.dumps(decision), catalog)["passed"]
    decision["intent"]["filter_mode"] = "clear"
    assert not score_route(case, json.dumps(decision), catalog)["passed"]


def test_equivalent_temporal_units_and_role_names():
    first = ApplicationIntent(
        requires_direction=True,
        pattern_vertex_count=3,
        pattern_edges=[[0, 1], [1, 2], [0, 2]],
        time_window=20,
        time_unit="seconds",
    )
    other = first.model_copy(
        update={
            "pattern_edges": [[4, 8], [8, 9], [4, 9]],
            "time_window": 20000,
            "time_unit": "native",
        }
    )
    assert semantic_intent(first) == semantic_intent(other, "milliseconds")
    other.time_window = 20
    assert semantic_intent(first) != semantic_intent(other, "milliseconds")


def test_raw_and_semantic_scores_are_separate_and_missing_cases_incomplete():
    rows = []
    for arm, passed in (("base_nf4", True), ("adapter_nf4", False)):
        rows.append(
            {
                "arm": arm,
                "id": "a",
                "family": "barbell",
                "behavior": "execute",
                "operation_id": "maximal-cliques",
                "finish_reason": "stop",
                "score": {
                    "passed": passed,
                    "schema_valid": True,
                    "raw_route_matches": True,
                },
            }
        )
    report = summarize(rows, 2, ["base_nf4", "adapter_nf4"])
    assert not report["complete"]
    assert report["regressions"] == ["a"]
    assert report["paired_nf4"] == {"regressed": 1}
    assert report["by_arm"]["adapter_nf4"]["passed"] == 0
    assert report["by_arm"]["adapter_nf4"]["raw_route_matches"] == 1


def test_nested_semantic_fields_cannot_be_omitted_from_generation():
    schema = routing_schema()
    for item in [
        schema,
        schema["$defs"]["ApplicationIntent"],
        schema["$defs"]["DataFilter"],
    ]:
        assert set(item["required"]) == set(item["properties"])
        assert all("default" not in prop for prop in item["properties"].values())


def test_truncated_generation_cannot_pass_when_rescored_on_resume(corpus, catalog):
    example = corpus["examples"][0]
    result = {"raw": json.dumps(example["gold_route"]), "finish_reason": "length"}
    score = score_generation(make_case(example), result, catalog)
    assert not score["passed"]
    assert score["issues"] == ["generation exhausted token budget"]


def test_safe_refusal_is_distinct_from_preserving_problem_identity(corpus, catalog):
    example = next(
        e for e in corpus["examples"] if e["task"]["reason"] == "weighted_cost_required"
    )
    decision = deepcopy(example["gold_route"])
    decision["problem_id"] = None
    score = score_route(make_case(example), json.dumps(decision), catalog)
    assert not score["passed"]
    assert score["behavior_correct"]
    assert score["semantic_requirements_correct"]
    assert not score["unsafe_execution"]


def test_application_review_does_not_reject_static_pattern_descriptions(
    corpus, catalog
):
    example = next(
        e for e in corpus["examples"] if e["task"]["operation_id"] == "k-cliques"
    )
    decision = deepcopy(example["gold_route"])
    decision["intent"].update(
        pattern_vertex_count=3, pattern_edges=[[0, 1], [1, 2], [0, 2]]
    )
    result = {"raw": json.dumps(decision), "finish_reason": "stop"}
    strict, reviewed = review_generation(make_case(example), result, catalog)
    assert not strict["passed"] and reviewed["passed"]
    assert reviewed["ignored_differences"]
    decision["operation_id"] = "maximum-clique"
    decision["problem_id"] = "maximum_clique"
    _, reviewed = review_generation(
        make_case(example), {**result, "raw": json.dumps(decision)}, catalog
    )
    assert not reviewed["passed"]


def test_application_review_still_rejects_wrong_temporal_pattern(corpus, catalog):
    example = next(
        e
        for e in corpus["examples"]
        if e["task"]["operation_id"] == "temporal-motif-mining"
        and e["task"]["behavior"] == "execute"
    )
    decision = deepcopy(example["gold_route"])
    decision["intent"]["pattern_edges"] = [[0, 1], [1, 2], [2, 0]]
    _, reviewed = review_generation(
        make_case(example),
        {"raw": json.dumps(decision), "finish_reason": "stop"},
        catalog,
    )
    assert not reviewed["passed"]
    assert not reviewed["semantic_requirements_correct"]


def test_application_review_capability_refusal_precedes_missing_inputs(corpus, catalog):
    example = next(
        e for e in corpus["examples"] if e["task"]["reason"] == "weighted_cost_required"
    )
    decision = deepcopy(example["gold_route"])
    decision["missing_information"] = ["Please provide the edge costs."]
    strict, reviewed = review_generation(
        make_case(example),
        {"raw": json.dumps(decision), "finish_reason": "stop"},
        catalog,
    )
    assert strict["behavior"] == "clarify" and not strict["passed"]
    assert reviewed["behavior"] == "unsupported" and reviewed["passed"]
    assert reviewed["application_blocker"][0] == "unsupported"


def test_application_review_unavailable_operation_precedes_clarification(
    corpus, catalog
):
    example = next(e for e in corpus["examples"] if e["task"]["behavior"] == "execute")
    case = make_case(example)
    decision = deepcopy(case["expected"])
    decision.update(
        problem_id="graphlet_counting",
        operation_id=None,
        supported=False,
        ambiguity=["Which graphlet sizes should I use?"],
    )
    case.update(expected=decision, behavior="unsupported", operation_id=None)
    strict, reviewed = review_generation(
        case, {"raw": json.dumps(decision), "finish_reason": "stop"}, catalog
    )
    assert strict["behavior"] == "clarify"
    assert reviewed["behavior"] == "unsupported" and reviewed["passed"]


def test_application_review_missing_operation_cannot_count_as_execution(
    corpus, catalog
):
    example = next(e for e in corpus["examples"] if e["task"]["behavior"] == "execute")
    decision = deepcopy(example["gold_route"])
    decision["operation_id"] = None
    strict, reviewed = review_generation(
        make_case(example),
        {"raw": json.dumps(decision), "finish_reason": "stop"},
        catalog,
    )
    assert strict["behavior"] == "execute"
    assert reviewed["behavior"] == "unsupported"
    assert not reviewed["behavior_correct"] and not reviewed["passed"]


@pytest.mark.parametrize(
    "defect", [None, "wrong_suite", "changed_case", "duplicate", "no_reason"]
)
def test_label_audit_binds_corrections_to_original_inputs(tmp_path, defect):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "plan.json").write_text('{"version": "test"}')
    case = {
        "id": "missing-attachment",
        "behavior": "execute",
        "payload": {"message": "Use the attached query graph."},
    }
    correction = {
        "id": case["id"],
        "case_sha256": digest(case),
        "original_behavior": "execute",
        "reviewed_behavior": "clarify",
        "reason": "The fixture supplies no query graph or file reference.",
    }
    audit = {
        "suite_plan_sha256": HistoryStore.digest(suite / "plan.json"),
        "corrections": [correction],
    }
    if defect == "wrong_suite":
        audit["suite_plan_sha256"] = "0" * 64
    elif defect == "changed_case":
        case["payload"]["message"] = "A different request"
    elif defect == "duplicate":
        audit["corrections"].append(correction)
    elif defect == "no_reason":
        correction["reason"] = " "
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(audit))
    if defect:
        with pytest.raises(ValueError):
            audited_cases(suite, [case], path)
    else:
        original, changes = audited_cases(suite, [case], path)
        assert original == audit
        assert changes[case["id"]]["behavior"] == "clarify"
        assert case["behavior"] == "execute"
        assert changes[case["id"]]["payload"] == case["payload"]
