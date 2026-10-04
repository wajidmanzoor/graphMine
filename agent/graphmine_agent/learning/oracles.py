"""Exhaustive small-graph references independent of the native adapters and answers.

These deliberately favor transparency over scale. Never apply them to uploaded
production graphs: their caller must supply a bounded synthetic graph.
"""

from __future__ import annotations

import itertools
import json
import math
from collections import Counter, deque
from fractions import Fraction
from typing import Any

MAX_VERTICES = 12
MAX_EVENTS = 24


def key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def adjacency(graph: dict) -> tuple[list[Any], list[set[int]]]:
    identifiers = [row["id"] for row in graph["vertices"]]
    if len(identifiers) > MAX_VERTICES:
        raise ValueError(f"Reference oracles are limited to {MAX_VERTICES} vertices")
    index = {key(value): position for position, value in enumerate(identifiers)}
    if len(index) != len(identifiers):
        raise ValueError("Duplicate entity IDs")
    neighbors = [set() for _ in identifiers]
    for edge in graph["edges"]:
        a, b = index[key(edge["source"])], index[key(edge["target"])]
        if a == b:
            raise ValueError("Synthetic reference graphs must have no self loops")
        neighbors[a].add(b)
        if not graph["graph"]["directed"]:
            neighbors[b].add(a)
    return identifiers, neighbors


def selected_graph(graph: dict, filters: list[dict]) -> dict:
    """Independent oracle projection; intentionally not graph_context.project_graph."""
    records = {"vertices": list(graph["vertices"]), "edges": list(graph["edges"])}
    for condition in filters:
        if condition["operator"] != "eq":
            raise ValueError("This generator's reference filters support equality only")

        def matches(row, condition=condition):
            value = row
            for component in condition["field"].split("."):
                value = value.get(component) if isinstance(value, dict) else None
            return (
                type(value) is type(condition["value"]) and value == condition["value"]
            )

        records[condition["target"]] = [
            row for row in records[condition["target"]] if matches(row)
        ]
    ids = {key(row["id"]) for row in records["vertices"]}
    records["edges"] = [
        edge
        for edge in records["edges"]
        if key(edge["source"]) in ids and key(edge["target"]) in ids
    ]
    return {"graph": graph["graph"], **records}


def all_cliques(neighbors: list[set[int]]) -> list[tuple[int, ...]]:
    return [
        group
        for size in range(1, len(neighbors) + 1)
        for group in itertools.combinations(range(len(neighbors)), size)
        if all(b in neighbors[a] for a, b in itertools.combinations(group, 2))
    ]


def core_vertices(neighbors: list[set[int]], threshold: int) -> list[int]:
    remaining = set(range(len(neighbors)))
    while True:
        removed = {v for v in remaining if len(neighbors[v] & remaining) < threshold}
        if not removed:
            return sorted(remaining)
        remaining -= removed


def betweenness(neighbors: list[set[int]]) -> list[float]:
    """Enumerate shortest paths for ordered endpoint pairs; exclude endpoints."""
    scores = [Fraction(0) for _ in neighbors]
    for source in range(len(neighbors)):
        paths: dict[int, list[list[int]]] = {source: [[source]]}
        distance = {source: 0}
        queue = deque([source])
        while queue:
            current = queue.popleft()
            for target in sorted(neighbors[current]):
                if target not in distance:
                    distance[target] = distance[current] + 1
                    paths[target] = []
                    queue.append(target)
                if distance[target] == distance[current] + 1:
                    paths[target].extend(path + [target] for path in paths[current])
        for target, routes in paths.items():
            if target == source:
                continue
            for path in routes:
                for vertex in path[1:-1]:
                    scores[vertex] += Fraction(1, len(routes))
    return [float(score) for score in scores]


def expected_answer(graph: dict, task: dict) -> dict:
    graph = selected_graph(graph, task.get("filters", []))
    ids, neighbors = adjacency(graph)
    operation = task.get("operation_id")
    parameters = task.get("parameters", {})
    if task["behavior"] != "execute":
        return {"behavior": task["behavior"], "reason": task["reason"]}
    if operation in {"maximal-cliques", "maximum-clique", "k-cliques"}:
        groups = all_cliques(neighbors)
        if operation == "maximum-clique":
            size = max(map(len, groups), default=0)
            groups = [group for group in groups if len(group) == size]
        elif operation == "maximal-cliques":
            groups = [
                group
                for group in groups
                if len(group) >= parameters["minimum_clique_size"]
                and not any(set(group) < set(other) for other in groups)
            ]
        else:
            groups = [group for group in groups if len(group) == parameters["k"]]
        return {
            "groups": [[ids[index] for index in group] for group in groups],
            "size": max(map(len, groups), default=0),
            "count": len(groups),
        }
    if operation == "k-core":
        return {
            "vertices": [
                ids[index]
                for index in core_vertices(neighbors, parameters["requested_k"])
            ]
        }
    if operation == "betweenness-centrality":
        return {
            "scores": [
                {"vertex": identifier, "score": score}
                for identifier, score in zip(ids, betweenness(neighbors), strict=True)
            ]
        }
    if operation == "community-detection":
        # An arbitrary optimal partition is not a gold label for a heuristic.
        return {"check": "partition_coverage_and_modularity", "vertex_ids": ids}
    if operation == "maximal-bicliques":
        left = [
            index
            for index, row in enumerate(graph["vertices"])
            if row["type"] == "customer"
        ]
        right = [index for index in range(len(ids)) if index not in left]
        candidates = [
            (set(a), set(b))
            for na in range(parameters["minimum_left_size"], len(left) + 1)
            for nb in range(parameters["minimum_right_size"], len(right) + 1)
            for a in itertools.combinations(left, na)
            for b in itertools.combinations(right, nb)
            if all(v in neighbors[u] for u in a for v in b)
        ]
        return {
            "bicliques": [
                {
                    "left": [ids[i] for i in sorted(a)],
                    "right": [ids[i] for i in sorted(b)],
                }
                for a, b in candidates
                if not any(
                    a <= c and b <= d and (a != c or b != d) for c, d in candidates
                )
            ]
        }
    if operation == "temporal-motif-mining":
        if len(graph["edges"]) > MAX_EVENTS:
            raise ValueError("Temporal reference oracle event limit exceeded")
        instances = []
        for a, b, c in itertools.permutations(graph["edges"], 3):
            if (
                not a["timestamp"]
                < b["timestamp"]
                < c["timestamp"]
                <= a["timestamp"] + parameters["max_time_span"]
            ):
                continue
            if (
                a["target"] == b["source"]
                and b["target"] == c["target"]
                and a["source"] == c["source"]
                and len({key(a["source"]), key(a["target"]), key(b["target"])}) == 3
            ):
                instances.append([a["id"], b["id"], c["id"]])
        return {"event_ids": instances, "count": len(instances)}
    raise ValueError(f"No independent reference for {operation}")


def verify_output(graph: dict, task: dict, output: dict) -> list[str]:
    """Validate native results, including membership, not just aggregate counts."""
    expected = expected_answer(graph, task)
    operation = task["operation_id"]
    groups = lambda values: Counter(
        tuple(sorted(key(v) for v in group)) for group in values
    )

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    try:
        if operation in {"maximal-cliques", "k-cliques"}:
            require(
                groups(output["cliques"]) == groups(expected["groups"]),
                "Returned groups differ from exhaustive oracle",
            )
            require(output.get("complete") is True, "Incomplete materialization")
            require(
                output.get("count" if operation == "k-cliques" else "returned_count")
                == expected["count"],
                "Group count differs from exhaustive oracle",
            )
        elif operation == "maximum-clique":
            require(
                output["maximum_size"] == expected["size"]
                and output["optimal"] is True,
                "Maximum size/optimality differs",
            )
            actual = groups(output["cliques"])
            require(
                actual and not actual - groups(expected["groups"]),
                "Returned group is not an exact maximum",
            )
        elif operation == "k-core":
            require(
                Counter(map(key, output["requested_core_vertices"]))
                == Counter(map(key, expected["vertices"])),
                "Wrong surviving entities",
            )
        elif operation == "betweenness-centrality":
            actual = {
                key(row["vertex"]): row["score"] for row in output["score_by_vertex"]
            }
            require(
                len(actual)
                == len(output["score_by_vertex"])
                == len(expected["scores"]),
                "Duplicate or missing score rows",
            )
            for row in expected["scores"]:
                require(
                    math.isclose(
                        actual[key(row["vertex"])],
                        row["score"],
                        rel_tol=1e-5,
                        abs_tol=1e-5,
                    ),
                    "Wrong shortest-route score",
                )
        elif operation == "maximal-bicliques":
            pairs = lambda values: Counter(
                (
                    tuple(sorted(map(key, row["left"]))),
                    tuple(sorted(map(key, row["right"]))),
                )
                for row in values
            )
            require(
                pairs(output["bicliques"]) == pairs(expected["bicliques"]),
                "Wrong customer/product bundles",
            )
            require(output.get("complete") is True, "Incomplete materialization")
            require(
                output.get("returned_count") == len(expected["bicliques"]),
                "Wrong bundle count",
            )
        elif operation == "temporal-motif-mining":
            require(
                output["count"] == expected["count"]
                and output["instances_complete"] is True,
                "Wrong sequence count/completeness",
            )
            require(
                Counter(
                    tuple(map(key, row["edges_in_temporal_order"]))
                    for row in output["instances"]
                )
                == Counter(tuple(map(key, row)) for row in expected["event_ids"]),
                "Wrong event identities/order",
            )
        elif operation == "community-detection":
            selected = selected_graph(graph, task.get("filters", []))
            ids, neighbors = adjacency(selected)
            assignments = output["assignment_by_vertex"]
            labels = {key(row["vertex"]): key(row["community"]) for row in assignments}
            require(
                len(labels) == len(assignments) == len(ids)
                and set(labels) == {key(v) for v in ids},
                "Partition does not cover each entity exactly once",
            )
            require(
                output["community_count"] == len(set(labels.values())),
                "Wrong group count",
            )
            m = sum(map(len, neighbors)) / 2
            q = 0.0
            if m:
                for label in set(labels.values()):
                    members = {
                        i
                        for i, identifier in enumerate(ids)
                        if labels[key(identifier)] == label
                    }
                    internal = sum(len(neighbors[i] & members) for i in members) / 2
                    volume = sum(len(neighbors[i]) for i in members)
                    q += internal / m - (volume / (2 * m)) ** 2
            require(
                math.isclose(output["modularity"], q, rel_tol=1e-5, abs_tol=1e-5),
                "Modularity does not match the returned partition",
            )
        else:
            raise ValueError(f"No result checker for {operation}")
    except (KeyError, TypeError, ValueError) as error:
        return [str(error)]
    return []


def isomorphic(left: dict, right: dict) -> bool:
    """Exact bounded topology deduplication, ignoring names and attributes."""
    if left["graph"]["directed"] != right["graph"]["directed"]:
        return False
    _, a = adjacency(left)
    _, b = adjacency(right)
    if len(a) != len(b) or sorted(map(len, a)) != sorted(map(len, b)):
        return False
    incoming_a = [sum(i in row for row in a) for i in range(len(a))]
    incoming_b = [sum(i in row for row in b) for i in range(len(b))]
    candidates = {
        i: [
            j
            for j in range(len(b))
            if (len(a[i]), incoming_a[i]) == (len(b[j]), incoming_b[j])
        ]
        for i in range(len(a))
    }
    order = sorted(range(len(a)), key=lambda i: (len(candidates[i]), -len(a[i])))

    def search(mapping: dict[int, int]) -> bool:
        if len(mapping) == len(a):
            return True
        i = order[len(mapping)]
        for j in candidates[i]:
            if j in mapping.values() or any(
                ((u in a[i]) != (v in b[j])) or ((i in a[u]) != (j in b[v]))
                for u, v in mapping.items()
            ):
                continue
            if search({**mapping, i: j}):
                return True
        return False

    return search({})
