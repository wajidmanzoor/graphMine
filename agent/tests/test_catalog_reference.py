from __future__ import annotations

import copy

import pytest
from graphmine_agent.learning.catalog_reference import reference_for_case
from graphmine_agent.learning.catalog_suite import build_suite


@pytest.fixture
def cases(catalog):
    return {case["id"]: case for case in build_suite(catalog)["cases"]}


def expected(cases, operation, tag="supported"):
    return reference_for_case(cases[f"{operation}--{tag}"])["expected"]


def test_every_current_operation_has_a_bounded_reference(cases):
    before = copy.deepcopy(cases)
    checked = [reference_for_case(case) for case in cases.values()]
    assert len(checked) == 46
    assert sum(row["kind"] != "non_executable" for row in checked) == 26
    assert cases == before


def test_exhaustive_groups_distinguish_exact_size_maximal_and_maximum(cases):
    assert expected(cases, "maximal-cliques")["count"] == 2
    assert expected(cases, "maximum-clique")["count"] == 1
    assert expected(cases, "maximum-clique")["size"] == 4
    assert expected(cases, "k-cliques")["count"] == 5
    assert expected(cases, "quasi-cliques")["count"] == 2
    assert expected(cases, "triangle-counting")["count"] == 5
    assert expected(cases, "graph-motifs")["patterns"][0]["count"] == 5
    assert expected(cases, "subgraph-isomorphism")["patterns"][0]["count"] == 30
    assert expected(cases, "k-cliques", "empty_filter")["count"] == 0


def test_dynamic_reference_accounts_for_deleted_and_inserted_triangles(cases):
    value = expected(cases, "dynamic-triangle-counting")
    assert (value["initial_count"], value["final_count"]) == (5, 4)
    assert len(value["deleted"]) == 2 and len(value["inserted"]) == 1
    case = copy.deepcopy(cases["dynamic-triangle-counting--supported"])
    case["attachments"]["updates"][0]["content"]["updates"][0]["kind"] = "bad"
    with pytest.raises(ValueError, match="Unknown update"):
        reference_for_case(case)


def test_components_and_reflexive_reachability_include_isolates(cases):
    assert sorted(map(len, expected(cases, "connected-components")["groups"])) == [
        1,
        1,
        1,
        2,
    ]
    assert sorted(
        map(len, expected(cases, "connected-components", "weak_connectivity")["groups"])
    ) == [1, 4]
    pairs = expected(cases, "transitive-closure")["pairs"]
    assert len(pairs) == 12 and sum(source == target for source, target in pairs) == 5


def test_weighted_references_use_the_requested_attribute_and_leave_inputs_intact(cases):
    assert expected(cases, "max-flow-min-cut")["max_flow_value"] == 6
    assert expected(cases, "linear-assignment")["objective_value"] == 8
    assert expected(cases, "group-steiner-tree")["tree_weight"] == 6
    altered = copy.deepcopy(cases["group-steiner-tree--supported"])
    for edge in altered["graph"]["edges"]:
        edge["weight"] = 999  # The requested attributes.value still holds the costs.
    before = copy.deepcopy(altered)
    assert reference_for_case(altered)["expected"]["tree_weight"] == 6
    assert altered == before


def test_bipartite_density_and_truss_references_have_hand_checked_values(cases):
    assert expected(cases, "butterfly-counting")["count"] == 1
    assert expected(cases, "maximal-biclique-counting")["count"] == 3
    density = expected(cases, "densest-subgraph")
    assert density["density"] == 1.5
    assert len(density["optimal_groups"]) == 1
    assert len(density["optimal_groups"][0]["vertices"]) == 4
    assert density["optimal_groups"][0]["induced_edge_value"] == 6
    truss = expected(cases, "k-truss")
    assert truss["maximum"] == 4
    assert sorted(row["truss_number"] for row in truss["edges"]) == [
        2,
        3,
        3,
        3,
        4,
        4,
        4,
        4,
        4,
        4,
    ]


def test_approximate_methods_do_not_gain_false_optimality_or_error_guarantees(cases):
    page = reference_for_case(cases["personalized-pagerank--supported"])
    assert page["kind"] == "approximate_scores_measured_against_stationary_distribution"
    assert [row["score"] for row in page["expected"]["scores"]] == pytest.approx(
        [125 / 297, 100 / 297, 40 / 297, 32 / 297, 0], abs=1e-11
    )
    influence = reference_for_case(cases["influence-maximization--supported"])
    assert (
        influence["kind"]
        == "exact_spread_for_returned_seeds_without_optimality_requirement"
    )
    assert sorted(row["spread"] for row in influence["expected"]["seed_sets"]) == [
        1,
        2,
        3,
        4,
    ]
    assert influence["expected"]["best_possible_spread"] == 4
    assert (
        reference_for_case(cases["community-detection--supported"])["kind"]
        == "partition_and_score_consistency"
    )


def test_reference_limits_are_enforced_before_exhaustive_enumeration(cases):
    case = copy.deepcopy(cases["k-cliques--supported"])
    case["graph"]["vertices"].extend({"id": f"extra-{i}"} for i in range(2))
    with pytest.raises(ValueError, match="limited to 8"):
        reference_for_case(case)
