"""Checked binary models solved by SciPy's HiGHS integration.

No timed-out incumbent is promoted to an optimum. All binary variables and
constraints are checked again after rounding, using the original coefficients.
HiGHS is a floating-point solver: its optimal status is a numerical certificate,
not a formal exact-arithmetic proof. Results disclose that distinction.
"""

from __future__ import annotations

import math
import time
from fractions import Fraction
from functools import reduce

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from ..exceptions import GraphMineError, ResourceLimit


def integral_balance_row(weights, *, lower=None, upper):
    """Keep subset-weight bounds exact on the rational input weight grid."""
    rational = [Fraction(w) for w in weights]
    denominator = math.lcm(*(w.denominator for w in rational))
    integers = [int(w * denominator) for w in rational]
    divisor = reduce(math.gcd, integers, 0) or 1
    scale = Fraction(denominator, divisor)
    integers = [v // divisor for v in integers]
    if sum(abs(v) for v in integers) > 2**53:
        raise GraphMineError(
            "Balance weights exceed the exact float64 integer range after rational scaling"
        )
    return (
        integers,
        (math.ceil(Fraction(lower) * scale) if lower is not None else -math.inf),
        math.floor(Fraction(upper) * scale),
    )


def coefficient(value):
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise GraphMineError(
            "MILP coefficients must fit finite float64 values"
        ) from exc
    if not math.isfinite(converted) or (type(value) is int and int(converted) != value):
        raise GraphMineError("MILP coefficients must be representable as float64")
    return converted


class BinaryModel:
    def __init__(self, costs, work):
        self.costs = list(costs)
        self.work = work
        work.tick(len(self.costs))
        self.rows = []

    def constrain(self, terms, lower=-math.inf, upper=math.inf):
        self.work.tick()
        if any(type(i) is not int or not 0 <= i < len(self.costs) for i in terms):
            raise GraphMineError("Invalid variable index in optimization model")
        self.rows.append((dict(terms), lower, upper))

    def solve(self):
        self.work.tick()
        if sum(abs(c) for c in self.costs) > 2**53:
            raise GraphMineError(
                "Total MILP objective magnitude exceeds the reliable float64 integer range"
            )
        if not self.costs:
            if any(not lo <= 0 <= hi for _, lo, hi in self.rows):
                return None, {"status": "infeasible"}
            return [], {"status": "optimal", "objective": 0, "dual_bound": 0}
        indices, columns, values = [], [], []
        lower, upper = [], []
        for i, (terms, lo, hi) in enumerate(self.rows):
            for j, value in terms.items():
                indices.append(i)
                columns.append(j)
                values.append(coefficient(value))
            lower.append(coefficient(lo) if math.isfinite(lo) else lo)
            upper.append(coefficient(hi) if math.isfinite(hi) else hi)
        matrix = coo_array(
            (np.asarray(values, dtype=np.float64), (indices, columns)),
            shape=(len(self.rows), len(self.costs)),
        ).tocsc()
        remaining = self.work.budget.timeout_seconds - (
            time.monotonic() - self.work.started
        )
        if remaining <= 0:
            raise ResourceLimit("Optimization time budget exhausted")
        result = milp(
            np.asarray([coefficient(c) for c in self.costs]),
            integrality=np.ones(len(self.costs)),
            bounds=Bounds(0, 1),
            constraints=LinearConstraint(matrix, lower, upper),
            options={"time_limit": remaining, "mip_rel_gap": 0.0},
        )
        self.work.tick(int(getattr(result, "mip_node_count", 0) or 0))
        if result.status == 2:
            return None, {"status": "infeasible", "solver": "scipy.optimize.milp/HiGHS"}
        if result.status == 1:
            raise ResourceLimit("HiGHS reached a resource limit; no optimum is claimed")
        if result.status != 0 or result.x is None or not np.isfinite(result.x).all():
            raise GraphMineError(f"Optimization did not complete: {result.message}")
        rounded = np.rint(result.x).astype(int).tolist()
        if (
            any(v not in (0, 1) for v in rounded)
            or np.max(abs(result.x - rounded)) > 1e-7
        ):
            raise GraphMineError("Optimization result is not binary within tolerance")
        for terms, lo, hi in self.rows:
            value = sum(c * rounded[i] for i, c in terms.items())
            # Integer rows are checked exactly. Real-valued feasibility is
            # additionally checked by each problem using original input values.
            integers = all(type(c) is int for c in terms.values()) and all(
                type(b) is int or not math.isfinite(b) for b in (lo, hi)
            )
            tolerance = 0 if integers else 1e-9 * max(1, abs(value))
            if value < lo - tolerance or value > hi + tolerance:
                raise GraphMineError(
                    "Rounded optimization result violates a constraint"
                )
        objective = sum(c * v for c, v in zip(self.costs, rounded, strict=True))
        dual = float(result.mip_dual_bound)
        tolerance = 1e-8 * max(1.0, abs(objective))
        if not math.isfinite(dual) or abs(objective - dual) > tolerance:
            raise GraphMineError("Solver objective and optimality bound disagree")
        return rounded, {
            "solver": "scipy.optimize.milp/HiGHS",
            "status": "optimal",
            "objective": objective,
            "dual_bound": dual,
            "absolute_gap": abs(objective - dual),
            "certificate": "floating_point_solver_optimality",
            "integer_feasibility_checked": True,
            "objective_tolerance": tolerance,
        }


def induced_model(vertex_count, terms, work):
    """x[v] selects a vertex; y[t] is AND(x[v] for v in term t)."""
    model = BinaryModel([0] * vertex_count + [-weight for _, weight in terms], work)
    for t, (vertices, _) in enumerate(terms):
        y = vertex_count + t
        for v in vertices:
            model.constrain({y: 1, v: -1}, upper=0)
        model.constrain({y: 1, **{v: -1 for v in vertices}}, lower=1 - len(vertices))
    return model
