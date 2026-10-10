from __future__ import annotations

import numpy as np
from scipy.linalg import eigh, solve

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import vertex_values
from ._numeric import float64, laplacian, require_positive_tolerance


@register(
    id="laplacian-eigenpairs",
    problem_id="graph_laplacian_eigenpairs",
    family="spectral",
    title="Compute graph Laplacian eigenvalues and eigenvectors",
    description="SciPy symmetric eigensolver with explicit residual and orthogonality checks. The direct solver has no max_iterations parameter.",
    parameters={
        "num_eigenpairs": P("integer", required=True, minimum=1),
        "laplacian": P(
            "string", "combinatorial", choices=("combinatorial", "symmetric_normalized")
        ),
        "selection": P("string", "smallest", choices=("smallest", "largest")),
        "tolerance": P("number", 1e-6, minimum=0),
    },
    library="scipy",
    quality="numerical",
    references=(
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.eigh.html",
    ),
)
def eigenpairs(graph, args, work, backend="networkx"):
    require_positive_tolerance(args["tolerance"])
    n, k = graph.vertex_count, args["num_eigenpairs"]
    if k > n:
        raise GraphMineError("num_eigenpairs exceeds the number of vertices")
    _, matrix = laplacian(
        graph, work, normalized=args["laplacian"] == "symmetric_normalized"
    )
    interval = [0, k - 1] if args["selection"] == "smallest" else [n - k, n - 1]
    values, vectors = eigh(matrix, subset_by_index=interval, driver="evr")
    residuals = np.linalg.norm(matrix @ vectors - vectors * values, axis=0)
    orthogonality = float(np.linalg.norm(vectors.T @ vectors - np.eye(k), ord=np.inf))
    if (
        not np.isfinite(values).all()
        or float(max(residuals)) > args["tolerance"]
        or orthogonality > args["tolerance"]
    ):
        raise GraphMineError(
            "Eigenpairs did not meet the requested residual and orthogonality tolerance"
        )
    work.output(n * k + k)
    data = {
        "eigenvalues": values.tolist(),
        "eigenvectors": vectors.tolist(),
        "vertex_order": list(graph.node_ids),
        "residual_norms": residuals.tolist(),
        "orthogonality_error": orthogonality,
        "converged": True,
    }
    return AlgorithmOutput(
        data,
        {"eigenpairs": {"type": "eigenpairs", "value": data, "complete": True}},
        quality="numerical",
        diagnostics={
            "solver": "scipy.linalg.eigh/evr",
            "absolute_tolerance": args["tolerance"],
        },
    )


@register(
    id="graph-signal-denoising",
    problem_id="graph_signal_denoising",
    family="spectral",
    title="Smooth noisy measurements over a graph",
    description="Minimize one-half squared observation error plus a declared Laplacian, total-variation or graph-trend penalty. Numerical accuracy is checked with stationarity or a feasible dual bound.",
    parameters={
        "observed_signal": P(
            "array",
            required=True,
            description="One {vertex, value} row per vertex; values are scalars or equal-width vectors.",
        ),
        "regularizer": P(
            "string",
            "total_variation",
            choices=("total_variation", "trend_filtering", "laplacian_quadratic"),
        ),
        "regularization_strength": P("number", required=True, minimum=0),
        "difference_order": P("integer", 0, minimum=0),
        "tolerance": P("number", 1e-6, minimum=0),
        "max_iterations": P("integer", 1000, minimum=1),
    },
    library="cvxpy",
    quality="numerical",
)
def denoising(graph, args, work, backend="networkx"):
    import cvxpy as cp

    require_positive_tolerance(args["tolerance"])
    if args["regularizer"] != "trend_filtering" and args["difference_order"] != 0:
        raise GraphMineError("difference_order applies only to trend_filtering")
    values = vertex_values(graph, args["observed_signal"], "observed_signal")
    rows = [values[v] for v in range(graph.vertex_count)]
    scalar = not rows or not isinstance(rows[0], list)
    if scalar:
        rows = [[value] for value in rows]
    if any(
        not isinstance(row, list) or not row or len(row) != len(rows[0]) for row in rows
    ):
        raise GraphMineError(
            "Observed signal values must be all scalars or equal-width vectors"
        )
    g, matrix = laplacian(graph, work)
    width = len(rows[0]) if rows else 1
    work.tick(graph.vertex_count * width)
    y = np.asarray([[float64(v) for v in row] for row in rows], dtype=float).reshape(
        len(g), width
    )
    strength = float64(args["regularization_strength"])
    tolerance = args["tolerance"]
    diagnostics = {}
    if not len(g) or strength == 0:
        x, objective = y.copy(), 0.0
        diagnostics = {"solver": "closed_form_identity", "objective_gap_bound": 0.0}
    elif args["regularizer"] == "laplacian_quadratic":
        system = np.eye(len(g)) + strength * matrix
        x = solve(system, y, assume_a="pos")
        residual = system @ x - y
        gap_bound = float(0.5 * np.sum(residual**2))
        objective = float(
            0.5 * np.sum((x - y) ** 2) + 0.5 * strength * np.sum(x * (matrix @ x))
        )
        if not np.isfinite(gap_bound) or gap_bound > tolerance:
            raise GraphMineError(
                "Quadratic smoothing failed the objective-gap tolerance"
            )
        diagnostics = {
            "solver": "scipy.linalg.solve",
            "objective_gap_bound": gap_bound,
            "solution_l2_error_bound": float(np.sqrt(2 * gap_bound)),
            "penalty": "0.5 * strength * trace(X.T @ L @ X)",
        }
    else:
        edges = list(g.edges(data=True))
        work.tick(len(edges) * len(g))
        difference = np.zeros((len(edges), len(g)))
        for i, (u, v, data) in enumerate(edges):
            weight = (
                data["weight"]
                if args["regularizer"] == "total_variation"
                else np.sqrt(data["weight"])
            )
            difference[i, u], difference[i, v] = weight, -weight
        order = args["difference_order"]
        if args["regularizer"] == "trend_filtering":
            work.tick(max(1, order.bit_length()) * len(g) ** 2)
            with np.errstate(over="ignore", invalid="ignore"):
                difference = (
                    difference @ np.linalg.matrix_power(matrix, order // 2)
                    if order % 2 == 0
                    else np.linalg.matrix_power(matrix, (order + 1) // 2)
                )
            if not np.isfinite(difference).all():
                raise GraphMineError("Graph difference operator overflowed")
        if not difference.size or not np.any(difference):
            x, objective = y.copy(), 0.0
            diagnostics = {"solver": "closed_form_identity", "objective_gap_bound": 0.0}
        else:
            variable = cp.Variable(y.shape)
            auxiliary = cp.Variable((difference.shape[0], width))
            constraints = [
                difference @ variable <= auxiliary,
                -(difference @ variable) <= auxiliary,
            ]
            problem = cp.Problem(
                cp.Minimize(
                    0.5 * cp.sum_squares(variable - y) + strength * cp.sum(auxiliary)
                ),
                constraints,
            )
            try:
                problem.solve(
                    solver="CLARABEL",
                    max_iter=args["max_iterations"],
                    tol_gap_abs=min(1e-9, tolerance * 0.01),
                    tol_gap_rel=0.0,
                    tol_feas=min(1e-9, tolerance * 0.01),
                )
            except cp.error.SolverError as exc:
                raise GraphMineError("Denoising solver did not complete") from exc
            if problem.status != cp.OPTIMAL or variable.value is None:
                raise GraphMineError(f"Denoising did not converge: {problem.status}")
            x = np.asarray(variable.value)
            dual = np.clip(
                constraints[0].dual_value - constraints[1].dual_value,
                -strength,
                strength,
            )
            transpose = difference.T @ dual
            bound = float(np.sum(dual * (difference @ y)) - 0.5 * np.sum(transpose**2))
            objective = float(
                0.5 * np.sum((x - y) ** 2) + strength * np.abs(difference @ x).sum()
            )
            gap = objective - bound
            if (
                not np.isfinite(gap)
                or gap < -1e-10 * max(1, abs(objective))
                or gap > tolerance
            ):
                raise GraphMineError(
                    "Denoising primal-dual gap exceeds the requested tolerance"
                )
            diagnostics = {
                "solver": "cvxpy/CLARABEL",
                "dual_objective": bound,
                "objective_gap_bound": max(0, gap),
                "solution_l2_error_bound": float(np.sqrt(2 * max(0, gap))),
                "difference_operator": "diag(weight) B"
                if args["regularizer"] == "total_variation"
                else "B_weighted L^(order/2) for even order; L^((order+1)/2) for odd order",
                "iterations": problem.solver_stats.num_iters,
            }
    estimated = [
        {
            "vertex": graph.vertex_id(v),
            "value": float(x[v, 0]) if scalar else x[v].tolist(),
        }
        for v in range(len(g))
    ]
    work.output(len(g) * width)
    return AlgorithmOutput(
        {
            "estimated_signal": estimated,
            "objective_value": objective,
            "converged": True,
        },
        {"signal": {"type": "vertex_signal", "value": estimated, "complete": True}},
        quality="numerical",
        diagnostics=diagnostics,
    )
