from __future__ import annotations

import numpy as np
from scipy.sparse.linalg import LinearOperator, gmres

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register


def _id_order(value):
    return (0, value) if type(value) is int else (1, value)


@register(
    id="simrank",
    problem_id="simrank_vertex_similarity",
    family="similarity",
    title="Compare vertices by the similarity of their neighbors",
    description="SciPy solves the SimRank fixed-point equations with a separately recomputed residual and contraction error bound. Direction and output-pair scope are explicit.",
    parameters={
        "query_mode": P(
            "string",
            required=True,
            choices=("single_pair", "single_source_all", "top_k_pairs"),
        ),
        "source_vertex": P("vertex_id", None, nullable=True),
        "target_vertex": P("vertex_id", None, nullable=True),
        "decay_factor": P("number", 0.8, minimum=0, maximum=1),
        "direction_mode": P(
            "string", "incoming", choices=("incoming", "undirected_projection")
        ),
        "top_k": P("integer", None, minimum=1, nullable=True),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
        "convergence_tolerance": P("number", 1e-6, minimum=0),
        "max_iterations": P("integer", 1000, minimum=1),
    },
    library="scipy",
    quality="numerical",
)
def simrank(graph, args, work, backend="networkx"):
    decay, tolerance = args["decay_factor"], args["convergence_tolerance"]
    if not 0 < decay < 1 or tolerance <= 0:
        raise GraphMineError(
            "SimRank requires 0 < decay_factor < 1 and positive tolerance"
        )
    mode = args["query_mode"]
    source = (
        graph.index(args["source_vertex"])
        if args["source_vertex"] is not None
        else None
    )
    target = (
        graph.index(args["target_vertex"])
        if args["target_vertex"] is not None
        else None
    )
    if mode != "top_k_pairs" and source is None:
        raise GraphMineError("This query mode requires source_vertex")
    if mode == "single_pair" and target is None:
        raise GraphMineError("single_pair requires target_vertex")
    if mode != "single_pair" and target is not None:
        raise GraphMineError("target_vertex applies only to single_pair")
    if mode == "top_k_pairs" and source is not None:
        raise GraphMineError("source_vertex does not restrict top_k_pairs")
    if mode == "single_pair" and args["top_k"] is not None:
        raise GraphMineError("top_k does not apply to single_pair")
    n = graph.vertex_count
    work.tick(n * n)
    g = graph.to_networkx(
        direction="undirected"
        if args["direction_mode"] == "undirected_projection"
        else "preserve",
        parallel_edges="collapse",
        self_loops="drop",
    )
    transition = np.zeros((n, n))
    for v in g:
        neighbors = list(g.predecessors(v)) if g.is_directed() else list(g[v])
        if neighbors:
            transition[v, neighbors] = 1 / len(neighbors)

    def multiply(vector):
        work.tick(n * n)
        values = vector.reshape(n, n)
        result = values - decay * transition @ values @ transition.T
        np.fill_diagonal(result, values.diagonal())
        return result.ravel()

    if n:
        system = LinearOperator((n * n, n * n), matvec=multiply, dtype=np.float64)
        rhs = np.eye(n).ravel()
        solution, status = gmres(
            system,
            rhs,
            x0=rhs,
            rtol=0,
            atol=tolerance * (1 - decay) / 4,
            maxiter=args["max_iterations"],
            restart=min(50, n * n),
            callback=lambda _: work.tick(0),
            callback_type="legacy",
        )
        if status != 0:
            raise GraphMineError("SimRank did not converge within max_iterations")
        matrix = solution.reshape(n, n)
        # SimRank is symmetric and in [0,1]; projection cannot increase its
        # sup-norm error. Recheck the defining equations after projection.
        matrix = np.clip((matrix + matrix.T) / 2, 0, 1)
        np.fill_diagonal(matrix, 1)
    else:
        matrix = np.empty((0, 0))
    updated = decay * transition @ matrix @ transition.T
    np.fill_diagonal(updated, 1)
    residual = float(np.max(np.abs(updated - matrix))) if n else 0.0
    error = residual / (1 - decay)
    if (
        not np.isfinite(matrix).all()
        or np.any(matrix < 0)
        or np.any(matrix > 1)
        or error > tolerance
    ):
        raise GraphMineError("SimRank fixed-point error bound exceeds tolerance")
    if mode == "single_pair":
        pairs = [(source, target)]
    elif mode == "single_source_all":
        pairs = [(source, v) for v in g if v != source]
    else:
        ordered = sorted(g, key=lambda v: _id_order(graph.vertex_id(v)))
        pairs = [(u, v) for i, u in enumerate(ordered) for v in ordered[i + 1 :]]
    pairs.sort(
        key=lambda p: (
            -matrix[p[0], p[1]],
            _id_order(graph.vertex_id(p[0])),
            _id_order(graph.vertex_id(p[1])),
        )
    )
    total = len(pairs)
    if args["top_k"] is not None:
        pairs = pairs[: args["top_k"]]
    rows = [
        {
            "source": graph.vertex_id(u),
            "target": graph.vertex_id(v),
            "similarity": float(matrix[u, v]),
        }
        for u, v in pairs
    ]
    work.output(len(rows))
    return AlgorithmOutput(
        {
            "similarity_scores": rows,
            "scored_pair_count": total,
            "complete": True,
            "error_bound": error,
        },
        {
            "pairs": {
                "type": "pair_scores",
                "value": rows,
                "complete": len(rows) == total,
            }
        },
        quality="numerical",
        diagnostics={
            "residual_max": residual,
            "absolute_error_bound": error,
            "single_source_includes_self": False,
        },
    )
