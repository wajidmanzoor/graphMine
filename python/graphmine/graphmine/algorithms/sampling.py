from __future__ import annotations

from collections import defaultdict
from fractions import Fraction

import numpy as np

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError
from ..registry import register
from ._events import timestamp


def random_generator(seed):
    if seed is None:
        seed = int(np.random.SeedSequence().generate_state(2, dtype=np.uint32)[0])
    return np.random.default_rng(seed), seed


def probabilities(values):
    weights = [Fraction(v) for v in values]
    if any(w < 0 for w in weights):
        raise GraphMineError("Sampling weights must be nonnegative")
    if not weights or not any(weights):
        return None
    maximum = max(weights)
    normalized = np.array([float(w / maximum) for w in weights])
    normalized /= normalized.sum()
    if any(w > 0 and p == 0 for w, p in zip(weights, normalized, strict=True)):
        raise GraphMineError(
            "A positive sampling probability underflowed float64; rescale the weight range"
        )
    return normalized


@register(
    id="random-walks",
    problem_id="random_walk_generation",
    family="sampling",
    title="Sample graph walks with an explicit transition model",
    description="NumPy random sampling over outgoing adjacency. Uniform walks collapse parallel edges; weighted and node2vec walks sum weights. Self-loops are retained. Zero total outgoing weight terminates a walk.",
    parameters={
        "start_vertices": P("array", required=True),
        "length": P("integer", required=True, minimum=0),
        "walk_model": P(
            "string", "uniform", choices=("uniform", "weighted", "node2vec")
        ),
        "p": P("number", 1.0, minimum=0),
        "q": P("number", 1.0, minimum=0),
        "random_seed": P("integer", None, minimum=0, nullable=True),
    },
    quality="stochastic",
    library="numpy",
    references=(
        "https://arxiv.org/abs/1607.00653",
        "https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.choice.html",
    ),
)
def walks(graph, args, work, backend="networkx"):
    if args["p"] <= 0 or args["q"] <= 0:
        raise GraphMineError("node2vec p and q must be positive")
    model = args["walk_model"]
    if model != "node2vec" and (args["p"] != 1 or args["q"] != 1):
        raise GraphMineError("p and q apply only to node2vec")
    weighted = model != "uniform"
    g = graph.to_networkx(
        direction="preserve",
        parallel_edges="sum" if weighted else "collapse",
        self_loops="keep",
        weighted=weighted,
        nonnegative=weighted,
    )
    starts = [graph.index(v) for v in args["start_vertices"]]
    rng, seed = random_generator(args["random_seed"])
    result, used = [], 0
    for source in starts:
        path = [source]
        work.output(used + 1)
        for _ in range(args["length"]):
            work.tick()
            current = path[-1]
            neighbors = list(g[current])
            if not neighbors:
                break
            if not weighted:
                chosen = neighbors[int(rng.integers(len(neighbors)))]
            else:
                weights = [g[current][v]["weight"] for v in neighbors]
                if model == "node2vec" and len(path) > 1:
                    previous = path[-2]
                    # Exact rational preprocessing avoids overflowing an
                    # intermediate inverse p/q before float64 normalization.
                    weights = [
                        Fraction(w)
                        / Fraction(
                            args["p"]
                            if v == previous
                            else 1
                            if g.has_edge(previous, v)
                            else args["q"]
                        )
                        for v, w in zip(neighbors, weights, strict=True)
                    ]
                p = probabilities(weights)
                if p is None:
                    break
                chosen = neighbors[int(rng.choice(len(neighbors), p=p))]
            path.append(chosen)
            work.output(used + len(path))
        result.append([graph.vertex_id(v) for v in path])
        used += len(path)
        work.output(used)
    return AlgorithmOutput(
        {"walks": result, "lengths": [len(path) - 1 for path in result]},
        {"walks": {"type": "walk_sample", "value": result, "complete": True}},
        quality="stochastic",
        diagnostics={
            "random_seed": seed,
            "generator": "numpy.default_rng/PCG64",
            "probability_arithmetic": "float64",
            "node2vec_adjacency": "previous_to_candidate_arc",
        },
    )


def _fanout(value):
    if type(value) is not int or value < -1:
        raise GraphMineError("Every fanout must be -1 or a nonnegative integer")
    return value


@register(
    id="neighborhood-sampling",
    problem_id="neighborhood_sampling",
    family="sampling",
    title="Sample neighborhoods while retaining original edge identities",
    description="Sample outgoing edge instances per distinct frontier vertex, hop and seed batch. Parallel edges and self-loops retain their identity. Typed fanouts and UTC timestamp cutoffs are explicit.",
    parameters={
        "seeds": P("array", required=True),
        "fanouts": P("array", required=True),
        "replacement": P("boolean", False),
        "sampling_model": P("string", "uniform", choices=("uniform", "weighted")),
        "edge_type_fanouts": P(
            "object",
            None,
            nullable=True,
            description="Map edge type to one fanout per hop; unlisted types use fanouts.",
        ),
        "time_cutoff": P("number", None, nullable=True),
        "random_seed": P("integer", None, minimum=0, nullable=True),
    },
    quality="stochastic",
    library="numpy",
    references=(
        "https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.choice.html",
    ),
)
def neighborhoods(graph, args, work, backend="networkx"):
    fanouts = [_fanout(v) for v in args["fanouts"]]
    overrides = args["edge_type_fanouts"]
    if overrides is not None:
        for name, values in overrides.items():
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(values, list)
                or len(values) != len(fanouts)
            ):
                raise GraphMineError(
                    "Typed fanouts need a nonempty type name and one value per hop"
                )
            for value in values:
                _fanout(value)
    seeds = [graph.index(v) for v in args["seeds"]]
    adjacency = defaultdict(list)
    weighted = args["sampling_model"] == "weighted"
    for edge in graph.to_canonical()["edges"]:
        work.tick()
        if overrides is not None and not edge.get("type"):
            raise GraphMineError(
                "Typed fanout sampling requires every edge to have a nonempty type"
            )
        weight = edge.get("weight", 1) if weighted else 1
        if weight < 0:
            raise GraphMineError("Sampling weights must be nonnegative")
        if args["time_cutoff"] is not None and timestamp(
            edge.get("timestamp")
        ) > Fraction(args["time_cutoff"]):
            continue
        u, v = graph.index(edge["source"]), graph.index(edge["target"])
        adjacency[u].append((v, edge["id"], weight, edge.get("type")))
        if not graph.directed and u != v:
            adjacency[v].append((u, edge["id"], weight, edge.get("type")))
    rng, seed = random_generator(args["random_seed"])
    rows, selected = [], set(seeds)
    for batch, source in enumerate(seeds):
        frontier = [source]
        for hop, default in enumerate(fanouts):
            following = {}
            for u in frontier:
                grouped = defaultdict(list)
                for item in adjacency[u]:
                    grouped[item[3] if overrides is not None else None].append(item)
                for kind, candidates in grouped.items():
                    count = (
                        overrides.get(kind, fanouts)[hop]
                        if overrides is not None
                        else default
                    )
                    if count == -1:
                        indices = list(range(len(candidates)))
                    else:
                        p = (
                            probabilities([row[2] for row in candidates])
                            if weighted
                            else None
                        )
                        if weighted and p is None:
                            indices = []
                        else:
                            eligible = (
                                int(np.count_nonzero(p))
                                if weighted
                                else len(candidates)
                            )
                            size = (
                                count if args["replacement"] else min(count, eligible)
                            )
                            work.tick(size)
                            work.output(len(rows) + size)
                            indices = rng.choice(
                                len(candidates),
                                size=size,
                                replace=args["replacement"],
                                p=p,
                            ).tolist()
                    for i in indices:
                        work.tick()
                        v, edge_id, _, _ = candidates[i]
                        rows.append(
                            {
                                "edge_id": edge_id,
                                "source": graph.vertex_id(u),
                                "target": graph.vertex_id(v),
                                "hop": hop + 1,
                                "batch": batch,
                                "seed": graph.vertex_id(source),
                            }
                        )
                        following[v] = None
                        selected.add(v)
                    work.output(len(rows) + len(selected))
            frontier = list(following)
    vertices = [graph.vertex_id(v) for v in sorted(selected)]
    work.output(len(rows) + len(vertices))
    return AlgorithmOutput(
        {"sampled_edges": rows, "sampled_vertices": vertices},
        {
            "edges": {"type": "edge_sample", "value": rows, "complete": True},
            "vertices": {
                "type": "vertex_set",
                "value": vertices,
                "complete": True,
                "scope": "requested_random_sample",
            },
        },
        quality="stochastic",
        diagnostics={
            "random_seed": seed,
            "sample_unit": "edge_instance",
            "frontier_multiplicity": "distinct_vertices_per_hop_and_seed_batch",
            "all_neighbors_includes_zero_weight_edges": True,
        },
    )
