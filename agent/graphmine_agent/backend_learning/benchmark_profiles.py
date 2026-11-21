"""Declarative graph/parameter grids and graph-local parameter bindings."""

from __future__ import annotations

import itertools
import json
import math

from .benchmark_graphs import NAME, canonical, digest


def expand_graphs(config):
    result = []
    grid = config["generated_grid"]
    for family, n, degree in itertools.product(grid["families"], grid["sizes"], grid["average_degrees"]):
        result.append(dict(id=f"{family}-{n}-{degree}", source="generated", generator=family,
                           n=n, average_degree=degree, seed=grid["seed"] + len(result), tags=["general"]))
    result.extend(config["special_graphs"])
    for source, limit in itertools.product(config["neo4j_extracts"]["datasets"], config["neo4j_extracts"]["edge_limits"]):
        if type(limit) is not int or not 1 <= limit <= 30000:
            raise ValueError("Neo4j extracts need an edge limit between 1 and 30,000")
        result.append(dict(id=f"neo4j-{source['dataset']}-{limit}", source="neo4j", tags=["general"],
                           dataset=source["dataset"], query=source["query"],
                           parameters=dict(offset=0, edge_limit=limit), directed=False))
    identifiers = [s["id"] for s in result]
    if len(identifiers) != len(set(identifiers)) or not all(NAME.fullmatch(n) for n in identifiers):
        raise ValueError("Benchmark graph IDs must be unique and safe file names")
    if not set(config["bootstrap_general_graphs"]) <= set(identifiers):
        raise ValueError("Bootstrap graph is missing from the configured graph set")
    return result


def load_config(path):
    config = json.loads(path.read_text())
    if config["schema_version"] != 1:
        raise ValueError("Unsupported benchmark configuration")
    for name, maximum in (("bootstrap_examples_per_operation", 3), ("repeats", 10)):
        if type(config[name]) is not int or not 1 <= config[name] <= maximum:
            raise ValueError(f"{name} must be between 1 and {maximum}")
    for name in ("max_candidates", "max_output_items"):
        value = config.setdefault(name, None)
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"{name} must be a positive integer or null")
    timeout = config.setdefault("timeout_seconds", None)
    if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout_seconds must be null or positive and finite")
    expand_graphs(config)
    for profile in config["operations"].values():
        for values in profile.get("parameter_grid", {}).values():
            if not isinstance(values, list) or not 1 <= len(values) <= 16:
                raise ValueError("Parameter grid entries need 1 to 16 values")
    return config


def parameter_grid(profile):
    keys = sorted(profile.get("parameter_grid", {}))
    values = [profile["parameter_grid"][key] for key in keys]
    return [{**profile.get("parameters", {}), **dict(zip(keys, combination))}
            for combination in itertools.product(*values)]


def bind_parameters(operation, graph, supplied):
    parameters = dict(supplied)
    vertices = [v["id"] for v in graph["vertices"]]
    if not vertices:
        raise ValueError("Benchmark bindings require a nonempty graph")
    first, last = vertices[0], vertices[-1]
    pattern = canonical("benchmark-triangle", 3, {(0, 1), (1, 2), (0, 2)},
                        directed=operation == "temporal-motifs")
    if operation == "temporal-motifs":
        pattern["edges"] = [dict(id=i, source=u, target=v)
                            for i, (u, v) in enumerate(((0, 1), (1, 2), (0, 2)))]
    bindings = {
        "breadth-first-search": {"sources": [first]},
        "single-source-shortest-paths": {"source": first},
        "many-source-shortest-paths": {"origins": [first, last]},
        "random-walks": {"start_vertices": [first]},
        "personalized-pagerank": {"seed_vertices": [first]},
        "induced-subgraph": {"vertices_or_seeds": [first]},
        "max-flow-min-cut": {"source": first, "sink": last},
        "group-steiner-tree": {"groups": [[first], [last]]},
        "link-prediction": {"candidate_pairs": [[first, v] for v in vertices[1:11]]},
        "subgraph-isomorphism": {"query_graph": pattern},
        "motif-counting": {"motifs": [pattern]},
        "temporal-motifs": {"temporal_motif": {"graph": pattern}},
    }
    if operation == "dynamic-triangle-counting":
        edges = graph["edges"]
        pairs = {(e["source"], e["target"]) for e in edges}
        updates = ([dict(kind="delete_edge", source=edges[0]["source"], target=edges[0]["target"])] if edges else [])
        for u, v in itertools.combinations(vertices, 2):
            if (u, v) not in pairs and (v, u) not in pairs:
                updates.append(dict(kind="insert_edge", source=u, target=v))
                break
        bindings[operation] = {"updates": updates}
    # Explicit configuration wins over convenience bindings. Native validation
    # still validates graph-local identities before a backend is run.
    return {**bindings.get(operation, {}), **parameters}


def select_graphs(config, cards, *, full=False):
    graphs = expand_graphs(config)
    by_id, selected, general = {s["id"]: s for s in graphs}, {}, 0
    for card in sorted(cards, key=lambda c: c["id"]):
        profile = config["operations"].get(card["id"])
        if profile is None:
            raise ValueError(f"No benchmark input/parameter profile for {card['id']}")
        tag = profile["graph_tag"]
        choices = [s for s in graphs if tag in s["tags"] or full and tag == "small" and "general" in s["tags"]]
        if not choices:
            raise ValueError(f"No graph for {card['id']}")
        if not full:
            if tag == "general":
                palette = config["bootstrap_general_graphs"]
                choices = [by_id[palette[general % len(palette)]]]
                general += 1
            else:
                choices = choices[:1]
        selected[card["id"]] = choices
    return selected


def attempt_keys(implementation, operation, backend, graph_hash, parameters, budget, repetition):
    # A comparison set must have exactly the same input, parameters and budget.
    comparison = digest(dict(implementation=implementation, operation=operation,
                             graph=graph_hash, parameters=parameters, budget=budget))
    pair = digest(dict(comparison=comparison, backend=backend))
    return comparison, pair, digest(dict(pair=pair, repetition=repetition))
