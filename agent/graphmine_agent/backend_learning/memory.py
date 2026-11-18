"""Small nonnegative memory fits, scoped to operation, implementation and hardware.

These estimates supplement the unchanged workflow admission reservation. A fit
needs 20 completed, non-evaluation observations and held-out graph validation.
Outside its observed range, or on any load error, use the admission estimate.
"""

from __future__ import annotations

import hashlib
import itertools
import fcntl
import json
import math
import re
import os
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from ..analytics_scheduler import estimate_memory
from .storage import atomic_json, utc_now, read_rows

MODEL_SCHEMA = 1
MIN_COMPLETED = 20
MARGIN = 1.25  # Sampling can miss peaks; never publish a bare least-squares fit.
_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def coordinates(features, output_estimate):
    values = [1.0, features.get("n"), features.get("m"), output_estimate]
    if not all(_number(v) for v in values):
        raise ValueError("Memory features must be finite and nonnegative")
    return values


def profile_key(operation, backend, features, parameters, hardware, implementation):
    device = backend.get("device")
    gpu = next((g for g in hardware.get("gpus", [])
                if g.get("index") == hardware.get("leased_gpu_index")), {})
    model = hardware.get("cpu_model") if device == "cpu" else gpu.get("model")
    if not model or not re.fullmatch(r"[0-9a-f]{64}", implementation or ""):
        raise ValueError("Memory fit requires hardware and implementation provenance")
    return _digest(dict(operation=operation, backend=backend["id"], device=device,
                        hardware_model=model, implementation=implementation,
                        input_kind=features.get("input_kind"), directed=features.get("directed"),
                        weighted=features.get("weighted"), parameters=parameters))


def effective_rows(rows):
    records = {r["run_id"]: r for r in rows}
    superseded = {r["supersedes"] for r in records.values() if r.get("supersedes")}
    return [r for key, r in records.items() if key not in superseded]


def _solve(matrix, vector):
    """Pivoted elimination for an at-most-four-dimensional active set."""
    work = [list(row) + [rhs] for row, rhs in zip(matrix, vector)]
    for i in range(len(work)):
        pivot = max(range(i, len(work)), key=lambda k: abs(work[k][i]))
        if abs(work[pivot][i]) < 1e-12:
            return None
        work[i], work[pivot] = work[pivot], work[i]
        divisor = work[i][i]
        work[i] = [v / divisor for v in work[i]]
        for j in range(len(work)):
            if j != i:
                multiplier = work[j][i]
                work[j] = [a - multiplier * b for a, b in zip(work[j], work[i])]
    return [row[-1] for row in work]


def nonnegative_fit(x, y):
    """Exact NNLS active-set enumeration (16 subsets), with scaled columns."""
    scales = [max(1, max(row[i] for row in x)) for i in range(4)]
    scaled = [[v / scale for v, scale in zip(row, scales)] for row in x]
    best, error = [0.0] * 4, sum(v * v for v in y)
    for count in range(1, 5):
        for active in itertools.combinations(range(4), count):
            gram = [[sum(row[i] * row[j] for row in scaled) for j in active] for i in active]
            target = [sum(row[i] * value for row, value in zip(scaled, y)) for i in active]
            solved = _solve(gram, target)
            if solved is None or any(v < -1e-8 for v in solved):
                continue
            weights = [0.0] * 4
            for i, value in zip(active, solved):
                weights[i] = max(0, value) / scales[i]
            loss = sum((actual - sum(a * b for a, b in zip(row, weights))) ** 2
                       for row, actual in zip(x, y))
            if loss < error:
                best, error = weights, loss
    return best


def _fit_group(completed, failures):
    result = dict(completed_count=len(completed), oom_count=len(failures), validated=False,
                  validation_reason="insufficient_completed_runs", coefficients=None,
                  oom_floors=failures)
    if len(completed) < MIN_COMPLETED:
        return result
    # Whole snapshots stay on one side of the split. Repeated benchmark runs
    # cannot leak a graph into both training and validation.
    fingerprints = sorted({r["snapshot"] for r in completed}, key=lambda s: _digest(s))
    if len(fingerprints) < 5:
        result["validation_reason"] = "insufficient_distinct_graphs"
        return result
    held_out = set(fingerprints[-max(1, len(fingerprints) // 5):])
    training = [r for r in completed if r["snapshot"] not in held_out]
    validation = [r for r in completed if r["snapshot"] in held_out]
    weights = nonnegative_fit([r["x"] for r in training], [r["peak"] for r in training])
    residual = max(0, max(r["peak"] - sum(a * b for a, b in zip(r["x"], weights)) for r in training))
    weights[0] += residual
    weights = [value * MARGIN for value in weights]
    ratios = [r["peak"] / max(1, sum(a * b for a, b in zip(r["x"], weights))) for r in validation]
    bounds = [[min(r["x"][i] for r in training), max(r["x"][i] for r in training)] for i in range(4)]
    valid = max(ratios) <= 1.0
    result.update(coefficients=weights, bounds=bounds, validated=valid,
                  validation_reason="passed" if valid else "held_out_underprediction",
                  training_count=len(training), held_out_count=len(validation),
                  held_out_max_actual_to_prediction=max(ratios), safety_margin=MARGIN)
    return result


def fit_models(rows):
    """Return derived documents; never generate observations to reach a threshold."""
    groups, skipped = defaultdict(lambda: [[], []]), 0
    for row in effective_rows(rows):
        if row.get("is_evaluation") is not False or row.get("source") not in {"application", "benchmark"}:
            continue
        if row.get("outcome") not in {"completed", "oom"}:
            continue
        try:
            backend = next(c for c in row["candidates"] if c["id"] == row["chosen_backend"])
            if not _NAME.fullmatch(backend["id"]) or not backend.get("admitted") or not backend.get("compiled"):
                raise ValueError("Unadmitted backend")
            features, hardware = row["graph_features"], row["hardware"]
            x = coordinates(features, row["output_estimate"])
            key = profile_key(row["operation"], backend, features, row["parameters"], hardware,
                              row["implementation_sha256"])
            snapshot = features["snapshot_fingerprint"]
            if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
                raise ValueError("Missing snapshot provenance")
            peak = row["peak_memory"].get("process_rss_bytes" if backend["device"] == "cpu" else "gpu_bytes")
            if backend["device"] == "gpu" and hardware.get("leased_gpu_index") != 1:
                raise ValueError("Unpermitted GPU")
            if row["outcome"] == "completed":
                if not _number(peak) or peak <= 0 or row.get("censored"):
                    raise ValueError("Missing completed peak measurement")
                if set(row.get("telemetry_warnings", [])) & {
                    "peak_sampler_unavailable", "peak_sampler_failed", "gpu_peak_sample_failed"
                }:
                    raise ValueError("Incomplete peak measurement")
                groups[backend["id"], key][0].append(dict(x=x, peak=peak, snapshot=snapshot))
            else:
                free = hardware.get("free_ram_bytes") if backend["device"] == "cpu" else next(
                    g["free_memory_bytes"] for g in hardware["gpus"] if g["index"] == 1)
                if not _number(free) or free <= 0:
                    raise ValueError("OOM observation has no memory bound")
                groups[backend["id"], key][1].append(dict(snapshot=snapshot, output_estimate=x[-1],
                    lower_bound_bytes=max(free, peak if _number(peak) else 0)))
        except (KeyError, TypeError, ValueError, StopIteration):
            skipped += 1
    models = {}
    for (backend, key), (completed, failures) in sorted(groups.items()):
        document = models.setdefault(backend, dict(schema_version=MODEL_SCHEMA, backend=backend, profiles={}))
        document["profiles"][key] = _fit_group(completed, failures)
    for document in models.values():
        document["version"] = utc_now() + "-" + _digest(document)[:12]
    return models, skipped


def save_models(data_dir, models):
    # A correction can invalidate the last training row for a backend. Publish
    # an empty derived document instead of retaining stale coefficients.
    for path in (Path(data_dir) / "memory_models").glob("*.json"):
        if _NAME.fullmatch(path.stem) and path.stem not in models:
            atomic_json(path, dict(schema_version=MODEL_SCHEMA, backend=path.stem,
                                   profiles={}, version=utc_now() + "-empty"))
    for backend, model in models.items():
        if not _NAME.fullmatch(backend):
            raise ValueError("Invalid backend model name")
        atomic_json(Path(data_dir) / "memory_models" / (backend + ".json"), model)


@contextmanager
def _fit_lock(data_dir):
    directory = Path(data_dir) / "memory_models"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / ".fit.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def rebuild(data_dir):
    with _fit_lock(data_dir):
        fitted, skipped = fit_models(read_rows(data_dir))
        save_models(data_dir, fitted)
        return fitted, skipped


def note_oom(data_dir, row):
    """Called by the asynchronous writer after the authoritative append/fsync."""
    if row.get("outcome") != "oom" or row.get("is_evaluation") is not False:
        return
    updates, _ = fit_models([row])
    with _fit_lock(data_dir):
        for backend, update in updates.items():
            path = Path(data_dir) / "memory_models" / (backend + ".json")
            try:
                saved = json.loads(path.read_text())
                if saved["schema_version"] != MODEL_SCHEMA or saved["backend"] != backend:
                    raise ValueError("Invalid memory model")
            except (OSError, ValueError, KeyError, TypeError):
                saved = dict(schema_version=MODEL_SCHEMA, backend=backend, profiles={})
            for key, new in update["profiles"].items():
                previous = saved["profiles"].get(key)
                if previous is None:
                    saved["profiles"][key] = new
                    continue
                floors = previous.setdefault("oom_floors", [])
                for floor in new["oom_floors"]:
                    if floor not in floors:
                        floors.append(floor)
                previous["oom_count"] = len(floors)
            saved["version"] = utc_now() + "-oom-" + _digest(saved)[:12]
            atomic_json(path, saved)


def predict_memory(operation, backend, features, parameters, hardware, *, output_estimate,
                   implementation, data_dir):
    fallback = estimate_memory({"steps": [{"budget": {"max_output_items": output_estimate}}]},
                               features["input_bytes"])
    value, version, reason = fallback, None, "conservative_default"
    try:
        if not _NAME.fullmatch(backend["id"]):
            raise ValueError("Invalid backend")
        path = Path(data_dir) / "memory_models" / (backend["id"] + ".json")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Memory model is too large")
        model = json.loads(path.read_text())
        if model["schema_version"] != MODEL_SCHEMA or model["backend"] != backend["id"]:
            raise ValueError("Wrong memory model")
        key = profile_key(operation, backend, features, parameters, hardware, implementation)
        profile = model["profiles"].get(key)
        if profile is None:
            return value, version, "unseen_memory_context"
        x = coordinates(features, output_estimate)
        if profile["validated"] is True and profile["completed_count"] >= MIN_COMPLETED:
            if (profile["validation_reason"] != "passed" or profile["held_out_count"] < 1
                    or not _number(profile["held_out_max_actual_to_prediction"])
                    or profile["held_out_max_actual_to_prediction"] > 1
                    or profile["safety_margin"] < MARGIN or profile["training_count"] < 4):
                raise ValueError("Memory validation metadata is invalid")
            weights, bounds = profile["coefficients"], profile["bounds"]
            if len(weights) != 4 or not all(_number(v) for v in weights):
                raise ValueError("Invalid coefficients")
            if len(bounds) != 4 or any(len(b) != 2 or not all(_number(v) for v in b) or b[0] > b[1] for b in bounds):
                raise ValueError("Invalid fit range")
            if all(low <= v <= high for v, (low, high) in zip(x, bounds)):
                value, version, reason = max(1, sum(a * b for a, b in zip(x, weights))), model["version"], "validated_fit"
            else:
                reason = "outside_memory_fit_range"
        for failure in profile.get("oom_floors", []):
            if failure["snapshot"] == features["snapshot_fingerprint"] and failure["output_estimate"] == output_estimate:
                if not _number(failure["lower_bound_bytes"]):
                    raise ValueError("Invalid OOM memory bound")
                value = max(value, MARGIN * failure["lower_bound_bytes"])
                version, reason = model["version"], "observed_oom_lower_bound"
        if not _number(value):
            raise ValueError("Invalid memory prediction")
        return value, version, reason
    except FileNotFoundError:
        return fallback, None, "conservative_default"
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError):
        return fallback, None, "invalid_memory_model"
