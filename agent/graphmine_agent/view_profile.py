"""Bounded, deterministic summaries of saved data, never new analysis results."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from statistics import median

from .graph_context import display_name, identity
from .view_contracts import field_roles

ROW_BUDGET = 10000
GRAPH_BUDGET = 20000
MEMBERSHIP_BUDGET = 100000


def finite(value):
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def fingerprint(value):
    """Streaming canonical hash; includes attributes, typed IDs and edge order."""
    digest = hashlib.sha256()
    for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False).iterencode(value):
        digest.update(part.encode())
    return digest.hexdigest()


def rows_for(port, limit=ROW_BUDGET):
    value = port.get("value")
    if isinstance(value, list):
        return value[:limit], len(value)
    if port.get("type") == "eigenpairs" and isinstance(value, dict):
        values = value.get("eigenvalues", [])
        vectors = value.get("eigenvectors", [])
        return [{"eigenvalue": v, "eigenvector": [row[i] for row in vectors[:GRAPH_BUDGET] if isinstance(row, list) and i < len(row)]} for i, v in enumerate(values[:min(limit, 64)])], len(values)
    if port.get("type") in {"motif_instances", "graphlet_instances"} and isinstance(value, dict):
        total = sum(len(rows) for rows in value.values() if isinstance(rows, list))
        rows = []
        for name, items in sorted(value.items()):
            if isinstance(items, list):
                rows.extend({"pattern": name, "vertices": item} for item in items[:max(0, limit - len(rows))])
        return rows, total
    if value is None:
        return [], 0
    return [value], 1


def node_type(vertex):
    attrs = vertex.get("attributes") or {}
    value = vertex.get("type") or attrs.get("type") or vertex.get("labels") or attrs.get("labels")
    if isinstance(value, list):
        value = " / ".join(map(str, value[:4]))
    return str(value)[:200] if value is not None else "Entity"


def edge_type(edge):
    attrs = edge.get("attributes") or {}
    return str(edge.get("type") or edge.get("relationship_type") or attrs.get("type") or attrs.get("relationship_type") or "Connection")[:200]


def graph_facts(graph):
    if graph is None:
        return None
    vertices, edges = graph.get("vertices", []), graph.get("edges", [])
    n, m = len(vertices), len(edges)
    directed = bool(graph.get("graph", {}).get("directed"))
    sample = edges[:GRAPH_BUDGET]
    pairs = [(identity(e["source"]), identity(e["target"])) for e in sample]
    pairs = pairs if directed else [tuple(sorted(pair)) for pair in pairs]
    unique = set(pair for pair in pairs if pair[0] != pair[1])
    denominator = n * (n - 1) / (1 if directed else 2)
    return {
        "vertices": n, "edges": m, "directed": directed,
        "density": len(unique) / denominator if m <= GRAPH_BUDGET and denominator else (0 if n < 2 else None),
        "density_definition": "distinct non-loop connections / possible connections",
        "parallel_edges": len(set(pairs)) < len(pairs),
        "self_loops": any(a == b for a, b in pairs),
        "vertex_types": dict(Counter(node_type(v) for v in vertices[:GRAPH_BUDGET]).most_common(32)),
        "edge_types": dict(Counter(edge_type(e) for e in sample).most_common(32)),
        "named_vertices": sum(display_name(v) != str(v["id"]) for v in vertices[:GRAPH_BUDGET]),
        "scanned_vertices": min(n, GRAPH_BUDGET), "scanned_edges": len(sample),
        "statistics_complete": n <= GRAPH_BUDGET and m <= GRAPH_BUDGET,
    }


def profile_result(problem, port, original=None, focused=None):
    rows, total = rows_for(port)
    roles = field_roles(problem, port, rows[:100])
    group_counts = Counter()
    membership = Counter()
    sizes = []
    scanned_memberships = 0
    memberships_complete = True
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if problem == "vertex-coloring":
            group_counts[identity(row.get(port.get("score_field", "score")))] += 1
        elif port.get("type") == "vertex_groups":
            members = row.get("vertices", [])
            sizes.append(len(members))
            group_counts[identity(row.get("group", i))] += len(members)
            retained = members[:max(0, MEMBERSHIP_BUDGET - scanned_memberships)]
            membership.update(identity(v) for v in retained)
            scanned_memberships += len(retained)
            memberships_complete &= len(retained) == len(members)
        elif port.get("type") == "vertex_partition":
            group = next((row[k] for k in ("group", "part", "community") if k in row), None)
            if group is not None:
                group_counts[identity(group)] += 1
                membership[identity(row.get("vertex"))] += 1
        elif port.get("type") == "bipartite_groups":
            left, right = row.get("left_vertices", row.get("left", [])), row.get("right_vertices", row.get("right", []))
            sizes.append(len(left) + len(right))
            for members in (left, right):
                retained = members[:max(0, MEMBERSHIP_BUDGET - scanned_memberships)]
                membership.update(identity(v) for v in retained)
                scanned_memberships += len(retained)
                memberships_complete &= len(retained) == len(members)
    score_field = port.get("score_field") or next((key for key, value in roles.items() if value["role"] == "score" and any(isinstance(r, dict) and finite(r.get(key)) is not None for r in rows[:100])), None)
    values = [finite(r.get(score_field)) for r in rows if isinstance(r, dict)] if score_field else [finite(r) for r in rows] if port.get("type") == "numeric_sample" else []
    if port.get("type") == "vertex_signal":
        score_field = "value[0]"
        values = [finite(r["value"][0]) for r in rows if isinstance(r, dict) and isinstance(r.get("value"), list) and r["value"]]
    values = [v for v in values if v is not None]
    scores = None
    if values:
        low, high = min(values), max(values)
        # Normalize before moments to avoid overflow with large finite scores.
        scale = max(abs(low), abs(high), 1)
        normalized = [v / scale for v in values]
        mean = sum(normalized) / len(values)
        variance = sum((v - mean) ** 2 for v in normalized) / len(values)
        skew = sum((v - mean) ** 3 for v in normalized) / len(values) / variance ** 1.5 if variance > 1e-20 else 0
        ranked = sorted(values, reverse=True)
        scores = {"field": score_field or "value", "minimum": low, "maximum": high, "signed": low < 0,
                  "skew": skew, "ties": len(values) - len(set(values)), "top_gap": (ranked[0] / scale - ranked[1] / scale) * scale if len(ranked) > 1 else 0,
                  "count": len(values), "statistics_complete": total <= ROW_BUDGET}
        if not math.isfinite(scores["top_gap"]):
            scores["top_gap"] = None
    source, witness = graph_facts(original), graph_facts(focused)
    source_ids = {identity(v["id"]) for v in (original or {}).get("vertices", [])[:GRAPH_BUDGET]}
    focused_ids = {identity(v["id"]) for v in (focused or {}).get("vertices", [])[:GRAPH_BUDGET]}
    coverage = len(focused_ids & source_ids) / len(source_ids) if source_ids and source and source["vertices"] <= GRAPH_BUDGET and witness and witness["vertices"] <= GRAPH_BUDGET else None
    collection_complete = total <= ROW_BUDGET and memberships_complete
    collection_sizes = sizes or list(group_counts.values())
    pairs = [(len(r.get("left_vertices", r.get("left", []))), len(r.get("right_vertices", r.get("right", []))))
             for r in rows if isinstance(r, dict)] if port.get("type") == "bipartite_groups" else []
    largest_pair = max(pairs, key=lambda pair: (sum(pair), pair[0] * pair[1]), default=None)
    return {
        "version": "1.0.0", "problem": problem, "port_type": port.get("type"), "field_roles": roles, "input": source, "witness": witness,
        "coverage": coverage, "items": total, "scanned_items": len(rows),
        "collection": {"count": len(group_counts) if port.get("type") == "vertex_partition" else total,
                       "covered_vertices": len(set(membership) & source_ids) if collection_complete and source and source["statistics_complete"] else None,
                       "largest_members": max(collection_sizes, default=0) if collection_complete else None,
                       "largest_sides": list(largest_pair) if largest_pair and collection_complete else None,
                       "median_members": median(collection_sizes) if collection_sizes and collection_complete else None,
                       "statistics_complete": collection_complete},
        "statistics_complete": total <= ROW_BUDGET and memberships_complete and all(g is None or g["statistics_complete"] for g in (source, witness)),
        "groups": {"count": len(group_counts), "sizes": [{"id": json.loads(k), "size": v} for k, v in group_counts.most_common(64)],
                   "overlap": any(count > 1 for count in membership.values()), "shared_members": sum(count > 1 for count in membership.values()), "statistics_complete": memberships_complete and total <= ROW_BUDGET,
                   "smallest": min(sizes, default=0), "largest": max(sizes, default=0)},
        "scores": scores, "budget": {"items": ROW_BUDGET, "graph_records": GRAPH_BUDGET, "memberships": MEMBERSHIP_BUDGET, "scanned_memberships": scanned_memberships},
    }
