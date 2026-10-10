from ..contracts import AlgorithmOutput
from ..exceptions import GraphMineError


def vertex_values(graph, rows, name):
    """Lossless keyed values: JSON object keys cannot distinguish 0 from '0'."""
    if not isinstance(rows, list):
        raise GraphMineError(
            f"{name} must be an array of objects with vertex and value"
        )
    values = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"vertex", "value"}:
            raise GraphMineError(f"Every {name} row needs exactly vertex and value")
        v = graph.index(row["vertex"])
        if v in values:
            raise GraphMineError(f"Duplicate vertex in {name}")
        values[v] = row["value"]
    if set(values) != set(range(graph.vertex_count)):
        raise GraphMineError(f"{name} must contain every input vertex exactly once")
    return values


def simple(
    graph, *, directed=False, weighted=False, nonnegative=False, aggregation="collapse"
):
    return graph.to_networkx(
        direction="preserve" if directed else "require_undirected",
        parallel_edges=aggregation,
        self_loops="drop",
        weighted=weighted,
        nonnegative=nonnegative,
    )


def vertex_rows(graph, values, name="value"):
    return [
        {"vertex": vertex, name: values.get(i)}
        for i, vertex in enumerate(graph.node_ids)
    ]


def vertex_set(graph, indices):
    return [graph.vertex_id(i) for i in sorted(indices)]


def scores(graph, values, name="score", *, quality="numerical", diagnostics=None):
    rows = vertex_rows(graph, values, name)
    return AlgorithmOutput(
        {"vertices": rows},
        {
            "scores": {
                "type": "vertex_scores",
                "value": rows,
                "score_field": name,
                "complete": True,
            }
        },
        quality=quality,
        diagnostics=diagnostics or {},
    )


def groups(graph, sets, *, quality="exact"):
    ordered = sorted(
        (tuple(sorted(group)) for group in sets), key=lambda v: (-len(v), v)
    )
    records = [
        {"group": i, "vertices": vertex_set(graph, members), "size": len(members)}
        for i, members in enumerate(ordered)
    ]
    return AlgorithmOutput(
        {"groups": records, "count": len(records)},
        {"groups": {"type": "vertex_groups", "value": records, "complete": True}},
        quality=quality,
    )
