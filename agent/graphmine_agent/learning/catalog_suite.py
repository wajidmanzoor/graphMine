"""Reproducible development probes for the current executable catalog.

Questions and expected intents are assistant-authored contract proposals. They
are not human labels, held-out data, native execution evidence, or training data.
The bundle is separate from the frozen adapter corpora and evaluation sources.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path

from ..catalog import Catalog
from ..models import ApplicationIntent

VERSION = "current-catalog-development-v1"
MAX_BUNDLE_BYTES = 4 * 1024 * 1024


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def contract_digest(catalog):
    return digest(
        {
            "catalog": catalog.global_catalog,
            "manifest": catalog.manifest,
            "instructions": catalog.program_instructions,
            "domains": catalog.domain_catalog,
        }
    )


def _graph(ids, pairs, *, directed=False, sides=False, weights=None, events=False):
    vertices = [
        {
            "id": identifier,
            "label": f"Entity {index + 1}",
            "type": ("customer" if index < 3 else "product") if sides else "entity",
            "attributes": {"side": "left" if index < 3 else "right"} if sides else {},
        }
        for index, identifier in enumerate(ids)
    ]
    edges = []
    for index, (a, b) in enumerate(pairs):
        edge = {
            "id": f"link-{index}",
            "source": ids[a],
            "target": ids[b],
            "attributes": {"year": 2026},
        }
        if weights is not None:
            edge["weight"] = weights[index]
            edge["attributes"]["value"] = weights[index]
        if events:
            edge["timestamp"] = index + 1
        edges.append(edge)
    return {
        "graph": {
            "id": "catalog-development",
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
            "attributes": {
                "description": "Fictional development records. Links have only the meaning stated in each question; no domain or causal claim is supported.",
                **({"timestamp_unit": "seconds"} if events else {}),
            },
        },
        "vertices": vertices,
        "edges": edges,
    }


def build_suite(catalog: Catalog, *, seed: int = 20261007) -> dict:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    rng = random.Random(seed)
    ids = [f"entity-{value}" for value in rng.sample(range(1000, 9999), 7)]
    small = _graph(
        ids,
        [
            (0, 1),
            (0, 2),
            (0, 3),
            (1, 2),
            (1, 3),
            (2, 3),
            (3, 4),
            (4, 5),
            (4, 6),
            (5, 6),
        ],
    )
    bipartite = _graph(
        ids[:6], [(0, 3), (0, 4), (1, 3), (1, 4), (2, 4), (2, 5)], sides=True
    )
    assignment = _graph(
        ids[:6],
        [(a, b) for a in range(3) for b in range(3, 6)],
        sides=True,
        weights=[9, 1, 7, 2, 8, 6, 3, 4, 5],
    )
    directed = _graph(ids[:5], [(0, 1), (1, 0), (1, 2), (2, 3)], directed=True)
    flow = _graph(
        ids[:4],
        [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)],
        directed=True,
        weights=[4, 2, 1, 3, 3],
    )
    steiner = _graph(ids[:4], [(0, 1), (1, 2), (0, 2), (2, 3)], weights=[2, 3, 20, 1])
    influence = _graph(
        ids[:4], [(0, 1), (1, 2), (2, 3)], directed=True, weights=[1, 1, 1]
    )
    temporal = _graph(
        ids[:4], [(0, 1), (1, 2), (0, 2), (3, 0)], directed=True, events=True
    )
    pattern = _graph(["a", "b", "c"], [(0, 1), (1, 2), (0, 2)])
    cases = []

    def add(
        operation,
        question,
        graph=small,
        *,
        parameters=None,
        outputs=(),
        attachments=None,
        intent=None,
        tag="supported",
        status="ready",
        identifier=None,
        problem_id=None,
    ):
        task = {
            "question": question,
            "problem_id": problem_id or catalog.operation(operation).problem_id,
            "operation_id": operation,
            "parameters": parameters or {},
            "optional_outputs": list(outputs),
            "intent": ApplicationIntent(
                objective=question, filter_mode="replace", **(intent or {})
            ).model_dump(mode="json"),
            "expected_status": status,
        }
        item = {
            "id": identifier or f"{operation}--{tag}",
            "domain_id": "general",
            "split": "development",
            "tags": [tag],
            "graph": copy.deepcopy(graph),
            "attachments": copy.deepcopy(attachments or {}),
            "task": task,
            "provenance": {
                "data_source": "seeded_synthetic_fixture",
                "label_source": "assistant_authored_contract_proposal",
                "human_review": "unreviewed",
                "training_eligible": False,
            },
        }
        item["sha256"] = digest(item)
        cases.append(item)

    add(
        "maximal-cliques",
        "List every fully connected group with at least three entities that cannot be enlarged while staying fully connected.",
        parameters={"minimum_clique_size": 3},
        outputs=["total_count"],
    )
    add(
        "maximum-clique",
        "Find the largest fully connected group. Return every tie and an upper bound on its size.",
        parameters={"return_all_ties": True},
        outputs=["upper_bound"],
    )
    add(
        "k-cliques",
        "List every fully connected group of exactly three entities, including triples inside larger groups. Count participation by entity.",
        parameters={"k": 3},
        outputs=["cliques", "per_vertex_count"],
    )
    add(
        "quasi-cliques",
        "List every inclusion-maximal set of at least three entities where each member connects to at least 75 percent of the other members.",
        parameters={"minimum_size": 3, "minimum_degree_ratio": 0.75},
        outputs=["total_count"],
    )
    add(
        "k-core",
        "Repeatedly remove entities with fewer than two remaining neighbors. List the survivors and their remaining links.",
        parameters={"requested_k": 2},
        outputs=["requested_core_vertices", "requested_core_edges"],
    )
    partition = {
        "left_partition": [
            {"role": "left_partition", "content": {"left_partition": ids[:3]}}
        ]
    }
    add(
        "maximal-bicliques",
        "List all groups of at least two customers and at least two products where every customer links to every product and neither side can be enlarged.",
        bipartite,
        parameters={"minimum_left_size": 2, "minimum_right_size": 2},
        outputs=["total_count"],
        attachments=partition,
        intent={"entity_type": "customer"},
    )
    add(
        "triangle-counting",
        "Count and list every triangle, with participation counts for each entity and link.",
        outputs=["triangles", "per_vertex_count", "per_edge_count"],
    )
    updates = {
        "updates": [
            {
                "role": "updates",
                "content": {
                    "updates": [
                        {"kind": "delete", "source": ids[0], "target": ids[1]},
                        {"kind": "insert", "source": ids[0], "target": ids[4]},
                    ]
                },
            }
        ]
    }
    add(
        "dynamic-triangle-counting",
        "Apply the attached link deletions and insertions. List the triangles removed and added, and report the total before and after.",
        outputs=[
            "initial_global_triangle_count",
            "final_global_triangle_count",
            "deleted_triangles",
            "inserted_triangles",
        ],
        attachments=updates,
    )
    add(
        "graph-motifs",
        "Count occurrences of the attached triangle pattern, counting each vertex set once. Extra links are allowed. List the matched entity sets.",
        parameters={
            "induced": False,
            "occurrence_identity": "unique-vertex-set-and-mapping-class",
        },
        outputs=["instances"],
        attachments={"motifs": [{"role": "motif", "content": pattern}]},
    )
    add(
        "subgraph-isomorphism",
        "List every mapping of the attached query graph into this dataset. Ignore vertex labels and count distinct query-to-data mappings separately.",
        parameters={"ignore_vertex_labels": True},
        outputs=["embeddings"],
        attachments={"query_graph": [{"role": "query_graph", "content": pattern}]},
    )
    add(
        "temporal-motif-mining",
        "List sequences A to B, then B to C, then A to C through three distinct entities, within three seconds from first to last event. Preserve event direction and order.",
        temporal,
        parameters={"max_time_span": 3},
        outputs=["instances"],
        intent={
            "requires_direction": True,
            "pattern_vertex_count": 3,
            "pattern_edges": [[0, 1], [1, 2], [0, 2]],
            "time_window": 3,
            "time_unit": "seconds",
        },
    )
    add(
        "community-detection",
        "Partition the entities into communities using modularity. Report the groups, score and links crossing groups without claiming a unique optimum.",
        outputs=["communities", "edge_cut"],
    )
    add(
        "betweenness-centrality",
        "Rank entities by how often they mediate unweighted shortest paths, sharing credit between equal-length paths.",
        outputs=["ranking", "maximum"],
    )
    add(
        "connected-components",
        "Group entities that can reach each other in both directions, including isolated entities.",
        directed,
        parameters={"connectivity_mode": "strongly_connected"},
        intent={"requires_direction": True},
    )
    add(
        "max-flow-min-cut",
        f"Use attributes.value as link capacities. Find maximum directed flow from {ids[0]} to {ids[3]} and the minimum cut.",
        flow,
        parameters={"source": ids[0], "sink": ids[3]},
        intent={
            "requires_direction": True,
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "other",
        },
    )
    add(
        "linear-assignment",
        "Assign every left-side entity to one distinct right-side entity, minimizing total cost from attributes.value. All pairs have costs.",
        assignment,
        intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "other",
        },
    )
    add(
        "transitive-closure",
        "List every ordered entity pair connected by a directed path, preserving direction.",
        directed,
        intent={"requires_direction": True},
    )
    add(
        "butterfly-counting",
        "Count sets of two left-side and two right-side entities with all four links across the sides. Count each set once.",
        bipartite,
    )
    add(
        "k-truss",
        "Compute the truss number of every link: repeatedly remove links with too few remaining triangles. Report the highest truss number.",
    )
    add(
        "densest-subgraph",
        "Find a nonempty entity set maximizing its internal unweighted link count divided by its number of entities. Do not fix the group size.",
    )
    add(
        "maximal-biclique-counting",
        "Count all nonempty maximal complete bipartite groups across the declared sides. A count alone is sufficient.",
        bipartite,
    )
    add(
        "personalized-pagerank",
        f"Rank the top five entities by approximate personalized PageRank from {ids[0]} using outgoing unweighted links and restart probability 0.2. Use sampling tolerance 0.01.",
        directed,
        parameters={
            "seed_vertex": ids[0],
            "top_k": 5,
            "restart_probability": 0.2,
            "epsilon": 0.01,
        },
        intent={"requires_direction": True},
    )
    add(
        "group-steiner-tree",
        f"Find a minimum-cost tree meeting each group {[[ids[0]], [ids[2]], [ids[3]]]}. Use attributes.value as integer link costs.",
        steiner,
        parameters={"groups": [[ids[0]], [ids[2]], [ids[3]]]},
        intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "other",
        },
    )
    add(
        "influence-maximization",
        "Select one seed under the independent-cascade model. Use attributes.value as activation probabilities and 32 samples. An estimate without a certified approximation guarantee is acceptable.",
        influence,
        parameters={
            "diffusion_model": "independent_cascade",
            "seed_set_size": 1,
            "sample_count": 32,
        },
        intent={
            "requires_direction": True,
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "other",
        },
    )

    # Boundary probes remain separate from the positive coverage count.
    add(
        "betweenness-centrality",
        "Rank entities by mediation of cheapest paths using attributes.value as path lengths.",
        tag="weighted_unsupported",
        status="unsupported",
        intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "path_length",
        },
    )
    add(
        "temporal-motif-mining",
        "Count directed event chains A to B, B to C, C to D through four distinct entities within three seconds.",
        temporal,
        tag="pattern_unsupported",
        status="unsupported",
        parameters={"max_time_span": 3},
        intent={
            "requires_direction": True,
            "pattern_vertex_count": 4,
            "pattern_edges": [[0, 1], [1, 2], [2, 3]],
            "time_window": 3,
            "time_unit": "seconds",
        },
    )
    add(
        "max-flow-min-cut",
        "Find the maximum directed flow using attributes.value as capacities; I have not specified the source and destination.",
        flow,
        tag="missing_endpoints",
        status="needs_information",
        intent={
            "requires_direction": True,
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "other",
        },
    )
    add(
        "linear-assignment",
        "Find a minimum-cost perfect assignment across the two sides using attributes.value as costs; some pair costs are absent.",
        bipartite,
        tag="missing_costs",
        status="needs_information",
        intent={
            "requires_edge_weights": True,
            "weight_attribute": "attributes.value",
            "weight_usage": "other",
        },
    )
    add(
        "graph-motifs",
        "Count the pattern I want to match; I have not supplied the pattern graph.",
        tag="missing_pattern",
        status="needs_information",
    )
    add(
        "k-cliques",
        "List fully connected triples using only relationships recorded after 2030. An empty selection is a valid answer.",
        tag="empty_filter",
        parameters={"k": 3},
        outputs=["cliques"],
        intent={
            "filters": [
                {
                    "target": "edges",
                    "field": "attributes.year",
                    "operator": "gt",
                    "value": 2030,
                }
            ]
        },
    )
    add(
        "connected-components",
        "Group entities connected when link direction is ignored, including isolates.",
        directed,
        tag="weak_connectivity",
        parameters={"connectivity_mode": "weakly_connected"},
    )

    unsupported = {
        name: problem
        for name, problem in catalog.problems.items()
        if problem["library_support"]["status"] != "validated"
    }
    for name, problem in sorted(unsupported.items()):
        add(
            None,
            problem["spec"]["problem_statement"],
            problem_id=name,
            identifier=f"{name}--unavailable",
            tag="catalog_capability_probe",
            status="unsupported",
        )
    covered = {
        case["task"]["operation_id"] for case in cases if case["tags"] == ["supported"]
    }
    if covered != set(catalog.manifest_operations):
        raise ValueError(
            "Current-catalog fixture coverage must be updated for the executable operations"
        )
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate development case IDs")
    return {
        "version": VERSION,
        "seed": seed,
        "split": "development",
        "evaluation_only": True,
        "training_eligible": False,
        "label_source": "assistant_authored_contract_proposal",
        "human_review": "unreviewed",
        "catalog_sha256": contract_digest(catalog),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Small synthetic contract probes, with shared graph families. No generalization, usability, native correctness or model accuracy claim. Unsupported probes reuse formal catalog statements, not independent natural-language labels.",
        "cases": cases,
    }


def write_suite(catalog, destination: Path, *, seed=20261007):
    document = build_suite(catalog, seed=seed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return document


def load_suite(catalog, path: Path):
    with path.open("rb") as handle:
        content = handle.read(MAX_BUNDLE_BYTES + 1)
    if len(content) > MAX_BUNDLE_BYTES:
        raise ValueError("Current-catalog bundle exceeds the size limit")
    document = json.loads(content)
    if not isinstance(document, dict) or document.get("version") != VERSION:
        raise ValueError("Unknown current-catalog development bundle")
    expected = build_suite(catalog, seed=document.get("seed"))
    if document != expected:
        raise ValueError(
            "Current-catalog bundle is stale or changed; rebuild from the generator and catalog"
        )
    return document
