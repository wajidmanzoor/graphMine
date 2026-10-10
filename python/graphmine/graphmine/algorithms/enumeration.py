from __future__ import annotations

import heapq
from itertools import pairwise, product

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..graph import external_id
from ..registry import register
from ._events import timestamp


@register(
    id="bounded-paths-cycles",
    problem_id="hop_constrained_cycle_path_enumeration",
    family="traversal",
    title="Enumerate bounded simple paths or cycles",
    description="NetworkX simple edge paths and bounded simple cycles, with explicit parallel-edge normalization and optional chronological filtering. A result limit retains the shortest results while still counting all qualifying results.",
    parameters={
        "task": P(
            "string",
            required=True,
            choices=(
                "s_t_path",
                "cycle_through_vertex",
                "cycle_through_edge",
                "all_cycles",
            ),
        ),
        "source": P("vertex_id", None, nullable=True),
        "target": P("vertex_id", None, nullable=True),
        "anchor_edge": P("vertex_id", None, nullable=True),
        "max_hops": P("integer", required=True, minimum=1),
        "result_limit": P("integer", None, minimum=1, nullable=True),
        "chronological_order_required": P("boolean", False),
        "parallel_edge_policy": P(
            "string", "collapse_first", choices=("collapse_first", "preserve")
        ),
    },
    references=(
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.simple_paths.all_simple_edge_paths.html",
        "https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.cycles.simple_cycles.html",
    ),
)
def bounded_paths(graph, args, work, backend="networkx"):
    if not graph.directed:
        raise GraphMineError("Bounded paths and cycles require directed input")
    task = args["task"]
    for name, required in (
        ("source", task in {"s_t_path", "cycle_through_vertex"}),
        ("target", task == "s_t_path"),
        ("anchor_edge", task == "cycle_through_edge"),
    ):
        if required != (args[name] is not None):
            raise GraphMineError(
                f"{name} is {'required' if required else 'not accepted'} for {task}"
            )
    source = graph.index(args["source"]) if args["source"] is not None else None
    target = graph.index(args["target"]) if args["target"] is not None else None
    if task == "s_t_path" and source == target:
        raise GraphMineError("s_t_path requires distinct source and target")
    raw = graph.to_canonical()["edges"]
    anchor = None
    if args["anchor_edge"] is not None:
        edge_id = external_id(args["anchor_edge"])
        anchor = next((i for i, e in enumerate(raw) if e["id"] == edge_id), None)
        if anchor is None:
            raise GraphMineError("Unknown anchor_edge")
    g = nx.MultiDiGraph(backend="networkx")
    g.add_nodes_from(range(graph.vertex_count))
    times = {}
    for i, edge in enumerate(raw):
        work.tick()
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        if u == v:
            continue
        if g.has_edge(u, v) and args["parallel_edge_policy"] == "collapse_first":
            if i == anchor:
                raise GraphMineError(
                    "anchor_edge was collapsed; choose parallel_edge_policy=preserve"
                )
            continue
        g.add_edge(u, v, key=i)
        if args["chronological_order_required"]:
            times[i] = timestamp(edge.get("timestamp"))

    def candidates():
        if task == "s_t_path":
            for edges in nx.all_simple_edge_paths(
                g, source, target, cutoff=args["max_hops"], backend="networkx"
            ):
                yield tuple(e[2] for e in edges)
        else:
            for vertices in nx.simple_cycles(
                g, length_bound=args["max_hops"], backend="networkx"
            ):
                work.tick()
                if task == "cycle_through_vertex" and source not in vertices:
                    continue
                pairs = list(pairwise([*vertices, vertices[0]]))
                for edges in product(*(g[u][v] for u, v in pairs)):
                    work.tick()
                    if task == "cycle_through_edge" and anchor not in edges:
                        continue
                    if task == "cycle_through_vertex":
                        rotation = vertices.index(source)
                    elif times:
                        rotation = min(
                            range(len(edges)), key=lambda j: (times[edges[j]], edges[j])
                        )
                    else:
                        rotation = edges.index(min(edges))
                    yield edges[rotation:] + edges[:rotation]

    kept, count, output_items = [], 0, 0
    limit = args["result_limit"]
    for edges in candidates():
        work.tick()
        if times and any(times[u] >= times[v] for u, v in pairwise(edges)):
            continue
        count += 1
        if limit is None:
            kept.append(edges)
            output_items += 1 + len(edges)
        else:
            # Negative key makes the longest/worst retained result the root.
            item = (-len(edges), tuple(-e for e in edges), edges)
            if len(kept) < limit:
                heapq.heappush(kept, item)
                output_items += 1 + len(edges)
            elif item > kept[0]:
                removed = heapq.heapreplace(kept, item)
                output_items += len(edges) - len(removed[2])
        work.output(output_items)
    sequences = sorted(
        kept if limit is None else [row[2] for row in kept],
        key=lambda row: (len(row), row),
    )
    edges_out = [[raw[i]["id"] for i in row] for row in sequences]
    vertices_out = [
        [raw[row[0]]["source"], *(raw[i]["target"] for i in row)] for row in sequences
    ]
    complete = len(sequences) == count
    data = {
        "paths_or_cycles": edges_out,
        "vertex_sequences": vertices_out,
        "result_count": len(sequences),
        "total_count": count,
        "complete": complete,
        "shortest_length_found": len(sequences[0]) if sequences else None,
    }
    return AlgorithmOutput(
        data,
        {
            "sequences": {
                "type": "edge_sequence_collection",
                "value": edges_out,
                "complete": complete,
            }
        },
        complete=complete,
        diagnostics={
            "count_complete": True,
            "parallel_edge_policy": args["parallel_edge_policy"],
            "cycle_start": "source_for_vertex_task_otherwise_earliest_event_or_first_input_edge",
        },
    )
