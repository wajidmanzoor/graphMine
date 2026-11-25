"""Measured overview values. Unknown historical telemetry remains unknown."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import admin_events


def percentile(values, fraction):
    values = sorted(v for v in values if isinstance(v, (float, int)))
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def queues(runtime):
    now = runtime.accounts.clock()
    with runtime.database._connect() as db:
        counts = dict(db.execute("SELECT kind,count(*) FROM account_leases WHERE expires_at>? GROUP BY kind", (now,)))
    result = {}
    for kind, lease_kind, limit in (("model", "model", runtime.settings.max_model_calls), ("job", "execution", runtime.settings.account_running_jobs)):
        waiting = runtime.accounts.waiting.get(lease_kind, [])
        starts = [runtime.accounts.wait_started[t[1]] for t in waiting if t[1] in runtime.accounts.wait_started]
        result[kind] = {"running": counts.get(lease_kind, 0), "limit": limit, "waiting": len(waiting),
                        "oldest_wait_seconds": max(0, now - min(starts)) if starts else 0 if not waiting else None,
                        "wait_reason": "Queue-entry time is unavailable" if waiting and not starts else None}
    return result


def overview(runtime):
    now = runtime.accounts.clock()
    today = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (today - timedelta(days=13)).timestamp()
    with runtime.database._connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM events WHERE ts>=? AND ts<=?", (start, now))]
        count = db.execute("SELECT count(*) FROM accounts WHERE login_disabled=0").fetchone()[0]
        active = db.execute("SELECT count(*) FROM accounts a WHERE a.disabled=0 AND a.login_disabled=0 AND a.graphmine_access=1 AND a.last_active>=? AND EXISTS (SELECT 1 FROM account_sessions s WHERE s.user_id=a.id AND s.expires_at>?)", (now - 300, now)).fetchone()[0]
        recorded = db.execute("SELECT value FROM admin_metadata WHERE key='recording_since'").fetchone()
        conversations = db.execute("SELECT count(*) FROM sessions").fetchone()[0]
    for row in rows:
        row["details"] = json.loads(row["details_json"])
    current = [r for r in rows if r["ts"] >= today.timestamp()]
    questions = [r for r in current if r["type"] == "question"]
    calculations = [r for r in current if r["type"] == "calculation"]
    errors = [r for r in current if r["type"] == "error"]
    token_values = [r["details"].get("tokens") for r in questions]
    known_tokens = [n for n in token_values if isinstance(n, int)]
    error_counts = Counter(r["details"].get("code", r["outcome"]) for r in errors)
    per_day = Counter(datetime.fromtimestamp(r["ts"], timezone.utc).date().isoformat() for r in rows if r["type"] == "question")
    workflows = runtime.analytics._all()
    problems = Counter(step["problem"] for w in workflows for step in w.get("validation", {}).get("plan", {}).get("steps", []) if w.get("status") == "completed")
    return {"now": now, "timezone": "UTC", "recording_since": float(recorded[0]) if recorded else None,
            "active_now": active, "accounts": count, "questions_today": len(questions),
            "questions_yesterday": sum(r["type"] == "question" and today.timestamp() - 86400 <= r["ts"] < today.timestamp() for r in rows),
            "calculations_today": len(calculations), "calculations_failed": sum(r["outcome"] == "failed" for r in calculations),
            "answer_median_ms": percentile([r["duration_ms"] for r in questions], .5),
            "answer_p95_ms": percentile([r["duration_ms"] for r in questions], .95),
            "errors_today": len(errors), "top_error": error_counts.most_common(1)[0][0] if errors else None,
            "tokens_today": sum(known_tokens) if len(known_tokens) == len(questions) else None,
            "tokens_recorded": sum(known_tokens), "tokens_reason": "Some questions have no provider token usage" if len(known_tokens) != len(questions) else None,
            "token_pool": runtime.settings.server_daily_tokens, "queues": queues(runtime),
            "recent": admin_events.query(runtime.database, limit=4)["items"],
            "questions_per_day": [{"day": (today - timedelta(days=13-i)).date().isoformat(), "questions": per_day[(today - timedelta(days=13-i)).date().isoformat()]} for i in range(14)],
            "problems": [{"problem": k, "count": v} for k, v in problems.most_common()],
            "saved_analyses": sum(w.get("status") == "completed" for w in workflows),
            "conversations": conversations, "failed_analyses": sum(w.get("status") == "failed" for w in workflows)}
