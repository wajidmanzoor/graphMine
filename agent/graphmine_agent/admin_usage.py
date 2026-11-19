"""Sixty-second cached UTC aggregates from operational events only."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .admin_summary import percentile
from .identity import AccountError


def aggregate(rows, days, start):
    questions = [r for r in rows if r["type"] == "question"]
    calculations = [r for r in rows if r["type"] == "calculation"]
    errors = Counter(r["details"].get("code") or r["outcome"] for r in rows if r["type"] == "error")
    measured = [r for r in questions if type(r["details"].get("tokens")) is int]
    reasoning = [r for r in measured if type(r["details"].get("reasoning_tokens")) is int]
    token_sum = sum(r["details"]["tokens"] for r in measured)
    durations = [r["duration_ms"] for r in questions]
    work = questions + calculations
    failures = sum(r["outcome"] in {"failed", "error", "interrupted"} for r in work)
    summary = {"active_users": len({r["user_id"] for r in rows if r["user_id"] and (r["type"] in {"question", "calculation"} or r["type"] == "sign_in" and r["outcome"] == "ok")}),
               "questions": len(questions), "calculations": len(calculations),
               "tokens": token_sum if len(measured) == len(questions) else None, "tokens_recorded": token_sum,
               "tokens_reason": "Some questions have no provider token usage" if len(measured) != len(questions) else None,
               "reasoning_share": sum(r["details"]["reasoning_tokens"] for r in reasoning) / token_sum if token_sum and len(reasoning) == len(questions) else None,
               "reasoning_reason": "Reasoning-token usage was not reported for every question" if len(reasoning) != len(questions) else "No tokens recorded" if not token_sum else None,
               "answer_median_ms": percentile(durations, .5), "answer_p95_ms": percentile(durations, .95),
               "error_rate": failures / len(work) if work else None, "failed_work": failures,
               "top_error": errors.most_common(1)[0][0] if errors else None}
    daily = []
    for i in range(days):
        day = start + timedelta(days=i)
        day_rows = [r for r in rows if day.timestamp() <= r["ts"] < day.timestamp() + 86400]
        values = [r["duration_ms"] for r in day_rows if r["type"] == "question"]
        daily.append({"day": day.date().isoformat(), "questions": sum(r["type"] == "question" for r in day_rows),
                      "calculations": sum(r["type"] == "calculation" for r in day_rows),
                      "median_ms": percentile(values, .5), "p95_ms": percentile(values, .95)})
    times = Counter()
    for row in questions:
        for stage, value in row["details"].get("stage_ms", {}).items():
            if isinstance(value, (int, float)) and value >= 0:
                label = "Explanation" if stage in {"analyst", "explanation"} else "Clarify" if stage == "clarify" else "Routing calls"
                times[label] += value / 1000
        wait = row["details"].get("model_queue_ms")
        if isinstance(wait, (int, float)):
            times["Model queue wait"] += wait / 1000
    calculation_times = [r["duration_ms"] for r in calculations if isinstance(r["duration_ms"], (int, float))]
    if calculation_times:
        times["Calculations"] = sum(calculation_times) / 1000
    tokens = defaultdict(lambda: {"tokens": 0, "missing": 0})
    for row in questions:
        name = row["username"] or "Deleted account"
        value = row["details"].get("tokens")
        if type(value) is int:
            tokens[name]["tokens"] += value
        else:
            tokens[name]["missing"] += 1
    datasets, missing_datasets = Counter(), 0
    for row in calculations:
        names = row["details"].get("datasets") or ([row["details"]["dataset"]] if row["details"].get("dataset") else [])
        if names:
            datasets.update(set(names))
        else:
            missing_datasets += 1
    corrections = [r for r in questions if type(r["details"].get("routing_corrected")) is bool]
    return {"summary": summary, "daily": daily, "time_breakdown": [{"stage": k, "seconds": round(v, 3)} for k, v in times.items()],
            "timing_reason": "Recorded totals across calls and calculations; not a decomposition of one answer. Model queue time is unavailable for older calls.",
            "errors": [{"type": k, "count": v} for k, v in errors.most_common()],
            "tokens_by_user": [{"user": k, **v} for k, v in sorted(tokens.items(), key=lambda item: -item[1]["tokens"])],
            "datasets": [{"dataset": k, "count": v} for k, v in datasets.most_common()],
            "datasets_missing": missing_datasets,
            "routing_corrections": sum(r["details"]["routing_corrected"] for r in corrections) if corrections else None,
            "routing_reason": "No structured routing feedback has been recorded" if not corrections else f"Feedback recorded for {len(corrections)} questions"}


def usage(runtime, days=14):
    if days not in {7, 14, 30, 90}:
        raise AccountError("Choose 7, 14, 30 or 90 days", "invalid_range", 422)
    now = runtime.accounts.clock()
    cache = getattr(runtime.accounts, "_admin_usage_cache", {})
    if days in cache and now - cache[days]["generated_at"] < 60:
        return cache[days]
    start = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    previous_end = now - days * 86400
    with runtime.database._connect() as db:
        rows = [dict(r) for r in db.execute("SELECT e.*,a.username FROM events e LEFT JOIN accounts a ON a.id=e.user_id WHERE e.ts>=? AND e.ts<=?", (previous_start.timestamp(), now))]
        recorded = db.execute("SELECT value FROM admin_metadata WHERE key='recording_since'").fetchone()
    for row in rows:
        row["details"] = json.loads(row.pop("details_json"))
    current = aggregate([r for r in rows if r["ts"] >= start.timestamp()], days, start)
    previous = aggregate([r for r in rows if r["ts"] <= previous_end], days, previous_start)
    result = {**current, "previous": previous["summary"], "generated_at": now, "days": days, "start": start.timestamp(), "end": now,
              "previous_start": previous_start.timestamp(), "previous_end": previous_end, "timezone": "UTC", "cache_seconds": 60,
              "recording_since": float(recorded[0]) if recorded else None,
              "error_rate_definition": "Failed or interrupted questions and calculations divided by all recorded questions and calculations. Cancellations are excluded from failures."}
    cache[days] = result
    runtime.accounts._admin_usage_cache = cache
    return result
