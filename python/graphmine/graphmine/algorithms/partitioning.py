from __future__ import annotations

import math
from fractions import Fraction
from itertools import combinations

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import simple, vertex_set, vertex_values
from ._milp import BinaryModel, integral_balance_row


def _assignment_output(graph, parts, data, *, quality, diagnostics=None):
    assignment = {v: i for i, part in enumerate(parts) for v in part}
    if (
        set(assignment) != set(range(graph.vertex_count))
        or sum(map(len, parts)) != graph.vertex_count
    ):
        raise GraphMineError("Partition does not cover each vertex exactly once")
    rows = [
        {"vertex": graph.vertex_id(v), "part": assignment[v]}
        for v in range(graph.vertex_count)
    ]
    groups = [
        {"group": i, "vertices": vertex_set(graph, part)}
        for i, part in enumerate(parts)
    ]
    return AlgorithmOutput(
        {"partition_assignment": rows, "groups": groups, **data},
        {
            "partition": {"type": "vertex_partition", "value": rows, "complete": True},
            "groups": {"type": "vertex_groups", "value": groups, "complete": True},
        },
        quality=quality,
        diagnostics=diagnostics or {},
    )


def _cpm(g, parts, resolution):
    return sum(
        sum(d["weight"] for _, _, d in g.subgraph(part).edges(data=True))
        - resolution * len(part) * (len(part) - 1) / 2
        for part in parts
    )


@register(
    id="community-detection",
    problem_id="community_detection",
    family="communities",
    title="Divide a network into communities",
    description="Louvain for heuristic modularity; checked binary partition optimization for exact modularity or CPM. CPM is internal edge weight minus resolution times the number of within-community vertex pairs.",
    parameters={
        "quality_function": P(
            "string", "modularity", choices=("modularity", "constant_potts_model")
        ),
        "resolution": P("number", 1.0, minimum=0),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "solution_quality": P("string", "heuristic", choices=("exact", "heuristic")),
        "seed": P("integer", 0, minimum=0),
    },
    quality="heuristic",
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html",
    ),
)
def community_detection(graph, args, work, backend="networkx"):
    resolution = args["resolution"]
    if resolution <= 0:
        raise GraphMineError("resolution must be positive")
    weighted = args["weight_mode"] == "edge_weight"
    g = simple(
        graph,
        weighted=weighted,
        nonnegative=True,
        aggregation="sum" if weighted else "collapse",
    )
    total = g.size(weight="weight")
    modularity = args["quality_function"] == "modularity"
    evidence, optimal, quality = {}, False, "heuristic"
    if not g or total == 0:
        parts = [{v} for v in g]
        optimal, quality = True, "exact"
    elif args["solution_quality"] == "heuristic" and modularity:
        parts = nx.community.louvain_communities(
            g,
            weight="weight",
            resolution=resolution,
            seed=args["seed"],
            backend="networkx",
        )
    else:
        pairs = list(combinations(g.nodes, 2))
        lookup = {pair: i for i, pair in enumerate(pairs)}
        degrees = dict(g.degree(weight="weight"))
        costs = []
        for u, v in pairs:
            weight = g[u][v]["weight"] if g.has_edge(u, v) else 0
            coefficient = (
                (weight - resolution * degrees[u] * degrees[v] / (2 * total)) / total
                if modularity
                else weight - resolution
            )
            costs.append(-coefficient)
        model = BinaryModel(costs, work)
        # Same-community is an equivalence relation. The three triangle
        # inequalities forbid exactly two true pair variables in a triple.
        for a, b, c in combinations(g.nodes, 3):
            i, j, k = lookup[a, b], lookup[a, c], lookup[b, c]
            for excluded, others in ((i, (j, k)), (j, (i, k)), (k, (i, j))):
                model.constrain({excluded: -1, others[0]: 1, others[1]: 1}, upper=1)
        values, evidence = model.solve()
        if values is None:
            raise GraphMineError("Community partition model unexpectedly infeasible")
        same = nx.Graph(backend="networkx")
        same.add_nodes_from(g)
        same.add_edges_from(
            pair for pair, value in zip(pairs, values, strict=True) if value
        )
        parts = list(nx.connected_components(same, backend="networkx"))
        if any(
            same.subgraph(part).number_of_edges() != len(part) * (len(part) - 1) // 2
            for part in parts
        ):
            raise GraphMineError("Community relation is not transitive")
        optimal, quality = True, "numerical_optimum"
    parts = sorted((set(part) for part in parts), key=lambda p: min(p))
    score = (
        (
            nx.community.modularity(
                g, parts, weight="weight", resolution=resolution, backend="networkx"
            )
            if total
            else 0
        )
        if modularity
        else _cpm(g, parts, resolution)
    )
    work.output(len(g) + len(parts))
    output = _assignment_output(
        graph,
        parts,
        {
            "community_count": len(parts),
            "quality_score": score,
            "quality_function": args["quality_function"],
            "optimal": optimal,
        },
        quality=quality,
        diagnostics=evidence,
    )
    output.data["community_by_vertex"] = [
        {"vertex": row["vertex"], "community": row["part"]}
        for row in output.data["partition_assignment"]
    ]
    return output


@register(
    id="balanced-partitioning",
    problem_id="balanced_graph_partitioning",
    family="partitioning",
    title="Split a graph into balanced groups with few crossing edges",
    description="Minimize crossing edge cost under both lower and upper balance limits and nonempty parts. Normalized cut is the sum of each part's boundary cost divided by its declared balance size.",
    parameters={
        "num_parts": P("integer", required=True, minimum=2),
        "balance_mode": P(
            "string", "vertex_count", choices=("vertex_count", "vertex_weight")
        ),
        "vertex_weights": P(
            "array",
            None,
            nullable=True,
            description="One {vertex, value} record per input vertex.",
        ),
        "imbalance_tolerance": P("number", 0.03, minimum=0),
        "edge_weight_mode": P(
            "string", "unweighted", choices=("unweighted", "edge_weight")
        ),
        "objective": P("string", "edge_cut", choices=("edge_cut", "normalized_cut")),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
    library="scipy",
    quality="numerical_optimum",
)
def balanced_partitioning(graph, args, work, backend="networkx"):
    n, k = graph.vertex_count, args["num_parts"]
    if k > n:
        raise GraphMineError("num_parts exceeds the number of vertices")
    weighted = args["edge_weight_mode"] == "edge_weight"
    g = simple(
        graph,
        weighted=weighted,
        nonnegative=True,
        aggregation="sum" if weighted else "collapse",
    )
    if args["balance_mode"] == "vertex_count":
        if args["vertex_weights"] is not None:
            raise GraphMineError(
                "vertex_weights applies only to balance_mode=vertex_weight"
            )
        weights = dict.fromkeys(g, 1)
    else:
        weights = vertex_values(graph, args["vertex_weights"], "vertex_weights")
        if any(
            type(w) not in (int, float) or not math.isfinite(w) or w < 0
            for w in weights.values()
        ):
            raise GraphMineError(
                "Vertex balance weights must be finite and nonnegative"
            )
    rational = {v: Fraction(w) for v, w in weights.items()}
    ideal = sum(rational.values()) / k
    tolerance = Fraction(str(args["imbalance_tolerance"]))
    lower, upper = max(Fraction(), (1 - tolerance) * ideal), (1 + tolerance) * ideal
    balance, balance_lower, balance_upper = integral_balance_row(
        [weights[v] for v in g], lower=lower, upper=upper
    )
    if args["objective"] == "edge_cut":
        edges = list(g.edges(data=True))
        model = BinaryModel([0] * (n * k) + [d["weight"] for _, _, d in edges], work)
        for v in g:
            model.constrain({v * k + p: 1 for p in range(k)}, 1, 1)
        for p in range(k):
            model.constrain(
                {v * k + p: balance[v] for v in g}, balance_lower, balance_upper
            )
            model.constrain({v * k + p: 1 for v in g}, lower=1)
        model.constrain({0: 1}, 1, 1)
        for e, (u, v, _) in enumerate(edges):
            y = n * k + e
            for p in range(k):
                model.constrain({y: 1, u * k + p: -1, v * k + p: 1}, lower=0)
                model.constrain({y: 1, u * k + p: 1, v * k + p: -1}, lower=0)
        values, evidence = model.solve()
        parts = (
            [{v for v in g if values[v * k + p]} for p in range(k)]
            if values is not None
            else None
        )
    else:
        # Set partitioning represents each feasible part once. This exact
        # formulation avoids replacing size-normalized cut by ordinary cut.
        candidates, costs = [], []
        for size in range(1, n - k + 2):
            for vertices in combinations(g.nodes, size):
                work.tick()
                chosen = set(vertices)
                weight = sum(rational[v] for v in chosen)
                if weight <= 0 or not lower <= weight <= upper:
                    continue
                cut = sum(
                    d["weight"]
                    for u, v, d in g.edges(data=True)
                    if (u in chosen) != (v in chosen)
                )
                candidates.append(chosen)
                costs.append(float(Fraction(cut) / weight))
        model = BinaryModel(costs, work)
        for v in g:
            model.constrain(
                {i: 1 for i, part in enumerate(candidates) if v in part}, 1, 1
            )
        model.constrain(dict.fromkeys(range(len(candidates)), 1), k, k)
        values, evidence = model.solve()
        parts = (
            [part for part, value in zip(candidates, values, strict=True) if value]
            if values is not None
            else None
        )
    if parts is None:
        return AlgorithmOutput(
            {
                "feasible": False,
                "balanced": False,
                "infeasibility_certified": True,
                "partition_assignment": [],
                "part_sizes": [],
                "objective_value": None,
                "optimal": False,
            },
            diagnostics=evidence,
        )
    sizes = [sum(rational[v] for v in part) for part in parts]
    if (
        len(parts) != k
        or any(not part for part in parts)
        or any(not lower <= size <= upper for size in sizes)
    ):
        raise GraphMineError(
            "The solver's partition violates the requested balance constraints"
        )
    assignment = {v: p for p, part in enumerate(parts) for v in part}
    cut = sum(
        d["weight"] for u, v, d in g.edges(data=True) if assignment[u] != assignment[v]
    )
    objective = (
        cut
        if args["objective"] == "edge_cut"
        else sum(
            float(
                Fraction(
                    sum(
                        d["weight"]
                        for u, v, d in g.edges(data=True)
                        if (u in part) != (v in part)
                    )
                )
                / size
            )
            for part, size in zip(parts, sizes, strict=True)
        )
    )
    deviation = (
        max((abs(size - ideal) / ideal for size in sizes), default=0) if ideal else 0
    )
    work.output(n + k)
    return _assignment_output(
        graph,
        parts,
        {
            "feasible": True,
            "balanced": True,
            "part_sizes": [float(s) for s in sizes],
            "objective_value": objective,
            "edge_cut": cut,
            "optimal": True,
            "imbalance_ratio": float(deviation),
        },
        quality="numerical_optimum",
        diagnostics=evidence,
    )


@register(
    id="signed-balance",
    problem_id="signed_network_structural_balance",
    family="partitioning",
    title="Check signed-network balance or minimize frustrated connections",
    description="Structural balance is an exact parity test, independent of edge costs. Frustration minimization uses binary XOR constraints and recomputes the weighted violations.",
    parameters={
        "task": P(
            "string",
            required=True,
            choices=("balance_check", "frustration_minimization"),
        ),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
)
def signed_balance(graph, args, work, backend="networkx"):
    if graph.directed:
        raise GraphMineError("Signed balance requires an undirected graph")
    g = nx.Graph(backend="networkx")
    g.add_nodes_from(range(graph.vertex_count))
    weighted = args["weight_mode"] == "edge_weight"
    for edge in graph.to_canonical()["edges"]:
        if edge.get("type") not in {"positive", "negative"}:
            raise GraphMineError("Every signed edge type must be positive or negative")
        weight = edge.get("weight", 1) if weighted else 1
        if weight < 0:
            raise GraphMineError("Frustration costs must be nonnegative")
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        if u == v:
            continue
        if g.has_edge(u, v):
            if g[u][v]["negative"] != (edge["type"] == "negative"):
                raise GraphMineError(
                    "Contradictory parallel signed edges require a resolution policy"
                )
            if weighted:
                g[u][v]["weight"] += weight
        else:
            g.add_edge(u, v, weight=weight, negative=edge["type"] == "negative")
    parity = {}
    components = list(nx.connected_components(g, backend="networkx"))
    for component in components:
        root = min(component)
        parity[root] = 0
        for u, v in nx.bfs_edges(g, root, backend="networkx"):
            work.tick()
            parity[v] = parity[u] ^ g[u][v]["negative"]
    balanced = all(
        (parity[u] != parity[v]) == d["negative"] for u, v, d in g.edges(data=True)
    )
    quality, evidence = "exact", {"balance_test": "signed_spanning_forest_parity"}
    if args["task"] == "frustration_minimization" and not balanced:
        edges = list(g.edges(data=True))
        n = len(g)
        model = BinaryModel(
            [0] * n
            + [(-d["weight"] if d["negative"] else d["weight"]) for _, _, d in edges],
            work,
        )
        for component in components:
            model.constrain({min(component): 1}, 0, 0)
        for e, (u, v, _) in enumerate(edges):
            y = n + e
            model.constrain({y: 1, u: -1, v: 1}, lower=0)
            model.constrain({y: 1, u: 1, v: -1}, lower=0)
            model.constrain({y: 1, u: -1, v: -1}, upper=0)
            model.constrain({y: 1, u: 1, v: 1}, upper=2)
        values, evidence = model.solve()
        if values is None:
            raise GraphMineError("Frustration model unexpectedly infeasible")
        parity = {v: values[v] for v in g}
        evidence["objective_offset"] = sum(
            d["weight"] for _, _, d in edges if d["negative"]
        )
        quality = "numerical_optimum"
    frustrated = [
        (u, v, d)
        for u, v, d in g.edges(data=True)
        if (parity[u] != parity[v]) != d["negative"]
    ]
    weight = sum(d["weight"] for _, _, d in frustrated)
    rows = [
        {"vertex": graph.vertex_id(v), "faction": "B" if parity[v] else "A"} for v in g
    ]
    work.output(len(rows) + len(frustrated))
    return AlgorithmOutput(
        {
            "balanced": balanced,
            "faction_assignment": rows,
            "frustrated_weight": weight,
            "optimal": True,
            "frustration_optimal": balanced
            or args["task"] == "frustration_minimization",
            "frustrated_edges": [
                {
                    "source": graph.vertex_id(u),
                    "target": graph.vertex_id(v),
                    "weight": d["weight"],
                }
                for u, v, d in frustrated
            ],
        },
        {
            "partition": {
                "type": "vertex_partition",
                "value": [
                    {"vertex": row["vertex"], "part": row["faction"]} for row in rows
                ],
                "complete": True,
            }
        },
        quality=quality,
        diagnostics=evidence,
    )
