"""Grade saved outputs against bounded development references, without execution."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from .catalog_reference import LEGACY_OPERATIONS, reference_for_case, selected_graph
from .oracles import adjacency, core_vertices, key, verify_output


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value),
        "Expected a finite numeric value",
    )
    return value


def same_number(actual, expected, field):
    require(
        math.isclose(number(actual), expected, rel_tol=1e-6, abs_tol=1e-6),
        f"Wrong {field}",
    )


def groups(values):
    require(isinstance(values, list), "Expected a list of groups")
    return Counter(tuple(sorted(key(value) for value in group)) for group in values)


def identities(values):
    require(isinstance(values, list), "Expected a list of identities")
    return Counter(map(key, values))


def indexed(rows, id_field, value_field):
    require(isinstance(rows, list), "Expected result rows")
    values = {key(row[id_field]): row[value_field] for row in rows}
    require(len(values) == len(rows), "Duplicate result identities")
    return values


def numeric_rows(actual, expected, id_field, value_field):
    actual = indexed(actual, id_field, value_field)
    expected = indexed(expected, id_field, value_field)
    require(actual.keys() == expected.keys(), "Missing or unexpected result identities")
    for identity, value in expected.items():
        same_number(actual[identity], value, value_field)


def _counts(group_list, ids, field):
    return [
        {
            field: value,
            "count": sum(
                key(value) in {key(member) for member in group} for group in group_list
            ),
        }
        for value in ids
    ]


def _pattern_keys(mappings, pattern, *, query_field, classes):
    query_ids = {key(row["id"]) for row in pattern["vertices"]}
    result = []
    for mapping in mappings:
        assigned = {key(row[query_field]): key(row["data_vertex"]) for row in mapping}
        require(
            len(assigned) == len(mapping) == len(set(assigned.values()))
            and assigned.keys() == query_ids,
            "Pattern mapping is not a full injection",
        )
        if classes:
            edges = [
                (assigned[key(edge["source"])], assigned[key(edge["target"])])
                for edge in pattern["edges"]
            ]
            if not pattern["graph"]["directed"]:
                edges = [tuple(sorted(pair)) for pair in edges]
            result.append((tuple(sorted(assigned.values())), tuple(sorted(edges))))
        else:
            result.append(tuple(sorted(assigned.items())))
    return Counter(result)


def grade_output(catalog, case, output):
    """Check requested values; expose narrower checks for heuristic operations.

    A zero issue count is not a human intent score or proof of optimality for a
    heuristic. PageRank error is measured, not thresholded by an invented bound.
    """
    reference = reference_for_case(case)
    measurements = {}
    issues = []
    task = case["task"]
    operation, parameters = task["operation_id"], task["parameters"]
    try:
        require(task["expected_status"] == "ready", "This case must not execute")
        require(isinstance(output, dict), "Expected an output object")
        expected = reference["expected"]
        required = set(catalog.operation(operation).instruction["required_outputs"])
        if operation != "graph-motifs":
            required |= set(task["optional_outputs"])
        require(
            required <= output.keys(),
            f"Missing requested output fields: {sorted(required - output.keys())}",
        )
        graph = selected_graph(case["graph"], task["intent"]["filters"])
        ids, neighbors = adjacency(
            graph,
            max_vertices=256
            if operation
            in {
                "community-detection",
                "k-core",
                "connected-components",
                "transitive-closure",
            }
            else 12,
        )
        edges = {key(edge["id"]): edge for edge in graph["edges"]}
        if operation in LEGACY_OPERATIONS:
            issues.extend(
                verify_output(
                    graph,
                    {
                        "operation_id": operation,
                        "parameters": parameters,
                        "filters": [],
                        "behavior": "execute",
                    },
                    output,
                )
            )
            require(not issues, "Legacy numerical reference rejected the output")
            scalar_counts = {
                "maximal-cliques": ("returned_count", len(expected.get("groups", []))),
                "maximum-clique": ("maximum_size", expected.get("size")),
                "k-cliques": ("count", expected.get("count")),
                "maximal-bicliques": (
                    "returned_count",
                    len(expected.get("bicliques", [])),
                ),
                "temporal-motif-mining": ("count", expected.get("count")),
            }
            if operation in scalar_counts:
                field, value = scalar_counts[operation]
                same_number(output[field], value, field)
            if (
                operation in {"maximal-cliques", "maximal-bicliques"}
                and "total_count" in task["optional_outputs"]
            ):
                same_number(
                    output["total_count"],
                    len(expected.get("groups", expected.get("bicliques"))),
                    "total_count",
                )
            if operation == "maximum-clique":
                if parameters.get("return_all_ties"):
                    require(
                        groups(output["cliques"]) == groups(expected["groups"]),
                        "Missing maximum-group ties",
                    )
                if "upper_bound" in task["optional_outputs"]:
                    require(
                        number(output["upper_bound"]) >= expected["size"],
                        "Invalid upper bound",
                    )
            elif (
                operation == "k-cliques"
                and "per_vertex_count" in task["optional_outputs"]
            ):
                numeric_rows(
                    output["per_vertex_count"],
                    _counts(expected["groups"], ids, "vertex"),
                    "vertex",
                    "count",
                )
            elif operation == "k-core":
                values = {key(value): 0 for value in ids}
                for threshold in range(1, len(ids)):
                    for index in core_vertices(neighbors, threshold):
                        values[key(ids[index])] = threshold
                numeric_rows(
                    output["core_number_by_vertex"],
                    [{"vertex": v, "core_number": values[key(v)]} for v in ids],
                    "vertex",
                    "core_number",
                )
                same_number(
                    output["degeneracy"], max(values.values(), default=0), "degeneracy"
                )
                if "requested_core_edges" in task["optional_outputs"]:
                    survivors = {key(v) for v in expected["vertices"]}
                    correct = [
                        e["id"]
                        for e in graph["edges"]
                        if key(e["source"]) in survivors
                        and key(e["target"]) in survivors
                    ]
                    require(
                        identities(output["requested_core_edges"])
                        == identities(correct),
                        "Wrong surviving relationships",
                    )
            elif operation == "betweenness-centrality":
                numeric_rows(
                    output["score_by_vertex"], expected["scores"], "vertex", "score"
                )
                if "ranking" in task["optional_outputs"]:
                    numeric_rows(
                        output["ranking"], expected["scores"], "vertex", "score"
                    )
                    scores = [row["score"] for row in output["ranking"]]
                    require(
                        scores == sorted(scores, reverse=True),
                        "Ranking is not descending",
                    )
                if "maximum" in task["optional_outputs"]:
                    maximum = max(row["score"] for row in expected["scores"])
                    same_number(output["maximum"]["score"], maximum, "maximum")
                    require(
                        any(
                            key(row["vertex"]) == key(output["maximum"]["vertex"])
                            and row["score"] == maximum
                            for row in expected["scores"]
                        ),
                        "Wrong maximum-score identity",
                    )
            elif operation == "temporal-motif-mining":
                for occurrence in output["instances"]:
                    a, b, _ = [
                        edges[key(value)]
                        for value in occurrence["edges_in_temporal_order"]
                    ]
                    require(
                        occurrence["vertices_by_role"]
                        == [a["source"], a["target"], b["target"]],
                        "Wrong event-role identities",
                    )
            elif operation == "community-detection":
                assigned = indexed(
                    output["assignment_by_vertex"], "vertex", "community"
                )
                members = defaultdict(list)
                for vertex in ids:
                    members[key(assigned[key(vertex)])].append(vertex)
                same_number(output["community_count"], len(members), "community_count")
                if "communities" in task["optional_outputs"]:
                    actual = {
                        key(row["id"]): identities(row["vertices"])
                        for row in output["communities"]
                    }
                    require(
                        len(actual) == len(output["communities"])
                        and actual
                        == {
                            label: identities(values)
                            for label, values in members.items()
                        },
                        "Communities disagree with assignments",
                    )
                if "edge_cut" in task["optional_outputs"]:
                    same_number(
                        output["edge_cut"],
                        sum(
                            key(assigned[key(e["source"])])
                            != key(assigned[key(e["target"])])
                            for e in graph["edges"]
                        ),
                        "edge_cut",
                    )
        elif operation in {"quasi-cliques", "triangle-counting"}:
            field = "quasi_cliques" if operation == "quasi-cliques" else "triangles"
            require(
                groups(output[field]) == groups(expected["groups"]),
                "Incorrect, duplicated or missing groups",
            )
            count = (
                "returned_count"
                if operation == "quasi-cliques"
                else "global_triangle_count"
            )
            same_number(output[count], expected["count"], count)
            require(
                output[
                    "complete" if operation == "quasi-cliques" else "instances_complete"
                ]
                is True,
                "Incomplete enumeration",
            )
            if "total_count" in task["optional_outputs"]:
                same_number(output["total_count"], expected["count"], "total_count")
            if "per_vertex_count" in task["optional_outputs"]:
                numeric_rows(
                    output["per_vertex_count"],
                    _counts(expected["groups"], ids, "vertex"),
                    "vertex",
                    "count",
                )
            if "per_edge_count" in task["optional_outputs"]:
                counts = [
                    {
                        "edge": edge["id"],
                        "count": sum(
                            {key(edge["source"]), key(edge["target"])}
                            <= {key(v) for v in group}
                            for group in expected["groups"]
                        ),
                    }
                    for edge in graph["edges"]
                ]
                numeric_rows(output["per_edge_count"], counts, "edge", "count")
        elif operation == "dynamic-triangle-counting":
            for field in ("deleted", "inserted"):
                require(
                    groups(output[field + "_triangles"]) == groups(expected[field]),
                    f"Wrong {field} triangles",
                )
                same_number(
                    output[field + "_triangle_count"],
                    len(expected[field]),
                    field + "_triangle_count",
                )
            same_number(
                output["initial_global_triangle_count"],
                expected["initial_count"],
                "initial count",
            )
            same_number(
                output["final_global_triangle_count"],
                expected["final_count"],
                "final count",
            )
            same_number(
                output["net_triangle_change"],
                expected["final_count"] - expected["initial_count"],
                "net change",
            )
            require(
                output["changed_instances_complete"] is True,
                "Incomplete changed instances",
            )
        elif operation in {"graph-motifs", "subgraph-isomorphism"}:
            if operation == "subgraph-isomorphism":
                observed = [
                    {
                        "count": output["count"],
                        "instances": output["embeddings"],
                        "complete": output["embeddings_complete"],
                    }
                ]
                attachments = case["attachments"]["query_graph"]
            else:
                require(
                    len(output["motifs"]) == len(expected["patterns"]),
                    "Wrong number of patterns",
                )
                by_id = {row["motif_id"]: row for row in output["motifs"]}
                require(len(by_id) == len(output["motifs"]), "Duplicate pattern IDs")
                require(
                    all(
                        set(task["optional_outputs"]) <= row.keys()
                        for row in by_id.values()
                    ),
                    "Missing requested per-pattern output fields",
                )
                observed = [
                    {
                        "count": by_id[row["pattern_id"]]["count"],
                        "instances": by_id[row["pattern_id"]]["instances"],
                        "complete": by_id[row["pattern_id"]]["instances_complete"],
                    }
                    for row in expected["patterns"]
                ]
                attachments = case["attachments"]["motifs"]
            for actual, wanted, attachment in zip(
                observed, expected["patterns"], attachments, strict=True
            ):
                same_number(actual["count"], wanted["count"], "pattern count")
                require(actual["complete"] is True, "Incomplete pattern instances")
                classes = (
                    operation == "graph-motifs"
                    and parameters["occurrence_identity"] != "all-embeddings"
                )
                actual_keys = _pattern_keys(
                    actual["instances"],
                    attachment["content"],
                    query_field="motif_vertex"
                    if operation == "graph-motifs"
                    else "query_vertex",
                    classes=classes,
                )
                correct_keys = _pattern_keys(
                    wanted["mappings"],
                    attachment["content"],
                    query_field="query_vertex",
                    classes=classes,
                )
                require(
                    actual_keys == correct_keys,
                    "Wrong pattern mappings or occurrence identity",
                )
        elif operation == "connected-components":
            assigned = indexed(output["component_assignment"], "vertex", "component")
            require(
                assigned.keys() == {key(value) for value in ids},
                "Incomplete component assignment",
            )
            components = defaultdict(list)
            for vertex in ids:
                components[key(assigned[key(vertex)])].append(vertex)
            require(
                groups(list(components.values())) == groups(expected["groups"]),
                "Wrong connectivity partition",
            )
            same_number(
                output["component_count"], len(expected["groups"]), "component_count"
            )
            require(
                Counter(output["component_sizes"])
                == Counter(map(len, expected["groups"])),
                "Wrong component sizes",
            )
            for size in output["component_sizes"]:
                number(size)
        elif operation == "transitive-closure":
            require(
                Counter(
                    (key(row["source"]), key(row["target"]))
                    for row in output["transitive_closure_edges"]
                )
                == Counter((key(a), key(b)) for a, b in expected["pairs"]),
                "Wrong reflexive reachability pairs",
            )
            same_number(
                output["reachable_pair_count"],
                len(expected["pairs"]),
                "reachable_pair_count",
            )
            require(
                output["complete"] is True and output["reachability_results"] == [],
                "Unexpected reachability status",
            )
        elif operation == "max-flow-min-cut":
            for field in ("max_flow_value", "min_cut_value"):
                same_number(output[field], expected[field], field)
            require(output["optimal"] is True, "Flow optimality not established")
            source_side = identities(output["source_side_vertices"])
            require(
                all(count == 1 for count in source_side.values())
                and source_side.keys() <= {key(value) for value in ids},
                "Invalid cut membership",
            )
            require(
                key(parameters["source"]) in source_side
                and key(parameters["sink"]) not in source_side,
                "Cut does not separate endpoints",
            )
            cut = [
                edge["id"]
                for edge in graph["edges"]
                if key(edge["source"]) in source_side
                and key(edge["target"]) not in source_side
            ]
            require(
                identities(output["min_cut_edges"]) == identities(cut),
                "Cut edges disagree with source-side membership",
            )
            flows = indexed(output["flow_assignment"], "edge", "flow")
            require(flows.keys() == edges.keys(), "Incomplete flow assignment")
            net = {key(value): 0.0 for value in ids}
            cut_capacity = 0
            for identity, edge in edges.items():
                capacity = edge
                for part in (task["intent"].get("weight_attribute") or "weight").split(
                    "."
                ):
                    capacity = capacity[part]
                flow = number(flows[identity])
                require(0 <= flow <= capacity, "Flow exceeds a link capacity")
                net[key(edge["source"])] += flow
                net[key(edge["target"])] -= flow
                if key(edge["id"]) in identities(cut):
                    cut_capacity += capacity
            same_number(cut_capacity, expected["min_cut_value"], "cut capacity")
            for vertex, value in net.items():
                target = (
                    expected["max_flow_value"]
                    if vertex == key(parameters["source"])
                    else -expected["max_flow_value"]
                    if vertex == key(parameters["sink"])
                    else 0
                )
                same_number(value, target, "flow conservation")
        elif operation == "linear-assignment":
            same_number(
                output["objective_value"],
                expected["objective_value"],
                "assignment objective",
            )
            same_number(
                output["matching_size"], expected["matching_size"], "matching size"
            )
            require(
                output["optimal"] is True and output.get("feasible") is True,
                "Assignment not feasible and optimal",
            )
            require(
                any(
                    identities(output["matching_edges"]) == identities(edges)
                    for edges in expected["optimal_edge_sets"]
                ),
                "Matching is not a minimum-cost perfect assignment",
            )
        elif operation in {"butterfly-counting", "maximal-biclique-counting"}:
            field = (
                "butterfly_count"
                if operation == "butterfly-counting"
                else "total_count"
            )
            same_number(output[field], expected["count"], field)
            require(output["complete"] is True, "Count is incomplete")
        elif operation == "k-truss":
            numeric_rows(
                output["truss_number_by_edge"],
                expected["edges"],
                "edge",
                "truss_number",
            )
            same_number(
                output["maximum_truss_number"],
                expected["maximum"],
                "maximum_truss_number",
            )
        elif operation == "densest-subgraph":
            same_number(output["density"], expected["density"], "density")
            same_number(output.get("clique_order", 2), expected["clique_order"], "clique_order")
            require(output["optimal"] is True, "Density optimality not established")
            match = next(
                (
                    row
                    for row in expected["optimal_groups"]
                    if identities(row["vertices"]) == identities(output["vertices"])
                ),
                None,
            )
            require(match is not None, "Returned set is not densest")
            same_number(output.get("clique_count", output["induced_edge_value"]), match["clique_count"], "clique_count")
            same_number(
                output["induced_edge_value"],
                match["induced_edge_value"],
                "induced_edge_value",
            )
        elif operation == "group-steiner-tree":
            require(
                output["feasible"] is expected["feasible"]
                and output["optimal"] is True,
                "Wrong tree feasibility or optimality",
            )
            if expected["feasible"]:
                same_number(
                    output["tree_weight"], expected["tree_weight"], "tree_weight"
                )
                require(
                    any(
                        identities(tree["edges"]) == identities(output["tree_edges"])
                        and identities(tree["vertices"])
                        == identities(output["selected_vertices"])
                        for tree in expected["optimal_trees"]
                    ),
                    "Returned edges and vertices do not describe an optimal group-covering tree",
                )
        elif operation == "personalized-pagerank":
            ranked = output["ranked_vertices"]
            require(
                len(ranked) == min(parameters["top_k"], len(ids)),
                "Wrong number of ranked vertices",
            )
            scores = indexed(ranked, "vertex", "score")
            require(
                scores.keys() <= {key(v) for v in ids},
                "Ranked entity absent from input",
            )
            for score in scores.values():
                require(0 <= number(score) <= 1, "Invalid PageRank probability")
            require(
                [row["rank"] for row in ranked] == list(range(1, len(ranked) + 1)),
                "Invalid rank indexes",
            )
            require(
                all(type(row["rank"]) is int for row in ranked),
                "Ranks must be integers",
            )
            require(
                list(scores.values()) == sorted(scores.values(), reverse=True),
                "Ranking is not descending",
            )
            require(
                output["approximate"] is True
                and output["error_bound_certified"] is False
                and output["error_bound"] is None,
                "Invented PageRank guarantee",
            )
            require(
                output["complete"] is (parameters["top_k"] >= len(ids)),
                "Wrong top-k completeness",
            )
            same_number(
                output["restart_probability_used"],
                parameters["restart_probability"],
                "restart probability",
            )
            same_number(
                output["epsilon_used"], parameters["epsilon"], "sampling tolerance"
            )
            truth = {key(row["vertex"]): row["score"] for row in expected["scores"]}
            measurements["maximum_returned_score_absolute_error"] = max(
                (abs(score - truth[identity]) for identity, score in scores.items()),
                default=0,
            )
            measurements["returned_score_mass"] = sum(scores.values())
            measurements["error_acceptance_threshold"] = None
        elif operation == "influence-maximization":
            match = next(
                (
                    row
                    for row in expected["seed_sets"]
                    if identities(row["seeds"]) == identities(output["seed_set"])
                ),
                None,
            )
            require(match is not None, "Seed selection violates identity or budget")
            same_number(
                output["expected_spread"],
                match["spread"],
                "deterministic-probability spread",
            )
            require(
                output["guarantee_met"] is False
                and output["diffusion_model"] == "independent_cascade",
                "Wrong diffusion model or invented guarantee",
            )
            same_number(
                output["sample_count"], parameters["sample_count"], "sample_count"
            )
            require(
                len(output["prefix_spread"]) == len(output["seed_set"]),
                "Missing prefix spread",
            )
            if len(output["seed_set"]) == 1:
                same_number(
                    output["prefix_spread"][0], match["spread"], "prefix spread"
                )
            measurements["gap_to_exact_best_spread"] = (
                expected["best_possible_spread"] - match["spread"]
            )
        else:
            raise ValueError(f"No output grader for {operation}")
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as error:
        if not issues:
            issues.append(str(error))
    return {
        "issues": issues,
        "checks_passed": not issues,
        "verification_scope": reference["kind"],
        "measurements": measurements,
        "numerical_accuracy_certified": reference["kind"] == "exact_enumeration"
        and not issues,
    }
