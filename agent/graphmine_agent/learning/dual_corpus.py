"""New, source-separated training scenarios; never imports evaluation fixtures.

Only the bounded mathematical reference implementations are reused. Business
questions are assistant-authored proposals, not human labels. Real source slices
are explicitly biased samples, and must never stand for their whole networks.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import gzip
import itertools
import json
import math
import random
import urllib.request
from dataclasses import replace
from pathlib import Path

from ..analysis import prepare_analysis
from ..answers import build_answer
from ..catalog import Catalog
from ..config import Settings
from ..database import Database
from ..execution import GraphMineRunner
from ..graph_store import GraphStore
from ..history import HistoryStore
from ..models import ApplicationIntent, ExecutionPlan, utc_now
from ..planning import PlanValidator
from .catalog_audit import audit_case, materialize_case
from .catalog_grade import grade_output
from .catalog_suite import contract_digest, digest

VERSION = "dual-adapter-corpus-v1"
SOURCES = {
    "email-eu-core": {
        "split": "train",
        "page": "https://snap.stanford.edu/data/email-Eu-core.html",
        "files": ["email-Eu-core.txt.gz", "email-Eu-core-department-labels.txt.gz"],
        "directed": True,
        "entity": "employee",
        "meaning": "An anonymized sender sent at least one email to a recipient. Department IDs are recorded categories, not names. No email volume, dates or performance outcomes are provided.",
        "citation": "Yin, Benson, Leskovec and Gleich, Local Higher-order Graph Clustering, KDD 2017.",
    },
    "ca-grqc": {
        "split": "validation",
        "page": "https://snap.stanford.edu/data/ca-GrQc.html",
        "files": ["ca-GrQc.txt.gz"],
        "directed": False,
        "entity": "author",
        "meaning": "An undirected link records coauthorship in arXiv GR-QC papers, January 1993 to April 2003. Names, paper counts and impact measures are absent.",
        "citation": "Leskovec, Kleinberg and Faloutsos, Graph Evolution: Densification and Shrinking Diameters, ACM TKDD 2007.",
    },
    "gnutella08": {
        "split": "test",
        "page": "https://snap.stanford.edu/data/p2p-Gnutella08.html",
        "files": ["p2p-Gnutella08.txt.gz"],
        "directed": True,
        "entity": "host",
        "meaning": "Directed connections between Gnutella hosts in the August 8, 2002 snapshot. Bandwidth, latency, uptime and traffic volumes are absent.",
        "citation": "Ripeanu, Foster and Iamnitchi, Mapping the Gnutella Network, IEEE Internet Computing 2002; Leskovec, Kleinberg and Faloutsos, ACM TKDD 2007.",
    },
}


def fetch_sources(root: Path):
    """Bound downloads to a fixed public allowlist, retaining attribution/hashes."""
    for name, source in SOURCES.items():
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        files = []
        for filename in source["files"]:
            path = directory / filename
            url = "https://snap.stanford.edu/data/" + filename
            if not path.exists():
                with urllib.request.urlopen(url, timeout=60) as response:
                    content = response.read(4 * 1024 * 1024 + 1)
                if len(content) > 4 * 1024 * 1024:
                    raise ValueError("Source exceeds the bounded download allowance")
                path.write_bytes(content)
            files.append(
                {
                    "name": filename,
                    "url": url,
                    "bytes": path.stat().st_size,
                    "sha256": HistoryStore.digest(path),
                }
            )
        HistoryStore.write(
            directory / "registry.json",
            {
                **source,
                "id": name,
                "files": files,
                "license": "No explicit license stated on the source page. Attribution retained; local research artifacts only.",
                "split_rule": "Every source descendant inherits this split; no training on validation or test sources.",
            },
        )


def graph_from_pairs(
    name,
    pairs,
    *,
    ids=None,
    directed=False,
    attributes=None,
    weights=None,
    times=None,
    description=None,
):
    ids = ids or [f"{name}-{i}" for i in range(8)]
    vertices = [
        {
            "id": value,
            "label": f"Record {i + 1}",
            "type": "entity",
            "attributes": (attributes or [{} for _ in ids])[i],
        }
        for i, value in enumerate(ids)
    ]
    edges = [
        {
            "id": f"edge-{i}",
            "source": ids[a],
            "target": ids[b],
            "attributes": {"year": 2026, "strength": (i % 5) + 1},
        }
        for i, (a, b) in enumerate(pairs)
    ]
    for i, edge in enumerate(edges):
        if weights is not None:
            edge["weight"] = weights[i]
        if times is not None:
            edge["timestamp"] = times[i]
    return {
        "graph": {
            "id": name,
            "directed": directed,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
            "attributes": {
                "description": description
                or "Fictional operational records. Edge strength is a recorded score, not a probability, cost or causal effect. No claims about real people or organizations are supported.",
                **({"timestamp_unit": "seconds"} if times is not None else {}),
            },
        },
        "vertices": vertices,
        "edges": edges,
    }


def synthetic_graph(split, seed):
    rng = random.Random(seed)
    pairs = list(itertools.combinations(range(8), 2))
    if split == "train":
        family = "planted_blocks"
        while True:
            chosen = [
                (a, b)
                for a, b in pairs
                if rng.random() < (0.7 if a // 4 == b // 4 else 0.13)
            ]
            if 7 <= len(chosen) <= 16:
                break
    elif split == "validation":
        family = "geometric_neighborhoods"
        while True:
            points = [(rng.random(), rng.random()) for _ in range(8)]
            chosen = [
                (a, b) for a, b in pairs if math.dist(points[a], points[b]) < 0.45
            ]
            if 7 <= len(chosen) <= 16:
                break
    else:
        family = "preferential_attachment"
        chosen = [(0, 1)]
        for node in range(2, 8):
            population = [v for edge in chosen for v in edge]
            targets = set()
            while len(targets) < min(2, node):
                targets.add(rng.choice(population))
            chosen.extend(
                (min(node, other), max(node, other)) for other in sorted(targets)
            )
    attrs = [
        {
            "team": ["North", "South", "West"][i % 3],
            "year": 2025 + i % 2,
            "region": "local" if i < 5 else "remote",
        }
        for i in range(8)
    ]
    return graph_from_pairs(
        f"{family}-{seed}", sorted(chosen), attributes=attrs
    ), f"synthetic:{family}"


def source_slice(root, name, seed, *, sources=None):
    source = (sources or SOURCES)[name]
    records = []
    with gzip.open(root / name / source["files"][0], "rt") as stream:
        for line in stream:
            if line.strip() and not line.startswith("#"):
                a, b = map(int, line.split()[:2])
                if a != b:
                    records.append((a, b))
    pairs = sorted({tuple(sorted(pair)) for pair in records})
    neighbors = {}
    for a, b in pairs:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    rng = random.Random(seed)
    for _ in range(1000):
        selected = {rng.choice(sorted(neighbors))}
        while len(selected) < 8:
            frontier = sorted(set().union(*(neighbors[v] for v in selected)) - selected)
            if not frontier:
                break
            selected.add(rng.choice(frontier))
        subset = [(a, b) for a, b in pairs if a in selected and b in selected]
        if len(selected) == 8 and 7 <= len(subset) <= 16:
            break
    else:
        raise ValueError("Could not construct a bounded source slice")
    ids = sorted(selected)
    labels = {}
    if name == "email-eu-core":
        with gzip.open(root / name / source["files"][1], "rt") as stream:
            labels = dict(map(int, line.split()) for line in stream if line.strip())
    description = (
        source["meaning"]
        + " This upload is a small induced neighborhood sample, selected by a seeded walk. Links have explicitly been made undirected, duplicates and self-loops removed. Results apply only to these uploaded records; this is not a representative sample or the whole source network."
    )
    graph = graph_from_pairs(
        f"{name}-sample-{seed}",
        [(ids.index(a), ids.index(b)) for a, b in subset],
        ids=ids,
        description=description,
    )
    for v in graph["vertices"]:
        v["label"] = f"{source['entity'].title()} {v['id']}"
        v["type"] = source["entity"]
        v["attributes"] = {"department": labels[v["id"]]} if labels else {}
    # Real sources must not inherit fictional attributes from the graph helper.
    for edge in graph["edges"]:
        edge["attributes"] = {}
    return graph, f"source:{name}"


def build_corpus(
    catalog,
    source_root,
    *,
    seed_offset=0,
    splits=None,
    sources=None,
    graph_factory=synthetic_graph,
):
    cases = []

    def add(
        graph,
        lineage,
        split,
        operation,
        question,
        *,
        parameters=None,
        outputs=(),
        intent=None,
        attachments=None,
        status="ready",
        problem=None,
        tag="clear",
    ):
        index = len(cases)
        case = {
            "id": f"dual-{index:04d}-{operation or 'clarify'}",
            "domain_id": "general",
            "split": split,
            "lineage": lineage,
            "tags": [tag, "question_first" if index % 2 else "plan_first"],
            "graph": copy.deepcopy(graph),
            "attachments": copy.deepcopy(attachments or {}),
            "task": {
                "question": question,
                "problem_id": problem
                or (catalog.operation(operation).problem_id if operation else None),
                "operation_id": operation,
                "parameters": parameters or {},
                "optional_outputs": list(outputs),
                "intent": ApplicationIntent(
                    objective=question, filter_mode="replace", **(intent or {})
                ).model_dump(mode="json"),
                "expected_status": status,
            },
            "provenance": {
                "data_source": lineage,
                "human_review": "unreviewed",
                "label_source": "assistant_authored_contract_proposal",
                "training_eligible": split == "train",
                "generation_version": VERSION,
            },
        }
        case["sha256"] = digest(case)
        cases.append(case)

    for split, offset, count, source_name in splits or [
        ("train", 86001, 4, "email-eu-core"),
        ("validation", 92003, 2, "ca-grqc"),
        ("test", 97001, 2, "gnutella08"),
    ]:
        offset += seed_offset
        graphs = [graph_factory(split, offset + i * 73) for i in range(count)]
        graphs += [
            source_slice(source_root, source_name, offset + i * 73, sources=sources)
            for i in range(2)
        ]
        for index, (graph, lineage) in enumerate(graphs):
            prefix = "For the supplied undirected sample, "
            add(
                graph,
                lineage,
                split,
                "maximal-cliques",
                prefix
                + "list every fully connected group of at least three records that cannot be enlarged. Include group membership and the total number.",
                parameters={"minimum_clique_size": 3},
                outputs=["total_count"],
            )
            add(
                graph,
                lineage,
                split,
                "maximum-clique",
                prefix + "find a largest fully connected group and show its members.",
                parameters={"return_all_ties": False},
            )
            add(
                graph,
                lineage,
                split,
                "k-cliques",
                prefix
                + "count fully connected groups containing exactly three records, including those inside larger groups, and show each group's membership.",
                parameters={"k": 3},
                outputs=["cliques"],
            )
            add(
                graph,
                lineage,
                split,
                "k-core",
                prefix
                + "show the largest remaining set where each record has at least two neighbors inside the set after repeatedly removing those that do not qualify.",
                parameters={"requested_k": 2},
                outputs=["requested_core_vertices", "requested_core_edges"],
            )
            add(
                graph,
                lineage,
                split,
                "betweenness-centrality",
                prefix
                + "rank all records by how often they lie on shortest routes between other records, splitting credit when several shortest routes exist. Treat links equally.",
                outputs=["ranking", "normalized_score_by_vertex"],
            )
            add(
                graph,
                lineage,
                split,
                "community-detection",
                prefix
                + "group records by their connection patterns and show the groups and the links crossing between them. This is exploratory grouping.",
                outputs=["communities", "edge_cut"],
            )
            if index < count:
                add(
                    graph,
                    lineage,
                    split,
                    "triangle-counting",
                    prefix
                    + "count all mutually connected triples and list them, with participation counts for each record.",
                    outputs=["triangles", "per_vertex_count"],
                )
                add(
                    graph,
                    lineage,
                    split,
                    "quasi-cliques",
                    prefix
                    + "list sets of at least four records where every member links to at least 60 percent of the other members. Return only sets that are not contained in a larger qualifying set.",
                    parameters={"minimum_degree_ratio": 0.6, "minimum_size": 4},
                    outputs=["total_count"],
                )
                add(
                    graph,
                    lineage,
                    split,
                    "densest-subgraph",
                    prefix
                    + "find a set maximizing its number of internal links divided by its number of records. Show the selected set.",
                )
                add(
                    graph,
                    lineage,
                    split,
                    "k-truss",
                    prefix
                    + "describe how strongly each link is supported by triangles after iterative removal of weakly supported links; give the full link support decomposition.",
                )
                if index == 0:
                    pagerank_graph = copy.deepcopy(graph)
                    pagerank_graph["graph"]["directed"] = True
                    pagerank_graph["graph"]["attributes"]["description"] += (
                        " For this fictional scenario, stored source-to-target order defines directed links."
                    )
                    add(
                        pagerank_graph,
                        lineage,
                        split,
                        "personalized-pagerank",
                        f"Starting from record {graph['vertices'][0]['id']}, rank the top five records by approximate random-walk relevance, restarting at that record with probability 0.2.",
                        parameters={
                            "seed_vertex": graph["vertices"][0]["id"],
                            "top_k": 5,
                            "restart_probability": 0.2,
                            "epsilon": 0.05,
                            "random_seed": 20261007,
                        },
                    )
                    add(
                        graph,
                        lineage,
                        split,
                        "k-cliques",
                        "Only use records with year equal to 2025. Count fully connected triples within that selection and show their membership, including triples inside larger groups.",
                        parameters={"k": 3},
                        outputs=["cliques"],
                        intent={
                            "filters": [
                                {
                                    "target": "vertices",
                                    "field": "attributes.year",
                                    "operator": "eq",
                                    "value": 2025,
                                }
                            ]
                        },
                        tag="filtered",
                    )
                    add(
                        graph,
                        lineage,
                        split,
                        "k-cliques",
                        "Only use records with year equal to 2038. Count fully connected triples within that selection; return an empty result if none qualify.",
                        parameters={"k": 3},
                        intent={
                            "filters": [
                                {
                                    "target": "vertices",
                                    "field": "attributes.year",
                                    "operator": "eq",
                                    "value": 2038,
                                }
                            ]
                        },
                        tag="empty_selection",
                    )
            # Every source remains intact in its assigned split even when several questions share a slice.
        graph, lineage = graphs[0]
        ids = [v["id"] for v in graph["vertices"]]
        rng = random.Random(offset)
        directed_pairs = (
            ([(i, (i + 1) % 8) for i in range(8)] + [(0, 4), (2, 6), (4, 1)])
            if split == "train"
            else (
                [(a, b) for a in range(8) for b in range(a + 1, min(a + 3, 8))]
                if split == "validation"
                else [
                    (0, 1),
                    (1, 2),
                    (2, 0),
                    (2, 3),
                    (3, 4),
                    (4, 5),
                    (5, 3),
                    (5, 6),
                    (6, 7),
                ]
            )
        )
        directed = graph_from_pairs(
            f"directed-{split}",
            directed_pairs,
            ids=ids,
            directed=True,
            weights=[rng.randint(1, 9) for _ in directed_pairs],
            description="Fictional directed transport links. Edge weight is a nonnegative integer capacity in units per hour. Node IDs are exact identifiers.",
        )
        directed_lineage = {
            "train": "synthetic:directed_cycle_chords",
            "validation": "synthetic:directed_acyclic",
            "test": "synthetic:linked_sccs",
        }[split]
        for mode, text in [
            (
                "strongly_connected",
                "put records together only when each can reach every other following the directed links",
            ),
            (
                "weakly_connected",
                "find disconnected sections when link direction is ignored",
            ),
        ]:
            add(
                directed,
                directed_lineage,
                split,
                "connected-components",
                text.capitalize() + ".",
                parameters={"connectivity_mode": mode},
                intent={"requires_direction": mode == "strongly_connected"},
            )
        add(
            directed,
            directed_lineage,
            split,
            "transitive-closure",
            "List every ordered source and destination pair connected by a directed path, including each record paired with itself.",
            intent={"requires_direction": True},
        )
        add(
            directed,
            directed_lineage,
            split,
            "max-flow-min-cut",
            f"What is the maximum total flow per hour from {ids[0]} to {ids[-1]}, respecting each link's capacity in weight? Show a separating minimum-capacity cut.",
            parameters={"source": ids[0], "sink": ids[-1]},
            intent={
                "requires_direction": True,
                "requires_edge_weights": True,
                "weight_attribute": "weight",
                "weight_usage": "other",
            },
        )
        add(
            directed,
            directed_lineage,
            split,
            "max-flow-min-cut",
            "How much can this network transport from end to end?",
            status="needs_information",
            tag="missing_endpoints",
            intent={
                "requires_direction": True,
                "requires_edge_weights": True,
                "weight_attribute": "weight",
                "weight_usage": "other",
            },
        )
        diffusion = copy.deepcopy(directed)
        diffusion["graph"]["attributes"]["description"] = (
            "Fictional directed influence opportunities. Edge weight is an explicitly supplied independent-cascade activation probability, not an empirical influence estimate."
        )
        for edge in diffusion["edges"]:
            edge["weight"] = rng.choice([0.0, 1.0])
        add(
            diffusion,
            directed_lineage,
            split,
            "influence-maximization",
            "Choose two starting records to approximately maximize expected reach under independent cascade, using weight as the activation probability. Report simulation uncertainty; no certified approximation ratio is required.",
            parameters={
                "diffusion_model": "independent_cascade",
                "seed_set_size": 2,
                "sample_count": 256,
                "random_seed": 20261007,
            },
            intent={
                "requires_direction": True,
                "requires_edge_weights": True,
                "weight_attribute": "weight",
                "weight_usage": "other",
            },
        )
        weighted = copy.deepcopy(graph)
        weighted["graph"]["attributes"]["description"] = (
            "Fictional undirected network. Edge weight is a nonnegative integer installation cost in credits; other scores are irrelevant to cost."
        )
        for edge in weighted["edges"]:
            edge["weight"] = rng.randint(1, 20)
        groups = [[ids[0], ids[1]], [ids[4], ids[5]], [ids[7]]]
        add(
            weighted,
            lineage,
            split,
            "group-steiner-tree",
            f"Find a minimum-total-installation-cost connected tree that includes at least one record from each of these groups: {json.dumps(groups)}. Use weight as cost in credits.",
            parameters={"groups": groups},
            intent={
                "requires_edge_weights": True,
                "weight_attribute": "weight",
                "weight_usage": "path_length",
            },
        )
        side = {"train": 3, "validation": 4, "test": 2}[split]
        b_ids = [f"worker-{i}" for i in range(side)] + [
            f"task-{i}" for i in range(side)
        ]
        pairs = [(a, b) for a in range(side) for b in range(side, side * 2)]
        attributes = [
            {"side": "left" if i < side else "right"} for i in range(side * 2)
        ]
        bip = graph_from_pairs(
            f"assignment-{split}",
            pairs,
            ids=b_ids,
            attributes=attributes,
            weights=[rng.randint(1, 90) for _ in pairs],
            description="Fictional complete worker-task table. Left records are workers and right records tasks. Every pair is feasible; weight is an integer cost in credits. One worker must be assigned to each task and each worker to one task.",
        )
        b_lineage = f"synthetic:assignment_{side}_per_side"
        add(
            bip,
            b_lineage,
            split,
            "linear-assignment",
            "Assign each worker to exactly one task and each task to exactly one worker, minimizing the total cost in weight.",
            intent={
                "requires_edge_weights": True,
                "weight_attribute": "weight",
                "weight_usage": "other",
            },
        )
        for operation, question in [
            (
                "maximal-bicliques",
                "Find every group of workers and tasks where each worker links to every task, and neither side can be enlarged while retaining that property.",
            ),
            (
                "maximal-biclique-counting",
                "Count every inclusion-maximal fully linked worker-task group without listing its members.",
            ),
            (
                "butterfly-counting",
                "How many distinct choices of two workers and two tasks have all four worker-task links? Count each choice once.",
            ),
        ]:
            unweighted = copy.deepcopy(bip)
            unweighted["graph"]["attributes"]["description"] = (
                "Fictional worker-task eligibility links, with attributes.side distinguishing workers and tasks. No costs or weights are used."
            )
            for edge in unweighted["edges"]:
                edge.pop("weight", None)
            attachments = (
                {
                    "left_partition": [
                        {
                            "role": "left_partition",
                            "content": {"left_partition": b_ids[:side]},
                        }
                    ]
                }
                if operation == "maximal-bicliques"
                else {}
            )
            add(
                unweighted,
                b_lineage,
                split,
                operation,
                question,
                attachments=attachments,
            )
        temporal_pairs = (
            [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5), (6, 7)]
            if split == "train"
            else (
                [(0, 2), (2, 4), (0, 4), (2, 6), (4, 6), (1, 3), (3, 5)]
                if split == "validation"
                else [(0, 1), (1, 3), (0, 3), (0, 2), (2, 5), (0, 5), (6, 7)]
            )
        )
        temporal = graph_from_pairs(
            f"events-{split}",
            temporal_pairs,
            directed=True,
            times=[i * 10 + 1 for i in range(len(temporal_pairs))],
            description="Fictional timestamped directed message events. Timestamps are seconds from a fixed recording start; they are not calendar dates.",
        )
        add(
            temporal,
            f"synthetic:temporal_{split}",
            split,
            "temporal-motif-mining",
            "Count sequences on three distinct records where A messages B, then B messages C, then A messages C, in that order within 30 seconds, and list the event instances.",
            parameters={"max_time_span": 30},
            outputs=["instances"],
            intent={
                "requires_direction": True,
                "pattern_vertex_count": 3,
                "pattern_edges": [[0, 1], [1, 2], [0, 2]],
                "time_window": 30,
                "time_unit": "seconds",
            },
        )
        pattern = graph_from_pairs(
            "path-pattern",
            [(0, 1), (1, 2)],
            ids=["p", "q", "r"],
            description="Unlabeled path on three distinct records; endpoints need not be disconnected in the data.",
        )
        add(
            graph,
            lineage,
            split,
            "graph-motifs",
            "Count occurrences of the attached three-record path pattern, allowing extra links among those records. Identify an occurrence by its selected records and mapping class, and list instances.",
            parameters={
                "induced": False,
                "occurrence_identity": "unique-vertex-set-and-mapping-class",
            },
            outputs=["instances"],
            attachments={"motifs": [{"role": "motif", "content": pattern}]},
        )
        add(
            graph,
            lineage,
            split,
            "subgraph-isomorphism",
            "List every mapping of the attached three-record path into the uploaded graph. Ignore labels and allow additional data links between matched records.",
            parameters={"ignore_vertex_labels": True},
            outputs=["embeddings"],
            attachments={"query_graph": [{"role": "query_graph", "content": pattern}]},
        )
        existing = graph["edges"][0]
        connected = {
            frozenset((edge["source"], edge["target"])) for edge in graph["edges"]
        }
        missing = next(
            (a, b)
            for a, b in itertools.combinations(ids, 2)
            if frozenset((a, b)) not in connected
        )
        changes = {
            "updates": [
                {
                    "kind": "delete",
                    "source": existing["source"],
                    "target": existing["target"],
                },
                {"kind": "insert", "source": missing[0], "target": missing[1]},
            ]
        }
        add(
            graph,
            lineage,
            split,
            "dynamic-triangle-counting",
            "Apply the attached link deletions, then insertions. Show the counts of mutually connected triples before and after, and list which triples disappear and appear at each phase.",
            outputs=[
                "initial_global_triangle_count",
                "final_global_triangle_count",
                "deleted_triangles",
                "inserted_triangles",
            ],
            attachments={"updates": [{"role": "updates", "content": changes}]},
        )
        add(
            graph,
            lineage,
            split,
            "betweenness-centrality",
            "Rank the records by their role on shortest routes, using attributes.strength as a route cost.",
            status="unsupported",
            tag="unsupported_weighted",
            intent={
                "requires_edge_weights": True,
                "weight_attribute": "attributes.strength",
                "weight_usage": "path_length",
            },
        )
    return {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "catalog_sha256": contract_digest(catalog),
        "source_registry": sources or SOURCES,
        "cases": cases,
        "scope": "New local research corpus; source/family-separated, synthetic semantics explicitly labeled. Complete-assignment topology is intrinsic to its profile; side counts differ across splits. No human preference or business-outcome labels.",
    }


async def verify_corpus(settings, corpus, destination, *, retry_quarantined=False):
    if not settings.graph_gpu_uuid or not settings.graph_gpu_uuid.startswith("GPU-"):
        raise ValueError(
            "Reference executions require an explicitly isolated GRAPHMINE_GRAPH_GPU_UUID"
        )
    isolated = replace(
        settings,
        data_root=destination / "store",
        history_directory=None,
        llm_enabled=False,
    )
    catalog = Catalog(isolated)
    database = Database(isolated.database_path)
    store = GraphStore(isolated, database)
    validator = PlanValidator(catalog)
    runner = GraphMineRunner(isolated, catalog, store, validator)
    runner.require_ready()
    results = []
    for case in corpus["cases"]:
        path = destination / "cases" / (case["id"] + ".json")
        if path.exists():
            record = json.loads(path.read_text())
            if record["case_sha256"] != case["sha256"]:
                raise ValueError("An existing reference case changed")
            if record["status"] != "quarantined" or not retry_quarantined:
                results.append(record)
                continue
            archive = destination / "quarantined-initial" / path.name
            attempt = 1
            while archive.exists():
                attempt += 1
                archive = destination / f"quarantined-attempt-{attempt}" / path.name
            archive.parent.mkdir(parents=True, exist_ok=True)
            path.rename(archive)
        record = {
            "id": case["id"],
            "case_sha256": case["sha256"],
            "split": case["split"],
            "lineage": case["lineage"],
        }
        try:
            audit = audit_case(catalog, store, database, case)
            record["contract"] = audit
            if not audit["passed"]:
                raise ValueError(audit["reason"] or "Contract status mismatch")
            if case["task"]["expected_status"] == "ready":
                session, graph, auxiliary = materialize_case(store, database, case)
                task = case["task"]
                plan = validator.validate(
                    ExecutionPlan(
                        session_id=session.id,
                        graph_id=graph.id,
                        problem_id=task["problem_id"],
                        operation_id=task["operation_id"],
                        parameters=task["parameters"],
                        optional_outputs=task["optional_outputs"],
                        auxiliary_inputs=auxiliary,
                        application_intent=task["intent"],
                    ),
                    for_execution=True,
                )
                workspace = isolated.workspaces_root / case["id"]
                payload, command = await runner.execute(plan, workspace)
                record.update(
                    plan=plan.model_dump(mode="json"), payload=payload, command=command
                )
                record["native_binary_sha256"] = HistoryStore.digest(
                    settings.graphmine_binary
                )
                if not payload.get("ok"):
                    raise ValueError(
                        "Native execution failed: " + str(payload.get("error"))
                    )
                grade = grade_output(catalog, case, payload["output"])
                record["numerical_validation"] = grade
                if not grade["checks_passed"]:
                    raise ValueError("Independent reference mismatch: " + str(grade))
                answer = build_answer(
                    case["graph"], plan, payload, source_hash=graph.sha256
                )
                prepare_analysis(answer)
                record["answer"] = answer
            record["status"] = "verified"
        except (
            ValueError,
            RuntimeError,
            OSError,
            KeyError,
            TypeError,
            AssertionError,
        ) as error:
            record.update(
                status="quarantined", error=f"{type(error).__name__}: {error}"
            )
        HistoryStore.write(path, record)
        results.append(record)
        print(
            json.dumps(
                {
                    "id": case["id"],
                    "status": record["status"],
                    "error": record.get("error"),
                }
            ),
            flush=True,
        )
    report = {
        "version": VERSION,
        "corpus_sha256": digest(corpus),
        "current_native_binary_sha256": HistoryStore.digest(settings.graphmine_binary),
        "binary_provenance": "Per-case native_binary_sha256 identifies newly executed records. Reused early records without that field have unrecorded historical binary identity; the current binary hash does not attest those executions.",
        "verified": sum(r["status"] == "verified" for r in results),
        "total": len(results),
        "cases": [
            {k: r[k] for k in ("id", "status", "split", "lineage")} for r in results
        ],
    }
    HistoryStore.write(destination / "verification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--retry-quarantined", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    path = args.root / "corpus.json"
    if args.command == "build":
        if path.exists():
            raise ValueError("Existing corpus is immutable; choose a new root")
        fetch_sources(args.root / "sources")
        corpus = build_corpus(Catalog(settings), args.root / "sources")
        HistoryStore.write(path, corpus)
        print(json.dumps({"cases": len(corpus["cases"]), "path": str(path)}))
    else:
        print(
            json.dumps(
                asyncio.run(
                    verify_corpus(
                        settings,
                        json.loads(path.read_text()),
                        args.root / "references",
                        retry_quarantined=args.retry_quarantined,
                    )
                )
            )
        )


if __name__ == "__main__":
    main()
