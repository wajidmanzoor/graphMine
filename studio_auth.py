"""Users, roles and login sessions for Dataset Studio (standard library only).

Users live in ``<workspace>/auth/users.json``. Passwords are stored only as
salted PBKDF2-SHA256 hashes. Sessions are random tokens sent in an HttpOnly,
SameSite=Strict cookie; only their SHA-256 is written to
``<workspace>/auth/sessions.json``, so restarting the server keeps people
signed in without storing anything that works as a login.

Roles:
- ``admin`` sees every dataset and manages users (create users and admins,
  grant dataset access, reset passwords, remove users).
- ``user`` sees only the datasets granted to them, plus datasets they create.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROLES = ("admin", "user")
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{1,31}")
MIN_PASSWORD = 8
ITERATIONS = 310_000
SESSION_DAYS = 7
# After this many wrong passwords for one name, wait before the next try.
MAX_FAILURES, LOCK_SECONDS, FAILURE_WINDOW = 5, 300, 900


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


# Compared against for unknown names, so a wrong name costs the same as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


class AuthError(ValueError):
    """Bad credentials or a refused account change (shown to the person)."""


class Forbidden(PermissionError):
    pass


class Auth:
    def __init__(self, folder: Path):
        self.folder = folder
        self.users_path = folder / "users.json"
        self.sessions_path = folder / "sessions.json"
        self.lock = threading.RLock()
        self._failures: dict[str, list[float]] = {}
        self.users = self._load(self.users_path).get("users", {})
        self.sessions = self._load(self.sessions_path).get("sessions", {})
        self._drop_expired()

    # ---------------- storage ----------------
    @staticmethod
    def _load(path: Path) -> dict:
        return json.loads(path.read_text()) if path.is_file() else {}

    def _save(self, path: Path, key: str, value: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.folder.chmod(0o700)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, key: value}, indent=2, ensure_ascii=False) + "\n")
        tmp.chmod(0o600)
        tmp.replace(path)

    def _save_users(self) -> None:
        self._save(self.users_path, "users", self.users)

    def _save_sessions(self) -> None:
        self._save(self.sessions_path, "sessions", self.sessions)

    @property
    def has_users(self) -> bool:
        return bool(self.users)

    # ---------------- users ----------------
    @staticmethod
    def _check_username(username: str) -> str:
        username = (username or "").strip().lower()
        if not USERNAME.fullmatch(username):
            raise AuthError("Usernames are 2–32 characters: lowercase letters, digits, dot, dash or underscore")
        return username

    @staticmethod
    def _check_password(password: str) -> str:
        if len(password or "") < MIN_PASSWORD:
            raise AuthError(f"Passwords need at least {MIN_PASSWORD} characters")
        return password

    def public(self, username: str) -> dict:
        user = self.users[username]
        return {"username": username, "role": user["role"], "datasets": sorted(user.get("datasets", [])),
                "disabled": bool(user.get("disabled")), "created_at": user.get("created_at"),
                "created_by": user.get("created_by"), "last_login": user.get("last_login")}

    def list_users(self) -> list[dict]:
        with self.lock:
            return [self.public(name) for name in sorted(self.users)]

    def create_user(self, username: str, password: str, role: str = "user", datasets=(), by: str | None = None) -> dict:
        with self.lock:
            username = self._check_username(username)
            if username in self.users:
                raise AuthError(f"User {username!r} already exists")
            if role not in ROLES:
                raise AuthError(f"Role must be one of {', '.join(ROLES)}")
            self.users[username] = {"role": role, "password": hash_password(self._check_password(password)),
                                    "datasets": sorted(set(datasets)), "created_at": _iso(_now()), "created_by": by}
            self._save_users()
            return self.public(username)

    def _admins(self) -> list[str]:
        return [n for n, u in self.users.items() if u["role"] == "admin" and not u.get("disabled")]

    def update_user(self, username: str, *, role=None, datasets=None, password=None, disabled=None) -> dict:
        with self.lock:
            if username not in self.users:
                raise KeyError(f"user {username}")
            user = self.users[username]
            losing_admin = user["role"] == "admin" and not user.get("disabled") and (
                (role is not None and role != "admin") or disabled)
            if losing_admin and self._admins() == [username]:
                raise AuthError("Keep at least one active admin")
            if role is not None:
                if role not in ROLES:
                    raise AuthError(f"Role must be one of {', '.join(ROLES)}")
                user["role"] = role
            if datasets is not None:
                user["datasets"] = sorted(set(datasets))
            if password:
                user["password"] = hash_password(self._check_password(password))
                self._end_sessions_of(username)
            if disabled is not None:
                user["disabled"] = bool(disabled)
                if disabled:
                    self._end_sessions_of(username)
            self._save_users()
            return self.public(username)

    def delete_user(self, username: str) -> None:
        with self.lock:
            if username not in self.users:
                raise KeyError(f"user {username}")
            if self._admins() == [username]:
                raise AuthError("Keep at least one active admin")
            del self.users[username]
            self._end_sessions_of(username)
            self._save_users()

    def change_password(self, username: str, current: str, new: str) -> None:
        with self.lock:
            if not verify_password(current or "", self.users[username]["password"]):
                raise AuthError("The current password is not right")
            self.users[username]["password"] = hash_password(self._check_password(new))
            self._save_users()

    def grant(self, username: str, key: str) -> None:
        """Give a user access to a dataset (admins already see all)."""
        with self.lock:
            user = self.users.get(username)
            if user and user["role"] != "admin" and key not in user.get("datasets", []):
                user["datasets"] = sorted(set(user.get("datasets", [])) | {key})
                self._save_users()

    def forget_dataset(self, key: str) -> None:
        with self.lock:
            changed = False
            for user in self.users.values():
                if key in user.get("datasets", []):
                    user["datasets"] = [k for k in user["datasets"] if k != key]
                    changed = True
            if changed:
                self._save_users()

    # ---------------- access ----------------
    def is_admin(self, username: str) -> bool:
        user = self.users.get(username)
        return bool(user and user["role"] == "admin")

    def can_access(self, username: str, key: str) -> bool:
        user = self.users.get(username)
        if not user or user.get("disabled"):
            return False
        return user["role"] == "admin" or key in user.get("datasets", [])

    def visible(self, username: str, datasets: list[dict]) -> list[dict]:
        return [d for d in datasets if self.can_access(username, d["key"])]

    # ---------------- sessions ----------------
    @staticmethod
    def _token_id(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def login(self, username: str, password: str) -> str:
        """A new session token, or AuthError. Wrong passwords are throttled per name."""
        name = (username or "").strip().lower()
        with self.lock:
            recent = [t for t in self._failures.get(name, []) if time.time() - t < FAILURE_WINDOW]
            if len(recent) >= MAX_FAILURES and time.time() - recent[-1] < LOCK_SECONDS:
                wait = int(LOCK_SECONDS - (time.time() - recent[-1]))
                raise AuthError(f"Too many wrong passwords. Try again in {wait // 60 + 1} minutes.")
            user = self.users.get(name)
            # Verify even for unknown names so timing does not reveal which names exist.
            ok = verify_password(password or "", user["password"] if user else _DUMMY_HASH)
            if not user or not ok or user.get("disabled"):
                self._failures[name] = recent + [time.time()]
                raise AuthError("Wrong username or password")
            self._failures.pop(name, None)
            token = secrets.token_urlsafe(32)
            now = _now()
            self.sessions[self._token_id(token)] = {"username": name, "created_at": _iso(now),
                                                    "expires_at": _iso(now + timedelta(days=SESSION_DAYS)),
                                                    "current": None}
            user["last_login"] = _iso(now)
            self._save_users()
            self._save_sessions()
            return token

    def session(self, token: str | None) -> dict | None:
        """The session for a cookie token (with its id), or None when absent, expired or disabled."""
        if not token:
            return None
        with self.lock:
            sid = self._token_id(token)
            record = self.sessions.get(sid)
            if not record:
                return None
            user = self.users.get(record["username"])
            if not user or user.get("disabled") or record["expires_at"] < _iso(_now()):
                self.sessions.pop(sid, None)
                self._save_sessions()
                return None
            return {**record, "id": sid}

    def set_current(self, sid: str, key: str | None) -> None:
        with self.lock:
            if sid in self.sessions and self.sessions[sid].get("current") != key:
                self.sessions[sid]["current"] = key
                self._save_sessions()

    def logout(self, sid: str) -> None:
        with self.lock:
            if self.sessions.pop(sid, None) is not None:
                self._save_sessions()

    def _end_sessions_of(self, username: str) -> None:
        dropped = [sid for sid, s in self.sessions.items() if s["username"] == username]
        for sid in dropped:
            del self.sessions[sid]
        if dropped:
            self._save_sessions()

    def _drop_expired(self) -> None:
        now = _iso(_now())
        expired = [sid for sid, s in self.sessions.items() if s["expires_at"] < now]
        for sid in expired:
            del self.sessions[sid]
        if expired:
            self._save_sessions()
