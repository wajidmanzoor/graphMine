"""Full-input profiles and conservative, application-owned routing eligibility."""

from collections import Counter
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from .graph_context import fields, identity, infer_bipartition


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def field_profile(records):
    """Scan every record and field; keep at most five example values per field."""
    result = {}
    for record in records:
        for name, value in fields(record).items():
            entry = result.setdefault(name, {"present": 0, "numeric": 0, "examples": []})
            entry["present"] += 1
            if numeric(value):
                entry["numeric"] += 1
                entry["minimum"] = min(entry.get("minimum", value), value)
                entry["maximum"] = max(entry.get("maximum", value), value)
            if value is not None and isinstance(value, (str, int, float, bool)):
                if len(entry["examples"]) < 5 and not any(identity(value) == identity(old) for old in entry["examples"]):
                    entry["examples"].append(value if not isinstance(value, str) else value[:240])
    for entry in result.values():
        entry["missing"] = len(records) - entry["present"]
    return result


def input_profile(descriptor):
    data, kind = descriptor["data"], descriptor["kind"]
    vertices, edges = data.get("vertices", []), data.get("edges", [])
    result = {"input_kind": kind, "directed": None, "weighted": False,
              "bipartite": False, "temporal": False,
              "vertices_count": len(vertices), "edges_count": len(edges)}
    if kind == "graph_collection":
        graphs = data.get("graphs", [])
        result.update(graphs_count=len(graphs),
                      vertices_count=sum(len(row.get("vertices", [])) for row in graphs),
                      edges_count=sum(len(row.get("edges", [])) for row in graphs))
    elif kind == "hypergraph":
        result["hyperedges_count"] = len(data.get("hyperedges", []))
    elif kind == "feature_vectors":
        result["vectors_count"] = len(data.get("vectors", []))
    if kind != "graph":
        return result
    vertex_fields, edge_fields = field_profile(vertices), field_profile(edges)
    weight_fields = [name for name, stats in edge_fields.items()
                     if (name == "weight" or name.startswith("attributes.")) and stats["numeric"]]
    complete_weights = sum(numeric(row.get("weight")) for row in edges) == len(edges)
    candidates = [name for name in weight_fields if name != "weight" and edge_fields[name]["numeric"] == len(edges)]
    timestamps = sum(row.get("timestamp") is not None for row in edges)
    left = infer_bipartition(data)
    # The routing profile follows the strict crossing-edge definition. Native
    # algorithms may separately declare a loop-dropping projection.
    left_keys = {identity(value) for value in left or []}
    crossing = left is not None and all(
        (identity(edge["source"]) in left_keys) != (identity(edge["target"]) in left_keys)
        for edge in edges)
    types = Counter(row.get("type", "unspecified") for row in vertices)
    result.update(
        directed=data["graph"]["directed"], weighted=bool(weight_fields),
        canonical_weights_complete=complete_weights, weight_fields=weight_fields,
        weight_candidates=candidates, temporal=bool(timestamps),
        timestamps_complete=timestamps == len(edges),
        timestamp_candidates=[name for name, info in edge_fields.items()
                              if name == "attributes.timestamp" and info["present"] == len(edges)
                              and all((type(fields(row).get(name)) is int or isinstance(fields(row).get(name), str))
                                      and fields(row).get(name) != "" for row in edges)],
        bipartite=crossing,
        bipartition={"available": left is not None, "source": "attributes.side" if any("side" in row.get("attributes", {}) for row in vertices) else "vertex_types",
                     "left_count": len(left) if left is not None else None,
                     "right_count": len(vertices) - len(left) if left is not None else None},
        vertex_types=sorted(types), vertex_type_count=dict(types),
        edge_type_count=dict(Counter(row.get("type", "unspecified") for row in edges)),
        vertex_fields=vertex_fields, edge_fields=edge_fields,
    )
    return result


@lru_cache(maxsize=4)
def _requirements(path):
    return json.loads(Path(path).read_text())["problems"]


def attach_requirements(cards, repository_root):
    requirements = _requirements(str(Path(repository_root) / "catalog/problem_requirements.json"))
    for card in cards:
        if card["id"] not in requirements:
            raise ValueError(f"Problem requirements are missing for {card['id']}")
        spec = deepcopy(requirements[card["id"]])
        if spec["input_kind"] != card["input_kind"]:
            raise ValueError(f"Problem input contract changed for {card['id']}")
        card["requirements"] = spec
    return cards


def requested_preferences(question, parameters=None):
    text = question.casefold()
    return {"exact": bool(re.search(r"\b(exact|guaranteed|certified)\b", text)),
            "weighted": bool(re.search(r"(?<!un)\bweighted\b|\b(weights|costs|capacities)\b", text)),
            "unweighted": bool(re.search(r"\bunweighted\b", text)),
            "parameters": parameters or {}}


def eligible(card, profile, requested=None):
    """Only hard exclusions. Direction/weight preferences do not hide choices."""
    requested = requested or {}
    req = card["requirements"]
    if req["input_kind"] != profile["input_kind"]:
        return False, f"Requires {req['input_kind'].replace('_', ' ')} input."
    qualities = card.get("parameters", {}).get("solution_quality", {}).get("choices", [])
    if requested.get("exact") and card.get("quality") == "heuristic" and "exact" not in qualities:
        return False, "Only a heuristic is available; it cannot meet the explicit exact request."
    if profile.get("unknown_data"):
        return True, None  # A prior preparation step can produce this input kind.
    if (req["weights"] == "required" and not req["unit_weight_mode"]
            and not profile.get("canonical_weights_complete") and not profile.get("weight_candidates")):
        return False, "Every edge needs a weight; no complete numeric field or unit-weight mode is available."
    parameters = requested.get("parameters", {})
    for need in req["needs"]:
        if need == "bipartite_side" and not (profile.get("bipartite") or profile.get("bipartition", {}).get("available")) and not (
                parameters.get("left_partition") is not None and parameters.get("right_partition") is not None):
            return False, "Bipartite sides are missing or some edges do not cross between the declared sides."
        if need == "timestamps" and not profile.get("timestamps_complete") and not profile.get("timestamp_candidates"):
            return False, "Every event needs a timestamp."
        if need == "query_graph" and not profile.get("query_graph_available") and not any(
                parameters.get(key) is not None for key in ("query_graph", "other_graph", "temporal_motif", "motifs")):
            return False, "A separate query or comparison graph is required."
    # Source/sink values are arguments, not absent graph data. The lane handler
    # asks for those values before constructing an executable plan.
    return True, None


def score_hints(card, profile, requested=None):
    requested = requested or {}
    req, score, reasons = card["requirements"], 0, []
    direction = None if profile.get("directed") is None else "directed" if profile["directed"] else "undirected"
    if direction is not None and req["direction"] == direction:
        score += 2
        reasons.append("Matches the input direction.")
    elif direction is not None and req["direction"] != "either":
        score -= 2
        reasons.append("Input direction needs an explicit conversion before execution.")
    if requested.get("weighted"):
        score += 1 if req["weights"] != "ignored" else -1
    if requested.get("unweighted"):
        score += 1 if req["weights"] == "ignored" or req["unit_weight_mode"] else -1
    if requested.get("exact") and card.get("quality") == "exact":
        score += 1
    return {"score": score, "reasons": reasons}


def promotion_choices(card, profile):
    req, choices = card["requirements"], []
    if req["weights"] != "ignored" and not profile.get("canonical_weights_complete"):
        choices.extend({"kind": "weight", "field": field, "label": f"Use {field.removeprefix('attributes.')} as the weight?"}
                       for field in profile.get("weight_candidates", []))
    if "bipartite_side" in req["needs"] and profile.get("bipartite") and profile["bipartition"]["source"] == "vertex_types":
        choices.append({"kind": "sides", "types": profile["vertex_types"],
                        "label": f"Use {' / '.join(profile['vertex_types'])} as the two sides?"})
    return choices
