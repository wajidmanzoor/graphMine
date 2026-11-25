"""One masked shared policy with exact behavior propensities and fixed controls."""
from __future__ import annotations

import fcntl
import json
import math
import os
import random
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ..calculation_limits import DEFAULT_EXECUTION_TIMEOUT_SECONDS
from .feasibility import native_choice
from .shared import digest, finite, preferences
from .storage import atomic_json

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")


def distribution(scores, temperature=1., floor=.02):
    if not finite(temperature) or temperature <= 0 or not finite(floor) or not 0 <= floor <= 1:
        raise ValueError("Invalid softmax controls")
    if not scores or any(not finite(value) for value in scores.values()):
        raise ValueError("Invalid backend preferences")
    peak = max(scores.values())
    values = {key: math.exp((value - peak) / temperature) for key, value in scores.items()}
    total = sum(values.values())
    return {key: (1 - floor) * value / total + floor / len(values) for key, value in values.items()}


def sample(probabilities, seed):
    return random.Random(seed).choices(list(probabilities), weights=list(probabilities.values()), k=1)[0]


def measured_ranges(model, row):
    return [r for r in model.get("controls", {}).get(row["problem"], [])
            if r["parameters_sha256"] == digest(row.get("parameters", {}))]


def size_allows_exploration(model, row):
    ranges = measured_ranges(model, row)
    shape = row["graph_features"]
    return bool(ranges) and all(type(shape.get(k)) is int and
        min(r[k][0] for r in ranges) <= shape[k] <= max(r[k][1] for r in ranges) for k in ("n", "m"))


def control_range(model, row):
    ranges = measured_ranges(model, row) or model.get("controls", {}).get(row["problem"], [])
    if not ranges:
        return None
    shape = row["graph_features"]
    def distance(r):
        return sum(max(0., math.log1p(r[k][0]) - math.log1p(shape[k]),
                       math.log1p(shape[k]) - math.log1p(r[k][1])) for k in ("n", "m"))
    # Use the slowest measured bound on a tie, including different parameter settings.
    return min(ranges, key=lambda r: (distance(r), -r["slowest_seconds"]))


def timeout_seconds(*, remaining=None, default=DEFAULT_EXECUTION_TIMEOUT_SECONDS):
    """A fixed attempt allowance; training timings never shorten execution."""
    if not finite(default) or default <= 0:
        raise ValueError("Invalid attempt timeout configuration")
    if remaining is not None and (not finite(remaining) or remaining < 0):
        raise ValueError("Invalid remaining deadline")
    return min(default, remaining) if remaining is not None else default


def reserve_exploration(data_dir, problem, decision_id, mode, fraction, *, probabilities, best, seed, now=None):
    """Budget gating and the draw share a lock so the logged probability is exact.

    A rejected budget changes the distribution BEFORE drawing, including when
    the original softmax would have drawn the greedy backend. Fallbacks do not
    reserve; crashes retain reservations and cannot inflate the denominator.
    """
    if not NAME.fullmatch(problem) or mode not in {"shadow", "bandit"} or not 0 <= fraction <= 1:
        raise ValueError("Invalid exploration ledger request")
    now = now or datetime.now(timezone.utc)
    directory = Path(data_dir) / "reports/exploration" / now.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{problem}-{mode}.json"
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {"reserved_decisions": []}
        records = {}
        day = Path(data_dir) / "runs" / now.strftime("%Y/%m/%d")
        for log in sorted(day.glob("runs-*.jsonl")):
            for line in log.read_text().splitlines():
                try:
                    row = json.loads(line)
                    if row.get("problem") == problem and row.get("source") == "application" and row.get("is_evaluation") is False:
                        records[row["run_id"]] = row
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
        superseded = {r["supersedes"] for r in records.values() if r.get("supersedes")}
        rows = [r for key, r in records.items() if key not in superseded]
        decisions = {r.get("decision_id", r["run_id"]) for r in rows}
        reserved = set(state["reserved_decisions"])
        reserved.update(r.get("decision_id", r["run_id"]) for r in rows if r.get("selection_mode") == mode
                        and r.get("shadow_reason" if mode == "shadow" else "backend_choice_reason") == "explore")
        limit = math.floor(len(decisions) * fraction + 1e-12)
        allowed = len(reserved) < limit
        actual = dict(probabilities) if allowed else {b: float(b == best) for b in probabilities}
        choice = sample(actual, seed)
        if choice != best:
            reserved.add(decision_id)
            atomic_json(path, {"reserved_decisions": sorted(reserved)})
        return dict(choice=choice, probabilities=actual, allowed=allowed,
                    logged_decisions=len(decisions), reserved_explorations=len(reserved), limit=limit)
    finally:
        os.close(fd)


def decide(candidates, row, *, model=None, model_version=None, mode="native", live_allowed=False,
           requested_backend="auto", requested_device="auto", seed=None,
           exploration_enabled=True, exploration_budget=.10, temperature=1., floor=.02, reserve=None):
    if mode not in {"native", "shadow", "bandit"}:
        raise ValueError("Unknown backend selection mode")
    eligible = [c for c in candidates if c.get("feasible") is True and
                (requested_device == "auto" or c["device"] == requested_device)]
    chosen = native_choice(eligible, requested_backend)
    if chosen is None:
        raise ValueError("No feasible backend for the requested backend/device")
    ids = [c["id"] for c in eligible]
    forced = requested_backend != "auto"
    result = dict(chosen_backend=chosen, native_backend=chosen, reason="forced" if forced or requested_device != "auto" else "native_rule",
        selection_mode="native", model_version=model_version, eligible_backends=ids,
        probabilities={b: float(b == chosen) for b in ids}, selection_probability=1.,
        selection_seed=None, shadow_choice=None, shadow_reason=None, shadow_probability=None,
        shadow_probabilities=None, policy_warning=None, exploration={}, context_features=None,
        cost_scale_seconds=None, failure_cost=None)
    if forced or len(ids) == 1 or mode == "native":
        if len(ids) == 1 and not forced and requested_device == "auto":
            result["reason"] = "only_option"
        return result
    if model is None:
        result["policy_warning"] = "shared_model_unavailable"
        return result
    scores = preferences(model, row, ids)
    best = max(ids, key=lambda b: scores[b])
    seed = secrets.randbits(63) if seed is None else seed
    proposed = distribution(scores, temperature, floor)
    blocked = []
    if not exploration_enabled:
        blocked.append("disabled")
    if not size_allows_exploration(model, row):
        blocked.append("unmeasured_size_or_parameters")
    if blocked:
        proposed = {b: float(b == best) for b in ids}
        choice = best
    elif reserve is not None:
        budget = reserve(probabilities=proposed, best=best, seed=seed)
        proposed, choice = budget["probabilities"], budget["choice"]
        result["exploration"]["daily_budget"] = {k: v for k, v in budget.items() if k not in {"choice", "probabilities"}}
        if not budget["allowed"]:
            blocked.append("daily_budget")
    else:
        # Online serving cannot spend an unaccounted budget. Offline evaluation
        # passes an explicit draw callback to measure the configured distribution.
        proposed, choice = {b: float(b == best) for b in ids}, best
        blocked.append("ledger_unavailable")
    reason = "exploit" if choice == best else "explore"
    bounds = control_range(model, row)
    from .shared import raw_features
    result.update(selection_seed=seed, context_features=raw_features(row, model["feature_schema"]).tolist(),
        cost_scale_seconds=bounds["fastest_seconds"] if bounds else None,
        failure_cost=model["training"]["failure_penalty"] * bounds["slowest_seconds"] / bounds["fastest_seconds"] if bounds else None)
    result["exploration"].update(best_backend=best, blocked_by=blocked, fraction=exploration_budget)
    if mode == "shadow" or not live_allowed:
        result.update(selection_mode="shadow", shadow_choice=choice, shadow_reason=reason,
                      shadow_probability=proposed[choice], shadow_probabilities=proposed)
        if mode == "bandit":
            result["policy_warning"] = "rollout_gate_not_met"
    else:
        result.update(chosen_backend=choice, native_backend=choice, reason="forced" if requested_device != "auto" else reason,
                      backend_choice_reason=reason, selection_mode="bandit",
                      probabilities=proposed, selection_probability=proposed[choice])
    return result
