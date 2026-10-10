from __future__ import annotations

from fractions import Fraction

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._common import vertex_set
from ._events import number
from ._milp import BinaryModel


@register(
    id="group-steiner-tree",
    problem_id="group_steiner_tree",
    family="optimization",
    title="Connect at least one representative of every required group",
    description="SciPy/HiGHS binary tree model with separated connectivity cuts. Covers every group and required vertex, removes self-loops, and retains the cheapest original parallel edge. Requires a completed numerical optimum; no terminal-only approximation is substituted for the group problem.",
    library="scipy",
    quality="numerical_optimum",
    parameters={
        "groups": P("array", required=True),
        "required_vertices": P("array", None, nullable=True),
        "solution_quality": P("string", "exact", choices=("exact", "approximate")),
    },
    references=(
        "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html",
    ),
)
def group_steiner(graph, args, work, backend="networkx"):
    if graph.directed:
        raise GraphMineError("Group Steiner trees require undirected input")
    if not args["groups"] or any(
        not isinstance(group, list) or not group for group in args["groups"]
    ):
        raise GraphMineError("groups must contain at least one nonempty vertex array")
    groups = [{graph.index(v) for v in group} for group in args["groups"]]
    required = {graph.index(v) for v in args["required_vertices"] or []}
    demands = groups + [{v} for v in sorted(required)]
    selected_edges = {}
    for edge in graph.to_canonical()["edges"]:
        work.tick()
        if "weight" not in edge or edge["weight"] < 0:
            raise GraphMineError("Every group-Steiner edge needs a nonnegative weight")
        u, v = sorted((graph.index(edge["source"]), graph.index(edge["target"])))
        if u != v and (
            (u, v) not in selected_edges
            or edge["weight"] < selected_edges[u, v]["weight"]
        ):
            selected_edges[u, v] = edge
    edges = list(selected_edges.items())
    n, m = graph.vertex_count, len(edges)
    roots = sorted(min(demands, key=len))
    x = {v: m + v for v in range(n)}
    r = {v: m + n + i for i, v in enumerate(roots)}
    model = BinaryModel(
        [edge["weight"] for _, edge in edges] + [0] * (n + len(roots)), work
    )
    for group in demands:
        model.constrain({x[v]: 1 for v in group}, lower=1)
    model.constrain(dict.fromkeys(r.values(), 1), lower=1, upper=1)
    for v in roots:
        model.constrain({r[v]: 1, x[v]: -1}, upper=0)
    for i, ((u, v), _) in enumerate(edges):
        model.constrain({i: 1, x[u]: -1}, upper=0)
        model.constrain({i: 1, x[v]: -1}, upper=0)
    model.constrain(
        {**dict.fromkeys(range(m), 1), **dict.fromkeys(x.values(), -1)},
        lower=-1,
        upper=-1,
    )
    rounds, cuts = 0, 0
    while True:
        values, evidence = model.solve()
        rounds += 1
        if values is None:
            return AlgorithmOutput(
                {
                    "feasible": False,
                    "tree_edges": [],
                    "tree_weight": None,
                    "selected_vertices": [],
                    "optimal": False,
                },
                quality="numerical_optimum",
                diagnostics={
                    **evidence,
                    "connectivity_rounds": rounds,
                    "connectivity_cuts": cuts,
                },
            )
        selected = {v for v in range(n) if values[x[v]]}
        tree = nx.Graph(backend="networkx")
        tree.add_nodes_from(selected)
        chosen = [i for i in range(m) if values[i]]
        tree.add_edges_from(edges[i][0] for i in chosen)
        components = list(nx.connected_components(tree, backend="networkx"))
        if len(components) == 1:
            break
        for component in components:
            boundary = {
                i: 1
                for i, ((u, v), _) in enumerate(edges)
                if (u in component) != (v in component)
            }
            root_terms = {r[v]: 1 for v in component if v in r}
            for v in component:
                # A selected vertex in C requires either the chosen root in C
                # or a selected boundary edge. This cut is valid for any tree.
                model.constrain({**boundary, **root_terms, x[v]: -1}, lower=0)
                cuts += 1
    if not nx.is_tree(tree, backend="networkx") or any(
        not group & selected for group in demands
    ):
        raise GraphMineError("Group Steiner result failed tree or coverage validation")
    total = sum((Fraction(edges[i][1]["weight"]) for i in chosen), Fraction())
    vertices = vertex_set(graph, selected)
    result_edges = [edges[i][1]["id"] for i in chosen]
    representatives = [
        {"group": i, "vertex": graph.vertex_id(min(group & selected))}
        for i, group in enumerate(groups)
    ]
    work.output(len(vertices) + len(result_edges) + len(representatives))
    return AlgorithmOutput(
        {
            "feasible": True,
            "tree_edges": result_edges,
            "tree_weight": number(total),
            "tree_weight_fraction": str(total),
            "selected_vertices": vertices,
            "group_representatives": representatives,
            "optimal": True,
        },
        {
            "vertices": {"type": "vertex_set", "value": vertices, "complete": True},
            "edges": {"type": "edge_set", "value": result_edges, "complete": True},
        },
        quality="numerical_optimum",
        diagnostics={
            **evidence,
            "connectivity_rounds": rounds,
            "connectivity_cuts": cuts,
            "tree_and_group_coverage_checked": True,
        },
    )
