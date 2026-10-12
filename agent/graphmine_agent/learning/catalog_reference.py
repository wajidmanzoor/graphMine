"""Bounded CPU references for current-catalog synthetic development cases.

These compute from input records, independently of native outputs and answer
rendering. Approximate and heuristic operations retain their actual guarantees.
Never call these exhaustive routines on unbounded user uploads.
"""

from __future__ import annotations

import copy
import itertools
import operator
from fractions import Fraction

from .oracles import adjacency, all_cliques, expected_answer, key

LEGACY_OPERATIONS = {
    "maximal-cliques",
    "maximum-clique",
    "k-cliques",
    "k-core",
    "maximal-bicliques",
    "betweenness-centrality",
    "community-detection",
    "temporal-motif-mining",
}


def selected_graph(graph, filters):
    """Independent projection, including numeric/string threshold comparisons."""
    selected = copy.deepcopy(graph)
    comparisons = {
        "gt": operator.gt,
        "gte": operator.ge,
        "lt": operator.lt,
        "lte": operator.le,
    }
    for condition in filters:
        kept = []
        for row in selected[condition["target"]]:
            value = row
            try:
                for part in condition["field"].split("."):
                    value = value[part]
            except (KeyError, TypeError):
                continue
            other, operation = condition["value"], condition["operator"]
            if operation in {"eq", "ne"}:
                match = (key(value) == key(other)) == (operation == "eq")
            elif operation == "in":
                if not isinstance(other, list):
                    raise ValueError("Membership filter requires a list")
                match = key(value) in {key(item) for item in other}
            elif (
                value is None
                or other is None
                or isinstance(value, bool)
                or isinstance(other, bool)
            ):
                match = False
            else:
                numeric = isinstance(value, (int, float)) and isinstance(
                    other, (int, float)
                )
                if not numeric and not (
                    isinstance(value, str) and isinstance(other, str)
                ):
                    raise ValueError("Incomparable filter operands")
                match = comparisons[operation](value, other)
            if match:
                kept.append(row)
        selected[condition["target"]] = kept
    identifiers = {key(vertex["id"]) for vertex in selected["vertices"]}
    selected["edges"] = [
        edge
        for edge in selected["edges"]
        if key(edge["source"]) in identifiers and key(edge["target"]) in identifiers
    ]
    return selected


def subsets(values, minimum=1):
    values = list(values)
    for size in range(minimum, len(values) + 1):
        yield from itertools.combinations(values, size)


def closure(neighbors):
    result = []
    for start in range(len(neighbors)):
        reached, pending = {start}, [start]
        while pending:
            vertex = pending.pop()
            for neighbor in neighbors[vertex] - reached:
                reached.add(neighbor)
                pending.append(neighbor)
        result.append(reached)
    return result


def pattern_mappings(graph, pattern, *, induced=False, ignore_labels=True):
    ids, neighbors = adjacency(graph)
    query_ids, query_neighbors = adjacency(pattern)
    if graph["graph"]["directed"] != pattern["graph"]["directed"]:
        raise ValueError("Reference pattern direction must match the dataset")
    matches = []
    for mapping in itertools.permutations(range(len(ids)), len(query_ids)):
        if not ignore_labels and any(
            pattern["vertices"][a].get("label") != graph["vertices"][b].get("label")
            for a, b in enumerate(mapping)
        ):
            continue
        if all(
            (mapping[b] in neighbors[mapping[a]])
            if b in query_neighbors[a]
            else (not induced or mapping[b] not in neighbors[mapping[a]])
            for a in range(len(query_ids))
            for b in range(len(query_ids))
            if a != b
        ):
            matches.append(
                [
                    {"query_vertex": query_ids[a], "data_vertex": ids[b]}
                    for a, b in enumerate(mapping)
                ]
            )
    return matches


def pagerank(neighbors, seed, restart):
    values = [float(index == seed) for index in range(len(neighbors))]
    for _ in range(1000):
        following = [0.0] * len(values)
        following[seed] = restart
        for vertex, probability in enumerate(values):
            targets = neighbors[vertex] or {seed}
            for target in targets:
                following[target] += (1 - restart) * probability / len(targets)
        if max(abs(a - b) for a, b in zip(values, following, strict=True)) < 1e-13:
            return following
        values = following
    raise ValueError("PageRank reference did not converge")


def reference_for_case(case):
    task = case["task"]
    if task["expected_status"] != "ready":
        return {"kind": "non_executable", "expected_status": task["expected_status"]}
    graph = copy.deepcopy(selected_graph(case["graph"], task["intent"]["filters"]))
    scalable = task["operation_id"] in {
        "community-detection",
        "k-core",
        "connected-components",
        "transitive-closure",
    }
    vertex_limit, edge_limit = (256, 4096) if scalable else (8, 16)
    if len(graph["vertices"]) > vertex_limit or len(graph["edges"]) > edge_limit:
        raise ValueError(
            f"References for this operation are limited to {vertex_limit} vertices "
            f"and {edge_limit} edges"
        )
    ids, neighbors = adjacency(graph, max_vertices=vertex_limit)
    index = {key(value): position for position, value in enumerate(ids)}
    operation, parameters = task["operation_id"], task["parameters"]
    if operation in {
        "max-flow-min-cut",
        "linear-assignment",
        "group-steiner-tree",
        "influence-maximization",
    }:
        field = task["intent"].get("weight_attribute") or "weight"
        for edge in graph["edges"]:
            if parameters.get("unit_capacity"):
                edge["weight"] = 1
            else:
                value = edge
                for part in field.split("."):
                    value = value[part]
                edge["weight"] = value
    legacy = {
        "operation_id": operation,
        "parameters": parameters,
        "filters": [],
        "behavior": "execute",
    }
    if operation in LEGACY_OPERATIONS:
        expected = expected_answer(graph, legacy)
        return {
            "kind": "partition_and_score_consistency"
            if operation == "community-detection"
            else "exact_enumeration",
            "expected": expected,
        }
    if operation == "quasi-cliques":
        ratio = Fraction(str(parameters["minimum_degree_ratio"]))
        groups = [
            [ids[v] for v in group]
            for group in subsets(range(len(ids)), parameters["minimum_size"])
            if all(
                len(neighbors[v].intersection(group)) >= ratio * (len(group) - 1)
                for v in group
            )
        ]
        # The executable cuQC profile returns inclusion-maximal qualifying sets.
        # Quasi-clique validity is not hereditary, so compare every larger valid
        # set rather than checking only one-vertex extensions.
        groups = [
            group
            for group in groups
            if not any(set(map(key, group)) < set(map(key, other)) for other in groups)
        ]
        expected = {"groups": groups, "count": len(groups)}
    elif operation == "triangle-counting":
        groups = [
            [ids[v] for v in group]
            for group in all_cliques(neighbors)
            if len(group) == 3
        ]
        expected = {"groups": groups, "count": len(groups)}
    elif operation == "dynamic-triangle-counting":

        def triangles(value):
            vertex_ids, adjacent = adjacency(value)
            return {
                tuple(sorted(key(vertex_ids[v]) for v in group))
                for group in all_cliques(adjacent)
                if len(group) == 3
            }

        updates = case["attachments"]["updates"][0]["content"]["updates"]
        initial = triangles(graph)
        changed = copy.deepcopy(graph)
        for update in updates:
            if update["kind"] not in {"delete", "insert"}:
                raise ValueError("Unknown update kind")
            pair = {key(update["source"]), key(update["target"])}
            if len(pair) != 2 or not pair <= set(index):
                raise ValueError("Invalid update endpoints")
            if update["kind"] == "delete":
                matches = [
                    edge
                    for edge in changed["edges"]
                    if {key(edge["source"]), key(edge["target"])} == pair
                ]
                if len(matches) != 1:
                    raise ValueError("Invalid deletion")
                changed["edges"].remove(matches[0])
        after_deletions = triangles(changed)
        for number, update in enumerate(updates):
            if update["kind"] == "insert":
                pair = {key(update["source"]), key(update["target"])}
                if any(
                    {key(edge["source"]), key(edge["target"])} == pair
                    for edge in changed["edges"]
                ):
                    raise ValueError("Invalid insertion")
                changed["edges"].append(
                    {
                        "id": f"insert-{number}",
                        "source": update["source"],
                        "target": update["target"],
                    }
                )
        final = triangles(changed)
        original_ids = {key(value): value for value in ids}
        decode = lambda groups: [
            [original_ids[value] for value in group] for group in sorted(groups)
        ]
        expected = {
            "initial_count": len(initial),
            "final_count": len(final),
            "deleted": decode(initial - after_deletions),
            "inserted": decode(final - after_deletions),
        }
    elif operation in {"graph-motifs", "subgraph-isomorphism"}:
        name = "motifs" if operation == "graph-motifs" else "query_graph"
        patterns = []
        for item in case["attachments"][name]:
            pattern = item["content"]
            mappings = pattern_mappings(
                graph,
                pattern,
                induced=parameters.get("induced", False),
                ignore_labels=parameters.get("ignore_vertex_labels", True),
            )
            if (
                operation == "graph-motifs"
                and parameters["occurrence_identity"] != "all-embeddings"
            ):
                classes = {}
                for mapping in mappings:
                    assigned = {
                        key(row["query_vertex"]): key(row["data_vertex"])
                        for row in mapping
                    }
                    mapped_edges = [
                        (assigned[key(edge["source"])], assigned[key(edge["target"])])
                        for edge in pattern["edges"]
                    ]
                    if not pattern["graph"]["directed"]:
                        mapped_edges = [tuple(sorted(pair)) for pair in mapped_edges]
                    identity = (
                        tuple(sorted(assigned.values())),
                        tuple(sorted(mapped_edges)),
                    )
                    classes.setdefault(identity, mapping)
                mappings = list(classes.values())
            patterns.append(
                {
                    "pattern_id": pattern["graph"]["id"],
                    "count": len(mappings),
                    "mappings": mappings,
                }
            )
        expected = {"patterns": patterns}
    elif operation in {"connected-components", "transitive-closure"}:
        if (
            operation == "connected-components"
            and parameters["connectivity_mode"] == "weakly_connected"
        ):
            neighbors = [set(row) for row in neighbors]
            for vertex, row in enumerate(list(map(set, neighbors))):
                for other in row:
                    neighbors[other].add(vertex)
        reach = closure(neighbors)
        if operation == "transitive-closure":
            expected = {
                "pairs": [
                    [ids[a], ids[b]] for a in range(len(ids)) for b in sorted(reach[a])
                ]
            }
        else:
            components = {
                tuple(j for j in range(len(ids)) if j in reach[i] and i in reach[j])
                for i in range(len(ids))
            }
            expected = {
                "groups": [[ids[v] for v in group] for group in sorted(components)]
            }
    elif operation == "max-flow-min-cut":
        source, sink = index[key(parameters["source"])], index[key(parameters["sink"])]
        cuts = []
        for group in subsets(range(len(ids))):
            if source in group and sink not in group:
                cuts.append(
                    sum(
                        edge["weight"]
                        for edge in graph["edges"]
                        if index[key(edge["source"])] in group
                        and index[key(edge["target"])] not in group
                    )
                )
        expected = {"max_flow_value": min(cuts), "min_cut_value": min(cuts)}
    elif operation == "linear-assignment":
        left = [v["id"] for v in graph["vertices"] if v["attributes"]["side"] == "left"]
        right = [
            v["id"] for v in graph["vertices"] if v["attributes"]["side"] == "right"
        ]
        by_pair = {
            frozenset((key(e["source"]), key(e["target"]))): e for e in graph["edges"]
        }
        choices = []
        for order in itertools.permutations(right):
            edges = [
                by_pair[frozenset((key(a), key(b)))]
                for a, b in zip(left, order, strict=True)
            ]
            choices.append((sum(e["weight"] for e in edges), [e["id"] for e in edges]))
        optimum = min(cost for cost, _ in choices)
        expected = {
            "objective_value": optimum,
            "matching_size": len(left),
            "optimal_edge_sets": [edges for cost, edges in choices if cost == optimum],
        }
    elif operation == "butterfly-counting":
        left = [
            i
            for i, v in enumerate(graph["vertices"])
            if v["attributes"]["side"] == "left"
        ]
        right = [i for i in range(len(ids)) if i not in left]
        expected = {
            "count": sum(
                all(b in neighbors[a] for a in a_pair for b in b_pair)
                for a_pair in itertools.combinations(left, 2)
                for b_pair in itertools.combinations(right, 2)
            )
        }
    elif operation == "maximal-biclique-counting":
        expected = expected_answer(
            graph,
            {
                **legacy,
                "operation_id": "maximal-bicliques",
                "parameters": {"minimum_left_size": 1, "minimum_right_size": 1},
            },
        )
        expected["count"] = len(expected["bicliques"])
    elif operation == "k-truss":
        pairs = {
            tuple(sorted((index[key(e["source"])], index[key(e["target"])]))): e["id"]
            for e in graph["edges"]
        }
        numbers = {pair: 2 for pair in pairs}
        for threshold in range(3, len(ids) + 1):
            active = set(pairs)
            while True:
                low = {
                    pair
                    for pair in active
                    if sum(
                        tuple(sorted((pair[0], other))) in active
                        and tuple(sorted((pair[1], other))) in active
                        for other in range(len(ids))
                        if other not in pair
                    )
                    < threshold - 2
                }
                if not low:
                    break
                active -= low
            for pair in active:
                numbers[pair] = threshold
        expected = {
            "edges": [
                {"edge": identifier, "truss_number": numbers[pair]}
                for pair, identifier in pairs.items()
            ],
            "maximum": max(numbers.values(), default=0),
        }
    elif operation == "densest-subgraph":
        order = parameters.get("clique_order", 2)
        cliques = [] if order > len(ids) else [group for group in itertools.combinations(range(len(ids)), order)
                   if all(b in neighbors[a] for a, b in itertools.combinations(group, 2))]
        choices = []
        for group in subsets(range(len(ids))):
            edges = sum(len(neighbors[v].intersection(group)) for v in group) // 2
            count = sum(set(clique).issubset(group) for clique in cliques)
            choices.append((Fraction(count, len(group)), edges, count, group))
        optimum = max(density for density, _, _, _ in choices)
        expected = {
            "density": float(optimum),
            "clique_order": order,
            "optimal_groups": [
                {"vertices": [ids[v] for v in group], "induced_edge_value": edges, "clique_count": count}
                for density, edges, count, group in choices
                if density == optimum
            ],
        }
    elif operation == "personalized-pagerank":
        scores = pagerank(
            neighbors,
            index[key(parameters["seed_vertex"])],
            parameters["restart_probability"],
        )
        return {
            "kind": "approximate_scores_measured_against_stationary_distribution",
            "expected": {
                "scores": [
                    {"vertex": value, "score": score}
                    for value, score in zip(ids, scores, strict=True)
                ]
            },
            "acceptance": "Measure error; do not treat epsilon as a certified per-run error bound or require exact stochastic scores.",
        }
    elif operation == "group-steiner-tree":
        groups = [{key(v) for v in group} for group in parameters["groups"]]
        choices = []
        for value in ids:
            if all(key(value) in group for group in groups):
                choices.append((0, [], [value]))
        for edges in subsets(graph["edges"]):
            vertices = {
                key(edge[end]) for edge in edges for end in ("source", "target")
            }
            if len(edges) != len(vertices) - 1 or not all(
                vertices & group for group in groups
            ):
                continue
            connected = {next(iter(vertices))}
            while True:
                expanded = connected | {
                    key(edge[end])
                    for edge in edges
                    if key(edge["source"]) in connected
                    or key(edge["target"]) in connected
                    for end in ("source", "target")
                }
                if expanded == connected:
                    break
                connected = expanded
            if connected == vertices:
                choices.append(
                    (
                        sum(edge["weight"] for edge in edges),
                        [edge["id"] for edge in edges],
                        [value for value in ids if key(value) in vertices],
                    )
                )
        optimum = min((cost for cost, _, _ in choices), default=None)
        expected = {
            "feasible": optimum is not None,
            "tree_weight": optimum,
            "optimal_trees": [
                {"edges": edges, "vertices": vertices}
                for cost, edges, vertices in choices
                if cost == optimum
            ],
        }
    elif operation == "influence-maximization":
        if any(edge["weight"] not in (0, 1) for edge in graph["edges"]):
            raise ValueError(
                "This influence reference requires deterministic 0/1 probabilities"
            )
        active = copy.deepcopy(graph)
        active["edges"] = [edge for edge in active["edges"] if edge["weight"] == 1]
        _, active_neighbors = adjacency(active)
        reach = closure(active_neighbors)
        candidates = [
            {
                "seeds": [ids[v] for v in group],
                "spread": len(set().union(*(reach[v] for v in group))),
            }
            for group in itertools.combinations(
                range(len(ids)), parameters["seed_set_size"]
            )
        ]
        return {
            "kind": "exact_spread_for_returned_seeds_without_optimality_requirement",
            "expected": {
                "seed_sets": candidates,
                "best_possible_spread": max(row["spread"] for row in candidates),
            },
        }
    else:
        raise ValueError(f"No independent reference for {operation}")
    return {"kind": "exact_enumeration", "expected": expected}
