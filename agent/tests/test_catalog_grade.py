"""Hand-calculated outputs and deliberate corruptions, not native predictions."""

from __future__ import annotations

import copy
import itertools

import pytest
from graphmine_agent.learning.catalog_grade import grade_output
from graphmine_agent.learning.catalog_suite import build_suite

OPERATIONS = (
    "maximal-cliques",
    "maximum-clique",
    "k-cliques",
    "quasi-cliques",
    "k-core",
    "maximal-bicliques",
    "triangle-counting",
    "dynamic-triangle-counting",
    "graph-motifs",
    "subgraph-isomorphism",
    "temporal-motif-mining",
    "community-detection",
    "betweenness-centrality",
    "connected-components",
    "max-flow-min-cut",
    "linear-assignment",
    "transitive-closure",
    "butterfly-counting",
    "k-truss",
    "densest-subgraph",
    "maximal-biclique-counting",
    "personalized-pagerank",
    "group-steiner-tree",
    "influence-maximization",
)


@pytest.fixture
def cases(catalog):
    return {
        case["task"]["operation_id"]: case
        for case in build_suite(catalog)["cases"]
        if case["tags"] == ["supported"]
    }


def authored_output(case):
    op = case["task"]["operation_id"]
    ids = [vertex["id"] for vertex in case["graph"]["vertices"]]
    vertices = lambda indexes: [ids[index] for index in indexes]
    tri_indexes = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3), (4, 5, 6)]
    triangles = [vertices(group) for group in tri_indexes] if len(ids) == 7 else []
    if op == "maximal-cliques":
        return {
            "cliques": [vertices([0, 1, 2, 3]), vertices([4, 5, 6])],
            "returned_count": 2,
            "total_count": 2,
            "complete": True,
        }
    if op == "maximum-clique":
        return {
            "cliques": [vertices([0, 1, 2, 3])],
            "maximum_size": 4,
            "optimal": True,
            "upper_bound": 4,
        }
    if op == "k-cliques":
        return {
            "cliques": triangles,
            "count": 5,
            "complete": True,
            "per_vertex_count": [
                {"vertex": v, "count": 3 if i < 4 else 1} for i, v in enumerate(ids)
            ],
        }
    if op == "quasi-cliques":
        return {
            "quasi_cliques": [vertices([0, 1, 2, 3]), vertices([4, 5, 6])],
            "returned_count": 2,
            "total_count": 2,
            "complete": True,
        }
    if op == "k-core":
        return {
            "core_number_by_vertex": [
                {"vertex": v, "core_number": 3 if i < 4 else 2}
                for i, v in enumerate(ids)
            ],
            "degeneracy": 3,
            "requested_core_vertices": ids,
            "requested_core_edges": [f"link-{i}" for i in range(10)],
        }
    if op == "maximal-bicliques":
        return {
            "bicliques": [{"left": vertices([0, 1]), "right": vertices([3, 4])}],
            "returned_count": 1,
            "total_count": 1,
            "complete": True,
        }
    if op == "triangle-counting":
        return {
            "global_triangle_count": 5,
            "triangles": triangles,
            "instances_complete": True,
            "per_vertex_count": [
                {"vertex": v, "count": 3 if i < 4 else 1} for i, v in enumerate(ids)
            ],
            "per_edge_count": [
                {"edge": f"link-{i}", "count": count}
                for i, count in enumerate([2, 2, 2, 2, 2, 2, 0, 1, 1, 1])
            ],
        }
    if op == "dynamic-triangle-counting":
        return {
            "initial_global_triangle_count": 5,
            "final_global_triangle_count": 4,
            "deleted_triangle_count": 2,
            "inserted_triangle_count": 1,
            "net_triangle_change": -1,
            "deleted_triangles": triangles[:2],
            "inserted_triangles": [vertices([0, 3, 4])],
            "changed_instances_complete": True,
        }
    if op == "graph-motifs":
        return {
            "motifs": [
                {
                    "motif_id": "catalog-development",
                    "count": 5,
                    "instances_complete": True,
                    "instances": [
                        [
                            {"motif_vertex": q, "data_vertex": v}
                            for q, v in zip(["a", "b", "c"], group, strict=True)
                        ]
                        for group in triangles
                    ],
                }
            ]
        }
    if op == "subgraph-isomorphism":
        return {
            "count": 30,
            "embeddings_complete": True,
            "embeddings": [
                [
                    {"query_vertex": q, "data_vertex": v}
                    for q, v in zip(["a", "b", "c"], ordering, strict=True)
                ]
                for group in triangles
                for ordering in itertools.permutations(group)
            ],
        }
    if op == "temporal-motif-mining":
        return {
            "count": 1,
            "instances_complete": True,
            "instances": [
                {
                    "edges_in_temporal_order": ["link-0", "link-1", "link-2"],
                    "vertices_by_role": vertices([0, 1, 2]),
                }
            ],
        }
    if op == "community-detection":
        return {
            "assignment_by_vertex": [{"vertex": v, "community": 0} for v in ids],
            "community_count": 1,
            "modularity": 0,
            "communities": [{"id": 0, "vertices": ids}],
            "edge_cut": 0,
        }
    if op == "betweenness-centrality":
        scores = [
            {"vertex": v, "score": score}
            for v, score in zip(ids, [0, 0, 0, 18, 16, 0, 0], strict=True)
        ]
        return {
            "score_by_vertex": scores,
            "ranking": sorted(scores, key=lambda row: -row["score"]),
            "maximum": scores[3],
        }
    if op == "connected-components":
        return {
            "component_assignment": [
                {"vertex": v, "component": c}
                for v, c in zip(ids, [0, 0, 1, 2, 3], strict=True)
            ],
            "component_count": 4,
            "component_sizes": [2, 1, 1, 1],
        }
    if op == "max-flow-min-cut":
        return {
            "max_flow_value": 6,
            "min_cut_value": 6,
            "min_cut_edges": ["link-0", "link-1"],
            "source_side_vertices": [ids[0]],
            "flow_assignment": [
                {"edge": f"link-{i}", "flow": flow}
                for i, flow in enumerate([4, 2, 1, 3, 3])
            ],
            "optimal": True,
        }
    if op == "linear-assignment":
        return {
            "matching_edges": ["link-1", "link-3", "link-8"],
            "matching_size": 3,
            "objective_value": 8,
            "feasible": True,
            "optimal": True,
        }
    if op == "transitive-closure":
        pairs = [
            (0, 0),
            (0, 1),
            (0, 2),
            (0, 3),
            (1, 0),
            (1, 1),
            (1, 2),
            (1, 3),
            (2, 2),
            (2, 3),
            (3, 3),
            (4, 4),
        ]
        return {
            "reachable_pair_count": 12,
            "reachability_results": [],
            "transitive_closure_edges": [
                {"source": ids[a], "target": ids[b]} for a, b in pairs
            ],
            "complete": True,
        }
    if op == "butterfly-counting":
        return {"butterfly_count": 1, "complete": True}
    if op == "k-truss":
        return {
            "truss_number_by_edge": [
                {"edge": f"link-{i}", "truss_number": v}
                for i, v in enumerate([4, 4, 4, 4, 4, 4, 2, 3, 3, 3])
            ],
            "maximum_truss_number": 4,
        }
    if op == "densest-subgraph":
        return {
            "vertices": vertices([0, 1, 2, 3]),
            "density": 1.5,
            "clique_order": 2,
            "clique_count": 6,
            "induced_edge_value": 6,
            "optimal": True,
        }
    if op == "maximal-biclique-counting":
        return {"total_count": 3, "complete": True}
    if op == "personalized-pagerank":
        return {
            "ranked_vertices": [
                {"vertex": v, "score": score, "rank": i + 1}
                for i, (v, score) in enumerate(
                    zip(ids, [125 / 297, 100 / 297, 40 / 297, 32 / 297, 0], strict=True)
                )
            ],
            "restart_probability_used": 0.2,
            "epsilon_used": 0.01,
            "approximate": True,
            "complete": True,
            "error_bound_certified": False,
            "error_bound": None,
        }
    if op == "group-steiner-tree":
        return {
            "tree_edges": ["link-0", "link-1", "link-3"],
            "selected_vertices": ids,
            "tree_weight": 6,
            "feasible": True,
            "optimal": True,
        }
    if op == "influence-maximization":
        return {
            "seed_set": [ids[1]],
            "expected_spread": 3,
            "prefix_spread": [3],
            "guarantee_met": False,
            "sample_count": 32,
            "diffusion_model": "independent_cascade",
        }
    raise AssertionError(op)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_hand_computed_outputs_pass_the_correct_scope(catalog, cases, operation):
    case = cases[operation]
    checked = grade_output(catalog, case, authored_output(case))
    assert checked["checks_passed"], checked
    assert checked["numerical_accuracy_certified"] == (
        operation
        not in {
            "community-detection",
            "personalized-pagerank",
            "influence-maximization",
        }
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_wrong_values_or_identities_fail_even_when_success_flags_are_kept(
    catalog, cases, operation
):
    case = cases[operation]
    output = copy.deepcopy(authored_output(case))
    scalar_fields = {
        "maximum-clique": "maximum_size",
        "k-cliques": "count",
        "maximal-cliques": "returned_count",
        "maximal-bicliques": "returned_count",
        "quasi-cliques": "returned_count",
        "triangle-counting": "global_triangle_count",
        "dynamic-triangle-counting": "net_triangle_change",
        "k-core": "degeneracy",
        "temporal-motif-mining": "count",
        "community-detection": "modularity",
        "linear-assignment": "objective_value",
        "butterfly-counting": "butterfly_count",
        "maximal-biclique-counting": "total_count",
        "densest-subgraph": "density",
        "influence-maximization": "expected_spread",
    }
    if operation in scalar_fields:
        output[scalar_fields[operation]] += 1
    elif operation == "betweenness-centrality":
        output["score_by_vertex"][0]["score"] = False
    elif operation == "connected-components":
        output["component_assignment"][-1]["component"] = 0
    elif operation == "max-flow-min-cut":
        output["flow_assignment"][0]["flow"] = 5
    elif operation == "transitive-closure":
        output["transitive_closure_edges"][-1] = output["transitive_closure_edges"][0]
    elif operation == "k-truss":
        output["truss_number_by_edge"][6]["truss_number"] = 4
    elif operation == "group-steiner-tree":
        output["tree_edges"] = ["link-2"]
    elif operation == "personalized-pagerank":
        output["error_bound_certified"] = True
    elif operation == "graph-motifs":
        output["motifs"][0]["instances"][0][0]["data_vertex"] = "not-in-graph"
    elif operation == "subgraph-isomorphism":
        output["embeddings"][0] = output["embeddings"][1]
    else:
        raise AssertionError(operation)
    checked = grade_output(catalog, case, output)
    assert (
        checked["issues"]
        and not checked["checks_passed"]
        and not checked["numerical_accuracy_certified"]
    )


def test_approximate_error_is_measured_without_inventing_an_acceptance_bound(
    catalog, cases
):
    case = cases["personalized-pagerank"]
    output = authored_output(case)
    for row in output["ranked_vertices"]:
        row["score"] = 0.2
    checked = grade_output(catalog, case, output)
    assert checked["checks_passed"] and not checked["numerical_accuracy_certified"]
    assert checked["measurements"]["maximum_returned_score_absolute_error"] > 0.22
    assert checked["measurements"]["error_acceptance_threshold"] is None
    influence = grade_output(
        catalog,
        cases["influence-maximization"],
        authored_output(cases["influence-maximization"]),
    )
    assert influence["measurements"]["gap_to_exact_best_spread"] == 1
