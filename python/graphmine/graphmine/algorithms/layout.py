from __future__ import annotations

import networkx as nx
import numpy as np

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import vertex_values
from ._numeric import float64, require_positive_tolerance


def _energy_and_force(positions, edges, k):
    """Integrate the distance-clipped force law used by NetworkX's force solver."""
    n = len(positions)
    delta = positions[:, None, :] - positions[None, :, :]
    distances = np.linalg.norm(delta, axis=-1)
    floor = 0.01
    clipped = np.maximum(distances, floor)
    weights = np.zeros((n, n))
    for u, v, weight in edges:
        weights[u, v] = weights[v, u] = weight
    repulsion = np.where(
        distances >= floor,
        -(k * k) * np.log(clipped),
        -(k * k) * np.log(floor) + 0.5 * k * k * (1 - (distances / floor) ** 2),
    )
    attraction = np.where(
        distances >= floor,
        distances**3 / (3 * k),
        floor * distances**2 / (2 * k) - floor**3 / (6 * k),
    )
    energy = float(np.triu(repulsion + weights * attraction, k=1).sum())
    force = np.einsum("ijk,ij->ik", delta, k * k / clipped**2 - weights * clipped / k)
    residual = float(np.max(np.linalg.norm(force, axis=1), initial=0))
    if not np.isfinite(energy) or not np.isfinite(residual):
        raise GraphMineError("Layout energy/forces exceeded finite numerical range")
    return energy, residual


@register(
    id="force-directed-layout",
    problem_id="graph_layout_force_directed",
    family="layout",
    title="Compute a force-directed drawing of the network",
    description="NetworkX Fruchterman-Reingold force iterations in 2D or 3D, with its explicit 0.01 distance regularization and no final rescaling. Recomputes the matching potential and maximum force. Convergence means a small force residual, not optimality of the drawing. Directed edges project to undirected; loops are removed; parallel weights sum (unweighted duplicates collapse).",
    parameters={
        "dimensions": P("integer", 2, choices=(2, 3)),
        "force_model": P(
            "string", "fruchterman_reingold", choices=("fruchterman_reingold",)
        ),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "iterations": P(
            "integer",
            50,
            minimum=0,
            description="Fixed iteration count; null/unbounded stopping is not supported by this profile.",
        ),
        "random_seed": P("integer", 0, minimum=0),
        "initial_positions": P(
            "array",
            None,
            nullable=True,
            description="Optional {vertex, value:[coordinates]} rows for every vertex, preserved when iterations=0.",
        ),
        "optimal_distance": P(
            "number",
            None,
            nullable=True,
            minimum=0,
            description="Force-law length k; defaults to 1/sqrt(vertex count).",
        ),
        "force_tolerance": P("number", 1e-6, minimum=0),
        "solution_quality": P(
            "string", "approximate", choices=("approximate", "converged")
        ),
    },
    quality="heuristic",
    references=(
        "https://networkx.org/documentation/stable/reference/generated/networkx.drawing.layout.spring_layout.html",
    ),
)
def force_layout(graph, args, work, backend="networkx"):
    require_positive_tolerance(args["force_tolerance"])
    n, dim, iterations = graph.vertex_count, args["dimensions"], args["iterations"]
    work.tick(max(1, n * n) * max(1, iterations) * dim)
    weighted = args["weight_mode"] == "edge_weight"
    if weighted and any("weight" not in e for e in graph.to_canonical()["edges"]):
        raise GraphMineError("Weighted layout requires a weight on every edge")
    g = graph.to_networkx(
        direction="undirected",
        parallel_edges="sum" if weighted else "collapse",
        self_loops="drop",
        weighted=weighted,
        nonnegative=weighted,
    )
    edges = [(u, v, float64(data["weight"])) for u, v, data in g.edges(data=True)]
    for u, v, weight in edges:
        g[u][v]["weight"] = weight
    k = (
        float64(args["optimal_distance"])
        if args["optimal_distance"] is not None
        else 1 / np.sqrt(max(1, n))
    )
    if k <= 0:
        raise GraphMineError("optimal_distance must be positive")
    if args["initial_positions"] is None:
        initial = np.random.default_rng(args["random_seed"]).random((n, dim))
    else:
        values = vertex_values(graph, args["initial_positions"], "initial_positions")
        if any(not isinstance(v, list) or len(v) != dim for v in values.values()):
            raise GraphMineError("Each initial position must match dimensions")
        initial = np.array([[float64(x) for x in values[i]] for i in range(n)]).reshape(
            n, dim
        )
    if n <= 1 or not iterations:
        positions, iterations_run = initial, 0
    else:
        pos = nx.spring_layout(
            g,
            pos=dict(enumerate(initial)),
            k=k,
            iterations=iterations,
            threshold=0,
            weight="weight",
            scale=None,
            dim=dim,
            seed=0,
            method="force",
        )
        positions = np.array([pos[i] for i in range(n)])
        iterations_run = iterations
    if not np.isfinite(positions).all():
        raise GraphMineError("Layout positions exceeded finite numerical range")
    energy, residual = _energy_and_force(positions, edges, k)
    converged = residual <= args["force_tolerance"]
    if args["solution_quality"] == "converged" and not converged:
        raise GraphMineError("The fixed layout iterations did not meet force_tolerance")
    rows = [
        {"vertex": graph.vertex_id(i), "coordinates": position.tolist()}
        for i, position in enumerate(positions)
    ]
    work.output(n * dim)
    return AlgorithmOutput(
        {
            "vertex_positions": rows,
            "dimensions": dim,
            "final_energy": energy,
            "converged": converged,
            "iterations_run": iterations_run,
            "max_force_norm": residual,
        },
        {"positions": {"type": "vertex_positions", "value": rows, "complete": True}},
        quality="heuristic",
        diagnostics={
            "solver": "networkx.spring_layout/method=force",
            "distance_floor": 0.01,
            "optimal_distance": float(k),
            "force_tolerance": args["force_tolerance"],
            "convergence_criterion": "maximum uncooled force norm <= force_tolerance",
            "optimality_claimed": False,
            "rescaled_after_iteration": False,
            "energy_convention": "pairwise integrated distance-clipped Fruchterman-Reingold potential; continuous at 0.01",
        },
    )
