"""Linear-time, aggregate-only features of canonical native inputs.

Shape uses the simple undirected projection (including for directed inputs).
Size m counts original edge instances. Loops and multiplicity are separate flags.
No graph contents, labels, IDs, or attribute values leave this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from pathlib import Path

FEATURE_VERSION = 1
_CACHE = OrderedDict()
_NUMERIC_FIELDS = {"n", "m", "log_n", "log_m", "average_degree", "density", "max_degree",
                   "degree_cv", "degree_gini", "degeneracy", "connected_components", "largest_component",
                   "directed", "weighted", "self_loops", "parallel_edges", "bipartite_left",
                   "bipartite_right", "bipartite_ratio", "input_bytes", "feature_version", "graph_count"}


def _degeneracy(neighbors):
    """Batagelj/Zaversnik degree buckets: O(n + m), without a heap or sorting."""
    n = len(neighbors)
    if not n:
        return 0
    degree = [len(row) for row in neighbors]
    bins = [0] * (max(degree) + 1)
    for value in degree:
        bins[value] += 1
    start = 0
    for value, count in enumerate(bins):
        bins[value], start = start, start + count
    vertices, positions = [0] * n, [0] * n
    for vertex, value in enumerate(degree):
        positions[vertex] = bins[value]
        vertices[positions[vertex]] = vertex
        bins[value] += 1
    for value in range(len(bins) - 1, 0, -1):
        bins[value] = bins[value - 1]
    bins[0] = 0
    for vertex in vertices:
        for other in neighbors[vertex]:
            if degree[other] > degree[vertex]:
                value = degree[other]
                position, first = positions[other], bins[value]
                swap = vertices[first]
                if other != swap:
                    vertices[position], vertices[first] = swap, other
                    positions[other], positions[swap] = first, position
                bins[value] += 1
                degree[other] -= 1
    return max(degree)


def graph_features(data, *, input_kind="graph", input_bytes=None, snapshot_fingerprint=None):
    if input_bytes is None or snapshot_fingerprint is None:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode()
        input_bytes = len(raw) if input_bytes is None else input_bytes
        snapshot_fingerprint = snapshot_fingerprint or hashlib.sha256(raw).hexdigest()
    result = dict(feature_version=FEATURE_VERSION, snapshot_fingerprint=snapshot_fingerprint,
                  input_kind=input_kind, input_bytes=input_bytes)
    if input_kind != "graph":
        # Structured inputs have no implied pairwise edges. Never expand a
        # hyperedge or compute distances between feature vectors here.
        n = len(data.get("vertices", data.get("vectors", [])))
        m = len(data.get("hyperedges", [])) if input_kind == "hypergraph" else 0
        result.update(n=n, m=m, log_n=math.log1p(n), log_m=math.log1p(m),
                      average_degree=None, density=None, max_degree=None, degree_cv=None,
                      degree_gini=None, degeneracy=None, connected_components=None,
                      largest_component=None, directed=False, weighted=False,
                      self_loops=None, parallel_edges=None, bipartite_left=None,
                      bipartite_right=None, bipartite_ratio=None)
        if input_kind == "graph_collection":
            result["graph_count"] = len(data.get("graphs", []))
            n = sum(len(g.get("vertices", [])) for g in data.get("graphs", []))
            m = sum(len(g.get("edges", [])) for g in data.get("graphs", []))
            result.update(n=n, m=m, log_n=math.log1p(n), log_m=math.log1p(m))
        return result
    vertices, edges = data.get("vertices", []), data.get("edges", [])
    index = {(type(v["id"]), v["id"]): i for i, v in enumerate(vertices)}
    n, m = len(vertices), len(edges)
    neighbors = [set() for _ in vertices]
    directed = bool(data.get("graph", {}).get("directed", False))
    seen, loops, parallel, weighted = set(), False, False, False
    for edge in edges:
        u, v = (index[(type(edge[key]), edge[key])] for key in ("source", "target"))
        loops |= u == v
        weighted |= "weight" in edge
        pair = (u, v) if directed or u <= v else (v, u)
        parallel |= pair in seen
        seen.add(pair)
        if u != v:
            neighbors[u].add(v)
            neighbors[v].add(u)
    degree = [len(row) for row in neighbors]
    total = sum(degree)
    mean = total / n if n else 0.0
    maximum = max(degree, default=0)
    histogram = [0] * (maximum + 1)
    for value in degree:
        histogram[value] += 1
    rank, weighted_ranks = 0, 0
    for value, count in enumerate(histogram):
        weighted_ranks += value * (2 * rank + count + 1) * count / 2
        rank += count
    gini = 2 * weighted_ranks / (n * total) - (n + 1) / n if n and total else 0.0
    unvisited = bytearray([1]) * n
    components, largest = 0, 0
    for start in range(n):
        if not unvisited[start]:
            continue
        components += 1
        queue, size = [start], 0
        unvisited[start] = 0
        while queue:
            vertex = queue.pop()
            size += 1
            for other in neighbors[vertex]:
                if unvisited[other]:
                    unvisited[other] = 0
                    queue.append(other)
        largest = max(largest, size)
    left = sum(v.get("attributes", {}).get("side") == "left" for v in vertices)
    right = sum(v.get("attributes", {}).get("side") == "right" for v in vertices)
    known_sides = n > 0 and left + right == n
    result.update(n=n, m=m, log_n=math.log1p(n), log_m=math.log1p(m),
                  average_degree=mean, density=total / (n * (n - 1)) if n > 1 else 0.0,
                  max_degree=maximum,
                  degree_cv=math.sqrt(sum((d - mean) ** 2 for d in degree) / n) / mean if mean else 0.0,
                  degree_gini=max(0.0, gini), degeneracy=_degeneracy(neighbors),
                  connected_components=components, largest_component=largest,
                  directed=directed, weighted=weighted, self_loops=loops,
                  parallel_edges=parallel, bipartite_left=left if known_sides else None,
                  bipartite_right=right if known_sides else None,
                  bipartite_ratio=left / right if known_sides and right else None)
    return result


def cached_features(data, directory, *, snapshot_fingerprint, input_kind="graph", input_bytes=None):
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_fingerprint):
        raise ValueError("Expected a SHA-256 snapshot fingerprint")
    path = Path(directory) / "features" / (snapshot_fingerprint + ".json")
    key = str(path), input_kind, FEATURE_VERSION
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return dict(_CACHE[key])
    try:
        result = json.loads(path.read_text())
        if (result["feature_version"] == FEATURE_VERSION
                and result["snapshot_fingerprint"] == snapshot_fingerprint
                and result["input_kind"] == input_kind
                and _NUMERIC_FIELDS - {"graph_count"} <= set(result)
                and set(result) <= _NUMERIC_FIELDS | {"snapshot_fingerprint", "input_kind"}
                and all(value is None or type(value) in (int, float, bool)
                        and math.isfinite(value) for name, value in result.items() if name in _NUMERIC_FIELDS)):
            return result
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = graph_features(data, input_kind=input_kind, input_bytes=input_bytes,
                            snapshot_fingerprint=snapshot_fingerprint)
    _CACHE[key] = dict(result)
    while len(_CACHE) > 256:
        _CACHE.popitem(last=False)
    # The caller queues this write; feature computation never waits for fsync.
    return result


def safe_parameters(parameters, schemas):
    """Only typed scalars and catalog-defined enums; collections become counts."""
    result = {}
    identifiers = {"source", "target", "sink", "vertex", "seed_vertex", "anchor_edge",
                   "vertex_id", "edge_id", "root"}
    defaults = {}
    for key, schema in schemas.items():
        spec = schema.schema() if hasattr(schema, "schema") else schema
        if "default" in spec:
            defaults[key] = spec["default"]
    for key, value in {**defaults, **parameters}.items():
        spec = schemas.get(key, {})
        if hasattr(spec, "schema"):
            spec = spec.schema()
        if key not in schemas:
            continue  # Unknown names might themselves contain user data.
        kind = spec.get("kind", spec.get("type"))
        if isinstance(value, (list, dict)):
            result[key] = {"count": len(value)}
        elif value is None:
            result[key] = None
        elif kind == "vertex_id" or key in identifiers or key.endswith("_id"):
            result[key] = {"redacted": True}
        elif type(value) in (bool, int, float) and kind in {"boolean", "integer", "number"}:
            result[key] = value
        elif isinstance(value, str) and value in spec.get("choices", spec.get("enum", [])):
            result[key] = value
        else:
            result[key] = {"redacted": True}
    return result
