"""Reproducible generated graphs and bounded reads from registered Neo4j instances."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import replace
from pathlib import Path

from .storage import atomic_json, utc_now

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def canonical(name, n, pairs, *, directed=False, bipartite=False, weights=None, timestamps=False):
    vertices = [{"id": i, **({"attributes": {"side": "left" if i < n // 2 else "right"}}
                            if bipartite else {})} for i in range(n)]
    edges = [{"id": i, "source": u, "target": v,
              **({"weight": weights[i]} if weights is not None else {}),
              **({"timestamp": i} if timestamps else {})} for i, (u, v) in enumerate(sorted(pairs))]
    return dict(graph=dict(id=name, directed=directed, allows_self_loops=False, allows_parallel_edges=False),
                vertices=vertices, edges=edges)


def _er_pairs(n, probability, rng, *, directed, bipartite):
    """Geometric skipping generates G(n,p) in expected O(n+m), without NetworkX."""
    if probability == 0:
        return set()
    rows = range(n // 2) if bipartite else range(n)
    pairs = set()
    skip_scale = math.log1p(-probability) if probability < 1 else None
    for u in rows:
        begin = n // 2 if bipartite else (0 if directed else u + 1)
        v = begin
        while v < n:
            if skip_scale is not None:
                v += int(math.log1p(-rng.random()) / skip_scale)
            if v < n and u != v:
                pairs.add((u, v))
            v += 1
    return pairs


def generate(spec):
    n, family = spec["n"], spec["generator"]
    if type(n) is not int or not 2 <= n <= 1_000_000:
        raise ValueError("Generated graph n must be between 2 and 1,000,000")
    rng = random.Random(spec["seed"])
    directed, bipartite = bool(spec.get("directed")), bool(spec.get("bipartite"))
    average = spec.get("average_degree", 4)
    if type(average) not in (int, float) or not math.isfinite(average) or average < 0:
        raise ValueError("Invalid average degree")
    probability = spec.get("probability", min(1, average / max(1, n // 2 if bipartite else n - 1)))
    if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
        raise ValueError("Invalid graph probability")
    pairs_available = n * n // 4 if bipartite else n * (n - 1) / (1 if directed else 2)
    if family != "power_law" and pairs_available * probability > 1_000_000:
        raise ValueError("Requested density exceeds the native transport graph budget")
    if family == "power_law" and n * max(1, int(average / 2)) > 1_000_000:
        raise ValueError("Requested power-law size exceeds the native transport graph budget")
    if family in {"erdos_renyi", "planted_dense"}:
        pairs = _er_pairs(n, probability, rng, directed=directed, bipartite=bipartite)
        if family == "planted_dense":
            if bipartite:
                raise ValueError("Use bipartite Erdos-Renyi for bipartite inputs")
            size = spec.get("planted_size", min(8, n))
            if type(size) is not int or not 2 <= size <= min(n, 128):
                raise ValueError("Invalid planted clique size")
            pairs.update((u, v) for u in range(size) for v in range(u + 1, size))
    elif family == "power_law":
        if directed or bipartite:
            raise ValueError("The Barabasi-Albert generator is undirected and unpartitioned")
        degree = max(1, min(n - 1, int(average / 2)))
        pairs = {(0, v) for v in range(1, degree + 1)}
        urn = [endpoint for edge in sorted(pairs) for endpoint in edge]
        for v in range(degree + 1, n):
            selected = set()
            while len(selected) < degree:
                selected.add(rng.choice(urn))
            pairs.update((u, v) for u in selected)
            urn.extend(sorted(selected))
            urn.extend([v] * degree)
    else:
        raise ValueError("Unsupported generated graph family")
    if spec.get("acyclic"):
        if not directed:
            raise ValueError("acyclic requires directed input")
        pairs = {(min(u, v), max(u, v)) for u, v in pairs}
    weights = None
    if spec.get("weights") == "integer":
        weights = [rng.randint(1, 9) for _ in pairs]
    elif spec.get("weights") == "probability":
        weights = [0.1 for _ in pairs]
    elif spec.get("weights") is not None:
        raise ValueError("Unsupported weight generator")
    graph = canonical(spec["id"], n, pairs, directed=directed, bipartite=bipartite, weights=weights)
    if spec.get("timestamps"):
        rng.shuffle(graph["edges"])
        if family == "planted_dense" and directed:
            events = {(e["source"], e["target"]): e for e in graph["edges"]}
            triangle = [(0, 1), (1, 2), (0, 2)]
            if all(pair in events for pair in triangle):
                graph["edges"] = [events[pair] for pair in triangle] + [
                    e for e in graph["edges"] if (e["source"], e["target"]) not in triangle]
        for timestamp, edge in enumerate(graph["edges"]):
            edge["timestamp"] = timestamp
    return graph


def extract(spec, settings):
    from ..database_queries import CypherRequest, execute_query
    from ..database_sources import validate_cypher
    from ..neo4j_registry import sources

    source = next((s for s in sources(settings) if s._catalog["id"] == spec["dataset"]), None)
    if source is None:
        raise ValueError("Requested dataset is not verified and ready")
    validate_cypher(spec["query"])
    body = CypherRequest(statement=spec["query"], parameters=spec["parameters"], directed=bool(spec.get("directed")))
    # The existing path enforces READ_ACCESS, EXPLAIN query_type == r,
    # source row/byte limits, endpoint hydration, and transaction rollback.
    raw, _, _, rows, _ = execute_query(source, body, byte_limit=source.max_bytes,
                                      timeout_seconds=source.timeout_seconds)
    if not raw["vertices"] or not raw["edges"]:
        raise ValueError("The extract is empty; no placeholder graph will be substituted")
    identities = {json.dumps(v["id"], sort_keys=True): i for i, v in enumerate(raw["vertices"])}
    directed = bool(spec.get("directed"))
    pairs = set()
    for edge in raw["edges"]:
        u, v = (identities[json.dumps(edge[k], sort_keys=True)] for k in ("source", "target"))
        if u != v:
            pairs.add((u, v) if directed else (min(u, v), max(u, v)))
    graph = canonical(spec["id"], len(identities), pairs, directed=directed)
    # Export only anonymous topology for backend timings. No source labels,
    # attributes or Neo4j element identifiers leave the bounded read result.
    return graph, dict(dataset=spec["dataset"], query=spec["query"], parameters=spec["parameters"],
                       extracted_at=utc_now(), query_rows=rows, source_load_finished_at=source._catalog["load_finished_at"],
                       projection="anonymous simple topology; self-loops removed; parallel edges collapsed")


def dataset_settings(settings, *, registry=None, instances=None, password_file=None):
    root = settings.repository_root
    return replace(settings,
        neo4j_datasets_registry=registry or settings.neo4j_datasets_registry or root / "deploy/neo4j-datasets/registry.json",
        neo4j_instances_root=instances or settings.neo4j_instances_root or Path("/data/labdata/wajid/graphmine_data/neo4j-instances"),
        neo4j_datasets_password_file=password_file or settings.neo4j_datasets_password_file or root / ".database-workspace/demo.env")


def prepare_graph(directory, spec, settings):
    if not NAME.fullmatch(spec["id"]):
        raise ValueError("Invalid benchmark graph ID")
    path = Path(directory) / "graphs" / (spec["id"] + ".json")
    metadata = path.with_suffix(".metadata.json")
    if path.exists() or metadata.exists():
        saved = json.loads(metadata.read_text())
        if saved["spec_sha256"] != digest(spec) or saved["content_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("Saved benchmark graph or configuration changed")
        return path, saved
    if spec["source"] == "generated":
        graph, provenance = generate(spec), {"generator": spec, "generated_at": utc_now()}
    elif spec["source"] == "neo4j":
        graph, provenance = extract(spec, settings)
    else:
        raise ValueError("Benchmarks accept generated and registered Neo4j graphs only")
    raw = json.dumps(graph, separators=(",", ":"), allow_nan=False).encode()
    atomic_json(path, graph)
    saved = dict(graph_id=spec["id"], n=len(graph["vertices"]), m=len(graph["edges"]),
                 spec_sha256=digest(spec), content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                 snapshot_fingerprint=digest(graph), input_bytes=path.stat().st_size, provenance=provenance)
    atomic_json(metadata, saved)
    return path, saved
