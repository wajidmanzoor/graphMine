"""Seeded application examples with reproducible, independently checked labels."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from pathlib import Path

from ..history import HistoryStore
from ..models import ApplicationIntent, RouteDecision
from .oracles import expected_answer, isomorphic, key

VERSION = "synthetic-v2"
FAMILIES = {
    "train": ["random", "clique_tail", "two_blocks", "retail_random", "events_forward"],
    "validation": ["cycle_chords", "retail_nested", "events_cycle"],
    "test": ["barbell", "branching", "retail_overlap", "events_chain"],
}
DOMAINS = [
    ("social_networks", "employee", "coworkers", "worked on a project together"),
    ("bioinformatics", "protein", "proteins", "physically interacted in an assay"),
    ("fraud_detection", "account", "accounts", "exchanged payments"),
    (
        "communications_infrastructure",
        "device",
        "devices",
        "have a direct network connection",
    ),
]
PROBLEMS = {
    "maximal-cliques": "maximal_clique_enumeration",
    "maximum-clique": "maximum_clique",
    "k-cliques": "k_clique_counting_enumeration",
    "k-core": "k_core_decomposition",
    "betweenness-centrality": "centrality_influential_node_mining",
    "community-detection": "community_detection",
    "maximal-bicliques": "maximal_biclique_enumeration",
    "temporal-motif-mining": "temporal_motif_mining",
}


def digest(value) -> str:
    return hashlib.sha256(key(value).encode()).hexdigest()


def _graph(family: str, seed: int, domain_index: int) -> tuple[dict, dict]:
    rng = random.Random(seed)
    domain, entity, plural, relation = DOMAINS[domain_index % len(DOMAINS)]
    n = rng.randint(7, 10)
    pairs: set[tuple[int, int]] = set()
    directed = family.startswith("events_")
    if family == "random":
        pairs = {
            (a, b) for a, b in itertools.combinations(range(n), 2) if rng.random() < 0.4
        }
    elif family == "clique_tail":
        size = rng.randint(3, n - 3)
        pairs = set(itertools.combinations(range(size), 2)) | {
            (a - 1, a) for a in range(size, n)
        }
    elif family in {"two_blocks", "barbell"}:
        split = rng.randint(3, n - 3)
        pairs = set(itertools.combinations(range(split), 2)) | set(
            itertools.combinations(range(split, n), 2)
        )
        if family == "barbell":
            # Two connectors, not a renamed instance of the train family.
            middle = n
            n += 1
            pairs |= {(split - 1, middle), (split, middle)}
        else:
            pairs.add((split - 1, split))
    elif family == "cycle_chords":
        pairs = {(a, a + 1) for a in range(n - 1)} | {
            (0, n - 1),
            (0, rng.randint(2, n - 3)),
        }
    elif family == "branching":
        pairs = {(rng.randrange(max(1, a // 2)), a) for a in range(1, n)}
    elif family.startswith("retail_"):
        domain, entity, plural, relation = (
            "recommendation_ecommerce",
            "customer",
            "customers",
            "purchased a product",
        )
        n = rng.randint(7, 10)
        split = n // 2
        for a in range(split):
            for b in range(split, n):
                include = (
                    rng.random() < 0.6
                    if family == "retail_random"
                    else (
                        b - split <= a
                        if family == "retail_nested"
                        else (b - split - a) % (n - split) < 2
                    )
                )
                if include:
                    pairs.add((a, b))
    elif directed:
        domain, entity, plural, relation = (
            "cybersecurity",
            "host",
            "hosts",
            "sent a connection event to another host",
        )
        pairs = {(0, 1), (1, 2), (0, 2)}
        if family == "events_cycle":
            pairs |= {(2, 0), (3, 4), (4, 3)}
        elif family == "events_chain":
            pairs |= {(2, 3), (3, 4), (4, 5), (5, 6)}
        else:
            pairs |= {(3, 4), (4, 5), (3, 5)}
        pairs |= {(i, rng.randrange(i)) for i in range(6, n)}
    else:
        raise ValueError(f"Unknown graph family {family}")
    ids = [f"{entity}-{rng.randrange(100, 1000):03d}-{i}" for i in range(n)]
    vertices = [
        {
            "id": identifier,
            "label": f"{entity.title()} {chr(65 + index)}",
            "type": entity,
            "attributes": {
                "region": rng.choice(["North", "South"]),
                "tenure_years": rng.randint(1, 12),
            },
        }
        for index, identifier in enumerate(ids)
    ]
    if family.startswith("retail_"):
        for index, vertex in enumerate(vertices):
            vertex["type"] = "customer" if index < n // 2 else "product"
            vertex["label"] = f"{vertex['type'].title()} {chr(65 + index)}"
    edges = [
        {
            "id": f"relationship-{i}",
            "source": ids[a],
            "target": ids[b],
            "type": "connection" if directed else "relationship",
            "attributes": {
                "year": 2025 if i % 3 == 0 else 2026,
                "source_system": "synthetic-demo",
                "score": [0.52, 0.77, 0.94, 0.999][i % 4],
                "ascore": 0.0 if i % 3 else 0.8,
                "cost": i % 10 + 1,
            },
        }
        for i, (a, b) in enumerate(sorted(pairs))
    ]
    attributes = {
        "description": f"Fictional {plural}. A link means they {relation}. Year is recorded on each relationship. score and ascore are distinct, unitless synthetic confidence measures; cost is in fictional currency units. Names and regions are descriptive, not analysis instructions."
    }
    if directed:
        unit = rng.choice(["seconds", "milliseconds"])
        attributes["timestamp_unit"] = unit
        scale = 1000 if unit == "milliseconds" else 1
        # Deliberately not chronological row order; sorting must use timestamps.
        for edge, (a, b) in zip(edges, sorted(pairs), strict=True):
            position = {(0, 1): 1, (1, 2): 2, (0, 2): 3}.get((a, b), rng.randint(7, 25))
            edge["timestamp"] = position * 5 * scale
    return {
        "graph": {
            "id": "synthetic-records",
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
            "attributes": attributes,
        },
        "vertices": vertices,
        "edges": edges,
    }, {
        "domain": domain,
        "entity": entity,
        "plural": plural,
        "relation": relation,
    }


def _tasks(graph: dict, vocabulary: dict, seed: int) -> list[dict]:
    rng = random.Random(seed)
    noun, relation = vocabulary["plural"], vocabulary["relation"]
    tasks = []

    def add(
        operation,
        query,
        parameters=None,
        outputs=None,
        filters=None,
        behavior="execute",
        reason="",
        **intent,
    ):
        task = {
            "operation_id": operation,
            "problem_id": PROBLEMS.get(operation),
            "query": query,
            "parameters": parameters or {},
            "optional_outputs": outputs or [],
            "filters": filters or [],
            "behavior": behavior,
            "reason": reason,
            "intent": ApplicationIntent(
                objective=query,
                entity_type=vocabulary["entity"],
                relationship_meaning=relation,
                filters=filters or [],
                filter_mode="replace",
                **intent,
            ).model_dump(mode="json"),
        }
        task["oracle"] = expected_answer(graph, task)
        tasks.append(task)

    if graph["graph"]["directed"]:
        scale = (
            1000
            if graph["graph"]["attributes"]["timestamp_unit"] == "milliseconds"
            else 1
        )
        add(
            "temporal-motif-mining",
            "Find connection sequences from host A to B, then B to C, then A to C, using three different hosts, within 20 seconds from first to last event. List the hosts and event IDs in order.",
            {"max_time_span": 20 * scale},
            ["instances"],
            requires_direction=True,
            pattern_vertex_count=3,
            pattern_edges=[[0, 1], [1, 2], [0, 2]],
            time_unit="seconds",
            time_window=20,
        )
        add(
            "temporal-motif-mining",
            "Count the connection chains A to B, B to C, then C to D through four different hosts within 20 seconds. List the matching hosts and events.",
            behavior="unsupported",
            reason="four_entity_pattern",
            requires_direction=True,
            pattern_vertex_count=4,
            pattern_edges=[[0, 1], [1, 2], [2, 3]],
            time_unit="seconds",
            time_window=20,
        )
    elif {vertex["type"] for vertex in graph["vertices"]} == {"customer", "product"}:
        add(
            "maximal-bicliques",
            "Which groups of at least two customers all bought the same set of at least two products? List every group that cannot be enlarged, separating customer names from product names.",
            {"minimum_left_size": 2, "minimum_right_size": 2},
        )
    else:
        threshold = rng.choice([2, 3])
        add(
            "maximal-cliques",
            f"List every group of at least three {noun} where every pair {relation}. Leave out groups contained in a larger such group and show their names.",
            {"minimum_clique_size": 3},
        )
        add(
            "maximum-clique",
            f"I need the largest group of {noun} in which every pair {relation}. Show one largest group by name and its size; one is enough if there is a tie.",
        )
        add(
            "k-core",
            f"Keep removing {noun} with fewer than {threshold} remaining direct partners, including those that drop below {threshold} after removals. Which names remain?",
            {"requested_k": threshold},
            ["requested_core_vertices"],
        )
        add(
            "betweenness-centrality",
            f"Which {noun} lie on the most shortest connection routes between other {noun}? Rank all their names by that measure, without treating it as measured traffic.",
            outputs=["ranking"],
        )
        add(
            "community-detection",
            f"Suggest separate, non-overlapping groups of {noun} based on their connections, counting each relationship equally. Show names and regions, but do not use region labels to form the groups. Treat this as an exploratory grouping, not a guarantee about every member's connections.",
            outputs=["communities"],
        )
        filters = [
            {
                "target": "edges",
                "field": "attributes.year",
                "operator": "eq",
                "value": 2026,
            }
        ]
        add(
            "maximal-cliques",
            f"Using only relationships from 2026, list every group of at least three {noun} in which every pair {relation}. Exclude groups contained in a larger such group.",
            {"minimum_clique_size": 3},
            filters=filters,
        )
        add(
            None,
            f"Which {noun} should I focus on first?",
            behavior="clarify",
            reason="undefined_priority",
        )
        add(
            "betweenness-centrality",
            f"Rank these {noun} by shortest routes, using each relationship's monetary cost as the route length.",
            behavior="unsupported",
            reason="weighted_cost_required",
            requires_edge_weights=True,
            weight_attribute="attributes.cost",
            weight_usage="path_length",
        )
        add(
            "k-cliques",
            f"List all groups of exactly three {noun} in which every pair {relation}, including the three-member groups contained in larger groups.",
            {"k": 3},
            ["cliques"],
        )
        for value in (0.0, 0.999):
            add(
                "maximal-cliques",
                f"Keep only relationships whose score is exactly {value}, not ascore. Find every group of at least three {noun} where every pair {relation}, excluding groups contained in a larger qualifying group. If none qualify, tell me there are none.",
                {"minimum_clique_size": 3},
                filters=[
                    {
                        "target": "edges",
                        "field": "attributes.score",
                        "operator": "eq",
                        "value": value,
                    }
                ],
            )
        for region in ("North", "Central"):
            add(
                "maximal-cliques",
                f"Restrict this to {noun} whose region is {region}. List every group of at least three where every pair {relation}, excluding groups that can be enlarged. An empty answer is fine if nobody qualifies.",
                {"minimum_clique_size": 3},
                filters=[
                    {
                        "target": "vertices",
                        "field": "attributes.region",
                        "operator": "eq",
                        "value": region,
                    }
                ],
            )
        add(
            "betweenness-centrality",
            f"Rank all {noun} by how often they connect other pairs along shortest routes, using score as each relationship's route length.",
            behavior="unsupported",
            reason="weighted_score_required",
            requires_edge_weights=True,
            weight_attribute="attributes.score",
            weight_usage="path_length",
        )
        add(
            "betweenness-centrality",
            f"First keep only relationships from 2026, then rank the {noun} by how often they connect other pairs along shortest routes, using cost as each relationship's route length. Do not replace costs with a count of steps.",
            filters=filters,
            behavior="unsupported",
            reason="filter_and_weight_required",
            requires_edge_weights=True,
            weight_attribute="attributes.cost",
            weight_usage="path_length",
        )
    return tasks


def gold_route(task: dict) -> RouteDecision:
    ambiguous = task["behavior"] == "clarify"
    unsupported = task["behavior"] == "unsupported"
    return RouteDecision(
        problem_id=None if ambiguous else task["problem_id"],
        operation_id=None if ambiguous or unsupported else task["operation_id"],
        supported=not (ambiguous or unsupported),
        confidence=1,
        explanation=(
            "Would you like to find closely connected groups, or identify those that connect different groups?"
            if ambiguous
            else "The available computations cannot preserve the requested pattern or weight semantics."
            if unsupported
            else "This computation answers the specified relationship question."
        ),
        ambiguity=[
            "Would you like closely connected groups, or those that connect different groups?"
        ]
        if ambiguous
        else [],
        intent=ApplicationIntent.model_validate(task["intent"]),
    )


def generate_corpus(
    destination: Path, *, seed: int = 314159, graphs_per_family: int = 2
) -> dict:
    if destination.exists():
        raise ValueError(
            "Corpus destination already exists; use a new versioned directory"
        )
    if not 1 <= graphs_per_family <= 10:
        raise ValueError("graphs_per_family must be between 1 and 10")
    destination.mkdir(parents=True, mode=0o700)
    examples, graphs, prior = [], [], []
    for split, families in FAMILIES.items():
        for family in families:
            for index in range(graphs_per_family):
                base = int(digest([VERSION, seed, family, index])[:12], 16)
                for attempt in range(300):
                    graph, vocabulary = _graph(family, base + attempt, len(graphs))
                    if not any(isomorphic(graph, previous) for previous in prior):
                        break
                else:
                    raise ValueError(
                        f"Could not generate a distinct topology for {family}; reduce the requested count"
                    )
                prior.append(graph)
                graph_id = f"{family}-{index:02d}"
                graph_file = f"graphs/{graph_id}.json"
                HistoryStore.write(destination / graph_file, graph)
                graphs.append(
                    {
                        "id": graph_id,
                        "family": family,
                        "split": split,
                        "seed": base + attempt,
                        "task_seed": base,
                        "domain_index": len(graphs),
                        "vocabulary": vocabulary,
                        "path": graph_file,
                        "sha256": HistoryStore.digest(destination / graph_file),
                    }
                )
                for task_index, task in enumerate(_tasks(graph, vocabulary, base)):
                    examples.append(
                        {
                            "id": f"{graph_id}-q{task_index:02d}",
                            "graph_id": graph_id,
                            "family": family,
                            "split": split,
                            "domain": vocabulary["domain"],
                            "source": "synthetic_template_oracle",
                            "task": task,
                            "gold_route": gold_route(task).model_dump(mode="json"),
                        }
                    )
    manifest = {
        "schema_version": "1.0.0",
        "generator": VERSION,
        "seed": seed,
        "graphs_per_family": graphs_per_family,
        "synthetic_only": True,
        "split_policy": "Disjoint generator families; exact topology-isomorphism rejection across all graphs; all questions for a graph stay together.",
        "source_sha256": {
            name: HistoryStore.digest(Path(__file__).with_name(name))
            for name in ("corpus.py", "oracles.py")
        },
        "graphs": graphs,
        "examples": examples,
        "scope": "Bounded synthetic examples, not real-user data or a general accuracy benchmark. No fine-tuning is performed.",
    }
    HistoryStore.write(destination / "manifest.json", manifest)
    return manifest


def load_corpus(
    directory: Path, *, verify_labels: bool = True
) -> tuple[dict, dict[str, dict]]:
    root = directory.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if (
        manifest.get("generator") != VERSION
        or manifest.get("synthetic_only") is not True
    ):
        raise ValueError("Only versioned synthetic corpora are accepted")
    if not 1 <= len(manifest["graphs"]) <= 120 or len(manifest["examples"]) > 1000:
        raise ValueError("Corpus size exceeds the bounded synthetic workflow")
    graphs, metadata = {}, {}
    for item in manifest["graphs"]:
        HistoryStore.identifier(item["id"])
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Graph path escapes the corpus")
        if item["id"] in graphs or HistoryStore.digest(path) != item["sha256"]:
            raise ValueError(
                "Duplicate graph ID or graph content changed since generation"
            )
        if item["family"] not in FAMILIES.get(item["split"], []):
            raise ValueError("Graph family was moved across splits")
        graphs[item["id"]] = json.loads(path.read_text())
        regenerated_graph, vocabulary = _graph(
            item["family"], item["seed"], item["domain_index"]
        )
        if graphs[item["id"]] != regenerated_graph or item["vocabulary"] != vocabulary:
            raise ValueError("Graph is not the declared seeded synthetic example")
        metadata[item["id"]] = item
    seen = set()
    regenerated = (
        {
            item["id"]: _tasks(
                graphs[item["id"]], item["vocabulary"], item["task_seed"]
            )
            for item in manifest["graphs"]
        }
        if verify_labels
        else {}
    )
    for example in manifest["examples"]:
        HistoryStore.identifier(example["id"])
        item = metadata[example["graph_id"]]
        if (
            example["id"] in seen
            or example["split"] != item["split"]
            or example["family"] != item["family"]
            or example["domain"] != item["vocabulary"]["domain"]
        ):
            raise ValueError("Duplicate example or split leakage")
        seen.add(example["id"])
        if verify_labels:
            if example["task"] not in regenerated[item["id"]]:
                raise ValueError(f"Question or semantics changed: {example['id']}")
            if (
                expected_answer(graphs[item["id"]], example["task"])
                != example["task"]["oracle"]
            ):
                raise ValueError(f"Oracle label changed: {example['id']}")
            if (
                gold_route(example["task"]).model_dump(mode="json")
                != example["gold_route"]
            ):
                raise ValueError(f"Route label changed: {example['id']}")
    for left, right in itertools.combinations(manifest["graphs"], 2):
        if left["split"] != right["split"] and isomorphic(
            graphs[left["id"]], graphs[right["id"]]
        ):
            raise ValueError("An isomorphic topology appears in multiple splits")
    return manifest, graphs
