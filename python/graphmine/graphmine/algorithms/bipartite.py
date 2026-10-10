from __future__ import annotations

from itertools import combinations

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import vertex_set


def _partitions(graph, left=None, right=None):
    if left is None and right is None:
        sides = [
            v.get("attributes", {}).get("side")
            for v in graph.to_canonical()["vertices"]
        ]
        if any(
            not isinstance(side, str) or side not in {"left", "right"} for side in sides
        ):
            raise GraphMineError(
                "Every vertex needs attributes.side equal to left or right"
            )
        return {i for i, side in enumerate(sides) if side == "left"}, {
            i for i, side in enumerate(sides) if side == "right"
        }
    left_set, right_set = (
        {graph.index(v) for v in left},
        {graph.index(v) for v in right},
    )
    if len(left_set) != len(left) or len(right_set) != len(right):
        raise GraphMineError("Partitions must not contain duplicate IDs")
    if left_set & right_set or left_set | right_set != set(range(graph.vertex_count)):
        raise GraphMineError(
            "Partitions must be disjoint and cover every input vertex, including isolates"
        )
    return left_set, right_set


def _graph(graph, left, *, loop_policy="reject", objective=None):
    if graph.directed:
        raise GraphMineError("A bipartite operation requires an undirected graph")
    g = nx.Graph(backend="networkx")
    g.add_nodes_from(range(graph.vertex_count))
    for edge in graph.to_canonical()["edges"]:
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        if u == v and loop_policy == "drop":
            continue
        if (u in left) == (v in left):
            raise GraphMineError("An edge joins vertices on the same declared side")
        weighted = objective in {"maximum_weight", "minimum_cost"}
        if weighted and "weight" not in edge:
            raise GraphMineError(
                "Weighted bipartite objectives require every edge weight"
            )
        weight = edge["weight"] if weighted else 1
        if g.has_edge(u, v):
            old = g[u][v]["weight"]
            better = weight < old if objective == "minimum_cost" else weight > old
            if not better:
                continue
        g.add_edge(u, v, weight=weight, id=edge["id"])
    return g


@register(
    id="maximal-bicliques",
    problem_id="maximal_biclique_enumeration",
    family="dense_structures",
    title="Find maximal completely connected groups across two sides",
    description="A clique reduction followed by NetworkX maximal-clique enumeration; both biclique sides must be nonempty.",
    parameters={
        "left_partition": P("array", required=True),
        "right_partition": P("array", required=True),
        "minimum_left_size": P("integer", 1, minimum=1),
        "minimum_right_size": P("integer", 1, minimum=1),
        "result_limit": P("integer", None, minimum=1, nullable=True),
    },
)
def maximal_bicliques(graph, args, work, backend="networkx"):
    left, right = _partitions(graph, args["left_partition"], args["right_partition"])
    g = _graph(graph, left, loop_policy="drop")
    # Completing each side turns bicliques into cliques and preserves
    # inclusion-maximality. Single-side cliques are filtered below.
    work.tick(len(left) * (len(left) - 1) // 2 + len(right) * (len(right) - 1) // 2)
    g.add_edges_from(combinations(sorted(left), 2))
    g.add_edges_from(combinations(sorted(right), 2))
    rows, complete = [], True
    for clique in nx.find_cliques(g, backend="networkx"):
        work.tick()
        chosen = set(clique)
        l, r = chosen & left, chosen & right
        if len(l) < args["minimum_left_size"] or len(r) < args["minimum_right_size"]:
            continue
        if args["result_limit"] is not None and len(rows) >= args["result_limit"]:
            complete = False
            break
        rows.append(
            {
                "left_vertices": vertex_set(graph, l),
                "right_vertices": vertex_set(graph, r),
            }
        )
        work.output(len(rows))
    data = {"bicliques": rows, "returned_count": len(rows), "complete": complete}
    if complete:
        data["total_count"] = len(rows)
    return AlgorithmOutput(
        data,
        {
            "bicliques": {
                "type": "bipartite_groups",
                "value": rows,
                "complete": complete,
            }
        },
        complete=complete,
    )


def _butterflies(g, left, work):
    for u, v in combinations(sorted(left), 2):
        work.tick()
        for a, b in combinations(sorted(set(g[u]) & set(g[v])), 2):
            work.tick()
            yield u, v, a, b


@register(
    id="butterfly-counting",
    problem_id="butterfly_counting_bipartite",
    family="pattern_mining",
    title="Count four-way connections between two sides",
    description="Exact 2-by-2 biclique counts and participation. Core mode declares whether thresholds apply to ordinary degree or butterfly participation.",
    parameters={
        "mode": P(
            "string",
            "count",
            choices=("count", "per_vertex", "per_edge", "alpha_beta_core"),
        ),
        "alpha": P("integer", None, minimum=1, nullable=True),
        "beta": P("integer", None, minimum=1, nullable=True),
        "core_measure": P(
            "string",
            "butterfly_participation",
            choices=("butterfly_participation", "degree"),
        ),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
)
def butterflies(graph, args, work, backend="networkx"):
    left, right = _partitions(graph)
    g = _graph(graph, left)
    if args["mode"] != "alpha_beta_core" and (
        args["alpha"] is not None
        or args["beta"] is not None
        or args["core_measure"] != "butterfly_participation"
    ):
        raise GraphMineError(
            "alpha, beta and core_measure apply only to alpha_beta_core mode"
        )
    per_vertex = dict.fromkeys(g, 0)
    per_edge = {frozenset((u, v)): 0 for u, v in g.edges}
    count, instances = 0, []
    for u, v, a, b in _butterflies(g, left, work):
        count += 1
        for vertex in (u, v, a, b):
            per_vertex[vertex] += 1
        for edge in ((u, a), (u, b), (v, a), (v, b)):
            per_edge[frozenset(edge)] += 1
        if (
            args["mode"] == "alpha_beta_core"
            and args["core_measure"] == "butterfly_participation"
        ):
            instances.append(frozenset((u, v, a, b)))
    data = {"butterfly_count": count, "complete": True}
    ports = {"count": {"type": "scalar", "value": count, "complete": True}}
    if args["mode"] == "per_vertex":
        rows = [{"vertex": graph.vertex_id(v), "count": per_vertex[v]} for v in g]
        work.output(len(rows))
        data["vertices"] = rows
        ports["scores"] = {
            "type": "vertex_scores",
            "value": rows,
            "score_field": "count",
            "complete": True,
        }
    elif args["mode"] == "per_edge":
        rows = [
            {
                "source": graph.vertex_id(u),
                "target": graph.vertex_id(v),
                "count": per_edge[frozenset((u, v))],
            }
            for u, v in g.edges
        ]
        work.output(len(rows))
        data["edges"] = rows
        ports["edges"] = {
            "type": "edge_scores",
            "value": rows,
            "score_field": "count",
            "complete": True,
        }
    elif args["mode"] == "alpha_beta_core":
        measure = dict(g.degree()) if args["core_measure"] == "degree" else per_vertex
        alphas = (
            [args["alpha"]]
            if args["alpha"] is not None
            else range(1, max((measure[v] for v in left), default=0) + 1)
        )
        betas = (
            [args["beta"]]
            if args["beta"] is not None
            else range(1, max((measure[v] for v in right), default=0) + 1)
        )
        cores = []
        for alpha in alphas:
            for beta in betas:
                remaining = set(g)
                while True:
                    work.tick(len(remaining) + len(instances))
                    values = dict.fromkeys(remaining, 0)
                    if args["core_measure"] == "degree":
                        values = {v: len(set(g[v]) & remaining) for v in remaining}
                    else:
                        for instance in instances:
                            if instance <= remaining:
                                for v in instance:
                                    values[v] += 1
                    remove = {
                        v
                        for v in remaining
                        if values[v] < (alpha if v in left else beta)
                    }
                    if not remove:
                        break
                    remaining -= remove
                cores.append(
                    {
                        "alpha": alpha,
                        "beta": beta,
                        "vertices": vertex_set(graph, remaining),
                    }
                )
                work.output(len(cores) + sum(len(c["vertices"]) for c in cores))
        data["cores"] = cores
        data["core_measure"] = args["core_measure"]
        ports["cores"] = {"type": "vertex_groups", "value": cores, "complete": True}
    return AlgorithmOutput(data, ports)


@register(
    id="bipartite-matching",
    problem_id="bipartite_matching_assignment",
    family="matching",
    title="Match items on two sides by count, value, or cost",
    description="NetworkX maximum-weight matching with explicit cardinality and coverage semantics. Minimum-cost without required coverage may legitimately choose an empty matching.",
    parameters={
        "objective": P(
            "string",
            required=True,
            choices=("maximum_cardinality", "maximum_weight", "minimum_cost"),
        ),
        "weight_mode": P("string", "unweighted", choices=("unweighted", "edge_weight")),
        "perfect_matching_required": P("boolean", False),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
)
def matching(graph, args, work, backend="networkx"):
    objective = args["objective"]
    if objective != "maximum_cardinality" and args["weight_mode"] != "edge_weight":
        raise GraphMineError(
            "Weighted matching objectives require weight_mode=edge_weight"
        )
    left, right = _partitions(graph)
    g = _graph(graph, left, objective=objective)
    for u, v in g.edges:
        g[u][v]["score"] = (
            -g[u][v]["weight"] if objective == "minimum_cost" else g[u][v]["weight"]
        )
    pairs = nx.max_weight_matching(
        g,
        weight="score",
        maxcardinality=args["perfect_matching_required"]
        or objective == "maximum_cardinality",
        backend="networkx",
    )
    if args["perfect_matching_required"] and len(pairs) < min(len(left), len(right)):
        return AlgorithmOutput(
            {
                "feasible": False,
                "infeasibility_certified": True,
                "maximum_matching_size": len(pairs),
                "matching_edges": [],
                "matching_size": 0,
                "objective_value": None,
                "optimal": False,
            }
        )
    rows = []
    for u, v in sorted(tuple(sorted(edge)) for edge in pairs):
        if u not in left:
            u, v = v, u
        rows.append(
            {
                "id": g[u][v]["id"],
                "source": graph.vertex_id(u),
                "target": graph.vertex_id(v),
                "weight": g[u][v]["weight"],
            }
        )
    value = (
        len(rows)
        if objective == "maximum_cardinality"
        else sum(row["weight"] for row in rows)
    )
    work.output(len(rows))
    return AlgorithmOutput(
        {
            "matching_edges": [row["id"] for row in rows],
            "edges": rows,
            "matching_size": len(rows),
            "objective_value": value,
            "optimal": True,
            "feasible": True,
        },
        {"edges": {"type": "edge_set", "value": rows, "complete": True}},
    )
