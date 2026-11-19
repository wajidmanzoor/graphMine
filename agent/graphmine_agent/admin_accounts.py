"""Account-management extensions sharing the existing Accounts transactions."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from . import admin_events
from .identity import AccountError, current_principal


PUBLIC_FIELDS = ("id", "username", "role", "created_at", "created_by", "disabled",
                 "daily_token_limit", "storage_limit", "graphmine_access", "studio_access",
                 "must_change_password", "last_sign_in", "last_active", "studio_sync_error")


class AdminAccounts:
    def _initialize_admin(self, db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)")}
        migrating_sign_in = "last_sign_in" not in columns
        for name, definition in {
            "created_by": "TEXT", "storage_limit": "INTEGER", "last_sign_in": "REAL",
            "last_active": "REAL", "must_change_password": "INTEGER NOT NULL DEFAULT 0",
            "graphmine_access": "INTEGER NOT NULL DEFAULT 1", "studio_access": "INTEGER NOT NULL DEFAULT 0",
            "login_disabled": "INTEGER NOT NULL DEFAULT 0", "studio_sync_error": "TEXT",
        }.items():
            if name not in columns:
                db.execute(f"ALTER TABLE accounts ADD COLUMN {name} {definition}")
        columns = {row[1] for row in db.execute("PRAGMA table_info(admin_activity)")}
        for name in ("before", "after"):
            if name not in columns:
                db.execute(f"ALTER TABLE admin_activity ADD COLUMN {name} TEXT NOT NULL DEFAULT '{{}}'")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS admin_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admin_file_cleanup(path TEXT PRIMARY KEY,created_at REAL NOT NULL,destination TEXT);
            CREATE TABLE IF NOT EXISTS studio_sync_pending (
              user_id TEXT PRIMARY KEY, payload TEXT NOT NULL, options TEXT NOT NULL, reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS support_grants (
              id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, session_hash TEXT NOT NULL,
              user_id TEXT NOT NULL, conversation_id TEXT NOT NULL, reason TEXT NOT NULL,
              created_at REAL NOT NULL, expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS support_grants_user ON support_grants(user_id,created_at);
        """)
        if "destination" not in {row[1] for row in db.execute("PRAGMA table_info(admin_file_cleanup)")}:
            db.execute("ALTER TABLE admin_file_cleanup ADD COLUMN destination TEXT")
        db.execute("INSERT OR IGNORE INTO admin_metadata VALUES ('recording_since',?)", (str(self.clock()),))
        if migrating_sign_in:
            db.execute("UPDATE accounts SET last_sign_in=(SELECT max(created_at) FROM account_sessions WHERE user_id=accounts.id)")
            from .studio_sync import auth_directory
            try:
                names = json.loads((auth_directory(self.settings) / "users.json").read_text()).get("users", {})
                db.executemany("UPDATE accounts SET studio_access=1 WHERE username=?", [(name,) for name in names])
            except (OSError, ValueError, TypeError):
                pass  # Existing access is reconciled when Studio becomes available.

    @staticmethod
    def _public_row(row):
        return {name: row[name] for name in PUBLIC_FIELDS}

    def _account_row(self, db, username):
        row = db.execute("SELECT * FROM accounts WHERE username=?", (self.username(username),)).fetchone()
        if row is None:
            raise ValueError("Unknown username.")
        return row

    def user(self, username):
        with self.database._connect() as db:
            return self._public_row(self._account_row(db, username))

    def _audit(self, db, action, target, details=None, *, before=None, after=None):
        principal = current_principal.get()
        now = self.clock()
        actor = principal.username if principal else "local administrator"
        before, after = before or {}, after if after is not None else (details or {})
        details = details or {}
        cursor = db.execute(
            'INSERT INTO admin_activity(at,actor_id,actor,action,target,details,"before","after") VALUES (?,?,?,?,?,?,?,?)',
            (datetime.fromtimestamp(now, timezone.utc).isoformat(), principal.user_id if principal else None,
             actor, action, target, json.dumps(details), json.dumps(before), json.dumps(after)))
        admin_events.insert(db, "admin_change", f"{actor}: {action} · {target}", ts=now,
                            details={"audit_id": cursor.lastrowid, "action": action, "target": target,
                                     "before": before, "after": after})

    def _protect_admin(self, db, row, *, role=None, disabled=None, access=None, delete=False):
        losing = delete or role == "user" or disabled is True or access is False
        if losing and row["role"] == "admin" and not row["disabled"] and row["graphmine_access"]:
            count = db.execute("SELECT count(*) FROM accounts WHERE role='admin' AND disabled=0 AND graphmine_access=1 AND login_disabled=0").fetchone()[0]
            if count <= 1:
                raise AccountError("Keep at least one active administrator.", "last_admin", 409)
        principal = current_principal.get()
        if principal and row["id"] == principal.user_id and (delete or disabled is True or access is False):
            raise AccountError("You cannot disable or delete your own administrator account.", "self_disable", 403)

    def update_user(self, username, changes):
        allowed = {"username", "role", "daily_token_limit", "storage_limit", "graphmine_access", "studio_access", "must_change_password"}
        if not changes or set(changes) - allowed:
            raise ValueError("Supply supported account fields.")
        if "role" in changes and changes["role"] not in {"admin", "user"}:
            raise ValueError("Role must be admin or user.")
        if "username" in changes:
            changes["username"] = self.username(changes["username"])
        if "daily_token_limit" in changes:
            self._validate_token_limit(changes["daily_token_limit"])
        limit = changes.get("storage_limit")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 2**53 - 1):
            raise ValueError("Storage limit must be a positive whole number of bytes.")
        for field in ("graphmine_access", "studio_access", "must_change_password"):
            if field in changes and type(changes[field]) is not bool:
                raise ValueError(f"{field} must be true or false.")
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._account_row(db, username)
            self._protect_admin(db, row, role=changes.get("role"), access=changes.get("graphmine_access"))
            name = changes.get("username", row["username"])
            if changes.get("studio_access", row["studio_access"]) and len(name) > 32:
                raise ValueError("Dataset Studio usernames must be at most 32 characters.")
            if name != row["username"] and db.execute("SELECT 1 FROM accounts WHERE username=?", (name,)).fetchone():
                raise ValueError("That username already exists.")
            before = self._public_row(row)
            changed = {key for key, value in changes.items() if row[key] != value}
            db.execute("UPDATE accounts SET " + ",".join(f"{key}=?" for key in changes) + " WHERE id=?",
                       [*changes.values(), row["id"]])
            if {"role", "username", "graphmine_access", "must_change_password"} & changed:
                db.execute("DELETE FROM account_sessions WHERE user_id=?", (row["id"],))
            after = self._public_row(self._account_row(db, name))
            self._audit(db, "account.updated", name, before=before, after=after)
        return after

    def force_signout(self, username):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._account_row(db, username)
            count = db.execute("DELETE FROM account_sessions WHERE user_id=?", (row["id"],)).rowcount
            self._audit(db, "account.signed_out", username, before={"sessions": count}, after={"sessions": 0})
        return {"sessions_removed": count}

    def reset_daily_tokens(self, username):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._account_row(db, username)
            now = self.clock()
            if db.execute("SELECT 1 FROM account_leases WHERE user_id=? AND kind='model' AND expires_at>?", (row["id"], now)).fetchone():
                raise AccountError("Wait for this user's current AI request to finish.", "tokens_in_use", 409)
            before = self._usage(db, row["id"], now)
            db.execute("UPDATE account_leases SET user_period=NULL WHERE user_id=? AND kind='model'", (row["id"],))
            db.execute("UPDATE quota_buckets SET tokens=0 WHERE scope=?", (row["id"],))
            after = self._usage(db, row["id"], now)
            self._audit(db, "tokens.reset", username, before={"tokens_used": before["tokens_used"]},
                        after={"tokens_used": after["tokens_used"]})
        return after

    def admin_users(self):
        now = self.clock()
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM accounts WHERE login_disabled=0 ORDER BY username").fetchall()
            since = float(db.execute("SELECT value FROM admin_metadata WHERE key='recording_since'").fetchone()[0])
            pending = [{"id": row[0], "username": json.loads(row[1])["username"], "reason": row[2]}
                       for row in db.execute("SELECT user_id,payload,reason FROM studio_sync_pending")]
            items = []
            for row in rows:
                item = self._public_row(row)
                item["quota"] = self._usage(db, row["id"], now)
                item["storage"] = self.storage_usage(row["id"], db=db)
                item["questions_7d"] = db.execute("SELECT count(*) FROM events WHERE user_id=? AND type='question' AND ts>=?", (row["id"], now - 7 * 86400)).fetchone()[0]
                item["failed_sign_ins"] = db.execute("SELECT count(*) FROM events WHERE user_id=? AND type='sign_in' AND outcome!='ok'", (row["id"],)).fetchone()[0]
                item["signed_in"] = bool(db.execute("SELECT 1 FROM account_sessions WHERE user_id=? AND expires_at>?", (row["id"], now)).fetchone())
                item["status"] = ("Disabled" if row["disabled"] else ("Never signed in" if row["created_at"] >= since else "Not available yet") if row["last_sign_in"] is None
                                  else "Active now" if item["signed_in"] and (row["last_active"] or 0) >= now - 300
                                  else "Active today" if (row["last_active"] or 0) >= now - 86400 else "Inactive")
                items.append(item)
        return {"items": items, "counts": {"all": len(items), "admins": sum(u["role"] == "admin" for u in items),
                "members": sum(u["role"] == "user" for u in items), "disabled": sum(bool(u["disabled"]) for u in items),
                "never": sum(u["status"] == "Never signed in" for u in items)},
                "defaults": {"daily_token_limit": self.settings.account_daily_tokens, "storage_limit": self.settings.account_storage_bytes},
                "server_token_limit": self.settings.server_daily_tokens, "now": now,
                "recording_since": since, "studio_pending": pending}

    def grant_support(self, conversation_id, reason, duration):
        principal = current_principal.get()
        if not principal or not principal.is_admin or not principal.session_hash or not self.session_active(principal):
            raise AccountError("Administrator session required.", "admin_required", 403)
        reason = reason.strip()
        if not reason or len(reason) > 1000 or duration not in {"hour", "session"}:
            raise ValueError("Give a reason and choose one hour or this session.")
        now, grant_id = self.clock(), secrets.token_urlsafe(24)
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner_id FROM sessions WHERE id=?", (conversation_id,)).fetchone()
            if row is None or row["owner_id"] is None:
                raise ValueError("Unknown conversation or conversation owner.")
            session = db.execute("SELECT expires_at FROM account_sessions WHERE token_hash=? AND expires_at>?", (principal.session_hash, now)).fetchone()
            if session is None:
                raise AccountError("Sign in again.", "admin_required", 403)
            expires = min(now + 3600, session[0]) if duration == "hour" else session[0]
            record = {"id": grant_id, "actor_id": principal.user_id, "user_id": row["owner_id"],
                      "conversation_id": conversation_id, "reason": reason, "created_at": now, "expires_at": expires}
            db.execute("INSERT INTO support_grants VALUES (?,?,?,?,?,?,?,?)",
                       (grant_id, principal.user_id, principal.session_hash, row["owner_id"], conversation_id, reason, now, expires))
            self._audit(db, "support.granted", row["owner_id"], before={}, after=record)
            admin_events.insert(db, "support_access", f"{principal.username} granted read-only support access", ts=now,
                                user_id=row["owner_id"], details=record)
        return record

    def support_grant(self, grant_id):
        principal = current_principal.get()
        with self.database._connect() as db:
            row = db.execute("SELECT g.* FROM support_grants g JOIN account_sessions s ON s.token_hash=g.session_hash "
                             "JOIN accounts a ON a.id=g.actor_id JOIN sessions c ON c.id=g.conversation_id AND c.owner_id=g.user_id "
                             "WHERE g.id=? AND g.actor_id=? AND g.session_hash=? AND g.expires_at>? AND s.expires_at>? "
                             "AND a.role='admin' AND a.disabled=0 AND a.graphmine_access=1",
                             (grant_id, principal.user_id if principal else None, principal.session_hash if principal else None,
                              self.clock(), self.clock())).fetchone()
        if row is None:
            raise AccountError("Support access has expired or is unavailable.", "support_expired", 403)
        return {key: row[key] for key in row.keys() if key != "session_hash"}

    def support_history(self, user_id):
        with self.database._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT g.id,g.reason,g.created_at,g.expires_at,g.conversation_id,a.username AS administrator "
                "FROM support_grants g LEFT JOIN accounts a ON a.id=g.actor_id WHERE g.user_id=? ORDER BY g.created_at DESC", (user_id,))]
