from __future__ import annotations

import math
import random
import statistics

import networkx as nx

from ..contracts import AlgorithmOutput
from ..contracts import Parameter as P
from ..exceptions import GraphMineError, ResourceLimit
from ..registry import register
from ._numeric import float64
from .sampling import random_generator


def statistic_function(definition, graph, work):
    name = definition.get("name")
    fields = {
        "triangles": set(),
        "directed_triangles": set(),
        "k_cliques": {"k"},
        "density": set(),
        "modularity": {"partition", "resolution"},
    }
    if (
        not isinstance(name, str)
        or name not in fields
        or set(definition) - ({"name"} | fields[name])
    ):
        raise GraphMineError(
            "Unsupported statistic_definition; use triangles, directed_triangles, k_cliques, density or modularity"
        )
    if name in {"triangles", "k_cliques"} and graph.directed:
        raise GraphMineError(
            "Use directed_triangles for directed input; clique statistics require undirected input"
        )
    if name == "directed_triangles" and not graph.directed:
        raise GraphMineError("directed_triangles requires directed input")
    k = definition.get("k", 3)
    if name == "k_cliques" and ("k" not in definition or type(k) is not int or k < 1):
        raise GraphMineError("k_cliques requires a positive integer k")
    if name == "modularity":
        partition = definition.get("partition")
        if not isinstance(partition, list) or any(
            not isinstance(group, list) or not group for group in partition
        ):
            raise GraphMineError(
                "modularity needs a partition of all vertices into nonempty arrays"
            )
        groups = [{graph.index(v) for v in group} for group in partition]
        flattened = [v for group in partition for v in group]
        if (
            len(flattened) != graph.vertex_count
            or len(set(flattened)) != graph.vertex_count
        ):
            raise GraphMineError(
                "modularity partition must cover every vertex exactly once"
            )
        resolution = float64(definition.get("resolution", 1))
        if resolution < 0:
            raise GraphMineError("modularity resolution must be nonnegative")

    def evaluate(g):
        work.tick(len(g) + g.number_of_edges())
        if name == "density":
            return nx.density(g)
        if name == "triangles":
            return sum(nx.triangles(g, backend="networkx").values()) // 3
        if name == "modularity":
            if not g.number_of_edges():
                raise GraphMineError(
                    "Modularity is undefined for a graph with no edges"
                )
            return nx.community.modularity(
                g, groups, weight=None, resolution=resolution, backend="networkx"
            )
        count = 0
        if name == "directed_triangles":
            for cycle in nx.simple_cycles(g, length_bound=3, backend="networkx"):
                work.tick()
                count += len(cycle) == 3
        else:
            for clique in nx.enumerate_all_cliques(g, backend="networkx"):
                work.tick()
                if len(clique) > k:
                    break
                count += len(clique) == k
        return count

    return evaluate


def configuration_sample(base, rng, work, attempts_remaining):
    """Condition uniform stub pairings on simplicity, without repairing samples."""
    for attempt in range(1, attempts_remaining + 1):
        work.tick(max(1, len(base) + base.number_of_edges()))
        if base.is_directed():
            trial = nx.directed_configuration_model(
                [base.in_degree(v) for v in base],
                [base.out_degree(v) for v in base],
                seed=rng,
                backend="networkx",
            )
            simple = nx.DiGraph(trial, backend="networkx")
        else:
            trial = nx.configuration_model(
                [base.degree(v) for v in base], seed=rng, backend="networkx"
            )
            simple = nx.Graph(trial, backend="networkx")
        if (
            not nx.number_of_selfloops(trial)
            and simple.number_of_edges() == trial.number_of_edges()
        ):
            return simple, attempt
    raise ResourceLimit(
        "Simple configuration sampling exhausted max_randomization_attempts; no complete null ensemble was produced"
    )


@register(
    id="null-model-significance",
    problem_id="null_model_significance_testing",
    family="statistics",
    title="Compare a declared statistic with a random graph ensemble",
    description="NetworkX uniform G(n,m), or configuration-model rejection sampling conditioned on a simple graph with the exact per-vertex degree sequence. Dense fixed-degree inputs are sampled through their complement. Statistical estimates retain their samples and declared tail convention.",
    parameters={
        "null_model": P(
            "string",
            "degree_preserving_configuration",
            choices=("degree_preserving_configuration", "erdos_renyi"),
        ),
        "statistic_definition": P(
            "object",
            required=True,
            description="name: triangles, directed_triangles, k_cliques (k), density, or modularity (partition and optional resolution).",
        ),
        "observed_value": P("number", None, nullable=True),
        "sample_count": P("integer", required=True, minimum=1),
        "random_seed": P("integer", None, minimum=0, nullable=True),
        "tail": P(
            "string",
            "greater",
            choices=("greater", "less", "two_sided_about_null_mean"),
        ),
        "max_randomization_attempts": P("integer", 100_000, minimum=1),
        "return_randomized_edges": P("boolean", False),
    },
    quality="statistical_estimate",
    references=(
        "https://networkx.org/documentation/stable/reference/generated/networkx.generators.degree_seq.configuration_model.html",
        "https://networkx.org/documentation/stable/reference/generated/networkx.generators.random_graphs.gnm_random_graph.html",
        "https://arxiv.org/abs/1608.00607",
    ),
)
def null_significance(graph, args, work, backend="networkx"):
    g = graph.to_networkx(
        direction="preserve", parallel_edges="collapse", self_loops="drop"
    )
    evaluate = statistic_function(args["statistic_definition"], graph, work)
    observed = evaluate(g) if args["observed_value"] is None else args["observed_value"]
    observed_float = float64(observed)
    _, seed = random_generator(args["random_seed"])
    rng = random.Random(seed)
    fixed = args["null_model"] == "degree_preserving_configuration"
    if args["max_randomization_attempts"] < args["sample_count"]:
        raise GraphMineError("max_randomization_attempts must be at least sample_count")
    n, m = len(g), g.number_of_edges()
    possible = n * (n - 1) // (1 if graph.directed else 2)
    complement = fixed and m > possible / 2
    base = nx.complement(g, backend="networkx") if complement else g
    values, random_edges, attempts = [], [], 0
    work.output(args["sample_count"] * (1 + m * int(args["return_randomized_edges"])))
    for _ in range(args["sample_count"]):
        if fixed:
            sample, used = configuration_sample(
                base, rng, work, args["max_randomization_attempts"] - attempts
            )
            attempts += used
            if complement:
                sample = nx.complement(sample, backend="networkx")
            degree_views = (
                ("in_degree", "out_degree") if graph.directed else ("degree",)
            )
            if any(
                dict(getattr(sample, view)) != dict(getattr(g, view))
                for view in degree_views
            ):
                raise GraphMineError(
                    "Randomization violated the per-vertex degree invariant"
                )
        else:
            work.tick(max(1, n + m))
            sample = nx.gnm_random_graph(
                n, m, directed=graph.directed, seed=rng, backend="networkx"
            )
            attempts += 1
        if (
            len(sample) != n
            or sample.number_of_edges() != m
            or nx.number_of_selfloops(sample)
        ):
            raise GraphMineError(
                "Randomization violated the simple graph size invariant"
            )
        values.append(evaluate(sample))
        if args["return_randomized_edges"]:
            random_edges.append(
                [[graph.vertex_id(u), graph.vertex_id(v)] for u, v in sample.edges]
            )
    numeric = [float64(v) for v in values]
    mean, std = statistics.fmean(numeric), statistics.pstdev(numeric)
    tail = args["tail"]
    extreme = (
        sum(v >= observed for v in values)
        if tail == "greater"
        else sum(v <= observed for v in values)
        if tail == "less"
        else sum(abs(v - mean) >= abs(observed_float - mean) for v in numeric)
    )
    summary = {
        "mean": mean,
        "standard_deviation": std,
        "minimum": min(values),
        "maximum": max(values),
        "standard_deviation_ddof": 0,
    }
    z_score = (observed_float - mean) / std if std else None
    if any(
        not math.isfinite(v)
        for v in (mean, std, *([] if z_score is None else [z_score]))
    ):
        raise GraphMineError("Null statistics exceeded finite float64 arithmetic")
    diagnostics = {
        "random_seed": seed,
        "generator": "python.random.Random/MT19937",
        "attempts": attempts,
        "accepted": len(values),
        "acceptance_rate": len(values) / attempts,
        "complement_sampling": complement,
        "sampler": "uniform_stub_pairing_conditioned_on_simplicity"
        if fixed
        else "uniform_G_n_m",
        "invariants_checked": True,
        "tail": tail,
    }
    data = {
        "observed_value": observed,
        "null_distribution_summary": summary,
        "z_score": z_score,
        "empirical_p_value": extreme / len(values),
        "null_distribution_samples": values,
        "randomization_diagnostics": diagnostics,
        "complete": True,
    }
    if args["return_randomized_edges"]:
        data["randomized_edges"] = random_edges
    return AlgorithmOutput(
        data,
        {"samples": {"type": "numeric_sample", "value": values, "complete": True}},
        quality="statistical_estimate",
        diagnostics=diagnostics,
    )
