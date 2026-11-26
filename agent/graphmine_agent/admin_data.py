"""Measured storage inventory, guarded cleanup, and the existing backup helpers."""

import hashlib
import json
import logging
import re
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from . import admin_lifecycle
from .identity import AccountError, current_principal
from .neo4j_records import require_visible, visible

storage_lock = RLock()
_logger = logging.getLogger(__name__)


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS admin_resource_access (kind TEXT NOT NULL,id TEXT NOT NULL,opened_at REAL NOT NULL,PRIMARY KEY(kind,id))")
    db.execute("CREATE TABLE IF NOT EXISTS admin_backup_checks (name TEXT PRIMARY KEY,verified_at REAL NOT NULL,manifest_hash TEXT NOT NULL,status TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS admin_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO admin_metadata VALUES ('resource_access_since',?)", (str(time.time()),))


def touch(database, kind, identifier):
    # Offline inspection/backup helpers must remain read-only. Only an
    # authenticated application access is an observed user open.
    if current_principal.get() is None:
        return
    with storage_lock, database._connect() as db:
        initialize(db)
        db.execute("INSERT INTO admin_resource_access VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET opened_at=excluded.opened_at", (kind, identifier, time.time()))


def timestamp(value):
    if isinstance(value, (int, float)):
        return value
    try:
        return datetime.fromisoformat(value).timestamp() if value else None
    except (ValueError, TypeError):
        return None


def strings(value):
    if isinstance(value, dict):
        yield from value.keys()
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def safe_path(runtime, path):
    root = runtime.settings.data_root.resolve()
    candidate = Path(path)
    resolved = candidate.resolve()
    if resolved == root or not resolved.is_relative_to(root) or candidate.is_symlink():
        raise AccountError("This stored path is outside the managed data directory.", "unsafe_path", 409)
    return candidate


def _ledger(db, runtime):
    db.execute("ATTACH DATABASE ? AS admin_workflows", (str(runtime.analytics.path),))


def busy_owners(db, runtime):
    actor = current_principal.get()
    # The administrator's cleanup POST itself owns one request lease. Ignore
    # that one lease, while retaining protection for their concurrent work.
    return {row[0] for row in db.execute(
        "SELECT user_id FROM account_leases WHERE expires_at>? GROUP BY user_id "
        "HAVING sum(kind!='request')>0 OR sum(kind='request')>CASE WHEN user_id=? THEN 1 ELSE 0 END",
        (runtime.accounts.clock(), actor.user_id if actor else ""))}


def _inventory(db, runtime):
    workflows = [json.loads(row[0]) for row in db.execute("SELECT document FROM admin_workflows.workflows")]
    files = [dict(row) for row in db.execute("SELECT f.id,f.session_id,f.payload,s.owner_id,a.username FROM files f JOIN sessions s ON s.id=f.session_id LEFT JOIN accounts a ON a.id=s.owner_id")]
    identifiers = {row["id"] for row in files}
    uses, last = defaultdict(set), {}
    protected_workflows = set()
    result_ids = {row[0] for row in db.execute("SELECT id FROM results")}
    result_ids.update(row[0] for row in db.execute("SELECT job_id FROM results"))
    result_ids.update(w["id"] for w in workflows)
    def add(document, label, when=None):
        for key in set(strings(document)) & identifiers:
            uses[key].add(label)
            if when:
                last[key] = max(last.get(key, 0), when)
    for work in workflows:
        shown = visible(work, runtime.settings)
        label = "Analysis " + work["id"] if shown else "Retained reference"
        when = timestamp(work.get("updated_at") or work.get("created_at")) if shown else None
        add(work.get("input_files", {}), label, when)
        add(work.get("input_provenance", {}), label, when)
        protected_workflows.update((set(strings(work.get("input_provenance", {}))) | set(strings(work.get("input_files", {})))) & result_ids)
    for row in db.execute("SELECT id,payload,updated_at FROM jobs"):
        document = json.loads(row[1])
        shown = visible(document, runtime.settings)
        add(document.get("plan", {}), "Calculation " + row[0] if shown else "Retained reference", timestamp(row[2]) if shown else None)
    for table, column, label in (("session_exploration", "document", "Saved view"), ("project_items", "metadata", "Project share"),
                                  ("dataset_versions", "metadata", "Saved snapshot"), ("workflow_templates", "document", "Saved template")):
        for row in db.execute(f"SELECT {column} FROM {table}"):
            value = json.loads(row[0])
            add(value, label if visible(value, runtime.settings) else "Retained reference")
            protected_workflows.update(set(strings(value)) & result_ids)
    for row in files:
        record = json.loads(row["payload"])
        shown = visible(record, runtime.settings)
        add(record.get("provenance", {}), "Snapshot " + record.get("original_name", row["id"]) if shown else "Retained reference", timestamp(record.get("created_at")) if shown else None)
        protected_workflows.update(set(strings(record.get("provenance", {}))) & result_ids)
    accesses = {(row[0], row[1]): row[2] for row in db.execute("SELECT kind,id,opened_at FROM admin_resource_access")}
    active = busy_owners(db, runtime)
    busy_sessions = {w["session_id"] for w in workflows if w["status"] in {"queued", "running"}}
    busy_sessions.update(row[0] for row in db.execute("SELECT session_id FROM jobs WHERE status IN ('queued','running','interpreting')"))
    result = []
    for row in files:
        record = json.loads(row["payload"])
        used = sorted(uses[row["id"]])
        busy = row["owner_id"] in active or row["session_id"] in busy_sessions
        opened = accesses.get(("file", row["id"]))
        try:
            safe_path(runtime, record["source_path"])
            managed = True
        except AccountError:
            managed = False
        result.append({"id": row["id"], "session_id": row["session_id"], "owner_id": row["owner_id"], "owner": row["username"],
                       "name": record.get("original_name", row["id"]), "size_bytes": record["size_bytes"], "sha256": record["sha256"],
                       "used_by": used, "analyses": sum(x.startswith(("Analysis ", "Calculation ")) for x in used),
                       "last_used": max(last.get(row["id"], 0), opened or 0) or None,
                       "deletable": managed and not used and not busy, "busy": busy, "managed": managed, "record": record})
    return result, workflows, protected_workflows, accesses


def inventory(runtime):
    with runtime.database._connect() as db:
        initialize(db)
        _ledger(db, runtime)
        files, workflows, protected, accesses = _inventory(db, runtime)
        users = [{"username": row[1], **runtime.accounts.storage_usage(row[0], db=db)} for row in db.execute("SELECT id,username FROM accounts WHERE login_disabled=0")]
        embedded = {
            "Saved inputs and snapshots": sum(db.execute(f"SELECT coalesce(sum({column}),0) FROM {table}").fetchone()[0] for table, column in (("dataset_versions", "size_bytes"), ("query_preview_blobs", "size_bytes"), ("project_items", "size_bytes"))),
            "Results": db.execute("SELECT coalesce(sum(length(CAST(payload AS BLOB))),0) FROM results").fetchone()[0],
            "Saved views": db.execute("SELECT coalesce(sum(length(CAST(document AS BLOB))),0) FROM session_exploration").fetchone()[0],
        }
        since = float(db.execute("SELECT value FROM admin_metadata WHERE key='resource_access_since'").fetchone()[0])
    sources = {str(Path(f["record"]["source_path"]).resolve()) for f in files if f["managed"]}
    categories = Counter({name: 0 for name in ("Uploaded files", "Saved inputs and snapshots", "Results", "Saved views", "Other")})
    # Only the managed store is scanned; model/download caches are not user data.
    roots = [runtime.settings.data_root / name for name in ("sessions", "analytics", "history", "jobs", "database-connections")]
    paths = [p for root in roots if root.is_dir() for p in root.rglob("*")]
    paths += [p for p in runtime.settings.data_root.glob("agent.sqlite3*") if p.is_file()]
    for path in paths:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(runtime.settings.data_root.resolve()):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if str(path.resolve()) in sources:
            kind = "Uploaded files"
        elif path.name == "inputs.json" or path.name.startswith("canonical"):
            kind = "Saved inputs and snapshots"
        elif path.name.endswith(".views.json"):
            kind = "Saved views"
        elif path.name.startswith(("result.", "step-")):
            kind = "Results"
        else:
            kind = "Other"
        categories[kind] += size
    for key, size in embedded.items():
        # These payload bytes are inside the physical SQLite files counted above.
        portion = min(size, categories["Other"])
        categories["Other"] -= portion
        categories[key] += portion
    disk = shutil.disk_usage(runtime.settings.data_root)
    # Keep all references and physical byte accounting above: hidden work must
    # still protect an ordinary upload from cleanup. Only its details are hidden.
    files = [row for row in files if visible(row["record"], runtime.settings)]
    public = [{k: v for k, v in f.items() if k not in {"record", "sha256", "owner_id", "session_id"}} for f in files]
    return {"files": public, "users": users, "total_bytes": sum(categories.values()), "categories": [{"name": k, "bytes": v} for k, v in categories.items()],
            "disk": {"used": disk.used, "total": disk.total, "percent": disk.used / disk.total * 100},
            "unused_count": sum(f["deletable"] for f in files), "unused_bytes": sum(f["size_bytes"] for f in files if f["deletable"]),
            "access_recording_since": since, "backups": backups(runtime),
            "scope": "Managed store files and embedded SQLite payloads; database overhead and archived history are Other. Model caches are excluded."}


def _preview(db, runtime, kind, days, identifiers=None):
    files, workflows, protected, accesses = _inventory(db, runtime)
    if identifiers:
        documents = [(row["id"], row["record"]) for row in files] + [(row["id"], row) for row in workflows]
        for identifier, document in documents:
            if identifier in identifiers:
                require_visible(document, runtime.settings)
        for identifier in identifiers:
            row = db.execute("SELECT payload FROM results WHERE id=?", (identifier,)).fetchone()
            if row:
                require_visible(json.loads(row[0]), runtime.settings)
    files = [row for row in files if visible(row["record"], runtime.settings)]
    workflows = [row for row in workflows if visible(row, runtime.settings)]
    if kind == "unused":
        items = [{"id": row["id"], "name": row["name"], "owner": row["owner"], "size_bytes": row["size_bytes"], "sha256": row["sha256"]} for row in files if row["deletable"]]
        reason = "Only files with no analysis, snapshot, project, template or saved-view references and no active owner work are eligible."
    elif kind == "results":
        if days not in {90, 180}:
            raise ValueError("Choose 90 or 180 days.")
        since = float(db.execute("SELECT value FROM admin_metadata WHERE key='resource_access_since'").fetchone()[0])
        cutoff = runtime.accounts.clock() - days * 86400
        owners = {r[0]: r[1] for r in db.execute("SELECT s.id,a.username FROM sessions s LEFT JOIN accounts a ON a.id=s.owner_id")}
        active = busy_owners(db, runtime)
        busy_sessions = {r[0] for r in db.execute("SELECT id,owner_id FROM sessions") if r[1] in active}
        items = []
        for row in workflows:
            observed = accesses.get(("workflow", row["id"]), max(timestamp(row.get("finished_at")) or 0, since))
            if row["status"] not in {"completed", "failed"} or row["id"] in protected or row["session_id"] in busy_sessions or observed >= cutoff:
                continue
            paths = result_paths(runtime, row["id"])
            if paths:
                items.append({"id": row["id"], "kind": "workflow", "name": ", ".join(s["problem"] for s in row.get("validation", {}).get("plan", {}).get("steps", [])) or "Saved analysis", "owner": owners.get(row["session_id"]),
                              "size_bytes": sum(p.stat().st_size for p in paths), "revision": row["revision"], "last_used": observed})
        for row in db.execute("SELECT r.id,r.job_id,r.session_id,r.created_at,length(CAST(r.payload AS BLOB)),r.payload FROM results r JOIN jobs j ON j.id=r.job_id WHERE j.status NOT IN ('queued','running','interpreting') AND neo4j_visible(r.payload) AND neo4j_visible(j.payload)"):
            observed = accesses.get(("result", row[0]), max(timestamp(row[3]) or 0, since))
            if observed >= cutoff or row[0] in protected or row[1] in protected or row[2] in busy_sessions:
                continue
            paths = legacy_result_paths(runtime, row[0], row[2])
            items.append({"id": row[0], "kind": "result", "name": json.loads(row[5])["problem_id"], "owner": owners.get(row[2]),
                          "size_bytes": row[4] + sum(p.stat().st_size for p in paths), "last_used": observed,
                          "sha256": hashlib.sha256(row[5].encode()).hexdigest()})
        reason = "Historical opens were not recorded. Results without an observed open are retained for the full period after access tracking began. Saved views and project references protect results."
    else:
        raise ValueError("Unknown cleanup kind.")
    if identifiers is not None:
        items = [row for row in items if row["id"] in identifiers]
    items.sort(key=lambda row: row["id"])
    total = len(items)
    items = items[:500]
    token = hashlib.sha256(json.dumps([kind, days, items], sort_keys=True).encode()).hexdigest()
    return {"kind": kind, "days": days, "items": items, "count": len(items), "total": total, "bytes": sum(row["size_bytes"] for row in items), "preview_token": token, "reason": reason}


def cleanup_preview(runtime, kind, days=90, identifiers=None):
    with storage_lock, runtime.database._connect() as db:
        initialize(db)
        _ledger(db, runtime)
        return _preview(db, runtime, kind, days, identifiers)


def result_paths(runtime, identifier):
    directory = safe_path(runtime, runtime.analytics.root / identifier)
    return [safe_path(runtime, p) for p in directory.rglob("*") if p.is_file() and not p.is_symlink() and p.name.startswith(("result.", "step-"))]


def legacy_result_paths(runtime, identifier, session_id):
    from .result_index import table_index_path
    # History is sometimes configured outside data_root. Leave that archive
    # alone; its lifecycle policy remains independent of live-result cleanup.
    history = runtime.database.history.root / session_id / "results" / identifier
    paths = [p for p in history.rglob("*") if p.is_file()] if history.resolve().is_relative_to(runtime.settings.data_root.resolve()) else []
    index = table_index_path(runtime.database, identifier)
    paths.extend(p for p in index.parent.glob(index.name + "*") if p.is_file())
    return [safe_path(runtime, p) for p in paths]


def cleanup(runtime, *, kind, days, identifiers, preview_token, confirm):
    if confirm is not True or not identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError("Confirm a nonempty list of distinct cleanup items.")
    with storage_lock, runtime.database._lock, runtime.database._connect() as db:
        initialize(db)
        db.commit()
        _ledger(db, runtime)
        db.execute("BEGIN IMMEDIATE")
        preview = _preview(db, runtime, kind, days, set(identifiers))
        if preview["preview_token"] != preview_token or len(preview["items"]) != len(identifiers):
            raise AccountError("Storage or references changed. Preview the cleanup again.", "cleanup_changed", 409)
        paths = []
        for identifier in identifiers:
            if kind == "unused":
                row = db.execute("SELECT session_id,payload FROM files WHERE id=?", (identifier,)).fetchone()
                file = json.loads(row[1])
                directory = safe_path(runtime, runtime.settings.data_root / "sessions" / row[0] / "files" / identifier)
                if not Path(file["source_path"]).resolve().is_relative_to(directory.resolve()):
                    raise AccountError("The file does not have a managed source directory.", "unsafe_path", 409)
                paths.append(directory)
                db.execute("DELETE FROM files WHERE id=?", (identifier,))
            elif next(item for item in preview["items"] if item["id"] == identifier)["kind"] == "workflow":
                row = json.loads(db.execute("SELECT document FROM admin_workflows.workflows WHERE id=?", (identifier,)).fetchone()[0])
                paths.extend(result_paths(runtime, identifier))
                row.update(status="interrupted", complete=False, steps={}, error={"code": "results_removed", "message": "Saved results were removed by an administrator after the retention period. Review and run the saved plan to calculate them again."})
                db.execute("UPDATE admin_workflows.workflows SET document=? WHERE id=?", (json.dumps(row), identifier))
            else:
                row = db.execute("SELECT job_id,session_id FROM results WHERE id=?", (identifier,)).fetchone()
                paths.extend(legacy_result_paths(runtime, identifier, row[1]))
                db.execute("DELETE FROM results WHERE id=?", (identifier,))
                job = json.loads(db.execute("SELECT payload FROM jobs WHERE id=?", (row[0],)).fetchone()[0])
                job.update(status="failed", result_id=None, error={"code": "results_removed", "message": "Saved results were removed by an administrator after the retention period. Run the saved plan to calculate them again."})
                db.execute("UPDATE jobs SET status='failed',payload=? WHERE id=?", (json.dumps(job), row[0]))
        db.executemany("INSERT OR IGNORE INTO admin_file_cleanup(path,created_at) VALUES (?,?)", [(str(p), runtime.accounts.clock()) for p in paths])
        runtime.accounts._audit(db, "storage.cleaned", kind, before={"items": preview["items"], "bytes": preview["bytes"]}, after={"removed": identifiers, "count": len(identifiers)})
    runtime.analytics.result_cache.clear()
    return {"removed": len(identifiers), "bytes": preview["bytes"], "cleanup": admin_lifecycle.cleanup(runtime)}


def download_file(runtime, identifier):
    with runtime.database._connect() as db:
        row = db.execute("SELECT payload FROM files WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise AccountError("File not found.", "not_found", 404)
        file = json.loads(row[0])
        require_visible(file, runtime.settings)
        path = safe_path(runtime, file["source_path"])
        if not path.is_file():
            raise AccountError("The uploaded source is no longer available.", "not_found", 404)
        runtime.accounts._audit(db, "file.downloaded", identifier, before={"file": file["original_name"]}, after={"download_requested": True})
    touch(runtime.database, "file", identifier)
    return path, file["original_name"]


def backup_directory(runtime):
    return runtime.settings.backup_directory or runtime.settings.data_root.parent / (runtime.settings.data_root.name + "-backups")


def record_verification(runtime, target):
    with runtime.database._connect() as db:
        initialize(db)
        db.execute("INSERT INTO admin_backup_checks VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET verified_at=excluded.verified_at,manifest_hash=excluded.manifest_hash,status=excluded.status",
                   (target.name, runtime.accounts.clock(), hashlib.sha256((target / "manifest.json").read_bytes()).hexdigest(), "verified"))


def backups(runtime):
    directory = backup_directory(runtime)
    with runtime.database._connect() as db:
        initialize(db)
        checked = {row[0]: tuple(row[1:]) for row in db.execute("SELECT name,verified_at,manifest_hash,status FROM admin_backup_checks")}
    items = []
    for path in directory.glob("*/manifest.json") if directory.is_dir() else []:
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            raw = path.read_bytes()
            manifest = json.loads(raw)
            if manifest.get("version") != "graphmine-offline-backup-v1":
                continue
            check = checked.get(path.parent.name)
            matches = check and check[1] == hashlib.sha256(raw).hexdigest()
            items.append({"name": path.parent.name, "created_at": timestamp(manifest["created_at"]),
                          "size_bytes": sum(v["size_bytes"] for v in manifest["files"].values()),
                          "verified": bool(matches and check[2] == "verified"), "verified_at": check[0] if matches else None})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {"items": sorted(items, key=lambda row: row["created_at"] or 0, reverse=True), "keep": runtime.settings.backup_keep,
            "scheduled": bool(runtime.settings.backup_directory), "interval_hours": runtime.settings.backup_hours,
            "directory": str(directory), "restore_mode": "Staged restore to a new directory, using the existing restore-backup implementation."}


def snapshot_path(runtime, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", name):
        raise ValueError("Invalid snapshot name.")
    directory = backup_directory(runtime).resolve()
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory or not path.is_dir():
        raise AccountError("Snapshot not found.", "not_found", 404)
    return path


def backup_action(runtime, action, *, name=None, confirm=False, confirm_name=None):
    from .backup import online_snapshot, restore_snapshot, verify_snapshot
    with storage_lock:
        if action == "restore" and (confirm is not True or confirm_name != name):
            raise ValueError("Confirm the restore and type the snapshot name exactly.")
        directory = backup_directory(runtime)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / ("manual-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]) if action == "create" else snapshot_path(runtime, name)
        if action not in {"create", "verify", "restore"}:
            raise ValueError("Unknown backup action.")
        with runtime.database._connect() as db:
            initialize(db)
            runtime.accounts._audit(db, "backup." + action + "_requested", target.name, before={"snapshot": name}, after={"status": "started"})
        try:
            if action == "create":
                online_snapshot(runtime.settings.data_root, target)
            if action in {"create", "verify"}:
                manifest = verify_snapshot(target)
                result = {"name": target.name, "verified": True, "size_bytes": sum(v["size_bytes"] for v in manifest["files"].values())}
                record_verification(runtime, target)
            else:
                parent = directory.parent / (directory.name + "-restores")
                parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                destination = parent / ("restore-" + uuid4().hex)
                report = restore_snapshot(target, destination)
                result = {"name": target.name, "restored": True, "data_root": report["data_root"], "services_started": False,
                          "reason": "The snapshot was restored into a new directory. A service switch is a separate deployment step."}
        except Exception:
            _logger.exception("Admin backup %s failed for %s", action, target.name)
            with runtime.database._connect() as db:
                db.execute("UPDATE admin_backup_checks SET status='failed' WHERE name=?", (target.name,))
                runtime.accounts._audit(db, "backup." + action + "_failed", target.name, before={"status": "started"}, after={"status": "failed"})
            raise AccountError("The backup problem failed its filesystem or integrity checks. Review the server log before retrying.", "backup_failed", 409) from None
        with runtime.database._connect() as db:
            runtime.accounts._audit(db, "backup." + action + "_completed", target.name, before={"status": "started"}, after=result)
        return result
