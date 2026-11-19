"""Provision and erase an exclusively synthetic, isolated performance store.

Cleanup refuses a store containing any account outside its creation manifest,
or one whose owned agent is still running. It cannot target a production store.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perf.common import ROOT, write_json, timestamp


def backend_directory(run):
    return Path.home()/".local/share/graphmine-perf"/Path(run).name


def create(run, settings):
    from graphmine_agent.accounts import Accounts
    from graphmine_agent.database import Database
    run = Path(run).resolve()
    private, data = run/"private", run/"private/data"
    if settings.data_root.resolve() != data or data.exists():
        raise ValueError("Provisioning requires a new <run>/private/data store")
    backend = backend_directory(run)
    if settings.backend_data_dir.resolve() != backend.resolve() or backend.exists():
        raise ValueError("Provisioning requires a new owned external backend ledger")
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private, 0o700)
    manifest = {"run": str(run), "data_root": str(data), "created_at": timestamp(), "agent_pid": None,
                "accounts": [], "complete": False, "backend_data_dir":str(backend)}
    write_json(private/"accounts.json", manifest, private=True)
    backend.mkdir(parents=True,mode=0o700)
    write_json(backend/"perf-owner.json",{"run":str(run)},private=True)
    database = Database(settings.database_path)
    accounts = Accounts(settings, database)
    # Quotas are elevated only in this disposable store, not in a live account.
    for name in [*(f"perftest{i:02d}" for i in range(1, 51)), "perftest_admin"]:
        password = secrets.token_urlsafe(24)
        result = accounts.create_user(name, password, daily_token_limit=settings.account_daily_tokens,
                                      admin=name == "perftest_admin")
        with database._connect() as db:
            identifier = db.execute("SELECT id FROM accounts WHERE username=?", (name,)).fetchone()[0]
        manifest["accounts"].append({"username": name, "id": identifier, "password": password})
        write_json(private/"accounts.json", manifest, private=True)
    manifest["complete"] = True
    write_json(private/"accounts.json", manifest, private=True)
    return manifest


def cleanup(run):
    run = Path(run).resolve()
    private, data = run/"private", run/"private/data"
    manifest_path = private/"accounts.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("run") != str(run) or manifest.get("data_root") != str(data) or data.is_symlink() or private.is_symlink():
        raise ValueError("The test store does not match its ownership manifest")
    pid = manifest.get("agent_pid")
    if pid and Path(f"/proc/{int(pid)}").exists():
        raise ValueError("Stop the test agent before cleanup")
    allowed = {a["id"]: a["username"] for a in manifest["accounts"]}
    if any(not (name == "perftest_admin" or name in {f"perftest{i:02d}" for i in range(1,51)}) for name in allowed.values()):
        raise ValueError("Manifest includes a non-test username")
    database = data/"agent.sqlite3"
    sessions = 0
    if database.exists():
        db = sqlite3.connect(database.as_uri()+"?mode=ro", uri=True)
        try:
            actual = dict(db.execute("SELECT id,username FROM accounts"))
            if any(allowed.get(identifier) != name for identifier, name in actual.items()):
                raise ValueError("Store contains an account not created by this performance run")
            sessions = db.execute("SELECT count(*) FROM sessions").fetchone()[0]
        finally:
            db.close()
    files = sum(p.is_file() for p in data.rglob("*")) if data.exists() else 0
    backend = backend_directory(run)
    if manifest.get("backend_data_dir"):
        if manifest["backend_data_dir"] != str(backend) or backend.is_symlink():
            raise ValueError("Unexpected external backend store")
        if backend.exists():
            if json.loads((backend/"perf-owner.json").read_text()) != {"run":str(run)}:
                raise ValueError("External backend store ownership mismatch")
            files += sum(p.is_file() for p in backend.rglob("*"))
            shutil.rmtree(backend)
    if data.exists():
        shutil.rmtree(data)
    # Backups, captures and history are all placed inside private/store or data.
    backups = private/"backups"
    if backups.exists():
        if backups.is_symlink():
            raise ValueError("Unexpected backup symlink")
        shutil.rmtree(backups)
    for name in ("accounts.json", "app-env.json", "monitor.json", "locust.json"):
        (private/name).unlink(missing_ok=True)
    record = {"ts": timestamp(), "accounts_deleted": len(allowed), "sessions_deleted": sessions,
              "files_deleted": files, "credentials_deleted": True, "data_root_removed": not data.exists()}
    write_json(run/"cleanup.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "cleanup"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.action == "cleanup":
        print(json.dumps(cleanup(args.run)))
    else:
        sys.path.insert(0, str(ROOT/"agent"))
        from graphmine_agent.config import Settings
        env = json.loads((args.run/"private/app-env.json").read_text())
        os.environ.update(env)
        result = create(args.run, Settings.from_env(ROOT))
        print(f"Created {len(result['accounts'])} synthetic accounts")


if __name__ == "__main__":
    main()
