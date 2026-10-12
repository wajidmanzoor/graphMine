"""Reproducible larger dual-adapter curriculum, separate from pilot artifacts."""

from __future__ import annotations

import argparse
import copy
import gzip
import itertools
import json
import random
import shutil
import urllib.request
from collections import Counter
from pathlib import Path

from ..catalog import Catalog
from ..config import Settings
from ..history import HistoryStore
from ..models import ApplicationIntent, utc_now
from .catalog_suite import contract_digest, digest
from .dual_corpus import SOURCES, build_corpus, graph_from_pairs, synthetic_graph

VERSION = "graphmine-full-corpus-v1"
SIZES = (16, 32, 64, 111, 128, 256)
REGISTRY = {name: copy.deepcopy(SOURCES[name]) for name in ("email-eu-core", "ca-grqc")}
REGISTRY["facebook-combined"] = {
    "split": "test",
    "page": "https://snap.stanford.edu/data/ego-Facebook.html",
    "files": ["facebook_combined.txt.gz"],
    "directed": False,
    "entity": "anonymized_account",
    "meaning": "An anonymized friendship edge from the combined Facebook ego networks. No names, private profile features, interaction counts, or observed outcomes are included.",
    "citation": "McAuley and Leskovec, Learning to Discover Social Circles in Ego Networks, NIPS 2012.",
}


def acquire_sources(root, pilot):
    for name, source in REGISTRY.items():
        target = root / "sources" / name
        target.mkdir(parents=True, exist_ok=True)
        files = []
        for filename in source["files"]:
            path = target / filename
            cached = pilot / "sources" / name / filename
            url = "https://snap.stanford.edu/data/" + filename
            if not path.exists():
                if cached.is_file():
                    shutil.copyfile(cached, path)
                else:
                    with urllib.request.urlopen(url, timeout=45) as response:
                        content = response.read(4 * 1024 * 1024 + 1)
                    if len(content) > 4 * 1024 * 1024:
                        raise ValueError("Source exceeds the download allowance")
                    path.write_bytes(content)
            files.append(
                {"name": filename, "url": url, "sha256": HistoryStore.digest(path)}
            )
        HistoryStore.write(
            target / "registry.json",
            {
                **source,
                "id": name,
                "files": files,
                "use": "Local research; retain original attribution and source terms.",
                "split_rule": "All descendants of this source retain its assigned split.",
            },
        )


def small_graph(split, seed):
    if split != "test":
        return synthetic_graph(split, seed)
    rng = random.Random(seed)
    pairs = {(i, (i + 1) % 8) for i in range(8)}
    pairs = {tuple(sorted(pair)) for pair in pairs}
    for _ in range(3):
        pairs.add(tuple(sorted(rng.sample(range(8), 2))))
    graph = graph_from_pairs(
        f"reserved-ring-{seed}",
        sorted(pairs),
        attributes=[
            {
                "team": ["East", "West"][i % 2],
                "year": 2025 + i % 2,
                "region": "local" if i < 5 else "remote",
            }
            for i in range(8)
        ],
    )
    return graph, "synthetic:reserved_ring_chords"


def large_synthetic(split, seed, size):
    rng = random.Random(seed)
    if split == "train":
        family = "planted_blocks"
        block = max(4, size // 5)
        pairs = [
            (a, b)
            for a, b in itertools.combinations(range(size), 2)
            if rng.random()
            < (min(0.7, 6 / block) if a // block == b // block else 0.6 / size)
        ]
    elif split == "validation":
        family = "geometric_neighborhoods"
        points = [(rng.random(), rng.random()) for _ in range(size)]
        radius2 = 5 / (3.14159 * size)
        pairs = [
            (a, b)
            for a, b in itertools.combinations(range(size), 2)
            if sum((points[a][j] - points[b][j]) ** 2 for j in (0, 1)) < radius2
        ]
    else:
        family = "reserved_ring_chords"
        pairs = {tuple(sorted((i, (i + 1) % size))) for i in range(size)}
        pairs.update(tuple(sorted(rng.sample(range(size), 2))) for _ in range(size))
        pairs = sorted(pairs)
    ids = [f"record-{seed}-{i}" for i in range(size)]
    graph = graph_from_pairs(
        f"full-{family}-{seed}-{size}",
        pairs,
        ids=ids,
        attributes=[
            {
                "team": ["North", "South", "West"][i % 3],
                "year": 2025 + i % 2,
                "region": "local" if i % 4 else "remote",
            }
            for i in range(size)
        ],
    )
    return graph, "synthetic:" + family


def large_public(root, name, seed, size):
    source = REGISTRY[name]
    neighbors = {}
    with gzip.open(root / "sources" / name / source["files"][0], "rt") as stream:
        for line in stream:
            if not line.strip() or line.startswith("#"):
                continue
            a, b = map(int, line.split()[:2])
            if a != b:
                neighbors.setdefault(a, set()).add(b)
                neighbors.setdefault(b, set()).add(a)
    rng = random.Random(seed)
    for _ in range(100):
        selected = {rng.choice(sorted(neighbors))}
        while len(selected) < size:
            frontier = sorted(set().union(*(neighbors[v] for v in selected)) - selected)
            if not frontier:
                break
            selected.add(rng.choice(frontier))
        pairs = [
            (a, b)
            for a in sorted(selected)
            for b in sorted(neighbors[a] & selected)
            if a < b
        ]
        if len(selected) == size and len(pairs) <= 4096:
            break
    else:
        raise ValueError(f"Cannot select bounded public sample {name}/{size}")
    ids = sorted(selected)
    index = {value: i for i, value in enumerate(ids)}
    graph = graph_from_pairs(
        f"{name}-full-{seed}-{size}",
        [(index[a], index[b]) for a, b in pairs],
        ids=ids,
        description=source["meaning"]
        + " This upload is a seeded induced neighborhood sample. Direction is explicitly ignored and duplicate links removed. Findings describe this biased sample only, not the original network or real-world importance.",
    )
    labels = {}
    if name == "email-eu-core":
        with gzip.open(root / "sources" / name / source["files"][1], "rt") as stream:
            labels = dict(map(int, line.split()) for line in stream if line.strip())
    for vertex in graph["vertices"]:
        vertex.update(
            label=f"{source['entity']} {vertex['id']}",
            type=source["entity"],
            attributes={"department": labels[vertex["id"]]} if labels else {},
        )
    for edge in graph["edges"]:
        edge["attributes"] = {}
    return graph, "source:" + name


def build(settings, root, pilot):
    if (root / "corpus.json").exists():
        raise ValueError("Corpus already frozen; use a new version")
    acquire_sources(root, pilot)
    catalog = Catalog(settings)
    cases = []
    for split, count, source, offset in (
        ("train", 8, "email-eu-core", 386001),
        ("validation", 2, "ca-grqc", 492003),
        ("test", 2, "facebook-combined", 597001),
    ):
        for shard in range(count):
            generated = build_corpus(
                catalog,
                root / "sources",
                seed_offset=shard * 1009,
                splits=[(split, offset, 4 if split == "train" else 2, source)],
                sources=REGISTRY,
                graph_factory=small_graph,
            )
            for row in generated["cases"]:
                row["id"] = f"full-{split}-{shard:02d}-{row['id']}"
                row["provenance"]["generation_version"] = VERSION
                row.pop("sha256", None)
                row["sha256"] = digest(row)
                cases.append(row)
        for size in SIZES:
            for sample in range(4 if split == "train" else 1):
                seed = offset + size * 101 + sample * 43
                graphs = [
                    large_synthetic(split, seed, size),
                    large_public(root, source, seed, size),
                ]
                for graph, lineage in graphs:
                    for operation, question, parameters, outputs in (
                        (
                            "community-detection",
                            "Help me understand the groups in this relationship dataset. Group the records by their connection patterns, show who belongs to each group and how many connections cross between groups. Treat the groups as exploratory.",
                            {},
                            ["communities", "edge_cut"],
                        ),
                        (
                            "k-core",
                            "Which records remain after repeatedly removing anyone with fewer than two connections to others still in the set? Show the remaining records and their connections.",
                            {"requested_k": 2},
                            ["requested_core_vertices", "requested_core_edges"],
                        ),
                        (
                            "connected-components",
                            "Find all disconnected sections in these relationships, ignoring direction. Include isolated records as their own sections and show every section's members.",
                            {"connectivity_mode": "weakly_connected"},
                            [],
                        ),
                    ):
                        row = {
                            "id": f"full-large-{split}-{size}-{sample}-{lineage.replace(':', '-')}-{operation}",
                            "domain_id": "general",
                            "split": split,
                            "lineage": lineage,
                            "tags": ["larger_graph", "question_first"],
                            "graph": copy.deepcopy(graph),
                            "attachments": {},
                            "task": {
                                "question": question,
                                "problem_id": catalog.operation(operation).problem_id,
                                "operation_id": operation,
                                "parameters": parameters,
                                "optional_outputs": outputs,
                                "intent": ApplicationIntent(
                                    objective=question, filter_mode="replace"
                                ).model_dump(mode="json"),
                                "expected_status": "ready",
                            },
                            "provenance": {
                                "data_source": lineage,
                                "human_review": "unreviewed",
                                "label_source": "assistant_authored_contract_proposal",
                                "generation_version": VERSION,
                                "training_eligible": split == "train",
                            },
                        }
                        row["sha256"] = digest(row)
                        cases.append(row)
    corpus = {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "catalog_sha256": contract_digest(catalog),
        "source_registry": REGISTRY,
        "cases": cases,
        "scope": "Larger local supervised cycle. Public source lineages are split-disjoint. Tiny exhaustive checks cover combinatorial operations; polynomial references extend selected operations to 256 vertices. Question/graph variants are correlated, not independent human requests. Fresh Facebook descendants are reserved for test only. No human labels or production-quality claim.",
    }
    HistoryStore.write(root / "corpus.json", corpus)
    summary = {
        "cases": len(cases),
        "by_split": dict(Counter(c["split"] for c in cases)),
        "by_operation": dict(Counter(c["task"]["operation_id"] for c in cases)),
        "by_vertex_count": dict(Counter(len(c["graph"]["vertices"]) for c in cases)),
        "distinct_graph_contents": len({digest(c["graph"]) for c in cases}),
        "corpus_sha256": HistoryStore.digest(root / "corpus.json"),
    }
    HistoryStore.write(root / "corpus-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(Settings.from_env(), args.root, args.pilot)))


if __name__ == "__main__":
    main()
