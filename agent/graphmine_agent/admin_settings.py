"""Validated durable settings, shared by the admin API and service startup."""

import json
import time
from dataclasses import fields, replace
from threading import RLock

from .identity import AccountError, current_principal

THINKING_STAGES = ("family", "problem", "route", "clarify", "analyst")
MODEL_KEYS = {
    "GRAPHMINE_LLM_SLEEP_MODE": ("llm_sleep_mode", "bool", None, None, True),
    "GRAPHMINE_LLM_IDLE_SLEEP_MINUTES": ("llm_idle_sleep_minutes", "minutes", 10, 60, False),
    "GRAPHMINE_LLM_THINKING_STAGES": ("llm_thinking_stages", "stages", None, None, False),
}
CAPACITY_DEFINITIONS = (
    ("GRAPHMINE_MAX_MODEL_CALLS", "max_model_calls", 1, 16, False, "Language model", "Model calls at once", "How many model calls run together. Others wait in line.", ""),
    ("GRAPHMINE_LLM_MAX_NUM_SEQS", "llm_max_num_seqs", 1, 32, True, "Language model", "vLLM requests at once", "Must be at least Model calls at once. Needs a model restart.", ""),
    ("MODEL_QUEUE_SECONDS", "model_queue_seconds", 10, 600, False, "Language model", "Wait in line up to", "After this, the user is told the model is busy.", "s"),
    ("GRAPHMINE_SERVER_DAILY_TOKENS", "server_daily_tokens", 1, 2**53 - 1, False, "Language model", "Daily token pool for everyone", "The shared allowance retains its existing rolling 24-hour reset.", "tokens"),
    ("GRAPHMINE_ACCOUNT_RUNNING_JOBS", "account_running_jobs", 1, 16, False, "Calculations", "Running at once, all users", "Graph calculations on CPU and GPU together.", ""),
    ("GRAPHMINE_ACCOUNT_USER_RUNNING_JOBS", "account_user_running_jobs", 1, 4, False, "Calculations", "Running at once, per user", "Limits each person's admitted calculations.", ""),
    ("GRAPHMINE_ANALYTICS_CPU_WORKERS", "analytics_cpu_workers", 1, 16, False, "Calculations", "CPU workers", "Native workflow workers that run on the CPU.", ""),
    ("GRAPHMINE_ACCOUNT_JOB_SECONDS", "account_job_seconds", 30, 3600, False, "Calculations", "Time limit per calculation", "Longer new calculations are stopped and marked timed out.", "s"),
    ("GRAPHMINE_ACCOUNT_QUEUE_SECONDS", "account_queue_seconds", 30, 3600, False, "Calculations", "Wait in line up to", "A calculation that cannot start by then is refunded.", "s"),
    ("GRAPHMINE_ACCOUNT_DAILY_TOKENS", "account_daily_tokens", 1, 2**53 - 1, False, "Defaults for new users", "Daily tokens per user", "Used by accounts without an individual limit on the Users page.", "tokens"),
    ("GRAPHMINE_ACCOUNT_STORAGE_BYTES", "account_storage_bytes", 1, 2**53 - 1, False, "Defaults for new users", "Storage per user", "Uploads, saved inputs and results; individual limits take priority.", "bytes"),
    ("GRAPHMINE_ANALYTICS_MAX_INPUT_BYTES", "analytics_max_input_bytes", 1, 2**53 - 1, False, "Defaults for new users", "Largest upload", "Applies to uploads and analytics inputs. Storage quota still applies.", "bytes"),
    ("GRAPHMINE_BACKUP_KEEP", "backup_keep", 1, 365, False, "Retention", "Daily snapshots to keep", "Older scheduled snapshots are removed only after a verified backup.", "snapshots"),
    ("GRAPHMINE_ADMIN_EVENT_RETENTION_DAYS", "admin_event_retention_days", 1, 3650, False, "Retention", "Activity history", "Retention for operational events, independent of conversations.", "days"),
)
CAPACITY_KEYS = {key: (attribute, "integer", low, high, restart) for key, attribute, low, high, restart, *_ in CAPACITY_DEFINITIONS}
ALLOWLIST = {**MODEL_KEYS, **CAPACITY_KEYS}
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
        raise ValueError(f"{key} must be one of 10, 20 or 60 minutes." if kind == "minutes" else f"{key} must be a whole number from {low} to {high}.")
    return value


def load(settings, database):
    with database._connect() as db:
        initialize(db)
        changes = {ALLOWLIST[row[0]][0]: validate(row[0], json.loads(row[1]))
                   for row in db.execute("SELECT key,value FROM settings_overrides") if row[0] in ALLOWLIST}
    return replace(settings, **upload_aliases(changes))


def upload_aliases(changes):
    if "analytics_max_input_bytes" in changes:
        changes = {**changes, "account_upload_bytes": changes["analytics_max_input_bytes"], "max_upload_bytes": changes["analytics_max_input_bytes"]}
    return changes


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


def save(runtime, changes, *, keys=MODEL_KEYS, target="model", expected=None):
    with _save_lock:
        return _save(runtime, changes, keys=keys, target=target, expected=expected)


def _save(runtime, changes, *, keys, target, expected):
    if not changes or set(changes) - set(keys):
        raise ValueError("Supply at least one allowed setting.")
    checked = {key: validate(key, value) for key, value in changes.items()}
    current = load(runtime.settings, runtime.database)
    if expected is not None and any(k not in expected or expected[k] != values(current, keys)[k] for k in checked):
        raise AccountError("Settings changed since this page loaded. Reload and review the new values.", "settings_conflict", 409)
    proposed = replace(current, **upload_aliases({ALLOWLIST[k][0]: v for k, v in checked.items()}))
    if set(checked) & {"GRAPHMINE_MAX_MODEL_CALLS", "GRAPHMINE_LLM_MAX_NUM_SEQS"} and proposed.llm_max_num_seqs < proposed.max_model_calls:
        raise ValueError("vLLM requests at once must be at least Model calls at once.")
    if set(checked) & {"GRAPHMINE_ACCOUNT_DAILY_TOKENS", "GRAPHMINE_SERVER_DAILY_TOKENS"} and proposed.account_daily_tokens > proposed.server_daily_tokens:
        raise ValueError("The default daily token limit cannot exceed the shared token pool.")
    before, after = values(current, keys), values(proposed, keys)
    principal = current_principal.get()
    with runtime.database._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for key, value in checked.items():
            db.execute("INSERT INTO settings_overrides VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                       (key, json.dumps(value), principal.user_id if principal else None, time.time()))
        runtime.accounts._audit(db, "settings.updated", target, before=before, after=after)
    live = replace(runtime.settings, **upload_aliases({ALLOWLIST[k][0]: v for k, v in checked.items() if not ALLOWLIST[k][4]}))
    apply_live(runtime, live)
    return {"values": after, "restart_required": [k for k in checked if ALLOWLIST[k][4] and getattr(runtime.settings, ALLOWLIST[k][0]) != checked[k]]}


def capacity(runtime):
    desired = load(runtime.settings, runtime.database)
    defaults = {field.name: field.default for field in fields(runtime.settings)}
    return {"values": values(desired, CAPACITY_KEYS), "effective": values(runtime.settings, CAPACITY_KEYS),
            "rows": [{"key": key, "value": getattr(desired, attribute), "effective": getattr(runtime.settings, attribute),
                      "default": defaults[attribute], "minimum": low, "maximum": high, "restart": restart,
                      "section": section, "label": label, "description": description, "unit": unit}
                     for key, attribute, low, high, restart, section, label, description, unit in CAPACITY_DEFINITIONS]}


def thinking(settings, stage, payload):
    """An enabled switch preserves the provider's existing per-stage defaults."""
    if settings.llm_thinking_stages is not None and stage in THINKING_STAGES and stage not in settings.llm_thinking_stages:
        payload["reasoning_effort"] = "none"
        payload["chat_template_kwargs"] = {**payload.get("chat_template_kwargs", {}), "enable_thinking": False}
        payload.pop("thinking_token_budget", None)
