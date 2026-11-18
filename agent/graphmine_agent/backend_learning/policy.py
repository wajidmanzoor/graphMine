"""Constrained Thompson decisions; this module never admits a native backend."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .feasibility import legacy_choice
from .linear import finite, predict
from .memory import effective_rows
from .storage import atomic_json

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")


def size_allows_exploration(head, features):
    size = {k: features.get(k) for k in ("n", "m")}
    if not all(type(v) is int and v >= 0 for v in size.values()):
        return False
    completed = head.get("completed_max")
    if completed and all(size[k] <= completed[k] for k in size):
        return True
    bounds = head.get("benchmark_range")
    # No measured range means no speculative enlargement, even for a new head.
    return bool(head.get("run_count", 0) < 5 and bounds
                and all(bounds[k][0] <= size[k] <= bounds[k][1] for k in size))


def reserve_exploration(data_dir, operation, decision_id, mode, fraction, *, now=None):
    """Reserve numerator slots atomically against authoritative logged runs.

    In-flight and crashed reservations never inflate the denominator. A lost
    telemetry row can only reduce exploration. Fallback attempts share a
    decision_id and count once. Benchmark and evaluation rows count neither.
    """
    if not NAME.fullmatch(operation) or mode not in {"shadow", "bandit"} or not 0 <= fraction <= 1:
        raise ValueError("Invalid exploration ledger request")
    now = now or datetime.now(timezone.utc)
    directory = Path(data_dir) / "reports/exploration" / now.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{operation}-{mode}.json"
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {"reserved_decisions": []}
        rows = []
        day = Path(data_dir) / "runs" / now.strftime("%Y/%m/%d")
        for log in sorted(day.glob("runs-*.jsonl")):
            for line in log.read_text().splitlines():
                try:
                    row = json.loads(line)
                    if (row.get("operation") == operation and row.get("source") == "application"
                            and row.get("is_evaluation") is False):
                        rows.append(row)
                except (ValueError, TypeError, AttributeError):
                    # Malformed or incomplete lines never grant budget.
                    continue
        rows = effective_rows(rows)
        decisions = {r.get("decision_id", r["run_id"]) for r in rows}
        explored = {r.get("decision_id", r["run_id"]) for r in rows
                    if (r.get("selection_mode") == mode and
                        (r.get("shadow_reason") if mode == "shadow" else r.get("reason")) == "explore")}
        explored.update(state["reserved_decisions"])
        limit = math.floor(len(decisions) * fraction + 1e-12)
        allowed = decision_id in explored or len(explored) < limit
        if allowed:
            explored.add(decision_id)
            atomic_json(path, {"reserved_decisions": sorted(explored)})
        return dict(allowed=allowed, logged_decisions=len(decisions), reserved_explorations=len(explored), limit=limit)
    finally:
        os.close(fd)


def decide(candidates, row, *, model=None, model_version=None, mode="legacy", live_allowed=False,
           requested_backend="auto", requested_device="auto", seed=None,
           exploration_enabled=True, exploration_budget=0.10, max_explore_ratio=1.5,
           reserve=None):
    """Return a decision over the already filtered native candidate set only."""
    if mode not in {"legacy", "shadow", "bandit"} or not 1 <= max_explore_ratio <= 1.5:
        raise ValueError("Invalid backend policy")
    feasible = [c["id"] for c in candidates if c.get("feasible") is True]
    legacy = legacy_choice(candidates, requested_backend)
    if legacy is None:
        raise ValueError("No feasible backend")
    result = dict(chosen_backend=legacy, native_backend=requested_backend,
        reason="forced" if requested_device != "auto" or requested_backend != "auto" else "legacy_auto",
        selection_mode=mode, model_version=model_version, predictions={}, selection_seed=None,
        shadow_choice=None, shadow_reason=None, policy_warning=None, exploration={})
    if mode == "legacy":
        return result
    if model is None:
        result["policy_warning"] = "runtime_model_unavailable"
        return result
    seed = secrets.randbits(63) if seed is None else seed
    predictions = predict(model, row, feasible, seed=seed)
    result.update(predictions=predictions, selection_seed=seed)
    if requested_backend != "auto":
        return result  # Never replace an explicitly named native backend.
    best = min(feasible, key=lambda b: (predictions[b]["p50_seconds"], b))
    proposed = max(feasible, key=lambda b: (predictions[b]["sampled_value"], b))
    reason, choice = ("only_option", best) if len(feasible) == 1 else ("exploit", best)
    blocked = []
    if len(feasible) > 1 and proposed != best:
        if not exploration_enabled:
            blocked.append("kill_switch")
        if predictions[proposed]["p50_seconds"] > max_explore_ratio * predictions[best]["p50_seconds"]:
            blocked.append("predicted_slowdown")
        if not size_allows_exploration(model["heads"].get(proposed, {}), row["graph_features"]):
            blocked.append("unmeasured_size")
        if not blocked:
            budget = reserve() if reserve else {"allowed": False}
            result["exploration"]["daily_budget"] = budget
            if not budget["allowed"]:
                blocked.append("daily_budget")
        if not blocked:
            choice, reason = proposed, "explore"
    result["exploration"].update(proposed_backend=proposed, best_p50_backend=best,
                                  blocked_by=blocked, fraction=exploration_budget)
    if mode == "shadow" or not live_allowed:
        result.update(shadow_choice=choice, shadow_reason=reason, selection_mode="shadow")
        if mode == "bandit" and not live_allowed:
            result["policy_warning"] = "rollout_gate_not_met"
        return result  # Native auto ordering and its budget remain unchanged.
    result.update(chosen_backend=choice, native_backend=choice, reason=reason)
    return result


def timeout_seconds(prediction, *, minimum, remaining, cap):
    if not 0 < minimum <= 1800 or not finite(remaining) or not finite(cap):
        raise ValueError("Invalid attempt deadline")
    p90 = prediction.get("p90_seconds") if prediction else None
    proposed = max(minimum, 3 * p90) if finite(p90) and p90 > 0 else cap
    return max(0.0, min(1800, remaining, cap, proposed))
