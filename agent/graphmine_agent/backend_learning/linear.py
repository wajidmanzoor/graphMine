"""Bayesian linear reward heads using aggregate contexts and plain JSON.

Observation noise has fixed variance 1 in log-seconds. Coefficients have an
independent Normal prior (intercept variance 25, slopes variance 4). Thus the
posterior and predictive log-runtime distribution are Gaussian. Timeouts use
the deliberately pessimistic reward -log(2 * timeout); OOM never enters this fit.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections import Counter

MODEL_SCHEMA = 1
ENCODER_VERSION = 1
TIMEOUT_PENALTY = 2.0
MAX_DIMENSIONS = 256
BASE_FEATURES = ("log_n", "log_m", "average_degree", "log_max_degree", "degree_cv",
                 "log_degeneracy", "directed", "weighted", "bipartite_ratio",
                 "log_free_gpu_memory", "gpu_busy")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def held_out(fingerprint):
    """A permanent graph split, independent of rewards and collection order."""
    return int(hashlib.sha256(("backend-holdout-v1:" + fingerprint).encode()).hexdigest()[:16], 16) % 5 == 0


def cholesky(matrix):
    n = len(matrix)
    if not 1 <= n <= MAX_DIMENSIONS or any(len(row) != n for row in matrix):
        raise ValueError("Invalid posterior dimensions")
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            if (not finite(matrix[i][j]) or not finite(matrix[j][i])
                    or not math.isclose(matrix[i][j], matrix[j][i], rel_tol=1e-9, abs_tol=1e-9)):
                raise ValueError("Posterior matrix must be finite and symmetric")
            value = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if value <= 0:
                    raise ValueError("Posterior matrix is not positive definite")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    return lower


def solve_lower(lower, vector):
    result = []
    for i, value in enumerate(vector):
        result.append((value - sum(lower[i][j] * result[j] for j in range(i))) / lower[i][i])
    return result


def solve_spd(lower, vector):
    result = solve_lower(lower, vector)
    for i in range(len(result) - 1, -1, -1):
        result[i] = (result[i] - sum(lower[j][i] * result[j] for j in range(i + 1, len(result)))) / lower[i][i]
    return result


def gpu_context(hardware):
    # Hardware features always describe physical GPU 1, including CPU benchmark
    # rows, so different heads observe the same machine context. This does not
    # grant a GPU lease; feasibility remains a separate mandatory gate.
    return next((g for g in hardware.get("gpus", []) if g.get("index") == 1), {})


def context_values(row, parameters_schema):
    features, hardware = row["graph_features"], row["hardware"]
    gpu = gpu_context(hardware)

    def number(value, *, log=False):
        if type(value) is bool:
            value = int(value)
        if value is None:
            return None
        if not finite(value) or abs(value) > 1e100 or log and value < 0:
            raise ValueError("Invalid aggregate context")
        return math.log1p(value) if log else float(value)

    utilization, processes = gpu.get("utilization_percent"), gpu.get("other_processes")
    busy = None if utilization is None and processes is None else bool((utilization or 0) > 0 or (processes or 0) > 0)
    values = dict(log_n=number(features.get("n"), log=True), log_m=number(features.get("m"), log=True),
        average_degree=number(features.get("average_degree")), log_max_degree=number(features.get("max_degree"), log=True),
        degree_cv=number(features.get("degree_cv")), log_degeneracy=number(features.get("degeneracy"), log=True),
        directed=number(features.get("directed")), weighted=number(features.get("weighted")),
        bipartite_ratio=number(features.get("bipartite_ratio")),
        log_free_gpu_memory=number(gpu.get("free_memory_bytes"), log=True), gpu_busy=number(busy),
        isolated_execution=float(bool(row.get("execution_isolated", False))))
    categories = {"gpu_model": gpu.get("model") or "unknown"}
    supplied = row.get("parameters", {})
    for name, schema in parameters_schema.items():
        value = supplied.get(name, schema.get("default"))
        kind = schema.get("kind", schema.get("type"))
        if isinstance(value, dict) and value.get("redacted"):
            continue
        if kind in {"integer", "number", "boolean"}:
            values["parameter:" + name] = number(value)
        elif kind in {"array", "object"}:
            values["parameter_count:" + name] = number(value.get("count") if isinstance(value, dict) else None)
        elif schema.get("choices"):
            categories["parameter:" + name] = value if value in schema["choices"] else "unknown"
    return values, categories


def make_encoder(rows, parameter_schema):
    observed = [context_values(row, parameter_schema) for row in rows]
    empty, empty_categories = context_values({"graph_features": {}, "hardware": {}}, parameter_schema)
    numeric = sorted(empty)
    categories = {key: sorted({"unknown", value, *(c.get(key, "unknown") for _, c in observed)})
                  for key, value in empty_categories.items()}
    for name, schema in parameter_schema.items():
        if schema.get("choices") and schema.get("kind", schema.get("type")) == "string":
            categories["parameter:" + name] = sorted({"unknown", *schema["choices"]})
    encoder = dict(version=ENCODER_VERSION, parameters=parameter_schema, numeric=numeric, categories=categories)
    vectors = [raw_vector(encoder, row) for row in rows]
    width = len(raw_vector(encoder, {"graph_features": {}, "hardware": {}}))
    if width + 1 > MAX_DIMENSIONS:
        raise ValueError("Operation has too many context dimensions")
    means = [statistics.mean(v[i] for v in vectors) if vectors else 0.0 for i in range(width)]
    scales = [math.sqrt(statistics.mean((v[i] - means[i]) ** 2 for v in vectors)) if vectors else 1.0 for i in range(width)]
    encoder.update(means=means, scales=[v if v > 1e-12 else 1.0 for v in scales],
                   feature_names=[name + suffix for name in numeric for suffix in ("", ":missing")]
                   + [key + "=" + value for key, choices in categories.items() for value in choices])
    return encoder


def raw_vector(encoder, row):
    values, categories = context_values(row, encoder["parameters"])
    result = [value for name in encoder["numeric"] for value in
              (values.get(name) or 0.0, float(values.get(name) is None))]
    for name, choices in encoder["categories"].items():
        value = categories.get(name, "unknown")
        if value not in choices:
            value = "unknown"
        result.extend(float(value == choice) for choice in choices)
    return result


def vector(encoder, row):
    values = raw_vector(encoder, row)
    if len(values) != len(encoder["means"]) or len(values) != len(encoder["scales"]):
        raise ValueError("Invalid feature scaler")
    result = [1.0]
    for value, mean, scale in zip(values, encoder["means"], encoder["scales"]):
        if not finite(mean) or not finite(scale) or scale <= 0:
            raise ValueError("Invalid feature scaler")
        result.append((value - mean) / scale)
    if not all(finite(v) and abs(v) <= 1e100 for v in result):
        raise ValueError("Invalid standardized context")
    return result


def runtime_observation(row):
    if (row.get("is_evaluation") is not False or row.get("source") not in {"application", "benchmark"}
            or row.get("execution_started", True) is not True):
        return None
    if row.get("outcome") == "completed" and not row.get("censored"):
        duration = row.get("runtime_seconds")
    elif row.get("outcome") == "timeout" and row.get("censored"):
        duration = row.get("timeout_seconds")
        duration = TIMEOUT_PENALTY * duration if finite(duration) else None
    else:
        return None
    return -math.log(max(duration, 1e-6)) if finite(duration) and duration > 0 else None


def prior_head(width, center):
    variance = [25.0, *([4.0] * (width - 1))]
    covariance = [[variance[i] if i == j else 0.0 for j in range(width)] for i in range(width)]
    return dict(mean=[center, *([0.0] * (width - 1))], covariance=covariance,
                completed_count=0, timeout_count=0, run_count=0, completed_max=None, benchmark_range=None)


def fit(operation, rows, backend_ids, parameter_schema, implementation):
    """Fit training graphs only. Callers retain held-out graphs for comparison."""
    all_rows = [r for r in rows if r.get("operation") == operation
                and r.get("implementation_sha256") == implementation and r.get("is_evaluation") is False
                and r.get("source") in {"application", "benchmark"}
                and r.get("chosen_backend") in backend_ids and not held_out(r["graph_features"]["snapshot_fingerprint"])]
    eligible = [(r, runtime_observation(r)) for r in all_rows]
    eligible = [(r, y) for r, y in eligible if y is not None]
    encoder = make_encoder([r for r, _ in eligible], parameter_schema)
    center = statistics.median(y for _, y in eligible) if eligible else -math.log(60)
    width = len(encoder["means"]) + 1
    heads = {}
    for backend in backend_ids:
        head = prior_head(width, center)
        precision = [[(0.04 if i == 0 else 0.25) if i == j else 0.0 for j in range(width)] for i in range(width)]
        target = [0.04 * center, *([0.0] * (width - 1))]
        for row, y in eligible:
            if row["chosen_backend"] != backend:
                continue
            x = vector(encoder, row)
            for i in range(width):
                target[i] += x[i] * y
                for j in range(width):
                    precision[i][j] += x[i] * x[j]
        lower = cholesky(precision)
        head["mean"] = solve_spd(lower, target)
        columns = [solve_spd(lower, [float(i == j) for i in range(width)]) for j in range(width)]
        head["covariance"] = [[columns[j][i] for j in range(width)] for i in range(width)]
        observed = [r for r in all_rows if r["chosen_backend"] == backend and r.get("execution_started", True)]
        completed = [r for r in observed if r["outcome"] == "completed" and runtime_observation(r) is not None]
        benchmarks = [r for r in observed if r["source"] == "benchmark"]
        head.update(completed_count=len(completed), timeout_count=sum(r["outcome"] == "timeout" for r in observed),
                    run_count=len(observed),
                    completed_max={key: max(r["graph_features"][key] for r in completed) for key in ("n", "m")} if completed else None,
                    benchmark_range={key: [min(r["graph_features"][key] for r in benchmarks),
                                          max(r["graph_features"][key] for r in benchmarks)] for key in ("n", "m")} if benchmarks else None)
        heads[backend] = head
    return dict(schema_version=MODEL_SCHEMA, operation=operation, implementation_sha256=implementation,
                encoder=encoder, heads=heads, prior_center=center, noise_variance=1.0,
                training_rows=len(eligible), training_data_sha256=digest(sorted(
                    (r["run_id"], r.get("observed_implementation_sha256", r["implementation_sha256"]), y,
                     vector(encoder, r)) for r, y in eligible)),
                observed_implementations=dict(Counter(r.get("observed_implementation_sha256", r["implementation_sha256"])
                                                      for r, _ in eligible)),
                training_snapshots=sorted({r["graph_features"]["snapshot_fingerprint"] for r, _ in eligible}),
                outcome_counts=dict(Counter(r["outcome"] for r, _ in eligible)), timeout_penalty=TIMEOUT_PENALTY)


def predict(model, row, backend_ids, *, seed):
    if model["schema_version"] != MODEL_SCHEMA or model["encoder"]["version"] != ENCODER_VERSION:
        raise ValueError("Unsupported runtime model")
    x = vector(model["encoder"], row)
    rng, predictions = random.Random(seed), {}
    for backend in sorted(backend_ids):
        head = model["heads"].get(backend) or prior_head(len(x), model["prior_center"])
        mean, covariance = head["mean"], head["covariance"]
        if len(mean) != len(x) or not all(finite(value) for value in mean) or len(covariance) != len(x):
            raise ValueError("Invalid posterior mean")
        lower = cholesky(covariance)
        projected = [sum(lower[i][j] * x[i] for i in range(j, len(x))) for j in range(len(x))]
        variance = max(0.0, sum(v * v for v in projected))
        expectation = sum(a * b for a, b in zip(mean, x))
        uncertainty = math.sqrt(variance + model["noise_variance"])
        # A draw of x^T beta is exactly a scalar Normal draw; allocating a whole
        # coefficient sample is unnecessary for a single contextual decision.
        sampled = rng.gauss(expectation, math.sqrt(variance))
        def duration(log_seconds):
            return math.exp(max(math.log(1e-6), min(math.log(1e12), log_seconds)))
        predictions[backend] = dict(p50_seconds=duration(-expectation),
            p90_seconds=duration(-expectation + 1.2815515655446004 * uncertainty),
            sampled_value=sampled, reward_mean=expectation, reward_std=math.sqrt(variance),
            prior_only=head["completed_count"] + head["timeout_count"] == 0)
    return predictions
