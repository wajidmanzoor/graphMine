from __future__ import annotations

import math

import networkx as nx
import numpy as np

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import ConvergenceError, GraphMineError
from ..registry import register
from ._common import scores, simple


def _pagerank(
    graph,
    g,
    *,
    alpha,
    tolerance,
    max_iterations,
    personalization=None,
    dangling=None,
    backend,
):
    if not 0 <= alpha < 1 or tolerance <= 0:
        raise GraphMineError("PageRank needs 0<=alpha<1 and positive tolerance")
    try:
        precision = {"dtype": np.float64} if backend == "cugraph" else {}
        if not len(g):
            values = {}
        elif not any(edge["weight"] for _, _, edge in g.edges(data=True)):
            # With no positive transitions, the PageRank equation reduces to
            # (1-alpha)*personalization + alpha*dangling. The upstream GPU
            # empty-edge path otherwise has ID-dtype and precision defects.
            base = personalization if personalization is not None else {v: 1 for v in g}
            sink = dangling if dangling is not None else base
            base_total, sink_total = sum(base.values()), sum(sink.values())
            values = {
                v: (1 - alpha) * base.get(v, 0) / base_total
                + alpha * sink.get(v, 0) / sink_total
                for v in g
            }
        else:
            values = nx.pagerank(
                g,
                alpha=alpha,
                personalization=personalization,
                dangling=dangling,
                tol=tolerance / max(1, len(g)),
                max_iter=max_iterations,
                weight="weight",
                backend=backend,
                **precision,
            )
    except nx.PowerIterationFailedConvergence as exc:
        raise ConvergenceError(
            "PageRank did not converge within max_iterations"
        ) from exc
    # Check the defining equation independently of the library's stopping rule.
    if not len(g):
        return scores(graph, values, diagnostics={"fixed_point_l1_residual": 0.0})
    p = (
        dict(personalization)
        if personalization is not None
        else {v: 1 / len(g) for v in g}
    )
    p_total = sum(p.values())
    p = {v: p.get(v, 0.0) / p_total for v in g}
    d = dict(dangling) if dangling is not None else p
    d_total = sum(d.values())
    d = {v: d.get(v, 0.0) / d_total for v in g}
    directed = g if g.is_directed() else g.to_directed()
    expected = {v: (1 - alpha) * p[v] for v in g}
    for u in directed:
        total = sum(edge["weight"] for edge in directed[u].values())
        if total == 0:
            for v in g:
                expected[v] += alpha * values[u] * d[v]
        else:
            for v, edge in directed[u].items():
                expected[v] += alpha * values[u] * edge["weight"] / total
    residual = sum(abs(values[v] - expected[v]) for v in g)
    if (
        not all(math.isfinite(v) and v >= -tolerance for v in values.values())
        or abs(sum(values.values()) - 1) > max(tolerance, 1e-12)
        or residual > max(tolerance, 1e-12)
    ):
        raise ConvergenceError(
            f"PageRank failed the fixed-point check (L1 residual={residual})"
        )
    return scores(
        graph,
        values,
        diagnostics={
            "fixed_point_l1_residual": residual,
            "l1_error_bound": residual / (1 - alpha),
            "tolerance": tolerance,
        },
    )


@register(
    id="pagerank",
    problem_id="centrality_influential_node_mining",
    family="centrality",
    title="Rank overall influence",
    description="Converged global PageRank with a checked fixed-point residual.",
    parameters={
        "alpha": P("number", 0.85, minimum=0, maximum=1),
        "tolerance": P("number", 1e-9, minimum=0),
        "max_iterations": P("integer", 1000, minimum=1),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
    },
    quality="numerical",
)
def pagerank(graph, args, work, backend="networkx"):
    g = simple(
        graph,
        directed=True,
        weighted=args["weight_mode"] == "edge_weight",
        nonnegative=True,
        aggregation="sum",
    )
    work.output(len(g))
    return _pagerank(
        graph,
        g,
        alpha=args["alpha"],
        tolerance=args["tolerance"],
        max_iterations=args["max_iterations"],
        backend=backend,
    )


@register(
    id="personalized-pagerank",
    problem_id="personalized_pagerank_rwr",
    family="centrality",
    title="Rank connections around selected starting points",
    description="Converged personalized PageRank with explicit direction, dangling-node behavior and residual checks.",
    parameters={
        "seed_vertices": P("array", required=True),
        "restart_probability": P("number", 0.15, minimum=0, maximum=1),
        "direction_mode": P(
            "string",
            "outgoing",
            choices=("outgoing", "incoming", "undirected_projection"),
        ),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "dangling_policy": P(
            "string",
            "redistribute_to_seeds",
            choices=("redistribute_to_seeds", "redistribute_uniformly", "self_loop"),
        ),
        "convergence_tolerance": P("number", 1e-9, minimum=0),
        "max_iterations": P("integer", 1000, minimum=1),
        "exclude_seeds_from_output": P("boolean", False),
        "top_k": P("integer", None, minimum=1, nullable=True),
    },
    quality="numerical",
)
def personalized_pagerank(graph, args, work, backend="networkx"):
    g = simple(
        graph,
        directed=True,
        weighted=args["weight_mode"] == "edge_weight",
        nonnegative=True,
        aggregation="sum",
    )
    if args["direction_mode"] == "incoming" and g.is_directed():
        g = g.reverse(copy=True)
    elif args["direction_mode"] == "undirected_projection" and g.is_directed():
        g = graph.to_networkx(
            direction="undirected",
            parallel_edges="sum",
            self_loops="drop",
            weighted=args["weight_mode"] == "edge_weight",
            nonnegative=True,
        )
    seeds = {graph.index(v) for v in args["seed_vertices"]}
    if not seeds:
        raise GraphMineError("At least one seed vertex is required")
    personalization = {v: 1.0 / len(seeds) for v in seeds}
    dangling = None
    if args["dangling_policy"] == "redistribute_uniformly":
        dangling = {v: 1.0 / len(g) for v in g}
    elif args["dangling_policy"] == "self_loop":
        for v in g:
            if sum(edge["weight"] for edge in g[v].values()) == 0:
                g.add_edge(v, v, weight=1)
    result = _pagerank(
        graph,
        g,
        alpha=1 - args["restart_probability"],
        tolerance=args["convergence_tolerance"],
        max_iterations=args["max_iterations"],
        personalization=personalization,
        dangling=dangling,
        backend=backend,
    )
    rows = result.data["vertices"]
    if args["exclude_seeds_from_output"]:
        rows = [r for r in rows if graph.index(r["vertex"]) not in seeds]
    rows = sorted(rows, key=lambda row: (-row["score"], graph.index(row["vertex"])))
    if args["top_k"] is not None:
        rows = rows[: args["top_k"]]
    result.data["ranking"] = rows
    work.output(len(g))
    return result


@register(
    id="betweenness-centrality",
    problem_id="centrality_influential_node_mining",
    family="centrality",
    title="Find bridges between people or places",
    description="All-source betweenness centrality; optional weights are positive path lengths.",
    parameters={
        "normalized": P("boolean", True),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
    },
    quality="numerical",
)
def betweenness(graph, args, work, backend="networkx"):
    weighted = args["weight_mode"] == "edge_weight"
    g = simple(
        graph, directed=True, weighted=weighted, nonnegative=True, aggregation="min"
    )
    if weighted and any(d["weight"] <= 0 for _, _, d in g.edges(data=True)):
        raise GraphMineError(
            "Weighted betweenness requires strictly positive path lengths"
        )
    if len(g) < 3:
        return scores(
            graph,
            {v: 0.0 for v in g},
            diagnostics={
                "computation": "closed_form_boundary",
                "reason": "No third vertex can lie inside a shortest path",
            },
        )
    # cuGraph 26.10 produces NaN when normalizing graphs with fewer than three
    # vertices. Compute the unnormalized library result and apply the declared
    # normalization with its defined small-graph boundary behavior.
    values = nx.betweenness_centrality(
        g,
        normalized=args["normalized"] if backend == "networkx" else False,
        weight="weight" if weighted else None,
        backend=backend,
    )
    if backend == "cugraph" and args["normalized"] and len(g) > 2:
        factor = (1 if g.is_directed() else 2) / ((len(g) - 1) * (len(g) - 2))
        values = {v: value * factor for v, value in values.items()}
    if not all(math.isfinite(value) for value in values.values()):
        raise ConvergenceError("Betweenness returned non-finite scores")
    work.output(len(g))
    return scores(graph, values)


@register(
    id="degree-centrality",
    problem_id="centrality_influential_node_mining",
    family="centrality",
    title="Rank the number of connections",
    description="Degree centrality or raw degree with explicit direction.",
    parameters={
        "direction_mode": P(
            "string", "outgoing", choices=("incoming", "outgoing", "both")
        ),
        "normalized": P("boolean", True),
    },
)
def degree(graph, args, work, backend="networkx"):
    g = simple(graph, directed=True)
    if g.is_directed() and args["direction_mode"] != "both":
        view = g.in_degree if args["direction_mode"] == "incoming" else g.out_degree
    else:
        view = g.degree
    denominator = max(1, len(g) - 1) if args["normalized"] else 1
    values = {
        v: count / denominator if args["normalized"] else count for v, count in view
    }
    work.output(len(g))
    return scores(graph, values, quality="exact")


@register(
    id="link-prediction",
    problem_id="link_prediction",
    family="similarity",
    title="Score possible connections",
    description="Exact local similarity scores for explicit pairs or all currently absent undirected edges.",
    parameters={
        "scoring_measure": P(
            "string",
            "jaccard",
            choices=(
                "common_neighbors",
                "jaccard",
                "adamic_adar",
                "resource_allocation",
                "preferential_attachment",
                "sorensen",
                "overlap",
                "cosine",
            ),
        ),
        "candidate_pairs": P("array", None, nullable=True),
        "exclude_existing_edges": P("boolean", True),
        "top_k": P("integer", None, minimum=1, nullable=True),
    },
)
def link_prediction(graph, args, work, backend="networkx"):
    g = simple(graph)
    if args["candidate_pairs"] is None:
        pairs = (
            nx.non_edges(g)
            if args["exclude_existing_edges"]
            else ((u, v) for u in g for v in g if u < v)
        )
    else:
        pairs = []
        seen = set()
        for pair in args["candidate_pairs"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise GraphMineError("Each candidate pair needs two vertex IDs")
            u, v = sorted(map(graph.index, pair))
            if u == v:
                raise GraphMineError(
                    "Link prediction pairs must contain distinct vertices"
                )
            if (u, v) in seen:
                continue
            seen.add((u, v))
            if not args["exclude_existing_edges"] or not g.has_edge(u, v):
                pairs.append((u, v))
    materialized = []
    for pair in pairs:
        work.tick()
        materialized.append(pair)
        work.output(len(materialized))
    measure = args["scoring_measure"]
    functions = {
        "jaccard": nx.jaccard_coefficient,
        "adamic_adar": nx.adamic_adar_index,
        "resource_allocation": nx.resource_allocation_index,
        "preferential_attachment": nx.preferential_attachment,
    }
    if not materialized:
        computed = []
    elif measure in functions:
        computed = list(functions[measure](g, materialized, backend=backend))
    else:
        computed = []
        for u, v in materialized:
            common = len(set(g[u]) & set(g[v]))
            a, b = len(g[u]), len(g[v])
            denominator = {
                "common_neighbors": 1,
                "sorensen": (a + b) / 2,
                "overlap": min(a, b),
                "cosine": math.sqrt(a * b),
            }[measure]
            computed.append((u, v, common / denominator if denominator else 0.0))
    computed.sort(key=lambda row: (-row[2], row[0], row[1]))
    all_count = len(computed)
    if args["top_k"] is not None:
        computed = computed[: args["top_k"]]
    rows = [
        {"source": graph.vertex_id(u), "target": graph.vertex_id(v), "score": value}
        for u, v, value in computed
    ]
    return AlgorithmOutput(
        {"pairs": rows, "candidate_count": all_count},
        {"pairs": {"type": "table", "value": rows, "complete": len(rows) == all_count}},
    )
