"""One shared encoder and one masked preference layer, trained offline with NumPy.

There are no runtime predictions, task heads, or auxiliary fitted models. The
linear encoder is an offline ablation only and cannot be loaded for serving.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict

import numpy as np

MODEL_SCHEMA = 1


def finite(value):
    return type(value) in (int, float, bool) and math.isfinite(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def feature_schema(cards):
    """Catalog vocabulary, independent of train/test measurements."""
    result = []
    for name in ("log_n", "log_m", "average_degree", "log_max_degree", "degree_cv",
                 "log_degeneracy", "directed", "weighted", "bipartite_ratio",
                 "free_core_fraction", "logical_cores", "log_free_ram",
                 "gpu_utilization", "log_free_vram", "isolated"):
        result.extend([dict(name=name, kind="aggregate"),
                       dict(name=name + ":missing", kind="missing", feature=name)])
    for card in sorted(cards, key=lambda c: c["id"]):
        problem = card["id"]
        result.append(dict(name="problem:" + problem, kind="problem", problem=problem))
        for key, spec in sorted(card["parameters"].items()):
            if hasattr(spec, "schema"):
                spec = spec.schema()
            kind = spec.get("kind", spec.get("type"))
            enum = spec.get("choices", spec.get("enum", []))
            common = dict(problem=problem, parameter=key, default=spec.get("default"))
            prefix = f"parameter:{problem}:{key}"
            # Identity values never enter the context, even when numeric.
            if kind == "vertex_id" or key.endswith("_id") or key in {
                "source", "target", "sink", "vertex", "seed_vertex", "anchor_edge", "root"
            }:
                continue
            if enum:
                result.extend(dict(name=prefix + ":" + str(value), kind="category",
                                   value=value, **common) for value in enum)
            elif kind in {"integer", "number", "boolean"}:
                result.append(dict(name=prefix, kind="number", **common))
            elif kind in {"array", "object"}:
                result.append(dict(name=prefix, kind="count", **common))
            else:
                continue
            result.append(dict(name=prefix + ":missing", kind="parameter_missing", **common))
    return result


def raw_features(row, schema):
    shape, hw = row.get("graph_features", {}), row.get("hardware", {})
    def log(value):
        return math.log1p(value) if finite(value) and value >= 0 else None
    cores, free = hw.get("total_cores"), hw.get("free_cores")
    # Physical GPU 0 is reserved for the LLM; use the analytics GPU even on a CPU run.
    gpu = next((g for g in hw.get("gpus", []) if g.get("index") == 1), {})
    aggregates = {key: shape.get(key) for key in
                  ("average_degree", "degree_cv", "directed", "weighted", "bipartite_ratio")}
    aggregates.update(log_n=log(shape.get("n")), log_m=log(shape.get("m")),
        log_max_degree=log(shape.get("max_degree")), log_degeneracy=log(shape.get("degeneracy")),
        free_core_fraction=min(1., max(0., free / cores))
            if finite(cores) and cores > 0 and finite(free) else None,
        logical_cores=cores, log_free_ram=log(hw.get("free_ram_bytes")),
        gpu_utilization=gpu.get("utilization_percent"), log_free_vram=log(gpu.get("free_memory_bytes")),
        isolated=row.get("execution_isolated"))
    result = []
    for item in schema:
        kind = item["kind"]
        if kind == "aggregate":
            value = aggregates[item["name"]]
        elif kind == "missing":
            value = not finite(aggregates[item["feature"]])
        elif kind == "problem":
            value = row["problem"] == item["problem"]
        elif row["problem"] != item["problem"]:
            value = 0.
        else:
            value = row.get("parameters", {}).get(item["parameter"], item.get("default"))
            if kind == "category":
                value = value == item["value"]
            elif kind == "count":
                value = value.get("count") if isinstance(value, dict) else len(value) if isinstance(value, list) else None
            elif kind == "parameter_missing":
                value = value is None or isinstance(value, dict) and value.get("redacted", False)
        result.append(float(value) if finite(value) else 0.)
    return np.asarray(result, dtype=float)


def normalize_fit(rows, schema):
    values = np.asarray([raw_features(row, schema) for row in rows])
    means, scales = values.mean(axis=0), values.std(axis=0)
    kept = np.flatnonzero(scales > 1e-10)
    return dict(indices=kept.tolist(), means=means[kept].tolist(), scales=scales[kept].tolist(),
                dropped_features=[schema[i]["name"] for i in range(len(schema)) if i not in set(kept)])


def matrix(rows, model):
    stats = model["normalization"]
    raw = np.asarray([raw_features(row, model["feature_schema"]) for row in rows])
    values = (raw[:, stats["indices"]] - stats["means"]) / stats["scales"]
    # Limits numerical amplification of unseen extremes without fitting on them.
    return np.clip(values, -20., 20.)


def _weights(model):
    size, backends = len(model["normalization"]["indices"]), len(model["backend_ids"])
    shapes = {"w1": (size, 64), "b1": (64,), "w2": (64, 32), "b2": (32,),
              "wo": (32, backends), "bo": (backends,)} if model["architecture"] == "shared_nn" else {
                  "w1": (size, 32), "b1": (32,), "wo": (32, backends), "bo": (backends,)}
    return {name: np.asarray(model["weights"][name], dtype=float).reshape(shape) for name, shape in shapes.items()}


def validate(model, *, serving=True):
    if model["schema_version"] != MODEL_SCHEMA or model["architecture"] not in {"shared_nn", "shared_linear"}:
        raise ValueError("Unknown shared policy format")
    if serving and model["architecture"] != "shared_nn":
        raise ValueError("The linear ablation is offline only")
    if not model["backend_ids"] or len(set(model["backend_ids"])) != len(model["backend_ids"]):
        raise ValueError("Invalid backend vocabulary")
    stats = model["normalization"]
    indices = stats["indices"]
    if len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < len(model["feature_schema"]) for i in indices):
        raise ValueError("Invalid feature indices")
    if len(indices) != len(stats["means"]) or len(indices) != len(stats["scales"]):
        raise ValueError("Invalid normalization dimensions")
    if any(not finite(v) for v in stats["means"]) or any(not finite(v) or v <= 0 for v in stats["scales"]):
        raise ValueError("Invalid normalization values")
    if not finite(model['training']['failure_penalty']) or model['training']['failure_penalty'] <= 1:
        raise ValueError('Invalid failure penalty')
    for ranges in model.get('controls', {}).values():
        for bounds in ranges:
            if (not all(finite(bounds.get(k)) and bounds[k] > 0 for k in ('slowest_seconds', 'fastest_seconds'))
                    or bounds['slowest_seconds'] < bounds['fastest_seconds']):
                raise ValueError('Invalid empirical timing bounds')
            for key in ('n', 'm'):
                if len(bounds[key]) != 2 or any(type(v) is not int or v < 0 for v in bounds[key]) or bounds[key][0] > bounds[key][1]:
                    raise ValueError('Invalid measured size range')
    if any(not np.isfinite(w).all() for w in _weights(model).values()):
        raise ValueError("Nonfinite shared policy weights")


def forward(x, weights, architecture="shared_nn"):
    z1 = x @ weights["w1"] + weights["b1"]
    if architecture == "shared_nn":
        h1 = np.maximum(z1, 0)
        z2 = h1 @ weights["w2"] + weights["b2"]
        context = np.maximum(z2, 0)
    else:
        h1, z2, context = z1, z1, z1
    return context @ weights["wo"] + weights["bo"], (x, z1, h1, z2, context)


def encode(model, row):
    if row["problem"] not in model["problem_ids"]:
        raise ValueError("Unseen runnable problem")
    return forward(matrix([row], model), _weights(model), model["architecture"])[1][-1][0]


def preferences(model, row, eligible):
    if not eligible or not set(eligible) <= set(model["backend_ids"]):
        raise ValueError("Unknown or empty eligible backend set")
    if row["problem"] not in model["problem_ids"]:
        raise ValueError("Unseen runnable problem")
    scores = forward(matrix([row], model), _weights(model), model["architecture"])[0][0]
    return {backend: float(scores[model["backend_ids"].index(backend)]) for backend in eligible}


def masked_softmax(logits, mask, temperature=1.):
    values = np.where(mask, logits / temperature, -np.inf)
    values = np.exp(values - np.max(values, axis=1, keepdims=True))
    return values / values.sum(axis=1, keepdims=True)


def backward(weights, cache, gradient, architecture):
    x, z1, h1, z2, context = cache
    result = {"wo": context.T @ gradient, "bo": gradient.sum(axis=0)}
    hidden = gradient @ weights["wo"].T
    if architecture == "shared_nn":
        hidden *= z2 > 0
        result.update(w2=h1.T @ hidden, b2=hidden.sum(axis=0))
        hidden = (hidden @ weights["w2"].T) * (z1 > 0)
    result.update(w1=x.T @ hidden, b1=hidden.sum(axis=0))
    return result


def split_graphs(cases, fraction=.2, seed=1729):
    graphs = sorted({case["context"]["graph_features"]["snapshot_fingerprint"] for case in cases},
                    key=lambda key: digest([seed, key]))
    if len(graphs) < 5:
        raise ValueError("At least five distinct graph snapshots are required")
    held = set(graphs[:max(1, round(len(graphs) * fraction))])
    return ([c for c in cases if c["context"]["graph_features"]["snapshot_fingerprint"] not in held],
            [c for c in cases if c["context"]["graph_features"]["snapshot_fingerprint"] in held])


def paired_cases(rows, *, failure_penalty=10.):
    """Keep full timings; penalize failure above the slowest completed choice.

    Missing counterfactual measurements are excluded, never imputed as wins.
    An all-failed comparison has no measured oracle and cannot define a ratio.
    """
    if not finite(failure_penalty) or failure_penalty <= 1:
        raise ValueError("Failure penalty must exceed one")
    groups = defaultdict(list)
    for row in rows:
        if row.get("source") == "benchmark" and row.get("comparison_id") and row.get("is_evaluation") is False:
            groups[(row["implementation_sha256"], row["comparison_id"], row.get("load_regime", "observed"))].append(row)
    cases, excluded = [], defaultdict(int)
    for (_, comparison, regime), group in sorted(groups.items()):
        first = group[0]
        context = first.get("pair_context") or {k: first[k] for k in
            ("problem", "parameters", "graph_features", "hardware", "execution_isolated")}
        eligible = first.get("paired_eligible_backends") or first.get("eligible_backends") or [
            c["id"] for c in first["candidates"] if c.get("feasible")]
        eligible = list(dict.fromkeys(eligible))
        measurements = {b: [r for r in group if (r.get("chosen_backend") or r.get("requested_backend")) == b] for b in eligible}
        if not eligible or any(not v for v in measurements.values()):
            excluded["incomplete_pairs"] += 1
            continue
        pair_contexts = {digest(r['pair_context']) for r in group if r.get('pair_context')}
        if len(pair_contexts) > 1:
            excluded['changed_pair_context'] += 1
            continue
        # Reject deliberately non-comparable measured contention. The threshold
        # uses free-core fractions, not a nominal idle/busy label.
        def load_fraction(hw):
            return hw['free_cores'] / hw['total_cores'] if finite(hw.get('free_cores')) and finite(hw.get('total_cores')) and hw['total_cores'] > 0 else None
        original_load = load_fraction(context.get('hardware', {}))
        loads = [load_fraction(r.get('hardware', {})) for r in group]
        if original_load is not None and any(v is not None and abs(v - original_load) > .15 for v in loads):
            excluded['load_drift'] += 1
            continue
        if any(r["problem"] != context["problem"] or r["parameters"] != context["parameters"] or
               r["graph_features"]["snapshot_fingerprint"] != context["graph_features"]["snapshot_fingerprint"] for r in group):
            excluded["inconsistent_pair"] += 1
            continue
        completed = [r["runtime_seconds"] for group_rows in measurements.values() for r in group_rows
                     if r["outcome"] == "completed" and finite(r.get("runtime_seconds")) and r["runtime_seconds"] > 0]
        if not completed:
            excluded["no_completed_oracle"] += 1
            continue
        penalty = max(completed) * failure_penalty
        timings = {b: [float(r["runtime_seconds"]) if r["outcome"] == "completed" and
                       finite(r.get("runtime_seconds")) and r["runtime_seconds"] > 0 else penalty for r in rs]
                   for b, rs in measurements.items()}
        seconds = {b: float(np.mean(values)) for b, values in timings.items()}
        best = min(seconds.values())
        cases.append(dict(comparison_id=comparison, context=context, eligible_backends=eligible,
            costs={b: seconds[b] / best for b in eligible}, seconds=seconds, timings=timings,
            outcomes={b: [r["outcome"] for r in measurements[b]] for b in eligible},
            observed_seconds={b: [r.get('runtime_seconds') for r in measurements[b]] for b in eligible},
            load_regime=regime, oracle_seconds=best,
            # Collection order is randomized; native order comes from preflight.
            native_backend=next((c["id"] for c in first["candidates"]
                                 if c["id"] in eligible and c.get("device") == "gpu"), "cpp")))
    return cases, dict(excluded)


def empirical_controls(cases):
    groups = defaultdict(list)
    for case in cases:
        row, sizes = case["context"], case["context"]["graph_features"]
        key = (row["problem"], digest(row["parameters"]), int(math.log2(1 + sizes["n"])), int(math.log2(1 + sizes["m"])))
        groups[key].append(case)
    result = defaultdict(list)
    for (problem, parameters, _, _), group in groups.items():
        successful = [t for c in group for b in c["eligible_backends"]
                      for t, outcome in zip(c["timings"][b], c["outcomes"][b]) if outcome == "completed"]
        if successful:
            result[problem].append(dict(parameters_sha256=parameters,
                n=[min(c["context"]["graph_features"]["n"] for c in group), max(c["context"]["graph_features"]["n"] for c in group)],
                m=[min(c["context"]["graph_features"]["m"] for c in group), max(c["context"]["graph_features"]["m"] for c in group)],
                slowest_seconds=max(successful), fastest_seconds=min(successful)))
    return dict(result)


def train(cases, cards, implementation, *, feedback=(), architecture="shared_nn", seed=1729,
          epochs=400, learning_rate=.003, ipw_clip=20., failure_penalty=10.):
    if architecture not in {"shared_nn", "shared_linear"} or not cases:
        raise ValueError("Invalid shared training request")
    if not any(len(c["eligible_backends"]) > 1 for c in cases):
        raise ValueError("Training requires paired measurements for multiple backends")
    if epochs <= 0 or not 0 < learning_rate < 1 or not finite(ipw_clip) or ipw_clip < 1:
        raise ValueError("Invalid training controls")
    rng = np.random.default_rng(seed)
    schema = feature_schema(cards)
    rows = [c["context"] for c in cases]
    backend_ids = sorted({b["id"] for c in cards for b in c["backends"]})
    model = dict(schema_version=MODEL_SCHEMA, architecture=architecture,
        implementation_sha256=implementation, backend_ids=backend_ids,
        problem_ids=sorted({c["id"] for c in cards}), feature_schema=schema,
        normalization=normalize_fit(rows, schema), controls=empirical_controls(cases))
    x = matrix(rows, model)
    def weight(a, b):
        return rng.normal(0, math.sqrt(2 / max(1, a)), (a, b))
    width = 64 if architecture == "shared_nn" else 32
    weights = dict(w1=weight(x.shape[1], width), b1=np.zeros(width), wo=weight(32, len(backend_ids)) * .1, bo=np.zeros(len(backend_ids)))
    if architecture == "shared_nn":
        weights.update(w2=weight(64, 32), b2=np.zeros(32))
    masks = np.asarray([[b in c["eligible_backends"] for b in backend_ids] for c in cases])
    costs = np.asarray([[c["costs"].get(b, 0.) - (1. if b in c["costs"] else 0.) for b in backend_ids] for c in cases])
    # Feedback must carry the actual behavior propensity, never a shadow proposal.
    online = [r for r in feedback if r.get("source") == "application" and r.get("is_evaluation") is False
              and r.get("selection_mode") == "bandit" and r.get("implementation_sha256") == implementation
              and r.get("problem") in model["problem_ids"] and finite(r.get("selection_probability"))
              and 0 < r["selection_probability"] <= 1 and r.get("chosen_backend") in backend_ids
              and r.get("chosen_backend") in r.get("eligible_backends", [])
              and set(r["eligible_backends"]) <= set(backend_ids) and r.get("outcome") in {"completed", "timeout", "oom", "error", "unsupported_input"}
              and finite(r.get("cost_scale_seconds")) and r["cost_scale_seconds"] > 0
              and (r["outcome"] != "completed" or finite(r.get("runtime_seconds")) and r["runtime_seconds"] > 0)]
    if online:
        ox = matrix(online, model)
        omask = np.asarray([[b in r["eligible_backends"] for b in backend_ids] for r in online])
        chosen = np.asarray([backend_ids.index(r["chosen_backend"]) for r in online])
        ocost = np.asarray([r["runtime_seconds"] / r["cost_scale_seconds"] if r["outcome"] == "completed"
                            else max(failure_penalty, r.get("failure_cost", failure_penalty)) for r in online])
        importance = np.asarray([min(ipw_clip, 1 / r["selection_probability"]) for r in online])
    moment, variance = ({k: np.zeros_like(v) for k, v in weights.items()} for _ in range(2))
    losses = []
    for epoch in range(1, epochs + 1):
        logits, cache = forward(x, weights, architecture)
        probs = masked_softmax(logits, masks)
        expected = (probs * costs).sum(axis=1, keepdims=True)
        gradient = probs * (costs - expected) / len(cases)
        gradients = backward(weights, cache, gradient, architecture)
        loss = float(expected.mean())
        if online:
            ol, ocache = forward(ox, weights, architecture)
            op = masked_softmax(ol, omask)
            weighted = importance * ocost * op[np.arange(len(online)), chosen]
            og = -op * weighted[:, None]
            og[np.arange(len(online)), chosen] += weighted
            extra = backward(weights, ocache, og / len(online), architecture)
            gradients = {k: gradients[k] + extra[k] for k in gradients}
            loss += float(weighted.mean())
        for key in weights:
            grad = np.clip(gradients[key], -100, 100)
            moment[key] = .9 * moment[key] + .1 * grad
            variance[key] = .999 * variance[key] + .001 * grad * grad
            weights[key] -= learning_rate * (moment[key] / (1 - .9 ** epoch)) / (np.sqrt(variance[key] / (1 - .999 ** epoch)) + 1e-8)
        if epoch == 1 or epoch == epochs:
            losses.append(loss)
    model.update(weights={k: v.tolist() for k, v in weights.items()}, training=dict(
        paired_cases=len(cases), feedback_rows=len(online), epochs=epochs, seed=seed,
        ipw_clip=ipw_clip, failure_penalty=failure_penalty, losses=losses,
        graphs=sorted({r["graph_features"]["snapshot_fingerprint"] for r in rows}),
        data_sha256=digest(cases)))
    validate(model, serving=False)
    return model
