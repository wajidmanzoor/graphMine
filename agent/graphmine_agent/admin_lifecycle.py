"""Account deletion with atomic ownership changes and durable file cleanup."""

import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .identity import AccountError, current_principal
from .studio_sync import sync_account


def preview(runtime, username):
    accounts = runtime.accounts
    user = accounts.user(username)
    with runtime.database._connect() as db:
        sessions = [row[0] for row in db.execute("SELECT id FROM sessions WHERE owner_id=?", (user["id"],))]
        files = db.execute("SELECT count(*),coalesce(sum(json_extract(f.payload,'$.size_bytes')),0) FROM files f JOIN sessions s ON s.id=f.session_id WHERE s.owner_id=?", (user["id"],)).fetchone()
        shares = db.execute("SELECT count(*) FROM project_items i JOIN projects p ON p.id=i.project_id WHERE p.owner_id=?", (user["id"],)).fetchone()[0]
    analyses = 0
    ledger = runtime.settings.data_root / "analytics" / "workflows.sqlite3"
    if ledger.is_file():
        with closing(sqlite3.connect(ledger)) as db:
            for sid in sessions:
                analyses += db.execute("SELECT count(*) FROM workflows WHERE session_id=?", (sid,)).fetchone()[0]
    return {"user": user, "conversations": len(sessions), "saved_analyses": analyses,
            "uploaded_files": files[0], "uploaded_bytes": files[1], "project_shares": shares,
            "storage": accounts.storage_usage(user["id"])}


def cleanup(runtime):
    with runtime.database._connect() as db:
        rows = db.execute("SELECT path,destination FROM admin_file_cleanup ORDER BY path DESC").fetchall()
    failures = []
    for row in rows:
        path = Path(row[0])
        destination = Path(row[1]) if row[1] else None
        roots = (runtime.settings.data_root, runtime.settings.workspaces_root,
                 runtime.settings.capture_root, runtime.database.history.root)
        if any(not any(candidate.resolve() != root.resolve() and candidate.resolve().is_relative_to(root.resolve()) for root in roots)
               for candidate in (path, destination) if candidate is not None):
            failures.append(str(path))
            continue
        try:
            if destination is not None:
                if path.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if destination.exists():
                        if destination.read_bytes() != path.read_bytes():
                            raise OSError("Capture destination changed; review before retrying")
                        path.unlink()
                    else:
                        os.replace(path, destination)
            elif path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            with runtime.database._connect() as db:
                db.execute("DELETE FROM admin_file_cleanup WHERE path=?", (str(path),))
        except OSError:
            failures.append(str(path))
    return {"pending": len(failures)}


def delete_user(runtime, username, *, data, confirm, confirm_username):
    accounts, actor = runtime.accounts, current_principal.get()
    if confirm is not True or confirm_username != username or data not in {"transfer", "erase"}:
        raise ValueError("Confirm the username and choose transfer or erase.")
    if actor is None:
        raise AccountError("Administrator session required.", "admin_required", 403)
    before = preview(runtime, username)
    user, now = before["user"], accounts.clock()
    ledger = runtime.settings.data_root / "analytics" / "workflows.sqlite3"
    with runtime.database._connect() as db:
        if ledger.is_file():
            db.execute("ATTACH DATABASE ? AS analytics_ledger", (str(ledger),))
        db.execute("BEGIN IMMEDIATE")
        row = accounts._account_row(db, username)
        accounts._protect_admin(db, row, delete=True)
        owner = row["id"]
        if db.execute("SELECT 1 FROM account_leases WHERE user_id=? AND expires_at>?", (owner, now)).fetchone():
            raise AccountError("Wait for this user's active requests and jobs to finish before deleting.", "account_busy", 409)
        if db.execute("SELECT 1 FROM database_jobs WHERE owner_id=? AND status IN ('queued','running','cancelling')", (owner,)).fetchone():
            raise AccountError("Cancel this user's database jobs before deleting.", "account_busy", 409)
        sessions = [r[0] for r in db.execute("SELECT id FROM sessions WHERE owner_id=?", (owner,))]
        workflows, paths = [], []
        for sid in sessions:
            if ledger.is_file():
                records = db.execute("SELECT id,document FROM analytics_ledger.workflows WHERE session_id=?", (sid,)).fetchall()
                if any(json.loads(r[1]).get("status") in {"queued", "running"} for r in records):
                    raise AccountError("Cancel this user's calculations before deleting.", "account_busy", 409)
                workflows.extend(r[0] for r in records)
            if db.execute("SELECT 1 FROM jobs WHERE session_id=? AND status IN ('queued','running','interpreting')", (sid,)).fetchone():
                raise AccountError("Cancel this user's graph jobs before deleting.", "account_busy", 409)
            paths.extend([runtime.settings.data_root / "sessions" / sid, runtime.database.history.session_path(sid)])
            paths.extend(runtime.settings.workspaces_root / r[0] for r in db.execute("SELECT id FROM jobs WHERE session_id=?", (sid,)))
        if data == "transfer":
            # Copy blob keys before moving their references (a recipient can
            # already have the same content hash). Preserve referential integrity.
            db.execute("INSERT OR IGNORE INTO query_preview_blobs SELECT ?,sha256,content,size_bytes FROM query_preview_blobs WHERE owner_id=?", (actor.user_id, owner))
            db.execute("UPDATE query_previews SET owner_id=? WHERE owner_id=?", (actor.user_id, owner))
            db.execute("DELETE FROM query_preview_blobs WHERE owner_id=?", (owner,))
            for table in ("sessions", "dataset_versions", "dataset_catalog", "workflow_templates", "projects", "user_connectors"):
                db.execute(f"UPDATE {table} SET owner_id=? WHERE owner_id=?", (actor.user_id, owner))
            db.execute("UPDATE database_jobs SET owner_id=?,request_key=?||request_key WHERE owner_id=?", (actor.user_id, owner + ":", owner))
            db.execute("INSERT OR IGNORE INTO project_members SELECT project_id,?,role FROM project_members WHERE user_id=?", (actor.user_id, owner))
            db.execute("UPDATE project_notes SET author_id=? WHERE author_id=?", (actor.user_id, owner))
            capture_source = runtime.settings.capture_root / "users" / owner
            for source in capture_source.rglob("*") if capture_source.is_dir() else ():
                if source.is_file():
                    target = runtime.settings.capture_root / "users" / actor.user_id / source.relative_to(capture_source)
                    db.execute("INSERT OR IGNORE INTO admin_file_cleanup(path,created_at,destination) VALUES (?,?,?)", (str(source), now, str(target)))
        else:
            for sid in sessions:
                if ledger.is_file():
                    db.execute("DELETE FROM analytics_ledger.workflows WHERE session_id=?", (sid,))
                    db.execute("DELETE FROM analytics_ledger.reviewed_examples WHERE session_id=?", (sid,))
            paths.extend(runtime.settings.data_root / "analytics" / wid for wid in workflows)
            paths.append(runtime.settings.capture_root / "users" / owner)
            for table in ("sessions", "dataset_versions", "dataset_catalog", "workflow_templates", "projects", "user_connectors", "query_previews", "query_preview_blobs", "database_jobs"):
                db.execute(f"DELETE FROM {table} WHERE owner_id=?", (owner,))
            db.execute("DELETE FROM project_notes WHERE author_id=?", (owner,))
            db.executemany("INSERT OR IGNORE INTO admin_file_cleanup(path,created_at) VALUES (?,?)", [(str(path), now) for path in paths])
        db.execute("DELETE FROM project_members WHERE user_id=?", (owner,))
        db.execute("DELETE FROM account_sessions WHERE user_id=?", (owner,))
        db.execute("DELETE FROM account_leases WHERE user_id=?", (owner,))
        db.execute("DELETE FROM quota_buckets WHERE scope=?", (owner,))
        db.execute("DELETE FROM accounts WHERE id=?", (owner,))
        accounts._audit(db, "account.deleted", username, before=before,
                        after={"deleted": True, "data": data, "transferred_to": actor.username if data == "transfer" else None})
    if runtime.database.capture:
        with runtime.database.capture._lock:
            for sid in sessions:
                runtime.database.capture._owners.pop(sid, None)
    result = {"deleted": True, "studio": sync_account(accounts, user, delete=True), "cleanup": cleanup(runtime)}
    return result
