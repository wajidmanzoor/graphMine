"""Administrator-created accounts and atomic, durable 24-hour resource budgets.

No signup endpoint exists. Passwords use salted scrypt; bearer/cookie credentials
are random and stored only as hashes. Quotas reserve before inference and settle
from provider usage. Failed/unknown requests retain the conservative reservation.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json as json_module
import math
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache

from .identity import AccountError, Principal, current_principal

DAY = 86400
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

    @staticmethod
    def username(value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", value):
            raise ValueError(
                "Username must be 3–64 letters, digits, dots, underscores or hyphens."
            )
        return value

    def create_user(self, username, password):
        username = self.username(username)
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
                "INSERT INTO accounts VALUES (?,?,?,?,0)",
                (user_id, username, encoded, now),
            )
            db.execute(
                "INSERT INTO quota_buckets(scope,started_at) VALUES (?,?)",
                (user_id, now),
            )
        return {"id": user_id, "username": username}

    def list_users(self):
        with self.database._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,username,created_at,disabled FROM accounts ORDER BY username"
                )
            ]

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
        return token, Principal(user["id"], username, self, digest)

    def authenticate(self, token):
        if not token or len(token) > 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.database._connect() as db:
            row = db.execute(
                "SELECT a.id,a.username FROM accounts a JOIN account_sessions s ON s.user_id=a.id WHERE s.token_hash=? AND s.expires_at>? AND a.disabled=0",
                (digest, self.clock()),
            ).fetchone()
        return Principal(row["id"], row["username"], self, digest) if row else None

    def session_principal(self, session_id):
        with self.database._connect() as db:
            row = db.execute(
                "SELECT a.id,a.username FROM sessions s JOIN accounts a ON a.id=s.owner_id WHERE s.id=? AND a.disabled=0",
                (session_id,),
            ).fetchone()
        if row is None:
            raise AccountError(
                "This job has no active account owner.", "account_unavailable", 403
            )
        return Principal(row["id"], row["username"], self)

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

    def upload_remaining(self, user_id):
        with self.database._connect() as db:
            used = db.execute(
                "SELECT coalesce(sum(json_extract(f.payload,'$.size_bytes')),0) FROM files f JOIN sessions s ON s.id=f.session_id WHERE s.owner_id=?",
                (user_id,),
            ).fetchone()[0]
        return max(0, self.settings.account_storage_bytes - used)

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
            user = self._bucket(db, user_id, self.clock())
            server = self._bucket(db, "server", self.clock())
        return {
            "tokens_used": user["tokens"],
            "token_limit": self.settings.account_daily_tokens,
            "tokens_remaining": max(
                0, self.settings.account_daily_tokens - user["tokens"]
            ),
            "jobs_used": user["jobs"],
            "job_limit": self.settings.account_daily_jobs,
            "resets_at": _stamp(user["started_at"] + DAY),
            "server_tokens_remaining": max(
                0, self.settings.server_daily_tokens - server["tokens"]
            ),
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
            (user_id, getattr(self.settings, "account_daily_" + field)),
            ("server", getattr(self.settings, "server_daily_" + field)),
        ):
            bucket = self._bucket(db, scope, now)
            if bucket[field] + amount > limit:
                label = "Your" if scope == user_id else "The server's shared"
                reset = bucket["started_at"] + DAY
                raise AccountError(
                    f"{label} 24-hour {field} allowance has insufficient capacity. It resets at {_stamp(reset)}.",
                    "daily_" + field + "_limit",
                    retry_after=math.ceil(reset - now),
                )
            periods.append(bucket["started_at"])
        # Values are from the fixed internal field names tokens/jobs, never input.
        for scope in (user_id, "server"):
            db.execute(
                f"UPDATE quota_buckets SET {field}={field}+? WHERE scope=?",
                (amount, scope),
            )
        return periods

    def reserve_tokens(self, user_id, amount):
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = self._slot(
                db, user_id, "model", self.settings.max_model_calls, 1, 240
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

    def abort_admission(self, lease):
        """Refund only when durable job creation itself failed, never after execution."""
        with self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM account_leases WHERE id=? AND kind='job'", (lease,)
            ).fetchone()
            if row:
                for scope, period in (
                    (row["user_id"], row["user_period"]),
                    ("server", row["server_period"]),
                ):
                    db.execute(
                        "UPDATE quota_buckets SET jobs=max(0,jobs-?) WHERE scope=? AND started_at=?",
                        (row["amount"], scope, period),
                    )
                db.execute("DELETE FROM account_leases WHERE id=?", (lease,))

    @asynccontextmanager
    async def execution_slot(self, user_id):
        lease = None
        try:
            async with asyncio.timeout(self.settings.account_job_seconds):
                while lease is None:
                    try:
                        lease = self.acquire(
                            user_id,
                            "execution",
                            self.settings.account_running_jobs,
                            ttl=self.settings.account_job_seconds + 30,
                        )
                    except AccountError as error:
                        if error.code != "concurrency_limit":
                            raise
                        await asyncio.sleep(0.2)
                yield
        except TimeoutError as error:
            raise AccountError(
                "The job exceeded its queue/execution time allowance.",
                "job_time_limit",
                429,
            ) from error
        finally:
            if lease:
                self.release(lease)


async def model_post(client, path, *, json, max_tokens=None):
    """Meter every real transport attempt, including repair calls and retries."""
    principal = current_principal.get()
    if principal is None:
        return await client.post(path, json=json)
    # UTF-8 bytes plus template headroom is deliberately conservative. Settle
    # against prompt + completion usage (including cached/reasoning tokens).
    output = max_tokens or json.get(
        "max_completion_tokens", json.get("max_tokens", 3072)
    )
    encoded = json_module.dumps(json, ensure_ascii=False).encode()
    reserved = len(encoded) + 1024 + output
    lease = principal.accounts.reserve_tokens(principal.user_id, reserved)
    used = None
    try:
        async with asyncio.timeout(180):
            response = await client.post(path, json=json)
        if response.is_success:
            try:
                usage = response.json().get("usage", {})
                prompt, completion = (
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                )
                if (
                    type(prompt) is int
                    and type(completion) is int
                    and min(prompt, completion) >= 0
                ):
                    used = prompt + completion
                    total = usage.get("total_tokens")
                    if type(total) is int:
                        used = max(used, total)
            except (ValueError, AttributeError, TypeError):
                pass
        return response
    finally:
        principal.accounts.settle_tokens(lease, used)
