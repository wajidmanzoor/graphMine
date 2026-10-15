"""Administrator-created accounts and atomic, durable 24-hour resource budgets.

No signup endpoint exists. Passwords use salted scrypt; bearer/cookie credentials
are random and stored only as hashes. Quotas reserve before inference and settle
from provider usage. Server failures are refunded; timeouts and cancellations
charge only the counted input; successful replies without usage keep the reservation.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json as json_module
import math
import re
import secrets
import sqlite3
import time
from collections import defaultdict
from contextlib import asynccontextmanager, closing, suppress
from datetime import datetime, timezone
from functools import lru_cache

import httpx

from .identity import AccountError, Principal, current_principal

DAY = 86400
MODEL_QUEUE_SECONDS = 60
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 3


def password_hash(password, *, salt=None):
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    )
    return f"scrypt${salt}${derived.hex()}"


@lru_cache(maxsize=1)
def _dummy_password():
    return password_hash("unavailable-account-password")


def password_matches(password, encoded):
    try:
        algorithm, salt, _ = encoded.split("$")
        return algorithm == "scrypt" and hmac.compare_digest(
            password_hash(password, salt=salt), encoded
        )
    except (ValueError, TypeError):
        return False


def _stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class Accounts:
    def __init__(self, settings, database, *, clock=time.time):
        self.settings, self.database, self.clock = settings, database, clock
        # Process-local arrival order for each kind of slot; leases stay in SQLite.
        self.waiting = defaultdict(list)
        database.path.chmod(0o600)
        with database._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, created_at REAL NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES accounts(id),
                    expires_at REAL NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS account_sessions_user ON account_sessions(user_id);
                CREATE TABLE IF NOT EXISTS quota_buckets (
                    scope TEXT PRIMARY KEY, started_at REAL NOT NULL,
                    tokens INTEGER NOT NULL DEFAULT 0, jobs INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS account_leases (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
                    expires_at REAL NOT NULL, amount INTEGER NOT NULL DEFAULT 0,
                    user_period REAL, server_period REAL
                );
                CREATE INDEX IF NOT EXISTS account_leases_kind ON account_leases(kind, user_id);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    key TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)")}
            if "role" not in columns:
                db.execute(
                    "ALTER TABLE accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )
            if "daily_token_limit" not in columns:
                db.execute("ALTER TABLE accounts ADD COLUMN daily_token_limit INTEGER")

    @staticmethod
    def username(value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", value):
            raise ValueError(
                "Username must be 3–64 letters, digits, dots, underscores or hyphens."
            )
        return value

    def _validate_token_limit(self, limit):
        if limit is not None and (
            type(limit) is not int
            or not 0 <= limit <= self.settings.server_daily_tokens
        ):
            raise ValueError(
                f"Daily token limit must be a whole number from 0 to {self.settings.server_daily_tokens:,}."
            )

    def create_user(self, username, password, daily_token_limit=None, *, admin=False):
        username = self.username(username)
        self._validate_token_limit(daily_token_limit)
        if not 12 <= len(password) <= 128:
            raise ValueError("Use a password of 12–128 characters.")
        encoded, now, user_id = (
            password_hash(password),
            self.clock(),
            secrets.token_hex(16),
        )
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM accounts WHERE username=?", (username,)
            ).fetchone():
                raise ValueError("That username already exists.")
            if (
                db.execute("SELECT count(*) FROM accounts").fetchone()[0]
                >= self.settings.max_accounts
            ):
                raise ValueError(
                    "Account limit reached; increase GRAPHMINE_MAX_ACCOUNTS deliberately."
                )
            db.execute(
                "INSERT INTO accounts(id,username,password_hash,created_at,disabled,role,daily_token_limit) VALUES (?,?,?,?,0,?,?)",
                (
                    user_id,
                    username,
                    encoded,
                    now,
                    "admin" if admin else "user",
                    daily_token_limit,
                ),
            )
            db.execute(
                "INSERT INTO quota_buckets(scope,started_at) VALUES (?,?)",
                (user_id, now),
            )
        return {
            "id": user_id,
            "username": username,
            "role": "admin" if admin else "user",
        }

    def list_users(self):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = self.clock()
            rows = db.execute(
                "SELECT id,username,created_at,disabled,role,daily_token_limit FROM accounts ORDER BY username"
            ).fetchall()
            return [dict(row, quota=self._usage(db, row["id"], now)) for row in rows]

    def set_token_limit(self, username, limit):
        self._validate_token_limit(limit)
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute(
                "SELECT id FROM accounts WHERE username=?", (self.username(username),)
            ).fetchone()
            if user is None:
                raise ValueError("Unknown username.")
            db.execute(
                "UPDATE accounts SET daily_token_limit=? WHERE id=?", (limit, user[0])
            )
            return self._usage(db, user[0], self.clock())

    def reset_tokens(self, username):
        """Clear this user's tokens; retain their reset schedule and shared charges."""
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute(
                "SELECT id FROM accounts WHERE username=?", (self.username(username),)
            ).fetchone()
            if user is None:
                raise ValueError("Unknown username.")
            now = self.clock()
            if db.execute(
                "SELECT 1 FROM account_leases WHERE user_id=? AND kind='model' AND expires_at>?",
                (user[0], now),
            ).fetchone():
                raise AccountError(
                    "Wait for this user's current AI request to finish before resetting tokens.",
                    "tokens_in_use",
                    409,
                )
            self._bucket(db, user[0], now)
            # A late settlement of an expired request must not refund new usage.
            # Its server period is retained so shared accounting remains correct.
            db.execute(
                "UPDATE account_leases SET user_period=NULL WHERE user_id=? AND kind='model'",
                (user[0],),
            )
            db.execute("UPDATE quota_buckets SET tokens=0 WHERE scope=?", (user[0],))
            return self._usage(db, user[0], now)

    def change_password(self, user_id, current_password, new_password):
        if not 12 <= len(new_password) <= 128:
            raise ValueError("Use a password of 12–128 characters.")
        self._login_attempt("password:" + user_id, "password:" + user_id)
        with self.database._connect() as db:
            user = db.execute(
                "SELECT * FROM accounts WHERE id=?", (user_id,)
            ).fetchone()
        if (
            not user
            or user["disabled"]
            or not password_matches(current_password, user["password_hash"])
        ):
            raise AccountError(
                "Your current password is incorrect.", "invalid_current_password", 400
            )
        encoded = password_hash(new_password)
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE accounts SET password_hash=? WHERE id=? AND password_hash=? AND disabled=0",
                (encoded, user_id, user["password_hash"]),
            ).rowcount
            if not changed:
                raise AccountError(
                    "Your account changed. Please sign in again.", "unauthorized", 401
                )
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (user_id,))
            db.execute(
                "DELETE FROM login_attempts WHERE key=?", ("name:password:" + user_id,)
            )

    def reset_password(self, username, password):
        if not 12 <= len(password) <= 128:
            raise ValueError("Use a password of 12–128 characters.")
        encoded = password_hash(password)
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM accounts WHERE username=?", (self.username(username),)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown username.")
            db.execute(
                "UPDATE accounts SET password_hash=? WHERE id=?", (encoded, row[0])
            )
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (row[0],))

    def disable(self, username):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM accounts WHERE username=?", (self.username(username),)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown username.")
            db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (row[0],))
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (row[0],))

    def adopt_legacy(self, username):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM accounts WHERE username=? AND disabled=0",
                (self.username(username),),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown or disabled username.")
            return db.execute(
                "UPDATE sessions SET owner_id=? WHERE owner_id IS NULL", (row[0],)
            ).rowcount

    def enable(self, username):
        with self.database._connect() as db:
            if not db.execute(
                "UPDATE accounts SET disabled=0 WHERE username=?",
                (self.username(username),),
            ).rowcount:
                raise ValueError("Unknown username.")

    def _login_attempt(self, username, address):
        now = self.clock()
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempts WHERE started_at<=?", (now - 900,))
            for key, limit in (("name:" + username, 10), ("ip:" + address, 200)):
                row = db.execute(
                    "SELECT * FROM login_attempts WHERE key=?", (key,)
                ).fetchone()
                if row and row["attempts"] >= limit:
                    raise AccountError(
                        "Too many login attempts. Try again later.",
                        "login_rate_limit",
                        retry_after=math.ceil(row["started_at"] + 900 - now),
                    )
                db.execute(
                    "INSERT INTO login_attempts VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1",
                    (key, now),
                )

    def login(self, username, password, address):
        username = username.strip().lower()
        self._login_attempt(username, address)
        with self.database._connect() as db:
            user = db.execute(
                "SELECT * FROM accounts WHERE username=?", (username,)
            ).fetchone()
        matched = password_matches(
            password, user["password_hash"] if user else _dummy_password()
        )
        if not matched or not user or user["disabled"]:
            raise AccountError(
                "Incorrect username or password.", "invalid_credentials", 401
            )
        token, now = secrets.token_urlsafe(32), self.clock()
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck after hashing, so a concurrent reset/disable cannot issue a session.
            current = db.execute(
                "SELECT * FROM accounts WHERE id=?", (user["id"],)
            ).fetchone()
            if current["disabled"] or current["password_hash"] != user["password_hash"]:
                raise AccountError(
                    "Incorrect username or password.", "invalid_credentials", 401
                )
            db.execute("DELETE FROM account_sessions WHERE expires_at<=?", (now,))
            db.execute(
                "DELETE FROM account_sessions WHERE token_hash IN (SELECT token_hash FROM account_sessions WHERE user_id=? ORDER BY created_at DESC LIMIT -1 OFFSET 4)",
                (user["id"],),
            )
            db.execute(
                "INSERT INTO account_sessions VALUES (?,?,?,?)",
                (digest, user["id"], now + self.settings.account_session_seconds, now),
            )
            db.execute("DELETE FROM login_attempts WHERE key=?", ("name:" + username,))
        return token, Principal(
            user["id"], username, self, digest, current["role"] == "admin"
        )

    def authenticate(self, token):
        if not token or len(token) > 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.database._connect() as db:
            row = db.execute(
                "SELECT a.id,a.username,a.role FROM accounts a JOIN account_sessions s ON s.user_id=a.id WHERE s.token_hash=? AND s.expires_at>? AND a.disabled=0",
                (digest, self.clock()),
            ).fetchone()
        return (
            Principal(row["id"], row["username"], self, digest, row["role"] == "admin")
            if row
            else None
        )

    def session_principal(self, session_id):
        with self.database._connect() as db:
            row = db.execute(
                "SELECT a.id,a.username,a.role FROM sessions s JOIN accounts a ON a.id=s.owner_id WHERE s.id=? AND a.disabled=0",
                (session_id,),
            ).fetchone()
        if row is None:
            raise AccountError(
                "This job has no active account owner.", "account_unavailable", 403
            )
        return Principal(
            row["id"], row["username"], self, is_admin=row["role"] == "admin"
        )

    def logout(self, principal):
        with self.database._connect() as db:
            db.execute(
                "DELETE FROM account_sessions WHERE token_hash=?",
                (principal.session_hash,),
            )

    def session_active(self, principal):
        with self.database._connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM account_sessions s JOIN accounts a ON a.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND a.disabled=0",
                    (principal.session_hash, self.clock()),
                ).fetchone()
                is not None
            )

    def storage_usage(self, user_id):
        """Raw uploads plus each conversation's saved analysis inputs and results."""
        with self.database._connect() as db:
            uploads = db.execute(
                "SELECT coalesce(sum(json_extract(f.payload,'$.size_bytes')),0) FROM files f JOIN sessions s ON s.id=f.session_id WHERE s.owner_id=?",
                (user_id,),
            ).fetchone()[0]
            sessions = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM sessions WHERE owner_id=?", (user_id,)
                )
            ]
        results = 0
        ledger = self.settings.data_root / "analytics" / "workflows.sqlite3"
        if sessions and ledger.is_file():
            workflows = []
            with closing(sqlite3.connect(ledger)) as db:
                for start in range(0, len(sessions), 500):
                    chunk = sessions[start : start + 500]
                    workflows += [
                        row[0]
                        for row in db.execute(
                            "SELECT id FROM workflows WHERE session_id IN "
                            f"({','.join('?' * len(chunk))})",
                            chunk,
                        )
                    ]
            for workflow in workflows:
                for path in (ledger.parent / workflow).rglob("*"):
                    with suppress(OSError):
                        results += path.stat().st_size if path.is_file() else 0
        return {
            "uploads": uploads,
            "results": results,
            "used": uploads + results,
            "limit": self.settings.account_storage_bytes,
        }

    def upload_remaining(self, user_id):
        return max(
            0, self.settings.account_storage_bytes - self.storage_usage(user_id)["used"]
        )

    def _bucket(self, db, scope, now):
        db.execute(
            "INSERT OR IGNORE INTO quota_buckets(scope,started_at) VALUES (?,?)",
            (scope, now),
        )
        row = db.execute(
            "SELECT * FROM quota_buckets WHERE scope=?", (scope,)
        ).fetchone()
        if now >= row["started_at"] + DAY:
            started = row["started_at"] + int((now - row["started_at"]) // DAY) * DAY
            db.execute(
                "UPDATE quota_buckets SET started_at=?,tokens=0,jobs=0 WHERE scope=?",
                (started, scope),
            )
            row = db.execute(
                "SELECT * FROM quota_buckets WHERE scope=?", (scope,)
            ).fetchone()
        return row

    def usage(self, user_id):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            usage = self._usage(db, user_id, self.clock())
            usage["tokens_reserved"] = db.execute(
                "SELECT coalesce(sum(amount),0) FROM account_leases "
                "WHERE kind='model' AND user_id=? AND expires_at>?",
                (user_id, self.clock()),
            ).fetchone()[0]
        usage.update(self._recent_questions(user_id, usage["tokens_remaining"]))
        usage["storage"] = self.storage_usage(user_id)
        return usage

    def _recent_questions(self, user_id, remaining, limit=5):
        """Tokens per recent question, from the planner's per-stage records."""
        with self.database._connect() as db:
            rows = db.execute(
                "SELECT e.payload, e.created_at FROM events e "
                "JOIN sessions s ON s.id=e.session_id "
                "WHERE s.owner_id=? AND e.type='workflow.diagnostics' "
                "ORDER BY e.sequence DESC LIMIT 300",
                (user_id,),
            ).fetchall()
        turns = {}
        for row in rows:
            report = json_module.loads(row["payload"])
            usage = report.get("usage") or {}
            tokens = usage.get("total_tokens") or (
                (usage.get("prompt_tokens") or 0)
                + (usage.get("completion_tokens") or 0)
            )
            turn = turns.setdefault(
                report.get("turn_id"), {"tokens": 0, "at": row["created_at"]}
            )
            turn["tokens"] += tokens if isinstance(tokens, int) else 0
        recent = [turn for turn in turns.values() if turn["tokens"]][:limit]
        average = (
            round(sum(t["tokens"] for t in recent) / len(recent)) if recent else None
        )
        return {
            "recent_questions": recent,
            "average_question_tokens": average,
            "questions_left": remaining // average if average else None,
        }

    def _token_limit(self, db, user_id):
        row = db.execute(
            "SELECT daily_token_limit FROM accounts WHERE id=?", (user_id,)
        ).fetchone()
        return (
            row[0] if row and row[0] is not None else self.settings.account_daily_tokens
        )

    def _usage(self, db, user_id, now):
        user = self._bucket(db, user_id, now)
        server = self._bucket(db, "server", now)
        limit = self._token_limit(db, user_id)
        return {
            "tokens_used": user["tokens"],
            "token_limit": limit,
            "default_token_limit": self.settings.account_daily_tokens,
            "tokens_remaining": max(0, limit - user["tokens"]),
            "jobs_used": user["jobs"],
            "job_limit": self.settings.account_daily_jobs,
            "resets_at": _stamp(user["started_at"] + DAY),
            "server_tokens_remaining": max(
                0, self.settings.server_daily_tokens - server["tokens"]
            ),
            "server_token_limit": self.settings.server_daily_tokens,
            "server_tokens_used": server["tokens"],
            "server_resets_at": _stamp(server["started_at"] + DAY),
            "window_seconds": DAY,
        }

    def _slot(self, db, user_id, kind, total, per_user, ttl):
        now = self.clock()
        db.execute("DELETE FROM account_leases WHERE expires_at<=?", (now,))
        counts = db.execute(
            "SELECT count(*),coalesce(sum(user_id=?),0) FROM account_leases WHERE kind=?",
            (user_id, kind),
        ).fetchone()
        if counts[0] >= total or counts[1] >= per_user:
            raise AccountError(
                "Your request or the server is already busy. Please wait for current work to finish.",
                "concurrency_limit",
                retry_after=5,
            )
        lease = secrets.token_hex(16)
        db.execute(
            "INSERT INTO account_leases(id,user_id,kind,expires_at) VALUES (?,?,?,?)",
            (lease, user_id, kind, now + ttl),
        )
        return lease

    def acquire(self, user_id, kind, total, per_user=1, ttl=600):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._slot(db, user_id, kind, total, per_user, ttl)

    def release(self, lease):
        with self.database._connect() as db:
            db.execute("DELETE FROM account_leases WHERE id=?", (lease,))

    def _charge(self, db, user_id, field, amount):
        now = self.clock()
        periods = []
        for scope, limit in (
            (
                user_id,
                self._token_limit(db, user_id)
                if field == "tokens"
                else self.settings.account_daily_jobs,
            ),
            ("server", getattr(self.settings, "server_daily_" + field)),
        ):
            bucket = self._bucket(db, scope, now)
            if bucket[field] + amount > limit:
                label = "Your" if scope == user_id else "The server's shared"
                reset = bucket["started_at"] + DAY
                remaining = max(0, limit - bucket[field])
                message = f"{label} 24-hour {field} allowance has insufficient capacity. It resets at {_stamp(reset)}."
                details = None
                if field == "tokens":
                    message = (
                        f"This AI request needs room for up to {amount:,} tokens "
                        f"(input plus maximum output). {label} 24-hour allowance "
                        f"has {remaining:,} tokens remaining. It resets at {_stamp(reset)}."
                    )
                    details = {
                        "required_tokens": amount,
                        "remaining_tokens": remaining,
                        "token_limit": limit,
                        "scope": "user" if scope == user_id else "server",
                        "resets_at": _stamp(reset),
                    }
                raise AccountError(
                    message,
                    "daily_" + field + "_limit",
                    retry_after=math.ceil(reset - now),
                    details=details,
                )
            periods.append(bucket["started_at"])
        # Values are from the fixed internal field names tokens/jobs, never input.
        for scope in (user_id, "server"):
            db.execute(
                f"UPDATE quota_buckets SET {field}={field}+? WHERE scope=?",
                (amount, scope),
            )
        return periods

    def reserve_tokens(self, user_id, amount, *, lease=None):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if lease is None:
                lease = self._slot(
                    db, user_id, "model", self.settings.max_model_calls, 1, 240
                )
            elif not db.execute(
                "SELECT 1 FROM account_leases WHERE id=? AND user_id=? AND kind='model' AND amount=0 AND expires_at>?",
                (lease, user_id, self.clock()),
            ).fetchone():
                raise AccountError(
                    "The model request slot expired. Please retry.",
                    "concurrency_limit",
                    retry_after=1,
                )
            user_period, server_period = self._charge(db, user_id, "tokens", amount)
            db.execute(
                "UPDATE account_leases SET amount=?,user_period=?,server_period=? WHERE id=?",
                (amount, user_period, server_period, lease),
            )
            return lease

    def settle_tokens(self, lease, used=None):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM account_leases WHERE id=? AND kind='model'", (lease,)
            ).fetchone()
            if row is None:
                return
            if used is not None:
                difference = used - row["amount"]
                for scope, period in (
                    (row["user_id"], row["user_period"]),
                    ("server", row["server_period"]),
                ):
                    db.execute(
                        "UPDATE quota_buckets SET tokens=max(0,tokens+?) WHERE scope=? AND started_at=?",
                        (difference, scope, period),
                    )
            db.execute("DELETE FROM account_leases WHERE id=?", (lease,))

    def admit_jobs(self, user_id, count=1):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = self._slot(
                db, user_id, "job", self.settings.account_pending_jobs, 1, 86400
            )
            user_period, server_period = self._charge(db, user_id, "jobs", count)
            db.execute(
                "UPDATE account_leases SET amount=?,user_period=?,server_period=? WHERE id=?",
                (count, user_period, server_period, lease),
            )
            return lease

    def _refund_jobs(self, lease, count=None, *, close=False):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM account_leases WHERE id=? AND kind='job'", (lease,)
            ).fetchone()
            if row:
                count = row["amount"] if count is None else min(count, row["amount"])
                for scope, period in (
                    (row["user_id"], row["user_period"]),
                    ("server", row["server_period"]),
                ):
                    db.execute(
                        "UPDATE quota_buckets SET jobs=max(0,jobs-?) WHERE scope=? AND started_at=?",
                        (count, scope, period),
                    )
                if close:
                    db.execute("DELETE FROM account_leases WHERE id=?", (lease,))
                else:
                    db.execute(
                        "UPDATE account_leases SET amount=amount-? WHERE id=?",
                        (count, lease),
                    )

    def abort_admission(self, lease):
        """Refund only when durable job creation itself failed, never after execution."""
        self._refund_jobs(lease, close=True)

    def refund_unstarted_job(self, lease):
        """Return one daily job that never started; its pending slot stays held."""
        self._refund_jobs(lease, 1)

    def _users_at_limit(self, kind, per_user):
        with self.database._connect() as db:
            rows = db.execute(
                "SELECT user_id FROM account_leases WHERE kind=? AND expires_at>? "
                "GROUP BY user_id HAVING count(*)>=?",
                (kind, self.clock(), per_user),
            ).fetchall()
        return {row[0] for row in rows}

    async def wait_slot(self, user_id, kind, total, per_user, ttl, timeout):
        """Take a slot in arrival order.

        Someone already at their own limit does not hold up the people behind
        them. Raises TimeoutError when no slot frees up in time.
        """
        ticket = (user_id, object())
        waiting = self.waiting[kind]
        waiting.append(ticket)
        try:
            async with asyncio.timeout(timeout):
                while True:
                    busy = self._users_at_limit(kind, per_user)
                    if next((t for t in waiting if t[0] not in busy), None) is ticket:
                        try:
                            return self.acquire(user_id, kind, total, per_user, ttl)
                        except AccountError as error:
                            if error.code != "concurrency_limit":
                                raise
                    await asyncio.sleep(0.2)
        finally:
            waiting.remove(ticket)

    @asynccontextmanager
    async def execution_slot(self, user_id, admission=None):
        """Wait in line for a slot, then run; waiting and running have separate limits.

        A job that times out or is cancelled before it starts gets its daily job back.
        """
        lease = None
        try:
            lease = await self.wait_slot(
                user_id,
                "execution",
                self.settings.account_running_jobs,
                1,
                self.settings.account_job_seconds + 30,
                self.settings.account_queue_seconds,
            )
        except (TimeoutError, asyncio.CancelledError) as error:
            if admission:
                self.refund_unstarted_job(admission)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise AccountError(
                "The server stayed busy, so your calculation did not start. "
                "It was not counted against your daily jobs; please try again.",
                "queue_time_limit",
                429,
            ) from error
        try:
            async with asyncio.timeout(self.settings.account_job_seconds):
                yield
        except TimeoutError as error:
            raise AccountError(
                "The job exceeded its execution time allowance.",
                "job_time_limit",
                429,
            ) from error
        finally:
            self.release(lease)


async def _prompt_tokens(client, path, payload):
    """Count the rendered chat with the configured model's own tokenizer.

    vLLM's /tokenize does no inference. It applies the chat template, including
    the generation prefix and thinking settings. JSON output schemas constrain
    decoding; their serialized bytes are not the model's input-token count.
    Other transports retain the conservative estimate if counting is unavailable.
    """
    fallback = len(json_module.dumps(payload, ensure_ascii=False).encode()) + 1024
    if (
        path.rstrip("/") != "/chat/completions"
        or not isinstance(payload.get("model"), str)
        or not isinstance(payload.get("messages"), list)
        or not isinstance(getattr(client, "base_url", None), httpx.URL)
    ):
        return fallback, "conservative_estimate"
    request = {
        key: payload[key]
        for key in (
            "model",
            "messages",
            "tools",
            "add_generation_prompt",
            "continue_final_message",
            "add_special_tokens",
            "chat_template",
        )
        if key in payload
    }
    template = dict(payload.get("chat_template_kwargs") or {})
    if payload.get("reasoning_effort") is not None:
        template["reasoning_effort"] = payload["reasoning_effort"]
        template.setdefault("enable_thinking", payload["reasoning_effort"] != "none")
    if "documents" in payload:
        template["documents"] = payload["documents"]
    if template:
        request["chat_template_kwargs"] = template
    base = client.base_url.path.rstrip("/").removesuffix("/v1")
    url = client.base_url.copy_with(path=base + "/tokenize", query=None, fragment=None)
    try:
        response = await client.post(url, json=request, timeout=10.0)
        if response.is_success:
            count = response.json().get("count")
            if type(count) is int and 0 <= count <= 10_000_000:
                return count, "model_tokenizer"
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        pass
    return fallback, "conservative_estimate"


def _reported_usage(usage):
    """Total tokens from provider usage, or None when it cannot be established."""
    if not isinstance(usage, dict):
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if (
        type(prompt) is not int
        or type(completion) is not int
        or min(prompt, completion) < 0
    ):
        return None
    total = usage.get("total_tokens")
    return (
        max(prompt + completion, total) if type(total) is int else prompt + completion
    )


@asynccontextmanager
async def _metered(client, path, payload, max_tokens):
    """Reserve before inference; settle what the caller records in meter["used"].

    The caller sets used=0 for a model-server error and the reported usage on
    success. Unreachable servers are free; timeouts and cancellations charge only
    the counted input; success without usage keeps the reservation.
    """
    principal = current_principal.get()
    if principal is None:
        yield None
        return
    # Count before inference, then reserve the actual prompt plus maximum output.
    # The model slot bounds both tokenization and inference across all users.
    output = max_tokens or payload.get(
        "max_completion_tokens", payload.get("max_tokens", 3072)
    )
    try:
        # Wait in line briefly rather than failing when every model slot is busy.
        lease = await principal.accounts.wait_slot(
            principal.user_id,
            "model",
            principal.accounts.settings.max_model_calls,
            1,
            240,
            MODEL_QUEUE_SECONDS,
        )
    except TimeoutError as error:
        raise AccountError(
            "The language model is busy with other people's questions. Please try again shortly.",
            "concurrency_limit",
            retry_after=5,
        ) from error
    prompt = method = None
    try:
        prompt, method = await _prompt_tokens(client, path, payload)
        principal.accounts.reserve_tokens(
            principal.user_id, prompt + output, lease=lease
        )
    except AccountError as error:
        principal.accounts.release(lease)
        if error.details is not None:
            error.details.update(
                prompt_tokens=prompt, max_output_tokens=output, count_method=method
            )
        raise
    except BaseException:
        principal.accounts.release(lease)
        raise
    meter = {"used": None}
    try:
        yield meter
    except (httpx.ConnectError, httpx.ConnectTimeout):
        meter["used"] = 0  # The request never reached the model server.
        raise
    except BaseException:
        # Timed out or cancelled: the model may have read the prompt, but the
        # user received no output, so only the counted input is charged.
        if meter["used"] is None:
            meter["used"] = prompt
        raise
    finally:
        principal.accounts.settle_tokens(lease, meter["used"])


async def model_post(client, path, *, json, max_tokens=None):
    """Meter every real transport attempt, including repair calls and retries."""
    async with _metered(client, path, json, max_tokens) as meter:
        async with asyncio.timeout(180):
            response = await client.post(path, json=json)
        if meter is not None:
            if not response.is_success:
                meter["used"] = 0  # The model server rejected or failed the request.
            else:
                try:
                    meter["used"] = _reported_usage(response.json().get("usage"))
                except (ValueError, AttributeError, TypeError):
                    pass
        return response


async def model_stream(client, path, *, json, on_reasoning, max_tokens=None):
    """Like model_post, but streams reasoning to on_reasoning as it is generated.

    Returns a non-streamed chat-completion body. A server that answers with
    plain JSON instead of an event stream is accepted unchanged.
    """
    request = {**json, "stream": True, "stream_options": {"include_usage": True}}
    async with _metered(client, path, request, max_tokens) as meter:
        async with asyncio.timeout(180):
            async with client.stream("POST", path, json=request) as response:
                if not response.is_success:
                    if meter is not None:
                        meter["used"] = 0
                    await response.aread()
                    response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    body = json_module.loads(await response.aread())
                else:
                    body = await _collect_stream(response, on_reasoning)
        if meter is not None:
            meter["used"] = _reported_usage(body.get("usage"))
        return body


async def _collect_stream(response, on_reasoning):
    content, reasoning, finish, usage = [], [], None, None
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json_module.loads(data)
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("reasoning_content") or delta.get("reasoning")
            if text:
                reasoning.append(text)
                await on_reasoning(text)
            if delta.get("content"):
                content.append(delta["content"])
            finish = choice.get("finish_reason") or finish
    message = {"content": "".join(content), "reasoning": "".join(reasoning)}
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage}
