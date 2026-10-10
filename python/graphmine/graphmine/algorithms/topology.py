from __future__ import annotations

import math

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._numeric import float64


@register(
    id="persistent-homology",
    problem_id="persistent_homology",
    family="topology",
    title="Track components, loops and higher-dimensional holes across edge thresholds",
    description="GUDHI flag-complex persistence over a declared prime field. Includes essential H0 intervals and enough cofaces to compute deaths in every requested homology dimension.",
    parameters={
        "max_homology_dimension": P("integer", 1, minimum=0),
        "max_filtration": P("number", None, minimum=0, nullable=True),
        "field_prime": P(
            "integer",
            2,
            minimum=2,
            maximum=46337,
            description="Prime modulus; 46337 is GUDHI's documented maximum.",
        ),
    },
    library="gudhi",
    references=("https://gudhi.inria.fr/python/latest/simplex_tree_ref.html",),
)
def persistence(graph, args, work, backend="networkx"):
    import gudhi

    p = args["field_prime"]
    if any(p % divisor == 0 for divisor in range(2, math.isqrt(p) + 1)):
        raise GraphMineError("field_prime must be prime")
    if any("weight" not in edge for edge in graph.to_canonical()["edges"]):
        raise GraphMineError("Every edge requires a filtration weight")
    g = graph.to_networkx(
        direction="require_undirected",
        parallel_edges="min",
        self_loops="reject",
        weighted=True,
        nonnegative=True,
    )
    cutoff = args["max_filtration"]
    tree = gudhi.SimplexTree()
    for v in g:
        work.tick()
        tree.insert([v], filtration=0)
    for u, v, data in g.edges(data=True):
        work.tick()
        value = float64(data["weight"])
        if cutoff is None or data["weight"] <= cutoff:
            tree.insert([u, v], filtration=value)

    def count_simplex(_simplex):
        work.tick()
        return False

    maximum = args["max_homology_dimension"]
    # H_d deaths require (d+1)-simplices, including for d=0.
    tree.expansion_with_blocker(min(maximum + 1, max(0, len(g) - 1)), count_simplex)
    intervals = []
    for dimension, (birth, death) in tree.persistence(
        homology_coeff_field=p, min_persistence=0.0, persistence_dim_max=True
    ):
        work.tick()
        if dimension <= maximum:
            intervals.append(
                {
                    "dimension": dimension,
                    "birth": birth,
                    "death": None if math.isinf(death) else death,
                }
            )
    intervals.sort(
        key=lambda row: (
            row["dimension"],
            row["birth"],
            math.inf if row["death"] is None else row["death"],
        )
    )
    work.output(len(intervals))
    convention = (
        "essential_in_complete_flag_filtration"
        if cutoff is None
        else "right_censored_at_max_filtration; may be essential or die after cutoff"
    )
    return AlgorithmOutput(
        {
            "intervals": intervals,
            "essential_interval_convention": convention,
            "coefficient_field": p,
            "interval_convention": "[birth, death); zero-length intervals omitted",
            "complete": True,
        },
        {
            "intervals": {
                "type": "persistence_intervals",
                "value": intervals,
                "complete": True,
            }
        },
        diagnostics={
            "simplex_count": tree.num_simplices(),
            "complex_dimension": tree.dimension(),
            "vertex_filtration": 0,
        },
    )
