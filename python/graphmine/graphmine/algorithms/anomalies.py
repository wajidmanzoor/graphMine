from __future__ import annotations

import networkx as nx
import numpy as np
from scipy import stats

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph, external_id
from ..registry import register
from ._numeric import float64
from .alignment import id_order
from .entity_resolution import _MISSING, _field

_MEASURES = {
    "vertex": {
        "degree",
        "in_degree",
        "out_degree",
        "strength",
        "in_strength",
        "out_strength",
        "triangle_count",
        "ego_edge_count",
        "event_count",
        "in_event_count",
        "out_event_count",
        "numeric_attribute",
    },
    "edge": {
        "edge_weight",
        "source_degree",
        "target_degree",
        "common_neighbors",
        "numeric_attribute",
    },
    "subgraph": {
        "vertex_count",
        "edge_count",
        "density",
        "weight_sum",
        "numeric_attribute",
    },
}


def _definitions(definitions, target, directed):
    if not definitions:
        raise GraphMineError("feature_definitions must not be empty")
    names = set()
    for feature in definitions:
        if not isinstance(feature, dict) or set(feature) - {"name", "measure", "field"}:
            raise GraphMineError("Unknown anomaly feature fields")
        name, measure = feature.get("name"), feature.get("measure")
        if not isinstance(name, str) or not name or name in names:
            raise GraphMineError("Feature names must be nonempty and unique")
        names.add(name)
        if not isinstance(measure, str) or measure not in _MEASURES[target]:
            raise GraphMineError(f"Unsupported {target} feature measure")
        if measure.startswith(("in_", "out_")) and not directed:
            raise GraphMineError("In/out features require directed input")
        if (
            measure in {"triangle_count", "ego_edge_count", "common_neighbors"}
            and directed
        ):
            raise GraphMineError(
                "Triangle/ego/common-neighbor features require undirected input"
            )
        if measure == "numeric_attribute":
            field = feature.get("field")
            if not isinstance(field, str) or not all(field.split(".")):
                raise GraphMineError(
                    "numeric_attribute requires a nonempty attributes field path"
                )
        elif "field" in feature:
            raise GraphMineError("field applies only to numeric_attribute")


def _population(graph, target, subgraphs):
    if target != "subgraph":
        if subgraphs is not None:
            raise GraphMineError("subgraphs applies only to subgraph anomalies")
        records = graph.to_canonical()["vertices" if target == "vertex" else "edges"]
    else:
        if not isinstance(subgraphs, list):
            raise GraphMineError(
                "Subgraph anomalies require a declared subgraphs array"
            )
        records = []
        for row in subgraphs:
            if (
                not isinstance(row, dict)
                or set(row) - {"id", "vertices", "attributes"}
                or "id" not in row
                or not isinstance(row.get("vertices"), list)
            ):
                raise GraphMineError(
                    "Every subgraph needs id and vertices, with optional attributes"
                )
            nodes = [graph.index(v) for v in row["vertices"]]
            if len(set(nodes)) != len(nodes):
                raise GraphMineError("Subgraph vertices must be distinct")
            if not isinstance(row.get("attributes", {}), dict):
                raise GraphMineError("Subgraph attributes must be an object")
            records.append({**row, "indices": set(nodes)})
    indexed = {}
    for record in records:
        key = external_id(record["id"])
        if key in indexed:
            raise GraphMineError("Anomaly entity IDs must be unique")
        indexed[key] = record
    return indexed


def _select(population, selection, name):
    if selection is None:
        return list(population)
    if not isinstance(selection, list):
        raise GraphMineError(f"{name} must be an array")
    selected = [external_id(v) for v in selection]
    if len(set(selected)) != len(selected) or any(
        v not in population for v in selected
    ):
        raise GraphMineError(f"{name} must contain distinct known entity IDs")
    return selected


def _features(graph, target, population, ids, definitions, work):
    work.tick(len(ids) * len(definitions) + graph.edge_count)
    g = graph.to_networkx(
        direction="preserve", parallel_edges="collapse", self_loops="keep"
    )
    measures = {d["measure"] for d in definitions}
    weighted = None
    if measures & {"strength", "in_strength", "out_strength"}:
        weighted = graph.to_networkx(
            direction="preserve", parallel_edges="sum", self_loops="keep", weighted=True
        )
    loop_free = g.copy()
    loop_free.remove_edges_from(nx.selfloop_edges(loop_free))
    events = graph.to_canonical()["edges"]
    endpoint_rows = [
        (graph.index(e["source"]), graph.index(e["target"]), e) for e in events
    ]
    triangles = (
        nx.triangles(loop_free, backend="networkx")
        if "triangle_count" in measures
        else {}
    )
    rows = []
    for entity in ids:
        record = population[entity]
        values = []
        for definition in definitions:
            measure = definition["measure"]
            if measure == "numeric_attribute":
                value = _field(record.get("attributes", {}), definition["field"])
                if value is _MISSING:
                    raise GraphMineError(
                        f"Entity {entity!r} is missing a numeric feature field"
                    )
            elif target == "vertex":
                v = graph.index(entity)
                if measure in {
                    "degree",
                    "in_degree",
                    "out_degree",
                    "strength",
                    "in_strength",
                    "out_strength",
                }:
                    method = measure.replace("strength", "degree")
                    value = getattr(weighted if "strength" in measure else g, method)(
                        v, weight="weight" if "strength" in measure else None
                    )
                elif measure == "triangle_count":
                    value = triangles[v]
                elif measure == "ego_edge_count":
                    value = loop_free.subgraph({v, *loop_free[v]}).number_of_edges()
                else:
                    value = sum(
                        (v == a or v == b)
                        if measure == "event_count"
                        else v == b
                        if measure == "in_event_count"
                        else v == a
                        for a, b, _ in endpoint_rows
                    )
            elif target == "edge":
                u, v = graph.index(record["source"]), graph.index(record["target"])
                if measure == "edge_weight":
                    value = record.get("weight", 1)
                elif measure == "source_degree":
                    value = g.degree(u)
                elif measure == "target_degree":
                    value = g.degree(v)
                else:
                    value = len((set(loop_free[u]) & set(loop_free[v])) - {u, v})
            else:
                nodes = record["indices"]
                if measure == "vertex_count":
                    value = len(nodes)
                elif measure == "density":
                    value = nx.density(loop_free.subgraph(nodes))
                elif measure == "edge_count":
                    value = sum(u in nodes and v in nodes for u, v, _ in endpoint_rows)
                else:
                    value = sum(
                        e.get("weight", 1)
                        for u, v, e in endpoint_rows
                        if u in nodes and v in nodes
                    )
            values.append(float64(value))
        rows.append(values)
    return np.asarray(rows, dtype=float).reshape((len(ids), len(definitions)))


@register(
    id="graph-anomalies",
    problem_id="graph_anomaly_detection",
    family="statistics",
    title="Rank graph entities against an explicit normality reference",
    description="NetworkX structural features and SciPy population statistics with declared standardized L1/L2/max scores. Supports vertices, original edge instances and explicitly supplied induced subgraphs. Reference populations are selected independently from candidates; no learned ground-truth anomaly claim is made.",
    library="scipy",
    quality="numerical",
    parameters={
        "anomaly_target": P(
            "string", required=True, choices=("vertex", "edge", "subgraph")
        ),
        "feature_definitions": P(
            "array",
            required=True,
            description="Rows with unique name and measure; numeric_attribute also needs field relative to attributes. Supported measures by target: "
            + "; ".join(
                f"{target}: {', '.join(sorted(measures))}"
                for target, measures in _MEASURES.items()
            ),
        ),
        "normality_reference": P(
            "object",
            required=True,
            description="kind=population with optional graph/entities/subgraphs, or kind=statistics with location/scale arrays.",
        ),
        "scoring_definition": P(
            "object",
            required=True,
            description="method=standardized_l1|standardized_l2|max_abs_z; optional feature_weights and minimum_scale.",
        ),
        "candidate_entities": P("array", None, nullable=True),
        "subgraphs": P(
            "array",
            None,
            nullable=True,
            description="Required for subgraph target: id, vertices, optional attributes.",
        ),
        "top_k": P("integer", required=True, minimum=1),
    },
    references=(
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.zscore.html",
    ),
)
def anomalies(graph, args, work, backend="networkx"):
    target, definitions = args["anomaly_target"], args["feature_definitions"]
    _definitions(definitions, target, graph.directed)
    dimension = len(definitions)
    population = _population(graph, target, args["subgraphs"])
    selected = _select(population, args["candidate_entities"], "candidate_entities")
    scoring, reference = args["scoring_definition"], args["normality_reference"]
    methods = {"standardized_l1", "standardized_l2", "max_abs_z"}
    if (
        set(scoring) - {"method", "feature_weights", "minimum_scale"}
        or not isinstance(scoring.get("method"), str)
        or scoring["method"] not in methods
    ):
        raise GraphMineError("Unsupported scoring_definition")
    weights = scoring.get("feature_weights", [1] * dimension)
    if not isinstance(weights, list) or len(weights) != dimension:
        raise GraphMineError("feature_weights must have one value per feature")
    weights = np.array([float64(w) for w in weights])
    floor = float64(scoring.get("minimum_scale", 0))
    if np.any(weights < 0) or floor < 0:
        raise GraphMineError("Feature weights and minimum_scale must be nonnegative")
    kind = reference.get("kind")
    reference_count, reference_hash = None, None
    if kind == "statistics":
        if set(reference) != {"kind", "location", "scale"} or any(
            not isinstance(reference[name], list) or len(reference[name]) != dimension
            for name in ("location", "scale")
        ):
            raise GraphMineError(
                "Statistics reference needs location/scale arrays matching the feature count"
            )
        location, scale = (
            np.array([float64(v) for v in reference[name]])
            for name in ("location", "scale")
        )
        if np.any(scale < 0):
            raise GraphMineError("Reference scale must be nonnegative")
        origin, mean_delta = location.copy(), np.zeros(dimension)
    elif kind == "population":
        if set(reference) - {"kind", "graph", "entities", "subgraphs"}:
            raise GraphMineError("Unknown population reference fields")
        other = Graph(reference["graph"]) if "graph" in reference else graph
        if other.directed != graph.directed:
            raise GraphMineError("Reference and target graph direction must match")
        subgraphs = reference.get(
            "subgraphs", args["subgraphs"] if "graph" not in reference else None
        )
        ref_population = _population(other, target, subgraphs)
        reference_ids = _select(
            ref_population, reference.get("entities"), "reference entities"
        )
        reference_count, reference_hash = len(reference_ids), other.fingerprint
        if not reference_ids:
            if selected:
                raise GraphMineError(
                    "Anomaly reference population must not be empty when candidates exist"
                )
            location, scale, origin, mean_delta = None, None, None, None
        else:
            reference_values = _features(
                other, target, ref_population, reference_ids, definitions, work
            )
            origin = reference_values[0].copy()
            varying = np.any(reference_values != origin, axis=0)
            mean_delta, scale = np.zeros(dimension), np.zeros(dimension)
            if np.any(varying):
                shifted = reference_values[:, varying] - origin[varying]
                if not np.isfinite(shifted).all():
                    raise GraphMineError(
                        "Reference centering exceeded finite float64 range"
                    )
                mean_delta[varying] = stats.tmean(shifted, axis=0)
                scale[varying] = stats.tstd(shifted, axis=0, ddof=0)
            location = origin + mean_delta
    else:
        raise GraphMineError(
            "normality_reference kind must be population or statistics"
        )
    values = _features(graph, target, population, selected, definitions, work)
    scores, contributions = np.zeros(len(selected)), np.zeros_like(values)
    if location is not None:
        if not np.isfinite(location).all() or not np.isfinite(scale).all():
            raise GraphMineError("Reference statistics exceeded finite float64 range")
        denominator = np.maximum(scale, floor)
        delta = (values - origin) - mean_delta
        if np.any((denominator == 0) & (weights > 0) & (delta != 0)):
            raise GraphMineError(
                "An active feature differs from a zero-variance reference; declare minimum_scale"
            )
        z = np.divide(
            delta,
            denominator,
            out=np.zeros_like(delta),
            where=(denominator > 0) & (weights > 0),
        )
        if scoring["method"] == "standardized_l2":
            contributions = weights * np.square(z)
            scores = np.sqrt(contributions.sum(axis=1))
        else:
            contributions = weights * np.abs(z)
            scores = (
                contributions.sum(axis=1)
                if scoring["method"] == "standardized_l1"
                else contributions.max(axis=1)
            )
        if not np.isfinite(scores).all() or not np.isfinite(contributions).all():
            raise GraphMineError("Anomaly scores exceeded finite float64 range")
    ranked = sorted(
        range(len(selected)), key=lambda i: (-scores[i], id_order(selected[i]))
    )[: args["top_k"]]
    rows = [
        {
            "entity": selected[i],
            "anomaly_target": target,
            "rank": rank + 1,
            "score": float(scores[i]),
            "feature_values": {
                d["name"]: float(values[i, j]) for j, d in enumerate(definitions)
            },
            "feature_contributions": {
                d["name"]: float(contributions[i, j]) for j, d in enumerate(definitions)
            },
        }
        for rank, i in enumerate(ranked)
    ]
    work.output(len(rows) * (1 + 2 * dimension))
    return AlgorithmOutput(
        {
            "ranked_anomalies": rows,
            "scored_entity_count": len(selected),
            "complete": True,
            "reference_statistics": {
                "location": location.tolist() if location is not None else None,
                "scale": scale.tolist() if scale is not None else None,
                "ddof": 0,
                "centering_origin": origin.tolist() if origin is not None else None,
                "mean_delta": mean_delta.tolist() if mean_delta is not None else None,
            },
        },
        {
            "ranking": {
                "type": "entity_ranking",
                "value": rows,
                "complete": len(rows) == len(selected),
                "scope": "top_k_of_scored_population",
            }
        },
        quality="numerical",
        diagnostics={
            "reference_kind": kind,
            "reference_population_count": reference_count,
            "reference_graph_fingerprint": reference_hash,
            "minimum_scale": floor,
            "feature_order": [d["name"] for d in definitions],
            "score_interpretation": "deviation_from_declared_reference_not_ground_truth",
            "edge_identity": "original_event_instances",
            "structural_degree": "parallel_collapsed_self_loop_counts_twice",
            "event_count": "incident_event_instances_self_loop_counts_once",
        },
    )
