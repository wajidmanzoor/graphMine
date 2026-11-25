from copy import deepcopy
import json
from pathlib import Path

import pytest

from graphmine_agent.analytics_eligibility import eligible, input_profile, promotion_choices, score_hints
from graphmine_agent.analytics_lane_choices import lookup_choices


def graph_profile(vertices=None, edges=None, directed=True):
    return input_profile({"kind": "graph", "data": {
        "graph": {"directed": directed}, "vertices": vertices or [{"id": 0}, {"id": 1}],
        "edges": edges if edges is not None else [{"source": 0, "target": 1}],
    }})


def card(**requirements):
    return {"id": "test", "quality": "exact", "parameters": {}, "requirements": {
        "input_kind": "graph", "direction": "either", "weights": "ignored",
        "unit_weight_mode": False, "needs": [], **requirements}}


def test_profile_reads_every_record_and_distinguishes_promotable_values():
    vertices = [{"id": i, "type": "User" if i < 40 else "Business"} for i in range(80)]
    edges = [{"source": i, "target": i + 40, "attributes": {"stars": 5, "flag": True}} for i in range(40)]
    edges[-1]["timestamp"] = 100
    profile = graph_profile(vertices, edges)
    assert profile["vertices_count"] == 80 and profile["edges_count"] == 40
    assert profile["vertex_type_count"] == {"User": 40, "Business": 40}
    assert profile["weighted"] and not profile["canonical_weights_complete"]
    assert profile["weight_candidates"] == ["attributes.stars"]
    assert profile["temporal"] and not profile["timestamps_complete"]
    assert profile["bipartite"]


def test_wide_input_does_not_hide_weights_or_timestamps():
    attributes = {f"note_{index}": "metadata" for index in range(90)}
    attributes.update(stars=4, timestamp=10)
    profile = graph_profile(edges=[{"source": 0, "target": 1, "attributes": attributes}])
    assert profile["weighted"]
    assert "attributes.stars" in profile["weight_candidates"]
    assert profile["timestamp_candidates"] == ["attributes.timestamp"]
    assert eligible(card(weights="required", needs=["timestamps"]), profile)[0]


@pytest.mark.parametrize("bad", [None, True, "5"])
def test_incomplete_or_non_numeric_attribute_is_never_promoted(bad):
    profile = graph_profile(edges=[{"source": 0, "target": 1, "attributes": {"stars": 5}},
                                   {"source": 0, "target": 1, "attributes": {"stars": bad}}])
    assert profile["weight_candidates"] == []
    assert eligible(card(weights="required"), profile)[0] is False


def test_bipartition_preserves_typed_ids_and_rejects_invalid_declarations():
    vertices = [{"id": 1, "type": "User"}, {"id": "1", "type": "Business"}]
    edges = [{"source": 1, "target": "1"}]
    assert graph_profile(vertices, edges)["bipartite"]
    vertices[0]["attributes"] = {"side": "left"}
    assert not graph_profile(vertices, edges)["bipartite"]
    vertices[1]["attributes"] = {"side": "right"}
    assert graph_profile(vertices, edges)["bipartite"]
    edges.append({"source": 1, "target": 1})
    assert not graph_profile(vertices, edges)["bipartite"]


def test_direction_and_weight_hints_score_but_do_not_remove_valid_options():
    profile = graph_profile()
    candidate = card(direction="undirected", weights="ignored")
    assert eligible(candidate, profile, {"weighted": True}) == (True, None)
    assert score_hints(candidate, profile, {"weighted": True})["score"] < 0


def test_unit_mode_and_complete_numeric_field_keep_weighted_problem_available():
    assert eligible(card(weights="required", unit_weight_mode=True), graph_profile())[0]
    weighted = graph_profile(edges=[{"source": 0, "target": 1, "attributes": {"stars": 4.5}}])
    assert eligible(card(weights="required"), weighted)[0]
    assert promotion_choices(card(weights="required"), weighted) == [
        {"kind": "weight", "field": "attributes.stars", "label": "Use stars as the weight?"}]


@pytest.mark.parametrize("requirement,fragment", [
    ({"input_kind": "feature_vectors"}, "feature vectors"),
    ({"weights": "required"}, "weight"),
    ({"needs": ["bipartite_side"]}, "sides"),
    ({"needs": ["timestamps"]}, "timestamp"),
    ({"needs": ["query_graph"]}, "query"),
])
def test_hard_exclusions_have_a_specific_reason(requirement, fragment):
    ok, reason = eligible(card(**requirement), graph_profile())
    assert not ok and fragment in reason


def test_exact_request_removes_heuristic_only_but_not_an_exact_variant():
    heuristic = {**card(), "quality": "heuristic"}
    assert eligible(heuristic, graph_profile())[0]
    assert not eligible(heuristic, graph_profile(), {"exact": True})[0]
    heuristic["parameters"] = {"solution_quality": {"choices": ["exact", "heuristic"]}}
    assert eligible(heuristic, graph_profile(), {"exact": True})[0]


def test_required_source_is_a_parameter_gap_not_absent_graph_data():
    assert eligible(card(needs=["source", "sink"]), graph_profile())[0]


@pytest.mark.parametrize("kind,data,key,count", [
    ("graph_collection", {"graphs": [{"vertices": [1, 2], "edges": [1]}, {"vertices": [3], "edges": []}]}, "graphs_count", 2),
    ("hypergraph", {"vertices": [1, 2], "hyperedges": [[1, 2]]}, "hyperedges_count", 1),
    ("feature_vectors", {"vectors": [[1, 2], [3, 4]]}, "vectors_count", 2),
])
def test_non_graph_input_sizes_are_profiled(kind, data, key, count):
    profile = input_profile({"kind": kind, "data": data})
    assert profile["input_kind"] == kind and profile[key] == count


def test_every_declared_requirement_has_the_machine_contract():
    path = Path(__file__).resolve().parents[2] / "catalog/problem_requirements.json"
    problems = json.loads(path.read_text())["problems"]
    assert len(problems) == 82
    for requirement in problems.values():
        assert set(requirement) == {"input_kind", "direction", "weights", "unit_weight_mode", "needs"}
        assert requirement["direction"] in {"directed", "undirected", "either"}
        assert requirement["weights"] in {"required", "optional", "ignored"}
        assert isinstance(requirement["unit_weight_mode"], bool)
        assert set(requirement["needs"]) <= {"bipartite_side", "timestamps", "source", "sink", "query_graph"}


def test_lookup_keeps_all_explicit_and_filters_in_one_code_plan():
    inputs = {"main": {"kind": "graph", "data": {"vertices": [
        {"id": 1, "attributes": {"country": "US", "balance": 12}},
        {"id": 2, "attributes": {"country": "US", "balance": 20}}], "edges": []}}}
    choices = lookup_choices(inputs, [{"id": "node-lookup"}], [], "country is US and balance equals 12.", "cpu")
    assert len(choices) == 1
    assert choices[0]["plan"]["steps"][0]["parameters"]["vertex_filters"] == [
        {"field": "attributes.balance", "op": "eq", "value": 12},
        {"field": "attributes.country", "op": "eq", "value": "US"}]
