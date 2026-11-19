"""One atomic, cross-process account bridge to Dataset Studio's users.json."""

import fcntl
import json
import os
import tempfile
from pathlib import Path


def auth_directory(settings):
    configured = os.getenv("GRAPHMINE_STUDIO_AUTH_DIR")
    return Path(configured) if configured else settings.repository_root / "dataset-studio" / "workspace" / "auth"


def sync_user(settings, user, *, old_username=None, delete=False, revoke_sessions=False):
    """Return a retryable error; a Studio failure never rolls back GraphMine."""
    folder = auth_directory(settings)
    path = folder / "users.json"
    temporary = None
    try:
        if not path.is_file():
            raise OSError("Studio account store is not available")
        with (folder / "users.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            payload = json.loads(path.read_text())
            users = payload["users"]
            name, previous = user["username"], old_username or user["username"]
            existing = users.get(previous, {})
            remove = delete or not user["studio_access"]
            active_admins = [name for name, account in users.items() if account.get("role") == "admin" and not account.get("disabled")]
            if active_admins == [previous] and (remove or user["disabled"] or user["role"] != "admin"):
                raise ValueError("Keep at least one active Studio administrator")
            if name != previous and name in users:
                raise ValueError("That Studio username already exists")
            users.pop(previous, None)
            if not remove:
                users[name] = {**existing, "role": user["role"], "disabled": bool(user["disabled"]),
                               "password": None, "datasets": existing.get("datasets", []),
                               "created_at": existing.get("created_at", user["created_at"]),
                               "created_by": existing.get("created_by", user.get("created_by")),
                               "graphmine": {"id": user["id"], "username": name}}
            descriptor, temporary = tempfile.mkstemp(prefix=".users-", dir=folder)
            with os.fdopen(descriptor, "w") as output:
                json.dump(payload, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            temporary = None
            if revoke_sessions or remove or user["disabled"] or name != previous:
                session_path = folder / "sessions.json"
                if session_path.is_file():
                    sessions = json.loads(session_path.read_text())
                    sessions["sessions"] = {key: value for key, value in sessions.get("sessions", {}).items()
                                            if value.get("username") not in {previous, name}}
                    descriptor, temporary = tempfile.mkstemp(prefix=".sessions-", dir=folder)
                    with os.fdopen(descriptor, "w") as output:
                        json.dump(sessions, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, session_path)
                    temporary = None
        return {"ok": True, "message": "Studio updated"}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"ok": False, "message": "Studio not updated: retry", "reason": str(error)}
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def sync_account(accounts, user, *, old_username=None, delete=False, revoke_sessions=False):
    with accounts.database._connect() as db:
        pending = db.execute("SELECT options FROM studio_sync_pending WHERE user_id=?", (user["id"],)).fetchone()
    if pending:
        previous = json.loads(pending[0])
        old_username = previous.get("old_username") or old_username
        revoke_sessions = revoke_sessions or previous.get("revoke_sessions", False)
    options = {"old_username": old_username, "delete": delete, "revoke_sessions": revoke_sessions}
    result = sync_user(accounts.settings, user, **options)
    with accounts.database._connect() as db:
        before = db.execute("SELECT studio_sync_error FROM accounts WHERE id=?", (user["id"],)).fetchone()
        error = None if result["ok"] else json.dumps({"reason": result["reason"], "old_username": old_username})
        db.execute("UPDATE accounts SET studio_sync_error=? WHERE id=?", (error, user["id"]))
        if result["ok"]:
            db.execute("DELETE FROM studio_sync_pending WHERE user_id=?", (user["id"],))
        else:
            db.execute("INSERT INTO studio_sync_pending VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload,options=excluded.options,reason=excluded.reason",
                       (user["id"], json.dumps(user), json.dumps(options), result["reason"]))
        accounts._audit(db, "studio.synced" if result["ok"] else "studio.sync_failed", user["username"],
                        before={"studio_sync_error": before[0] if before else None},
                        after={"studio_sync_error": error, "deleted": delete})
    return result
