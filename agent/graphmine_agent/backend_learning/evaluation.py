"""Measured, graph-held-out comparisons. Missing counterfactuals stay missing."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .linear import held_out, predict
from .policy import decide, size_allows_exploration


def measured_cases(rows, card, implementation):
    groups, skipped = defaultdict(list), Counter()
    admitted = [b["id"] for b in card["backends"] if b.get("verified")]
    for row in rows:
        if (row.get("source") == "benchmark" and row.get("is_evaluation") is False
                and row.get("operation") == card["id"] and row.get("implementation_sha256") == implementation
                and row.get("comparison_id")):
            groups[row["comparison_id"]].append(row)
    cases = []
    for identifier, group in sorted(groups.items()):
        by_backend = {b: [r for r in group if r.get("requested_backend") == b] for b in admitted}
        if any(not attempts for attempts in by_backend.values()):
            skipped["incomplete_backend_coverage"] += 1
            continue
        eligible, excluded = [], {}
        for backend, attempts in by_backend.items():
            native = [next((c for c in r["candidates"] if c["id"] == backend), {}) for r in attempts]
            if all(c.get("native_feasible") is False for c in native):
                excluded[backend] = "native_input_infeasible"
            elif not any(c.get("feasible") is True for c in native):
                excluded[backend] = "memory_or_admission_infeasible"
            else:
                eligible.append(backend)
        if len(eligible) < 2:
            skipped["fewer_than_two_feasible_backends"] += 1
            continue
        costs, worst, failures = {}, {}, {}
        for backend in eligible:
            attempts = by_backend[backend]
            measured = [r["runtime_seconds"] if r["outcome"] == "completed" and not r.get("censored")
                        else max(r["timeout_seconds"], r.get("runtime_seconds") or 0) for r in attempts]
            if not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in measured):
                raise ValueError("Invalid measured comparison duration")
            costs[backend], worst[backend] = statistics.median(measured), max(measured)
            failures[backend] = sum(r["outcome"] != "completed" for r in attempts) / len(attempts)
        successful = [b for b in eligible if any(r["outcome"] == "completed" for r in by_backend[b])]
        if not successful:
            skipped["no_completed_oracle"] += 1
            continue
        oracle = min(successful, key=lambda b: (costs[b], b))
        context = by_backend.get("cpp", group)[0]
        legacy = next((b["id"] for b in card["backends"] if b["device"] == "gpu" and b["id"] in eligible),
                      "cpp" if "cpp" in eligible else None)
        if legacy is None:
            skipped["legacy_unavailable"] += 1
            continue
        cases.append(dict(comparison_id=identifier, context=context, eligible=eligible, excluded=excluded,
            costs=costs, worst_costs=worst, failures=failures, oracle=oracle, legacy=legacy,
            fingerprint=context["graph_features"]["snapshot_fingerprint"],
            timeout=max(r["timeout_seconds"] for r in group)))
    return cases, dict(skipped)


def shadow_progress(rows, operation, implementation, *, now=None):
    now = now or datetime.now(timezone.utc)
    observed = [r for r in rows if r.get("operation") == operation and r.get("source") == "application"
                and r.get("is_evaluation") is False and r.get("implementation_sha256") == implementation
                and r.get("selection_mode") == "shadow" and r.get("model_version")
                and r.get("shadow_choice") and r.get("execution_started")]
    decisions = {r.get("decision_id", r["run_id"]) for r in observed}
    stamps = [datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) for r in observed]
    age = max(0.0, (now - min(stamps)).total_seconds() / 86400) if stamps else 0.0
    return dict(runs=len(decisions), elapsed_days=age, ready=len(decisions) >= 200 or age >= 14,
                failure_rate=sum(r["outcome"] != "completed" for r in observed) / len(observed) if observed else None)


def compare(model, rows, card, *, seed=1729, exploration_budget=0.1, max_explore_ratio=1.5,
            exploration_enabled=True, now=None, _diagnostic=False):
    cases, skipped = measured_cases(rows, card, model["implementation_sha256"])
    training = [c for c in cases if not held_out(c["fingerprint"])]
    validation = cases if _diagnostic else [c for c in cases if held_out(c["fingerprint"])]
    if not _diagnostic:
        assert not set(model["training_snapshots"]) & {c["fingerprint"] for c in validation}
    admitted = [b["id"] for b in card["backends"] if b.get("verified")]
    # Select the single-backend baseline using training graphs only. An
    # incompatible backend receives the failure penalty, not a silent fallback.
    fixed = min(admitted, key=lambda b: (statistics.mean(c["costs"].get(b, c["timeout"]) for c in training), b)) if training else None
    measurements, exploratory_costs, selections = [], [], []
    explored = 0
    for index, case in enumerate(validation):
        predictions = predict(model, case["context"], case["eligible"], seed=seed + index)
        candidates = [{**b, "feasible": b["id"] in case["eligible"]} for b in card["backends"]]
        decision = decide(candidates, case["context"], model=model, mode="bandit", live_allowed=True,
            seed=seed + index, exploration_enabled=exploration_enabled, exploration_budget=exploration_budget,
            max_explore_ratio=max_explore_ratio,
            reserve=lambda: {"allowed": explored < math.floor(index * exploration_budget)})
        chosen = decision["chosen_backend"]
        explored += decision["reason"] == "explore"
        best = min(case["eligible"], key=lambda b: (predictions[b]["p50_seconds"], b))
        possible = [best, *(b for b in case["eligible"] if b != best and exploration_enabled
            and predictions[b]["p50_seconds"] <= max_explore_ratio * predictions[best]["p50_seconds"]
            and size_allows_exploration(model["heads"].get(b, {}), case["context"]["graph_features"]))]
        oracle = case["costs"][case["oracle"]]
        selections.append(dict(comparison_id=case["comparison_id"], snapshot_fingerprint=case["fingerprint"],
            chosen=chosen, reason=decision["reason"], oracle=case["oracle"],
            regret=case["costs"][chosen] / oracle,
            exploration_worst_regret=max(case["worst_costs"][b] for b in possible) / oracle))
        measurements.append(dict(selected=case["costs"][chosen], greedy=case["costs"][best],
            legacy=case["costs"][case["legacy"]],
            fastest_average=case["costs"].get(fixed, case["timeout"]) if fixed else None,
            oracle=oracle, failure_rate=case["failures"][chosen],
            legacy_failure_rate=case["failures"][case["legacy"]],
            fastest_average_failure_rate=case["failures"].get(fixed, 1),
            oracle_failure_rate=case["failures"][case["oracle"]],
            accurate=math.isclose(case["costs"][chosen], oracle, rel_tol=1e-9),
            selected_worst_regret=case["worst_costs"][chosen] / oracle))
        exploratory_costs.append(max(case["costs"][b] for b in possible) - case["costs"][best])
    metrics = None
    if measurements:
        count = len(measurements)
        # The live daily budget can concentrate exploration on expensive cases.
        # Bound its held-out mean by charging the largest possible premiums.
        extras = sorted(exploratory_costs, reverse=True)[:math.ceil(count * exploration_budget)] if exploration_enabled else []
        upper = (sum(m["greedy"] for m in measurements) + sum(extras)) / count
        metrics = dict(selection_accuracy=statistics.mean(m["accurate"] for m in measurements),
            mean_regret=statistics.mean(s["regret"] for s in selections),
            worst_regret=max(m["selected_worst_regret"] for m in measurements),
            exploration_worst_regret=max(s["exploration_worst_regret"] for s in selections),
            failure_rate=statistics.mean(m["failure_rate"] for m in measurements),
            baseline_failure_rates={key: statistics.mean(m[key + "_failure_rate"] for m in measurements)
                                    for key in ("legacy", "fastest_average", "oracle")},
            mean_seconds={key: statistics.mean(m[key] for m in measurements) if key != "fastest_average" or fixed else None
                          for key in ("selected", "greedy", "legacy", "fastest_average", "oracle")},
            exploration_mean_seconds_upper_bound=upper)
    if _diagnostic:
        return dict(purpose="Descriptive warm-start fit check; includes training graphs and never opens the live gate",
                    measured_graphs=len({c["fingerprint"] for c in validation}), measured_comparisons=len(validation),
                    metrics=metrics, selections=selections)
    held_out_count = len({c["fingerprint"] for c in validation})
    enough = held_out_count >= 5 and len({c["fingerprint"] for c in training}) >= 2 and fixed is not None
    beats = bool(enough and metrics
        and metrics["exploration_mean_seconds_upper_bound"] < metrics["mean_seconds"]["legacy"]
        and metrics["exploration_mean_seconds_upper_bound"] < metrics["mean_seconds"]["fastest_average"]
        and max(metrics["worst_regret"], metrics["exploration_worst_regret"]) <= 1.5)
    progress = shadow_progress(rows, card["id"], model["implementation_sha256"], now=now)
    return dict(schema_version=1, operation=card["id"], implementation_sha256=model["implementation_sha256"],
        method="Fixed-seed constrained Thompson choices on permanent held-out snapshots; conservative exploration envelope",
        failure_cost="A failed attempt costs max(timeout_seconds, runtime_seconds); medians include failures, worst regret includes every measured repetition",
        held_out_graphs=held_out_count, held_out_comparisons=len(validation), training_comparisons=len(training),
        skipped_comparisons=skipped, fastest_average_backend=fixed, metrics=metrics, selections=selections,
        shadow=progress, held_out_gate_passed=beats, live_ready=beats and progress["ready"],
        insufficient_evidence=not enough,
        warm_start_diagnostics=compare(model, rows, card, seed=seed, exploration_budget=exploration_budget,
            max_explore_ratio=max_explore_ratio, exploration_enabled=exploration_enabled, now=now, _diagnostic=True),
        configuration=dict(seed=seed, exploration_budget=exploration_budget, max_explore_ratio=max_explore_ratio,
                           exploration_enabled=exploration_enabled))
