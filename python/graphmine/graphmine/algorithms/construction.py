from __future__ import annotations

import math
from collections import defaultdict

import networkx as nx
import numpy as np
from scipy.spatial.distance import cdist

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph
from ..registry import register
from ._common import vertex_values
from ._numeric import float64


@register(
    id="knn-graph",
    problem_id="knn_graph_construction",
    family="construction",
    input_kind="feature_vectors",
    title="Build a graph from nearby feature vectors",
    description="Exact all-pairs SciPy distance search with explicit self-exclusion, metric and symmetrization. Equal-distance ties follow original vector order.",
    parameters={
        "k": P("integer", required=True, minimum=0),
        "distance": P(
            "string",
            "squared_euclidean",
            choices=("squared_euclidean", "euclidean", "cosine"),
        ),
        "search_mode": P("string", "exact", choices=("exact", "approximate")),
        "symmetrization": P(
            "string", "directed", choices=("directed", "union", "mutual")
        ),
    },
    library="scipy",
    quality="numerical",
    references=(
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.distance.cdist.html",
    ),
)
def knn_graph(vectors, args, work, backend="networkx"):
    n, k = vectors.vertex_count, args["k"]
    if not 0 <= k < n:
        raise GraphMineError("k must be smaller than the number of feature vectors")
    work.tick(n * n + n * vectors.dimension)
    array = np.asarray(
        [
            [float64(v) for v in row["values"]]
            for row in vectors.to_canonical()["vectors"]
        ]
    )
    if args["distance"] == "cosine" and np.any(np.linalg.norm(array, axis=1) == 0):
        raise GraphMineError("Cosine distance is undefined for a zero vector")
    metric = (
        "sqeuclidean" if args["distance"] == "squared_euclidean" else args["distance"]
    )
    distances = cdist(array, array, metric=metric)
    if not np.isfinite(distances).all():
        raise GraphMineError("Distance computation exceeded finite numerical range")
    # Roundoff can place a cosine distance just outside its mathematical range.
    if metric == "cosine":
        distances = np.clip(distances, 0, 2)
    chosen = []
    for i in range(n):
        candidates = [j for j in range(n) if j != i]
        chosen.append(sorted(candidates, key=lambda j: (distances[i, j], j))[:k])
    arcs = {(i, j) for i, neighbors in enumerate(chosen) for j in neighbors}
    if args["symmetrization"] == "directed":
        pairs = sorted(arcs)
    elif args["symmetrization"] == "union":
        pairs = sorted({tuple(sorted(edge)) for edge in arcs})
    else:
        pairs = sorted({tuple(sorted((i, j))) for i, j in arcs if (j, i) in arcs})
    graph = Graph.from_edges(
        [
            (vectors.vertex_id(i), vectors.vertex_id(j), float(distances[i, j]))
            for i, j in pairs
        ],
        vertices=vectors.node_ids,
        directed=args["symmetrization"] == "directed",
    )
    rows = [
        {
            "vertex": vectors.vertex_id(i),
            "neighbors": [vectors.vertex_id(j) for j in neighbors],
            "distances": [float(distances[i, j]) for j in neighbors],
        }
        for i, neighbors in enumerate(chosen)
    ]
    work.output(n * k + len(pairs) + n)
    data = {
        "neighbor_lists": rows,
        "graph": graph.to_canonical(),
        "search_metadata": {
            "algorithm": "scipy.spatial.distance.cdist/exhaustive",
            "requested_search_mode": args["search_mode"],
            "actual_search_mode": "exact",
            "distance": args["distance"],
            "tie_break": "input_vector_order",
            "arithmetic": "float64",
        },
    }
    return AlgorithmOutput(
        data,
        {
            "graph": {"type": "graph", "value": graph.to_canonical(), "complete": True},
            "neighbors": {"type": "neighbor_lists", "value": rows, "complete": True},
        },
        quality="numerical",
    )


@register(
    id="graph-coarsening",
    problem_id="graph_coarsening",
    family="construction",
    title="Group vertices and build their weighted quotient graph",
    description="Use a supplied partition or NetworkX maximal matching, then aggregate all fine-edge weights and numeric vertex feature vectors by the declared rule.",
    parameters={
        "cluster_assignment": P(
            "array",
            None,
            nullable=True,
            description="One {vertex, value} row per vertex, with integer cluster values.",
        ),
        "method": P("string", "greedy_matching", choices=("greedy_matching",)),
        "self_loop_policy": P("string", "keep", choices=("keep", "drop")),
        "feature_reduction": P("string", "sum", choices=("sum", "mean")),
    },
)
def coarsening(graph, args, work, backend="networkx"):
    g = graph.to_networkx(
        direction="require_undirected",
        parallel_edges="sum",
        self_loops="reject",
        weighted=True,
        nonnegative=True,
    )
    if args["cluster_assignment"] is None:
        matched = nx.maximal_matching(g, backend="networkx")
        groups = [set(pair) for pair in sorted(tuple(sorted(e)) for e in matched)]
        covered = set().union(*groups) if groups else set()
        groups += [{v} for v in g if v not in covered]
        groups.sort(key=min)
        assignment = {v: i for i, group in enumerate(groups) for v in group}
        method = "networkx.maximal_matching"
    else:
        assignment = vertex_values(
            graph, args["cluster_assignment"], "cluster_assignment"
        )
        if any(type(v) is not int for v in assignment.values()):
            raise GraphMineError("Cluster identifiers must be integers")
        method = "supplied_partition"
    groups = defaultdict(list)
    for v, cluster in assignment.items():
        groups[cluster].append(v)
    weights = defaultdict(lambda: 0)
    for edge in graph.to_canonical()["edges"]:
        work.tick()
        u, v = (
            assignment[graph.index(edge["source"])],
            assignment[graph.index(edge["target"])],
        )
        if u == v and args["self_loop_policy"] == "drop":
            continue
        weights[tuple(sorted((u, v)))] += edge.get("weight", 1)
    fine = graph.to_canonical()["vertices"]
    features = [v.get("attributes", {}).get("features") for v in fine]
    if any(value is not None for value in features):
        if (
            any(not isinstance(value, list) or not value for value in features)
            or len({len(value) for value in features}) != 1
        ):
            raise GraphMineError(
                "All vertices must have equal-width attributes.features arrays when features are present"
            )
        if any(
            type(v) not in (int, float) or (type(v) is float and not math.isfinite(v))
            for row in features
            for v in row
        ):
            raise GraphMineError("Vertex features must be finite numbers")
    vertices = []
    for cluster, members in sorted(groups.items()):
        record = {"id": cluster, "attributes": {"cluster_size": len(members)}}
        if features and features[0] is not None:
            merged = [
                sum(features[v][i] for v in members) for i in range(len(features[0]))
            ]
            if args["feature_reduction"] == "mean":
                merged = [v / len(members) for v in merged]
            record["attributes"]["features"] = merged
        vertices.append(record)
    canonical = {
        "graph": {
            "id": graph.to_canonical()["graph"]["id"] + ":quotient",
            "directed": False,
            "allows_self_loops": args["self_loop_policy"] == "keep",
            "allows_parallel_edges": False,
        },
        "vertices": vertices,
        "edges": [
            {"id": i, "source": u, "target": v, "weight": weight}
            for i, ((u, v), weight) in enumerate(sorted(weights.items()))
        ],
    }
    quotient = Graph(canonical)
    rows = [{"vertex": graph.vertex_id(v), "cluster": assignment[v]} for v in g]
    work.output(len(rows) + quotient.vertex_count + quotient.edge_count)
    return AlgorithmOutput(
        {
            "fine_to_coarse": rows,
            "coarse_graph": quotient.to_canonical(),
            "cluster_sizes": [
                {"cluster": k, "size": len(v)} for k, v in sorted(groups.items())
            ],
        },
        {
            "graph": {
                "type": "graph",
                "value": quotient.to_canonical(),
                "complete": True,
            },
            "mapping": {"type": "vertex_coarsening", "value": rows, "complete": True},
        },
        quality="exact" if method == "supplied_partition" else "feasible",
        diagnostics={
            "method": method,
            "edge_aggregation": "sum_once_per_original_undirected_edge",
        },
    )
