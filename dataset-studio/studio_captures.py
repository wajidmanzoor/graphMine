"""GraphMine conversations as one private Dataset Studio dataset per account.

GraphMine writes every question, model call and piece of feedback to
``<store>/captures/users/<account id>/`` (see ``graphmine_agent.capture``).
This module

- signs people in with their GraphMine account, reading the account store
  read-only, and
- turns one account's captures into a dataset in the reusable layout: one
  training row per successful model call, holding the exact messages the model
  received and its raw output as the target. The user's feedback, the answer
  they saw and the data the question ran on travel with each row for review.

Captured calls never change, so rows are only ever appended: byte offsets that
an open dataset already indexed stay valid. Only the account that asked the
questions may open its dataset; there is no admin override.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "graphmine-captures__"
FORMAT = "graphmine-studio-captures-v1"
STAGE_SCHEMAS = {"route": "AnalyticsRoute", "plan": "AnalyticsPlan", "answer": "AnalyticsAnswer"}
# Planning stages run on the planner model; the answer is the analyst's.
ADAPTERS = {"route": "planner", "plan": "planner", "answer": "analyst"}
STAGE_ORDER = ("route", "plan", "answer")
FEEDBACK_FIELDS = ("id", "category", "rating", "what_went_wrong", "expected_behavior", "source", "created_at")


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:128] or "_"


def dataset_key(account_id: str) -> str:
    return PREFIX + _safe(account_id)


def key_owner(key: str) -> str | None:
    """The account a capture dataset belongs to, or None for any other dataset."""
    return key[len(PREFIX):] if key.startswith(PREFIX) else None


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class GraphMineAccounts:
    """GraphMine sign-in and capture location, from the GraphMine data root."""

    def __init__(self, store: Path):
        self.store = store.resolve()
        self.database = self.store / "agent.sqlite3"
        self.captures = Path(os.environ.get("GRAPHMINE_CAPTURE_ROOT") or self.store / "captures").resolve()
        self._dummy = None

    @property
    def available(self) -> bool:
        return self.database.is_file()

    def verify(self, username: str, password: str) -> dict | None:
        """The GraphMine account for these credentials, or None. Never writes the store."""
        from graphmine_agent.accounts import password_hash, password_matches

        name = (username or "").strip().lower()
        row = None
        if self.available and name:
            with closing(sqlite3.connect(f"file:{self.database}?mode=ro", uri=True, timeout=10)) as db:
                try:
                    columns = {item[1] for item in db.execute("PRAGMA table_info(accounts)")}
                    access = " AND studio_access=1 AND must_change_password=0 AND login_disabled=0" if "studio_access" in columns else ""
                    row = db.execute(
                        "SELECT id, username, password_hash, disabled FROM accounts WHERE username=?" + access, (name,)
                    ).fetchone()
                except sqlite3.OperationalError:
                    row = None
        if self._dummy is None:
            self._dummy = password_hash("unavailable-account-password")
        # Check a hash even for unknown names so timing does not reveal which exist.
        ok = password_matches(password or "", row[2] if row else self._dummy)
        if not row or not ok or row[3]:
            return None
        return {"id": row[0], "username": row[1]}

    def active(self, account_id: str) -> bool:
        """Whether the account still exists and is enabled in GraphMine."""
        if not self.available:
            return False
        with closing(sqlite3.connect(f"file:{self.database}?mode=ro", uri=True, timeout=10)) as db:
            try:
                columns = {item[1] for item in db.execute("PRAGMA table_info(accounts)")}
                access = " AND studio_access=1 AND must_change_password=0 AND login_disabled=0" if "studio_access" in columns else ""
                row = db.execute("SELECT disabled FROM accounts WHERE id=?" + access, (account_id,)).fetchone()
            except sqlite3.OperationalError:
                return False
        return bool(row) and not row[0]

    def account_dir(self, account_id: str) -> Path:
        return self.captures / "users" / _safe(account_id)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # A line still being written; it is read next time.
    return rows


def _content(call: dict) -> str | None:
    try:
        content = call["response"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) else None


def _reasoning(call: dict) -> str | None:
    try:
        message = call["response"]["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None
    text = message.get("reasoning") or message.get("reasoning_content")
    return text if isinstance(text, str) else None


def _turns(records: list[dict]) -> dict[str, dict]:
    """Everything one question produced, keyed by its turn."""
    turns: dict[str, dict] = {}

    def turn(turn_id):
        return turns.setdefault(turn_id, {"calls": [], "feedback": [], "question": None, "asked_at": None,
                                          "answer": None, "workflow": None, "dataset": None})

    datasets, workflows, inputs = {}, {}, {}
    for record in records:
        kind, data, turn_id = record.get("kind"), record.get("data") or {}, record.get("turn_id")
        if kind == "dataset.used":
            datasets[data.get("file_id")] = {k: data.get(k) for k in ("name", "sha256", "file_id")}
        elif kind == "workflow.saved" and turn_id:
            workflows[turn_id] = data
        if not turn_id:
            continue
        if kind == "workflow.chat" and data.get("role") == "user" and turn(turn_id)["question"] is None:
            turn(turn_id)["question"] = data.get("message")
            turn(turn_id)["asked_at"] = record.get("at")
            inputs[turn_id] = [ref.get("file_id") for ref in (data.get("inputs") or {}).values()
                               if isinstance(ref, dict)]
        elif kind == "model.call":
            turn(turn_id)["calls"].append(record)
        elif kind == "workflow.answer" and not data.get("pending"):
            turn(turn_id)["answer"] = {"lead": data.get("lead"), "source": data.get("source"),
                                       "facts": [f for f in data.get("facts") or []
                                                 if f.get("id") in (data.get("fact_ids") or [])]}
        elif kind == "feedback.saved":
            turn(turn_id)["feedback"].append({k: data.get(k) for k in FEEDBACK_FIELDS})
    for turn_id, value in turns.items():
        workflow = workflows.get(turn_id)
        if workflow:
            plan = (workflow.get("validation") or {}).get("plan") or {}
            value["workflow"] = {"id": workflow.get("id"), "status": workflow.get("status"),
                                 "operations": [s.get("operation") for s in plan.get("steps") or []]}
        used = [datasets[f] for f in inputs.get(turn_id, []) if f in datasets]
        value["dataset"] = used[0] if used else None
    return turns


def materialize(accounts: GraphMineAccounts, account_id: str, dest: Path, *, owner_name: str | None = None) -> dict:
    """Bring ``dest`` up to date with the account's captures; returns its summary.

    New calls are appended to the adapter files; the index is rewritten so
    feedback given after an earlier sync reaches every row of its question.
    """
    source = accounts.account_dir(account_id) / "sessions"
    logs = sorted(source.glob("*.jsonl")) if source.is_dir() else []
    fingerprint = [[p.name, p.stat().st_size, int(p.stat().st_mtime_ns)] for p in logs]
    state_path = dest / "capture-state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    if state.get("fingerprint") == fingerprint and state.get("format") == FORMAT and (dest / "sft-index.jsonl").is_file():
        return state
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest.chmod(0o700)
    (dest / "sft").mkdir(exist_ok=True)
    (dest / "schemas").mkdir(exist_ok=True)
    known: dict[str, dict] = {}
    index_path = dest / "sft-index.jsonl"
    if index_path.is_file():
        for item in _read_jsonl(index_path):
            known[item["id"]] = item
    counts: dict[str, int] = {}
    for item in known.values():
        counts[item["file"]] = max(counts.get(item["file"], 0), item["row"] + 1)
    index, skipped = [], 0
    for log in logs:
        records = _read_jsonl(log)
        deleted = any(r.get("kind") == "session.deleted" for r in records)
        title = next((((r.get("data") or {}).get("title")) for r in records if r.get("kind") == "session.deleted"), None)
        for turn_id, turn in _turns(records).items():
            calls = [c for c in turn["calls"] if (c.get("data") or {}).get("stage") in STAGE_SCHEMAS]
            for call in calls:
                data = call["data"]
                content = _content(data)
                if data.get("outcome") != "ok" or content is None:
                    skipped += 1
                    continue
                stage = data["stage"]
                schemas = {}
                for name in ("target_schema", "output_schema"):
                    schema = data.get(name) or (
                        ((data.get("request") or {}).get("response_format") or {}).get("json_schema", {}).get("schema")
                        if name == "target_schema" else None)
                    if schema:
                        sha = _digest(schema)
                        path = dest / "schemas" / f"{sha}.json"
                        if not path.is_file():
                            path.write_text(json.dumps(schema, ensure_ascii=False))
                        schemas[name] = sha
                item = known.get(call["id"])
                if item is None:
                    file = f"sft/{ADAPTERS[stage]}/train.jsonl"
                    row = {"messages": list(data["request"]["messages"]) + [{"role": "assistant", "content": content}]}
                    target = dest / file
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    item = {"id": call["id"], "file": file, "row": counts.get(file, 0), "row_sha256": _digest(row)}
                    counts[file] = item["row"] + 1
                item.update(
                    schema=STAGE_SCHEMAS[stage],
                    group=turn_id,
                    source=(turn["dataset"] or {}).get("name"),
                    capture={
                        "session_id": call.get("session_id"),
                        "turn_id": turn_id,
                        "stage": stage,
                        "stage_index": STAGE_ORDER.index(stage),
                        "question": turn["question"],
                        "asked_at": turn["asked_at"],
                        "owner": owner_name or (call.get("owner") or {}).get("username"),
                        "model": (data.get("request") or {}).get("model"),
                        "seconds": data.get("seconds"),
                        "deployment_id": call.get("deployment_id"),
                        "reasoning": _reasoning(data),
                        "feedback": turn["feedback"],
                        "answer": turn["answer"],
                        "workflow": turn["workflow"],
                        "dataset": turn["dataset"],
                        "conversation_deleted": deleted,
                        "conversation_title": title,
                        "schemas": schemas,
                    },
                )
                index.append(item)
    # Rows of a question are listed together, in the order the stages ran.
    index.sort(key=lambda i: (i["capture"]["asked_at"] or "", i["group"], i["capture"]["stage_index"], i["row"]))
    temporary = index_path.with_suffix(".tmp")
    temporary.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in index), encoding="utf-8")
    temporary.replace(index_path)
    state = {"format": FORMAT, "fingerprint": fingerprint, "rows": len(index), "skipped_calls": skipped,
             "questions": len({i["group"] for i in index}),
             "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    state_path.write_text(json.dumps(state) + "\n")
    return state


class SchemaCache:
    """Captured contracts by hash; shared by every open capture dataset."""

    def __init__(self):
        self._schemas: dict[Path, dict] = {}
        self._lock = threading.Lock()

    def get(self, folder: Path, sha: str | None) -> dict | None:
        if not sha:
            return None
        path = folder / "schemas" / f"{_safe(sha)}.json"
        with self._lock:
            if path not in self._schemas:
                try:
                    self._schemas[path] = json.loads(path.read_text())
                except (OSError, ValueError):
                    return None
            return self._schemas[path]


def check_output(stage: str, output, target_schema: dict | None, output_schema: dict | None) -> str | None:
    """Why an edited target would be rejected, checked as the planner checks the model."""
    import jsonschema

    if target_schema is None:
        return "The captured call has no output contract to check against"
    def problem(schema, value):
        # The most specific failure, not "the whole plan is invalid".
        error = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(schema).iter_errors(value))
        if error is None:
            return None
        location = "/".join(str(p) for p in error.absolute_path)
        return f"{error.message[:400]}{f' (at {location})' if location else ''}"

    try:
        found = problem(target_schema, output)
        if found or stage != "plan":
            return found
        from graphmine_agent.analytics_planning import decoded_plan

        return problem(output_schema, decoded_plan(output)) if output_schema is not None else None
    except (ValueError, TypeError, KeyError) as error:
        return str(error)[:600]
