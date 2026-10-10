from __future__ import annotations

import math

import networkx as nx
import numpy as np

from ..exceptions import GraphMineError


def float64(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GraphMineError("Numerical input must fit finite float64 values") from exc
    if (
        type(value) not in (int, float)
        or not math.isfinite(number)
        or (type(value) is int and int(number) != value)
    ):
        raise GraphMineError("Numerical input must be representable as finite float64")
    return number


def laplacian(graph, work, *, normalized=False):
    work.tick(graph.vertex_count**2)
    g = graph.to_networkx(
        direction="require_undirected",
        parallel_edges="sum",
        self_loops="reject",
        weighted=True,
        nonnegative=True,
    )
    for _, _, data in g.edges(data=True):
        data["weight"] = float64(data["weight"])
    matrix = nx.to_numpy_array(
        g, nodelist=list(g), weight="weight", dtype=np.float64, backend="networkx"
    )
    degree = matrix.sum(axis=1)
    result = np.diag(degree) - matrix
    if normalized:
        scale = np.zeros(len(g))
        np.divide(1, np.sqrt(degree), out=scale, where=degree > 0)
        result = scale[:, None] * result * scale[None, :]
    if not np.isfinite(result).all():
        raise GraphMineError("Laplacian construction exceeded finite numerical range")
    return g, result


def require_positive_tolerance(value):
    if value <= 0:
        raise GraphMineError("tolerance must be positive")
