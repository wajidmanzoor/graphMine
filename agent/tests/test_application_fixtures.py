"""Independent small-graph oracles for the application fixtures, without GPU code."""

import itertools
import json
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evaluation/applications/graphs"


def graph(name):
    return json.loads((ROOT / name).read_text())


def adjacency(payload):
    result = {vertex["id"]: set() for vertex in payload["vertices"]}
    for edge in payload["edges"]:
        result[edge["source"]].add(edge["target"])
        if not payload["graph"]["directed"]:
            result[edge["target"]].add(edge["source"])
    return result


def cliques(edges):
    return [
        set(group)
        for size in range(1, len(edges) + 1)
        for group in itertools.combinations(edges, size)
        if all(b in edges[a] for a, b in itertools.combinations(group, 2))
    ]


def test_application_group_and_pruning_expectations():
    fraud = cliques(adjacency(graph("fraud_accounts.json")))
    maximal = {
        frozenset(group)
        for group in fraud
        if len(group) >= 3 and not any(group < other for other in fraud)
    }
    assert maximal == {
        frozenset({"acct_alex", "acct_blair", "acct_casey"}),
        frozenset({"acct_casey", "acct_drew", "acct_erin"}),
    }
    biology = adjacency(graph("protein_interactions.json"))
    largest = max(cliques(biology), key=len)
    assert largest == {"TP53", "MDM2", "ATM", "CHEK2"}
    remaining = set(biology)
    while removed := {
        vertex for vertex in remaining if len(biology[vertex] & remaining) < 3
    }:
        remaining -= removed
    assert remaining == largest
    colleagues = cliques(adjacency(graph("coworker_collaboration.json")))
    assert len([group for group in colleagues if len(group) == 3]) == 5
    assert max(map(len, colleagues)) == 4


def ordered_betweenness(edges):
    scores = dict.fromkeys(edges, 0.0)
    for source in edges:
        for target in edges:
            if source == target:
                continue
            queue = deque([[source]])
            shortest = []
            while queue:
                path = queue.popleft()
                if shortest and len(path) > len(shortest[0]):
                    break
                if path[-1] == target:
                    shortest.append(path)
                else:
                    queue.extend(
                        path + [neighbor]
                        for neighbor in edges[path[-1]]
                        if neighbor not in path
                    )
            for path in shortest:
                for vertex in path[1:-1]:
                    scores[vertex] += 1 / len(shortest)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def test_bridge_rankings_use_ordered_endpoint_excluding_pairs():
    office = ordered_betweenness(adjacency(graph("office_network.json")))
    assert office[:3] == [("gateway-01", 18), ("east-router", 16), ("west-router", 16)]
    social = ordered_betweenness(adjacency(graph("coworker_collaboration.json")))
    assert social[:2] == [("Divya", 18), ("Eli", 16)]
    assert all(score == 0 for _, score in social[2:])


def test_temporal_patterns_are_different_queries():
    events = graph("security_events.json")["edges"]
    forward = []
    chains = []
    for a, b, c in itertools.permutations(events, 3):
        if not a["timestamp"] < b["timestamp"] < c["timestamp"] <= a["timestamp"] + 60:
            continue
        if (
            a["target"] == b["source"]
            and b["target"] == c["target"]
            and a["source"] == c["source"]
        ):
            forward.append([a["id"], b["id"], c["id"]])
        if (
            a["target"] == b["source"]
            and b["target"] == c["source"]
            and len({a["source"], a["target"], b["target"], c["target"]}) == 4
        ):
            chains.append([a["id"], b["id"], c["id"]])
    assert forward == [["event-1", "event-2", "event-3"]]
    assert len(chains) == 2


def test_customer_groups_require_both_sides_and_delivery_direction_matters():
    edges = adjacency(graph("customer_purchases.json"))
    customers = {"Alice", "Bob", "Carol"}
    products = {"Coffee", "Tea", "Cocoa"}
    candidates = [
        (set(left), set(right))
        for left_size in (2, 3)
        for right_size in (2, 3)
        for left in itertools.combinations(customers, left_size)
        for right in itertools.combinations(products, right_size)
        if all(product in edges[customer] for customer in left for product in right)
    ]
    assert {(frozenset(left), frozenset(right)) for left, right in candidates} == {
        (frozenset({"Alice", "Bob"}), frozenset({"Coffee", "Tea"})),
        (frozenset({"Bob", "Carol"}), frozenset({"Coffee", "Cocoa"})),
    }
    roads = graph("delivery_routes.json")
    costs = {(e["source"], e["target"]): e["weight"] for e in roads["edges"]}
    paths = []
    for size in range(3):
        for intermediates in itertools.permutations(["North", "South"], size):
            route = ("Depot", *intermediates, "Clinic")
            pairs = list(itertools.pairwise(route))
            if all(pair in costs for pair in pairs):
                paths.append((sum(costs[pair] for pair in pairs), route))
    assert min(paths) == (6, ("Depot", "North", "South", "Clinic"))
