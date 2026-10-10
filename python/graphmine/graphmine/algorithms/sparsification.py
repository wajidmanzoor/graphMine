from __future__ import annotations

from fractions import Fraction

import networkx as nx
import numpy as np
from scipy.linalg import LinAlgError, cho_solve, cholesky, eigvalsh

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph
from ..registry import register
from ._numeric import float64


@register(
    id="spectral-sparsification",
    problem_id="spectral_graph_sparsification",
    family="construction",
    title="Reduce edges while measuring Laplacian distortion",
    description="Static effective-resistance sampling with replacement and importance reweighting, using SciPy grounded Laplacian solves. Measures all generalized eigenvalues, not only sampled vectors. An explicit epsilon must pass that numerical check. An edge budget alone permits disclosed distortion. Requires undirected, explicitly weighted simple input; loops and parallel edges are rejected; zero-weight edges can be dropped.",
    parameters={
        "mode": P("string", "static", choices=("static",)),
        "edge_budget": P(
            "integer",
            required=True,
            minimum=0,
            description="At most this many edges; repeated draws merge. A budget covering all positive edges returns the identity sparsifier.",
        ),
        "epsilon": P(
            "number",
            None,
            nullable=True,
            minimum=0,
            maximum=1,
            description="Optional strict target 0<epsilon<1, checked by generalized eigenvalues in float64; failure asks for a larger edge budget.",
        ),
        "random_seed": P("integer", 0, minimum=0),
    },
    library="scipy",
    quality="heuristic",
    references=(
        "https://arxiv.org/abs/0803.0929",
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.eigvalsh.html",
    ),
)
def sparsify(graph, args, work, backend="networkx"):
    epsilon, budget = args["epsilon"], args["edge_budget"]
    if epsilon is not None and not 0 < epsilon < 1:
        raise GraphMineError("epsilon must lie strictly between zero and one")
    data = graph.to_canonical()
    if any("weight" not in e for e in data["edges"]):
        raise GraphMineError("Spectral sparsification requires explicit edge weights")
    # Validate even cases that later have an exact identity/zero shortcut.
    graph.to_networkx(
        direction="require_undirected",
        parallel_edges="reject",
        self_loops="reject",
        weighted=True,
        nonnegative=True,
    )
    edges = [e for e in data["edges"] if e["weight"] > 0]
    weights = np.array([float64(e["weight"]) for e in edges])
    m, n = len(edges), graph.vertex_count
    work.tick(n + len(data["edges"]))
    positive = nx.Graph(backend="networkx")
    positive.add_nodes_from(range(n))
    for index, e in enumerate(edges):
        positive.add_edge(
            graph.index(e["source"]), graph.index(e["target"]), index=index
        )
    components = list(nx.connected_components(positive, backend="networkx"))
    rank = n - len(components)
    exact_identity = budget >= m
    exact_zero = budget == 0
    draws, records = 0, []
    if exact_identity or exact_zero:
        retained = weights.copy() if exact_identity else np.zeros(m)
        lower = upper = 1.0 if exact_identity else 0.0
        bound_kind = (
            "exact_identity_after_zero_weight_removal"
            if exact_identity
            else "exact_zero_laplacian"
        )
    else:
        scale = float(weights.max())
        normalized = weights / scale
        if np.any(normalized == 0):
            raise GraphMineError(
                "Weight dynamic range exceeds float64 Laplacian scaling"
            )
        leverage = np.zeros(m)
        try:
            for component in components:
                nodes = sorted(component)
                if len(nodes) <= 1:
                    continue
                local = {node: i for i, node in enumerate(nodes[:-1])}
                component_edges = list(positive.subgraph(nodes).edges(data=True))
                indices = [e[2]["index"] for e in component_edges]
                r = len(nodes) - 1
                work.tick(r**3 + r * len(indices))
                incidence = np.zeros((r, len(indices)))
                for col, (u, v, _) in enumerate(component_edges):
                    if u in local:
                        incidence[local[u], col] = 1
                    if v in local:
                        incidence[local[v], col] = -1
                matrix = (incidence * normalized[indices]) @ incidence.T
                factor = cholesky(matrix, lower=True)
                resistances = np.sum(
                    incidence * cho_solve((factor, True), incidence), axis=0
                )
                leverage[indices] = normalized[indices] * resistances
                records.append((indices, incidence, matrix))
            if (
                not np.isfinite(leverage).all()
                or np.any(leverage <= 0)
                or np.any(leverage > 1 + 1e-7)
                or abs(float(leverage.sum()) - rank) > 1e-7 * max(1, rank)
            ):
                raise GraphMineError(
                    "Effective resistance solve failed positivity/rank checks"
                )
            probabilities = leverage / leverage.sum()
            if np.any(probabilities <= 0):
                raise GraphMineError("A positive sampling probability underflowed")
            work.tick(budget)
            samples = np.random.default_rng(args["random_seed"]).choice(
                m, size=budget, replace=True, p=probabilities
            )
            counts = np.bincount(samples, minlength=m)
            retained = np.zeros(m)
            for index in np.flatnonzero(counts):
                reweighted = (
                    Fraction(float(weights[index]))
                    * int(counts[index])
                    / (budget * Fraction(float(probabilities[index])))
                )
                retained[index] = float(reweighted)
                if not np.isfinite(retained[index]) or retained[index] <= 0:
                    raise GraphMineError(
                        "Sparsifier weight exceeds finite positive float64 range"
                    )
            normalized_output = retained / scale
            if np.any((retained > 0) & (normalized_output == 0)):
                raise GraphMineError(
                    "Sparsifier weight underflowed during verification"
                )
            eigenvalues = []
            for indices, incidence, matrix in records:
                candidate = (incidence * normalized_output[indices]) @ incidence.T
                work.tick(len(matrix) ** 3)
                eigenvalues.extend(eigvalsh(candidate, matrix).tolist())
            if not np.isfinite(eigenvalues).all():
                raise GraphMineError(
                    "Spectral verification exceeded finite numerical range"
                )
            lower, upper = min(eigenvalues), max(eigenvalues)
            draws = budget
            bound_kind = "numerical_generalized_eigenvalue_diagnostics"
        except (LinAlgError, OverflowError, FloatingPointError) as exc:
            raise GraphMineError(
                "Laplacian systems could not be resolved in float64"
            ) from exc
    output_edges = [
        {**edge, "weight": float(weight)}
        for edge, weight in zip(edges, retained, strict=True)
        if weight > 0
    ]
    data["graph"].update(
        id=data["graph"]["id"] + "-spectral-sparsifier",
        allows_self_loops=False,
        allows_parallel_edges=False,
    )
    data["edges"] = output_edges
    result = Graph(data)
    output_positive = result.to_networkx(direction="require_undirected", weighted=True)
    preserved = nx.number_connected_components(
        output_positive, backend="networkx"
    ) == len(components)
    if not preserved:
        # A missing positive-weight connection creates an exact extra null
        # direction, even if a floating eigensolver returns a tiny positive
        # value. Every strict epsilon<1 target must reject that result.
        lower = 0.0
    elif rank and lower <= 0:
        raise GraphMineError(
            "Positive spectral lower ratio was not resolved numerically"
        )
    error = max(abs(1 - lower), abs(upper - 1)) if rank else 0.0
    if epsilon is not None and error > epsilon:
        raise GraphMineError(
            f"Requested epsilon={epsilon} was not met; measured spectral error={error:.8g}. Increase edge_budget or choose another random_seed."
        )
    summary = {
        "input_positive_edge_count": m,
        "output_edge_count": len(output_edges),
        "edge_budget": budget,
        "sample_count": draws,
        "positive_weight_components_preserved": preserved,
        "laplacian_rank": rank,
        "lower_quadratic_form_ratio": lower if rank else None,
        "upper_quadratic_form_ratio": upper if rank else None,
        "maximum_relative_spectral_error": error,
        "epsilon": epsilon,
        "epsilon_met_numerically": error <= epsilon if epsilon is not None else None,
        "bound_kind": bound_kind,
        "exact_bound": exact_identity or exact_zero,
        "probabilistic_guarantee_claimed": False,
        "verification": "identity_or_zero_algebra"
        if exact_identity or exact_zero
        else "all generalized eigenvalues on grounded positive-weight components",
    }
    work.output(n + len(output_edges))
    return AlgorithmOutput(
        {"sparsifier": result.to_canonical(), "quality_summary": summary},
        {"graph": {"type": "graph", "value": result.to_canonical(), "complete": True}},
        quality="heuristic",
        diagnostics={
            "sampling": "probability proportional to weight times effective resistance; draws with replacement",
            "reweighting": "original weight * draw multiplicity / (sample count * draw probability)",
            "arithmetic": "float64 numerical diagnostics are not exact-arithmetic bounds",
            "zero_weight_edges": "removed; they contribute no Laplacian energy",
        },
    )
