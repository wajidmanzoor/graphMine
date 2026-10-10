from __future__ import annotations

from fractions import Fraction

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import Graph
from ..inputs import finite_number
from ..registry import register
from ._events import number
from ._milp import BinaryModel


def id_order(value):
    return (0, value) if type(value) is int else (1, value)


@register(
    id="network-alignment",
    problem_id="network_alignment",
    family="comparison",
    title="Align two graphs while conserving topology and supplied similarities",
    description="SciPy/HiGHS linearized quadratic assignment for a global one-to-one mapping covering every vertex of the smaller graph. Maximizes topology_weight times conserved-edge value plus supplied pair similarities. Weighted conservation uses the minimum of the two normalized nonnegative edge weights; unweighted conservation counts edges.",
    library="scipy",
    quality="numerical_optimum",
    parameters={
        "other_graph": P("object", required=True),
        "alignment_mode": P(
            "string", "global_one_to_one", choices=("global_one_to_one",)
        ),
        "node_similarity_prior": P(
            "array",
            None,
            nullable=True,
            description="Rows with graph_a_vertex, graph_b_vertex, value; unspecified pairs have prior zero.",
        ),
        "topology_weight": P("number", 1, minimum=0),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
    references=(
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html",
    ),
)
def align(graph, args, work, backend="networkx"):
    other = Graph(args["other_graph"])
    if graph.directed != other.directed:
        raise GraphMineError("Alignment graphs must have matching direction semantics")
    weighted = args["weight_mode"] == "edge_weight"
    if weighted and any(
        "weight" not in e for g in (graph, other) for e in g.to_canonical()["edges"]
    ):
        raise GraphMineError("Weighted alignment requires weights on both graphs")
    a, b = [
        g.to_networkx(
            direction="preserve",
            self_loops="drop",
            parallel_edges="sum" if weighted else "collapse",
            weighted=weighted,
            nonnegative=weighted,
        )
        for g in (graph, other)
    ]
    na, nb = len(a), len(b)
    count = na * nb
    work.tick(
        count + a.number_of_edges() * b.number_of_edges() * (1 if graph.directed else 2)
    )
    prior = {}
    for row in args["node_similarity_prior"] or []:
        if not isinstance(row, dict) or set(row) != {
            "graph_a_vertex",
            "graph_b_vertex",
            "value",
        }:
            raise GraphMineError(
                "Each prior row needs graph_a_vertex, graph_b_vertex and value"
            )
        pair = graph.index(row["graph_a_vertex"]), other.index(row["graph_b_vertex"])
        if pair in prior:
            raise GraphMineError("Duplicate pair in node_similarity_prior")
        prior[pair] = finite_number(row["value"], "Similarity prior")
    terms = []
    for u, v, da in a.edges(data=True):
        for p, q, db in b.edges(data=True):
            weight = min(da["weight"], db["weight"]) if weighted else 1
            for first, second in ((p, q),) if graph.directed else ((p, q), (q, p)):
                terms.append((u, v, first, second, weight))
    costs = [-prior.get((u, p), 0) for u in a for p in b] + [
        -args["topology_weight"] * w for _, _, _, _, w in terms
    ]
    model = BinaryModel(costs, work)
    for u in a:
        model.constrain({u * nb + p: 1 for p in b}, lower=1 if na <= nb else 0, upper=1)
    for p in b:
        model.constrain({u * nb + p: 1 for u in a}, lower=1 if nb <= na else 0, upper=1)
    for i, (u, v, p, q, _) in enumerate(terms):
        z, first, second = count + i, u * nb + p, v * nb + q
        model.constrain({z: 1, first: -1}, upper=0)
        model.constrain({z: 1, second: -1}, upper=0)
        model.constrain({z: 1, first: -1, second: -1}, lower=-1)
    values, evidence = model.solve()
    if values is None:
        raise GraphMineError("Unrestricted global alignment unexpectedly infeasible")
    mapping = {u: p for u in a for p in b if values[u * nb + p]}
    if len(mapping) != min(na, nb) or len(set(mapping.values())) != len(mapping):
        raise GraphMineError("Alignment violated mapping cardinality or injectivity")
    conserved, topology = [], Fraction()
    scores = {u: Fraction(prior.get((u, p), 0)) for u, p in mapping.items()}
    alpha = Fraction(args["topology_weight"])
    for u, v, data in a.edges(data=True):
        if u in mapping and v in mapping and b.has_edge(mapping[u], mapping[v]):
            w = Fraction(
                min(data["weight"], b[mapping[u]][mapping[v]]["weight"])
                if weighted
                else 1
            )
            topology += w
            scores[u] += alpha * w / 2
            scores[v] += alpha * w / 2
            conserved.append(
                {
                    "graph_a_endpoints": [graph.vertex_id(u), graph.vertex_id(v)],
                    "graph_b_endpoints": [
                        other.vertex_id(mapping[u]),
                        other.vertex_id(mapping[v]),
                    ],
                    "value": number(w),
                }
            )
    total_prior = sum(
        (Fraction(prior.get(pair, 0)) for pair in mapping.items()), Fraction()
    )
    objective = alpha * topology + total_prior
    if abs(float(objective) + evidence["objective"]) > evidence.get(
        "objective_tolerance", 1e-9
    ):
        raise GraphMineError("Alignment objective does not match the optimized model")
    rows = [
        {
            "graph_a_vertex": graph.vertex_id(u),
            "graph_b_vertex": other.vertex_id(p),
            "score": number(scores[u]),
        }
        for u, p in mapping.items()
    ]
    rows.sort(
        key=lambda r: (
            -r["score"],
            id_order(r["graph_a_vertex"]),
            id_order(r["graph_b_vertex"]),
        )
    )
    work.output(len(rows) + len(conserved))
    return AlgorithmOutput(
        {
            "vertex_mapping": rows,
            "objective_value": number(objective),
            "objective_fraction": str(objective),
            "conserved_edge_value": number(topology),
            "similarity_prior_value": number(total_prior),
            "conserved_edges": conserved,
            "edge_correctness": len(conserved) / a.number_of_edges()
            if a.number_of_edges()
            else None,
            "optimal": True,
            "complete": True,
        },
        {
            "mapping": {
                "type": "cross_graph_mapping",
                "value": rows,
                "complete": True,
                "other_graph_fingerprint": other.fingerprint,
            }
        },
        quality="numerical_optimum",
        diagnostics={
            **evidence,
            "other_graph_fingerprint": other.fingerprint,
            "weighted_conservation": "minimum_normalized_edge_weight",
            "pair_score": "prior_plus_half_incident_conserved_topology",
        },
    )
