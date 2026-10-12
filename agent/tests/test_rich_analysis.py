from __future__ import annotations

import copy
import json

import pytest
from graphmine_agent.analysis import (
    SCHEMA_URL,
    analysis_context,
    apply_narrative,
    prepare_analysis,
    validate_narrative,
    validate_vega_spec,
)
from graphmine_agent.answers import answer_interpretation, build_answer
from graphmine_agent.models import (
    ApplicationIntent,
    ExecutionPlan,
    GroundedNarrative,
    GroundedStatement,
    VegaLiteDraft,
)
from graphmine_agent.visualization import answer_visualizations


@pytest.fixture
def answer():
    graph = {
        "graph": {"id": "analysis-fixture", "directed": False},
        "vertices": [
            {"id": index, "label": name, "attributes": {"department": department}}
            for index, name, department in [
                (0, "Ari", "Design"),
                (1, "Bo", "Design"),
                (2, "Cam", "Support"),
            ]
        ],
        "edges": [
            {"id": "ab", "source": 0, "target": 1},
            {"id": "bc", "source": 1, "target": 2},
        ],
    }
    result = build_answer(
        graph,
        ExecutionPlan(
            session_id="fixture",
            graph_id="fixture",
            operation_id="maximal-cliques",
            problem_id="maximal_clique_enumeration",
            application_intent=ApplicationIntent(
                objective="Compare the groups and their membership overlap."
            ),
        ),
        {"output": {"cliques": [[0, 1], [1, 2]], "complete": True}},
        source_hash="authored-computation-fixture",
    )
    return prepare_analysis(result)


def composed_spec():
    return {
        "$schema": SCHEMA_URL,
        "hconcat": [
            {
                "data": {"name": "groups"},
                "mark": "bar",
                "encoding": {
                    "x": {"field": "group", "type": "nominal"},
                    "y": {
                        "field": "size",
                        "type": "quantitative",
                        "scale": {"zero": True},
                    },
                },
            },
            {
                "data": {"name": "overlap"},
                "mark": "rect",
                "encoding": {
                    "x": {"field": "group_a", "type": "nominal"},
                    "y": {"field": "group_b", "type": "nominal"},
                    "color": {"field": "shared", "type": "quantitative"},
                    "tooltip": [{"field": "shared", "type": "quantitative"}],
                },
            },
        ],
    }


def narrative(answer, spec=None):
    fact = answer["facts"][0]
    return GroundedNarrative(
        fact_ids=[fact["id"]],
        summary=GroundedStatement(text=fact["statement"], fact_ids=[fact["id"]]),
        findings=[
            GroundedStatement(
                text="Read the group sizes alongside their shared membership. Membership overlap is distinct from links between groups.",
                fact_ids=[fact["id"]],
            )
        ],
        charts=[
            VegaLiteDraft(
                title="Groups and overlap",
                description="Compare returned group sizes and shared memberships; the diagonal includes each group's own members.",
                spec_json=json.dumps(spec or composed_spec()),
                fact_ids=[fact["id"]],
            )
        ],
    )


def test_context_computes_overlap_and_attribute_denominators(answer):
    data = answer["analysis_datasets"]
    assert len(data["members"]["rows"]) == 3
    assert len(data["memberships"]["rows"]) == 4
    overlap = data["overlap"]["rows"]
    assert sorted(row["shared"] for row in overlap) == [1, 1, 2, 2]
    off_diagonal = [row for row in overlap if row["group_a"] != row["group_b"]]
    assert all(row["jaccard"] == pytest.approx(1 / 3) for row in off_diagonal)
    profile = data["attribute_counts"]["rows"]
    assert {row["category"]: row["count"] for row in profile} == {
        "Design": 2,
        "Support": 1,
    }
    assert all(row["denominator"] == 3 for row in profile)
    assert data["members"]["columns"]["id"] == "nominal"
    context = analysis_context(answer)
    assert "rows" not in context["datasets"]["members"]
    before = len(answer["facts"])
    prepare_analysis(answer)
    assert len(answer["facts"]) == before


def test_real_compiler_renders_composed_chart_and_binds_only_answer_data(answer):
    draft = narrative(answer)
    views = validate_narrative(
        draft, answer, answer_visualizations(answer), {"maximal-cliques"}
    )
    assert len(views) == 1
    assert views[0].type == "vega_lite"
    assert set(views[0].vega_lite["datasets"]) == {"groups", "overlap"}
    assert (
        views[0].vega_lite["datasets"]["groups"]
        == answer["analysis_datasets"]["groups"]["rows"]
    )
    interpretation = answer_interpretation(answer, views)
    original_facts = interpretation.findings.copy()
    apply_narrative(interpretation, draft, answer)
    assert interpretation.findings == original_facts
    assert interpretation.explanation[1].text.startswith("Read the group sizes")


@pytest.mark.parametrize(
    "change",
    [
        "unknown_field",
        "remote_data",
        "fabricated_data",
        "unknown_dataset",
        "remote_link",
        "wrong_version",
    ],
)
def test_rejects_unverifiable_chart_inputs(answer, change):
    spec = composed_spec()
    first = spec["hconcat"][0]
    if change == "unknown_field":
        first["encoding"]["y"]["field"] = "invented_revenue"
    elif change == "remote_data":
        first["data"] = {"url": "https://example.com/data.json"}
    elif change == "fabricated_data":
        first["data"] = {"values": [{"group": "Fabricated", "size": 9000}]}
    elif change == "unknown_dataset":
        first["data"] = {"name": "all_customers"}
    elif change == "remote_link":
        first["encoding"]["href"] = {"value": "https://example.com"}
    else:
        spec["$schema"] = "https://vega.github.io/schema/vega-lite/v5.json"
    with pytest.raises(ValueError):
        validate_vega_spec(spec, answer["analysis_datasets"])


def test_rejects_unsupported_numbers_and_missing_fact_references(answer):
    draft = narrative(answer)
    draft.summary.text = "There are 987654 groups."
    with pytest.raises(ValueError, match="unsupported number"):
        validate_narrative(draft, answer, [], set())
    draft.summary.fact_ids = ["invented_fact"]
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_narrative(draft, answer, [], set())


def test_additional_analysis_requires_available_operation(answer):
    draft = narrative(answer)
    draft.charts = []
    draft.analysis_request = (
        "Compare the connection-core thresholds of the returned people."
    )
    draft.analysis_operation_ids = ["k-core"]
    with pytest.raises(ValueError, match="supported operations"):
        validate_narrative(draft, answer, [], {"maximal-cliques"})
    validate_narrative(draft, answer, [], {"k-core"})
    result = apply_narrative(answer_interpretation(answer, []), draft, answer)
    assert result.requires_new_execution
    assert result.followup_actions[-1].request == draft.analysis_request


def test_composition_repair_feedback_locates_bad_wrapper(answer):
    spec = composed_spec()
    spec["hconcat"] = {"views": spec["hconcat"], "spacing": 12}
    with pytest.raises(ValueError, match=r"\$\.hconcat: expected an array") as error:
        validate_vega_spec(spec, answer["analysis_datasets"])
    assert "spacing beside" in str(error.value)
    assert len(str(error.value)) < 240


def test_filter_repair_feedback_locates_nested_invalid_key(answer):
    spec = composed_spec()
    spec["hconcat"][1]["transform"] = [{"filter": "datum.shared > 0", "join": "inner"}]
    with pytest.raises(ValueError, match=r"\$\.hconcat\[1\]\.transform\[0\]") as error:
        validate_vega_spec(spec, answer["analysis_datasets"])
    assert "remove ['join']" in str(error.value)
    # The corresponding valid transform retains the full validation path.
    del spec["hconcat"][1]["transform"][0]["join"]
    validate_vega_spec(spec, answer["analysis_datasets"])


def test_chart_json_repair_feedback_identifies_chart(answer):
    draft = narrative(answer)
    draft.charts[0].spec_json = '{"hconcat": [}'
    with pytest.raises(ValueError, match=r"charts\[0\]\.spec_json.*column"):
        validate_narrative(draft, answer, [], set())


def test_aggregate_aliases_are_available_but_source_typos_are_rejected(answer):
    spec = {
        "$schema": SCHEMA_URL,
        "data": {"name": "members"},
        "transform": [
            {
                "aggregate": [{"op": "count", "as": "people"}],
                "groupby": ["attribute_department"],
            }
        ],
        "mark": "bar",
        "encoding": {
            "x": {"field": "attribute_department", "type": "nominal"},
            "y": {"field": "people", "type": "quantitative"},
        },
    }
    assert validate_vega_spec(spec, answer["analysis_datasets"]) == {"members"}
    invalid = copy.deepcopy(spec)
    invalid["transform"][0]["groupby"] = ["unavailable_department"]
    with pytest.raises(ValueError, match="grouping field"):
        validate_vega_spec(invalid, answer["analysis_datasets"])
