"""Agent admission using authoritative native support and measured free memory."""

from __future__ import annotations

import math

from .memory import estimate_candidate_memory


def feasible(problem, backend, features, parameters, hardware):
    """Return (ok, reason) for a candidate enriched by native preflight.

    Backend-specific input support and declared limits come from the native API.
    This function only applies generic limits, lease and memory rules to them.
    """
    if not backend.get("compiled"):
        return False, "not_compiled"
    if not backend.get("admitted"):
        return False, "not_admitted"
    if backend.get("native_feasible", backend.get("feasible")) is not True:
        return False, backend.get("native_infeasible_reason", backend.get("infeasible_reason")) or "native_preflight_failed"
    limits = backend.get("limits")
    if not isinstance(limits, dict) or not {"n", "m"} <= limits.keys():
        return False, "native_limits_unavailable"
    for name in ("n", "m"):
        maximum, actual = limits[name], features.get(name)
        if type(maximum) is not int or maximum < 0 or type(actual) is not int or actual < 0:
            return False, "invalid_size_limit"
        if actual > maximum:
            return False, "size_or_index_limit"
    if backend.get("device") == "cpu":
        free = hardware.get("free_ram_bytes")
    elif backend.get("device") == "gpu":
        if hardware.get("leased_gpu_index") != 1:
            return False, "gpu_1_lease_required"
        gpu = next((g for g in hardware.get("gpus", []) if g.get("index") == 1), {})
        free = gpu.get("free_memory_bytes")
    else:
        return False, "unknown_device"
    prediction = backend.get("predicted_peak_memory_bytes")
    if type(free) not in (float, int) or not math.isfinite(free) or free <= 0:
        return False, "free_memory_unavailable"
    if type(prediction) not in (float, int) or not math.isfinite(prediction) or prediction < 0:
        return False, "memory_prediction_unavailable"
    safety = hardware.get("backend_memory_safety", 0.8)
    if type(safety) not in (float, int) or not 0 < safety <= 0.8:
        return False, "invalid_memory_safety"
    if prediction > safety * free:
        return False, "predicted_memory_exceeds_free_memory"
    return True, None


def filter_candidates(problem, candidates, features, parameters, hardware, *, output_estimate,
                      implementation, data_dir):
    result = []
    for native in candidates:
        candidate = dict(native, native_feasible=native.get("feasible"),
                         native_infeasible_reason=native.get("infeasible_reason"))
        predicted, reason = estimate_candidate_memory(problem, candidate, features, parameters, hardware,
            output_estimate=output_estimate, implementation=implementation, data_dir=data_dir)
        candidate.update(predicted_peak_memory_bytes=predicted, memory_estimate_reason=reason)
        ok, reason = feasible(problem, candidate, features, parameters, hardware)
        candidate.update(feasible=ok, infeasible_reason=reason)
        result.append(candidate)
    return result


def native_choice(candidates, requested_backend="auto"):
    if requested_backend != "auto":
        return next((c["id"] for c in candidates if c["id"] == requested_backend and c["feasible"]), None)
    return next((c["id"] for c in candidates if c["device"] == "gpu" and c["feasible"]),
                next((c["id"] for c in candidates if c["id"] == "cpp" and c["feasible"]), None))
