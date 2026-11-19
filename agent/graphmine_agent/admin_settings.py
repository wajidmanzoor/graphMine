"""Validated durable settings, shared by the admin API and service startup."""

import json
import time
from dataclasses import replace
from threading import RLock

from .identity import current_principal

THINKING_STAGES = ("family", "problem", "route", "clarify", "analyst")
MODEL_KEYS = {
    "GRAPHMINE_LLM_SLEEP_MODE": ("llm_sleep_mode", "bool", None, None, True),
    "GRAPHMINE_LLM_IDLE_SLEEP_MINUTES": ("llm_idle_sleep_minutes", "minutes", 10, 60, False),
    "GRAPHMINE_LLM_THINKING_STAGES": ("llm_thinking_stages", "stages", None, None, False),
}
ALLOWLIST = dict(MODEL_KEYS)
_save_lock = RLock()


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS settings_overrides (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by TEXT, updated_at REAL NOT NULL)")


def validate(key, value):
    if key not in ALLOWLIST:
        raise ValueError("This setting is not editable.")
    _, kind, low, high, _ = ALLOWLIST[key]
    if kind == "bool":
        if type(value) is not bool:
            raise ValueError(f"{key} must be true or false.")
    elif kind == "stages":
        if not isinstance(value, (list, tuple)) or any(x not in THINKING_STAGES for x in value) or len(set(value)) != len(value):
            raise ValueError("Choose distinct Family, Problem, Route, Clarify or Explanation steps.")
        value = tuple(value)
    elif type(value) is not int or not low <= value <= high or kind == "minutes" and value not in (10, 20, 60):
        raise ValueError(f"{key} must be one of 10, 20 or 60 minutes.")
    return value


def load(settings, database):
    with database._connect() as db:
        initialize(db)
        changes = {ALLOWLIST[row[0]][0]: validate(row[0], json.loads(row[1]))
                   for row in db.execute("SELECT key,value FROM settings_overrides") if row[0] in ALLOWLIST}
    return replace(settings, **changes)


def values(settings, keys=MODEL_KEYS):
    return {key: list(THINKING_STAGES) if getattr(settings, spec[0]) is None and spec[1] == "stages"
            else getattr(settings, spec[0]) for key, spec in keys.items()}


def apply_live(runtime, settings):
    """Replace the immutable config in known consumers; in-flight work keeps its snapshot."""
    for consumer in (runtime, runtime.accounts, runtime.graph_store, runtime.runner,
                     runtime.agent, runtime.agent.model, runtime.analytics,
                     runtime.analytics.scheduler, runtime.llm_power, runtime.database_pools):
        if hasattr(consumer, "settings"):
            consumer.settings = settings
    for manager in runtime.llm_power.managers.values():
        manager.idle_minutes = settings.llm_idle_sleep_minutes


def save(runtime, changes, *, keys=MODEL_KEYS):
    with _save_lock:
        return _save(runtime, changes, keys=keys)


def _save(runtime, changes, *, keys):
    if not changes or set(changes) - set(keys):
        raise ValueError("Supply at least one allowed setting.")
    checked = {key: validate(key, value) for key, value in changes.items()}
    current = load(runtime.settings, runtime.database)
    proposed = replace(current, **{ALLOWLIST[k][0]: v for k, v in checked.items()})
    before, after = values(current, keys), values(proposed, keys)
    principal = current_principal.get()
    with runtime.database._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for key, value in checked.items():
            db.execute("INSERT INTO settings_overrides VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                       (key, json.dumps(value), principal.user_id if principal else None, time.time()))
        runtime.accounts._audit(db, "settings.updated", "model", before=before, after=after)
    live = replace(runtime.settings, **{ALLOWLIST[k][0]: v for k, v in checked.items() if not ALLOWLIST[k][4]})
    apply_live(runtime, live)
    return {"values": after, "restart_required": [k for k in checked if ALLOWLIST[k][4] and getattr(runtime.settings, ALLOWLIST[k][0]) != checked[k]]}


def thinking(settings, stage, payload):
    """An enabled switch preserves the provider's existing per-stage defaults."""
    if settings.llm_thinking_stages is not None and stage in THINKING_STAGES and stage not in settings.llm_thinking_stages:
        payload["reasoning_effort"] = "none"
        payload["chat_template_kwargs"] = {**payload.get("chat_template_kwargs", {}), "enable_thinking": False}
        payload.pop("thinking_token_budget", None)
