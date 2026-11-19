"""Presentation roles for public output types, independent of model guesses.

Source namespaces and numeric meanings are explicit. Unrecognized diagnostic
fields stay inspectable but never become visual encodings by accident.
"""
from __future__ import annotations

from copy import deepcopy


def role(kind, **metadata):
    return {"role": kind, **metadata}


ENTITY = role("entity", namespace="input", identity="typed")
EDGE = role("entity", namespace="input_edge", identity="typed")
SCORE = role("score", signed=True, higher_is_better=None)
GROUP = role("group_key")
ITEM = role("item")
METRIC = role("metric")
TYPE_ROLES = {
    "scalar": {"value": METRIC},
    "rational_scalar": {"numerator": METRIC, "denominator": METRIC, "display": role("diagnostic")},
    "vertex_set": {"value[]": ENTITY},
    "edge_ids": {"value[]": EDGE},
    "edge_set": {"source": ENTITY, "target": ENTITY, "edge": EDGE, "weight": role("weight")},
    "vertex_scores": {"vertex": ENTITY, "score": SCORE},
    "edge_scores": {"edge": EDGE, "source": ENTITY, "target": ENTITY, "score": SCORE},
    "vertex_groups": {"group": GROUP, "vertices[]": ENTITY},
    "vertex_partition": {"vertex": ENTITY, "group": GROUP, "part": GROUP, "community": GROUP},
    "bipartite_groups": {"item": ITEM, "left_vertices[]": role("side", side="left", namespace="input"), "right_vertices[]": role("side", side="right", namespace="input")},
    "path_set": {"item": ITEM, "vertices[]": ENTITY, "edges[]": EDGE, "weight": role("weight")},
    "edge_sequence_collection": {"item": ITEM, "vertices[]": ENTITY, "edges[]": EDGE, "weight": role("weight")},
    "temporal_path_table": {"vertex": ENTITY, "source": ENTITY, "target": ENTITY, "arrival": role("time", unit="input"), "departure": role("time", unit="input")},
    "widest_path_tree": {"vertex": ENTITY, "predecessor": ENTITY, "capacity": role("weight"), "reachable": role("diagnostic")},
    "walk_sample": {"value[][]": role("entity", namespace="input", ordered=True)},
    "numeric_sample": {"value[]": role("score", signed=True, higher_is_better=None, namespace="sample")},
    "vertex_positions": {"vertex": ENTITY, "coordinates": role("coordinates", space="layout")},
    "vertex_locations": {"vertex": ENTITY, "location": role("coordinates", space="geographic", unit="degrees"), "confidence": SCORE},
    "vertex_confidence": {"vertex": ENTITY, "confidence": SCORE, "weighted_mean_neighbor_distance_km": role("score", unit="km", signed=False, higher_is_better=False, meaning="neighbor_dispersion")},
    "vertex_embeddings": {"vertex": ENTITY, "values": role("coordinates", space="embedding"), "embedding": role("coordinates", space="embedding")},
    "relation_embeddings": {"relation": role("entity", namespace="relation"), "values": role("coordinates", space="embedding")},
    "entity_embeddings": {"entity": role("entity", namespace="declared"), "embedding": role("coordinates", space="embedding")},
    "vertex_signal": {"vertex": ENTITY, "value": role("coordinates", space="signal"), "value[0]": role("score", signed=True, meaning="first_signal_component")},
    "entity_ranking": {"entity": role("entity", namespace="declared"), "vertex": ENTITY, "edge": EDGE, "score": SCORE, "rank": role("order")},
    "pair_scores": {"source": ENTITY, "target": ENTITY, "score": SCORE},
    "record_pair_collection": {"source": ENTITY, "target": ENTITY, "left": ENTITY, "right": ENTITY, "score": SCORE, "rule_ids": role("diagnostic")},
    "cross_graph_mapping": {"graph_a_vertex": role("entity", namespace="left"), "graph_b_vertex": role("entity", namespace="right"), "source": role("entity", namespace="left"), "target": role("entity", namespace="right"), "score": SCORE},
    "vertex_mappings": {"item": ITEM, "query_vertex": role("entity", namespace="pattern"), "data_vertex": ENTITY},
    "pattern_collection": {"pattern_id": ITEM, "pattern": role("graph", namespace="pattern"), "support": METRIC},
    "motif_instances": {"pattern": GROUP, "vertices[]": ENTITY, "item": ITEM},
    "graphlet_instances": {"pattern": GROUP, "vertices[]": ENTITY, "item": ITEM},
    "temporal_occurrence_collection": {"vertices[]": ENTITY, "edges[]": EDGE, "item": ITEM, "timestamp": role("time", unit="input")},
    "edge_sample": {"source": ENTITY, "target": ENTITY, "edge": EDGE},
    "neighbor_lists": {"vertex": ENTITY, "neighbors[]": ENTITY},
    "vertex_coarsening": {"vertex": ENTITY, "coarse_vertex": role("entity", namespace="output")},
    "persistence_intervals": {"dimension": GROUP, "birth": role("order", unit="filtration"), "death": role("order", unit="filtration", nullable="essential_or_right_censored")},
    "eigenpairs": {"eigenvalue": SCORE, "eigenvector": role("score", namespace="input_vertex_order", signed=True, higher_is_better=None)},
    "graph": {"vertices[].id": role("entity", namespace="output"), "edges[].id": role("entity", namespace="output_edge"), "edges[].source": role("entity", namespace="output"), "edges[].target": role("entity", namespace="output"), "edges[].weight": role("weight")},
    "learning_predictions": {"vertex": ENTITY, "entity": role("entity", namespace="declared"), "prediction": SCORE, "class": GROUP},
    "vertex_predictions": {"vertex": ENTITY, "prediction": role("score", signed=True, higher_is_better=None), "split": GROUP, "probabilities": role("diagnostic")},
    "graph_predictions": {"graph": role("entity", namespace="graph_collection"), "prediction": SCORE, "split": GROUP, "probabilities": role("diagnostic")},
    "learning_metrics": {"value": METRIC},
    "model_state": {"value": role("diagnostic")},
    "table": {"row": ITEM},
}

# Field meanings for open table outputs are operation-specific, not inferred
# from a numeric value or an arbitrary uploaded column name.
TABLE_ROLES = {
    "node-lookup": {"id": ENTITY},
    "neighbors": {"vertex": ENTITY, "id": ENTITY, "distance": role("order", unit="hops")},
    "common-neighbors": {"vertex": ENTITY, "id": ENTITY},
    "edge-filter": {"id": EDGE, "source": ENTITY, "target": ENTITY, "weight": role("weight")},
    "query-paths": {"vertices[]": ENTITY, "edges[]": EDGE, "length": role("order", unit="hops")},
    "breadth-first-search": {"vertex": ENTITY, "distance": role("order", unit="hops"), "predecessor": ENTITY},
    "many-source-shortest-paths": {"source": ENTITY, "target": ENTITY, "distance": role("score", signed=True, higher_is_better=False)},
    "transitive-closure": {"source": ENTITY, "target": ENTITY, "reachable": role("diagnostic")},
    "link-prediction": {"source": ENTITY, "target": ENTITY, "score": role("score", signed=False, higher_is_better=True)},
    "graph-aggregate": {"group": GROUP, "value": METRIC, "count": METRIC},
    "motif-counting": {"pattern": GROUP, "count": METRIC},
    "graphlet-counting": {"pattern": GROUP, "count": METRIC},
    "graph-edit-distance": {"source": role("entity", namespace="left"), "target": role("entity", namespace="right"), "cost": role("weight")},
}


def field_roles(operation, port, rows=()):
    fields = deepcopy(TYPE_ROLES.get(port.get("type"), {"value": role("diagnostic")}))
    if port.get("type") == "table":
        fields.update(deepcopy(TABLE_ROLES.get(operation, {})))
    if port.get("vertex_field"):
        fields[port["vertex_field"]] = deepcopy(ENTITY)
    if port.get("score_field"):
        fields[port["score_field"]] = deepcopy(SCORE)
    if operation == "vertex-coloring":
        fields[port.get("score_field", "color")] = deepcopy(GROUP)
    if operation == "single-source-shortest-paths":
        fields.update(distance=role("score", signed=True, higher_is_better=False), predecessor=deepcopy(ENTITY))
    if port.get("type") == "entity_ranking":
        targets = {r.get("anomaly_target") for r in rows if isinstance(r, dict)}
        if len(targets) == 1:
            fields["entity"] = role("entity", namespace={"vertex": "input", "edge": "input_edge", "subgraph": "input_subgraph"}.get(next(iter(targets)), "declared"), identity="typed")
    for row in rows:
        if isinstance(row, dict):
            for key, value in row.items():
                name = key + "[]" if isinstance(value, list) and key + "[]" in fields else key
                fields.setdefault(name, role("diagnostic"))
    return fields


def catalog_roles(operation, ports):
    """Attach roles without changing the native calculation contract."""
    return {name: field_roles(operation, {"type": typ if isinstance(typ, str) else typ.get("type")}) for name, typ in ports.items()}
