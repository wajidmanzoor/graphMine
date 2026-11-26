"""Application-owned, bounded database resources; never shared across owners."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Condition

from .analytics import AnalyticsError
from .database_job_context import checkpoint
from .identity import current_principal

current_database_pools = ContextVar("graphmine_database_pools", default=None)
logger = logging.getLogger(__name__)


@contextmanager
def pool_scope(pools):
    token = current_database_pools.set(pools)
    try:
        yield
    finally:
        current_database_pools.reset(token)


class DatabasePoolMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        with pool_scope(scope["app"].state.runtime.database_pools):
            await self.app(scope, receive, send)


def check_source_stamp(source):
    """A source read before an edit/delete cannot start borrowing afterwards."""
    stamp = source._config_stamp
    if stamp is None:
        return
    path, inode, modified, size = stamp
    try:
        info = path.stat()
        valid = (info.st_ino, info.st_mtime_ns, info.st_size) == (inode, modified, size)
    except OSError:
        valid = False
    if not valid:
        raise AnalyticsError("The database connection changed. Reload it before retrying.", "source_changed", 409)


@dataclass(eq=False, repr=False)
class _Resource:
    key: tuple
    value: object
    used_at: float
    active: int = 0
    waiting: int = 0
    retired: bool = False


class DatabasePools:
    def __init__(self, settings):
        self.settings = settings
        self.limit = settings.database_pool_limit
        self.size = settings.database_pool_size
        self.wait_seconds = settings.database_pool_wait_seconds
        self.idle_seconds = settings.database_pool_idle_seconds
        self._secret = secrets.token_bytes(32)
        self._condition = Condition()
        self._entries = {}
        self._closing = set()
        self._closed = False

    @staticmethod
    def _owner():
        principal = current_principal.get()
        return principal.user_id if principal else ""

    def _dispose(self, entries):
        for entry in entries:
            try:
                entry.value.close()
            except Exception:
                # Driver exceptions can include endpoint/credential details.
                logger.warning("Could not close a retired database resource")
            finally:
                with self._condition:
                    self._closing.discard(entry)
                    self._condition.notify_all()

    def _retire(self, entry, disposal):
        entry.retired = True
        if not entry.active and entry not in self._closing:
            self._entries.pop(entry.key, None)
            self._closing.add(entry)
            disposal.append(entry)

    def reap(self):
        disposal = []
        with self._condition:
            now = time.monotonic()
            for entry in list(self._entries.values()):
                if not entry.active and not entry.waiting and now - entry.used_at >= self.idle_seconds:
                    self._retire(entry, disposal)
            self._condition.notify_all()
        self._dispose(disposal)

    def invalidate(self, source_id):
        disposal = []
        owner = self._owner()
        with self._condition:
            for entry in list(self._entries.values()):
                if entry.key[:2] == (owner, source_id):
                    self._retire(entry, disposal)
            self._condition.notify_all()
        self._dispose(disposal)

    def retire(self, value):
        """Stop reconnecting a failed pool; drain any other borrowers first."""
        disposal = []
        with self._condition:
            for entry in list(self._entries.values()):
                if entry.value is value:
                    self._retire(entry, disposal)
            self._condition.notify_all()
        self._dispose(disposal)

    @contextmanager
    def lease(self, source, kind, signature, factory):
        check_source_stamp(source)
        checkpoint()
        # Password changes invalidate reuse without changing dataset lineage.
        stamp = source._config_stamp[1:] if source._config_stamp else None
        digest = hmac.new(self._secret, json.dumps([source.revision, stamp, signature], sort_keys=True).encode(), hashlib.sha256).digest()
        slot = (self._owner(), source.id, kind)
        key = (*slot, digest)
        entry = None
        acquired = False
        deadline = time.monotonic() + self.wait_seconds
        while entry is None:
            disposal = []
            try:
                with self._condition:
                    checkpoint()
                    check_source_stamp(source)
                    if self._closed:
                        raise AnalyticsError("Database connections are stopping.", "database_unavailable", 503)
                    now = time.monotonic()
                    for old in list(self._entries.values()):
                        if (old.key[:3] == slot and old.key != key) or (not old.active and not old.waiting and now - old.used_at >= self.idle_seconds):
                            self._retire(old, disposal)
                    entry = self._entries.get(key)
                    if entry is None:
                        if len(self._entries) + len(self._closing) >= self.limit:
                            idle = [item for item in self._entries.values() if not item.active and not item.waiting]
                            if idle and not disposal:
                                self._retire(min(idle, key=lambda item: item.used_at), disposal)
                            elif not self._closing:
                                raise AnalyticsError("Database connections are busy. Retry shortly.", "database_busy", 429)
                            if not disposal:
                                remaining = deadline - now
                                if remaining <= 0:
                                    raise AnalyticsError("Timed out waiting for database resources to close.", "database_busy", 429)
                                self._condition.wait(min(remaining, 0.1))
                            continue
                        # Factories construct lazy drivers/pools, not queries.
                        entry = _Resource(key, factory(), now)
                        self._entries[key] = entry
                    if entry.waiting >= self.size:
                        raise AnalyticsError("Database connection queue is full. Retry shortly.", "database_busy", 429)
                    entry.waiting += 1
                    try:
                        while True:
                            checkpoint()
                            check_source_stamp(source)
                            if self._closed or entry.retired:
                                raise AnalyticsError("The database connection changed or stopped. Retry with the current connection.", "source_changed", 409)
                            if entry.active < self.size:
                                entry.active += 1
                                acquired = True
                                break
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise AnalyticsError("Timed out waiting for a database connection. Retry shortly.", "database_busy", 429)
                            self._condition.wait(min(remaining, 0.1))
                    finally:
                        entry.waiting -= 1
            finally:
                self._dispose(disposal)
        try:
            yield entry.value
        finally:
            if acquired:
                disposal = []
                with self._condition:
                    entry.active -= 1
                    entry.used_at = time.monotonic()
                    if entry.retired and not entry.active:
                        self._retire(entry, disposal)
                    self._condition.notify_all()
                self._dispose(disposal)

    def close(self):
        disposal = []
        with self._condition:
            self._closed = True
            for entry in list(self._entries.values()):
                self._retire(entry, disposal)
            self._condition.notify_all()
        self._dispose(disposal)

    def drain(self, timeout=30):
        """Retire every old connection after switch admission has closed."""
        disposal = []
        deadline = time.monotonic() + timeout
        with self._condition:
            for entry in list(self._entries.values()):
                self._retire(entry, disposal)
            self._condition.notify_all()
        self._dispose(disposal)
        with self._condition:
            while self._entries or self._closing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AnalyticsError("Database connections did not drain in time.", "database_sessions_busy", 409)
                self._condition.wait(min(remaining, .1))


@contextmanager
def resource(source, kind, signature, factory):
    pools = current_database_pools.get()
    if pools is None:
        # CLI callers and connection validation have explicit one-shot lifetimes.
        check_source_stamp(source)
        checkpoint()
        value = factory()
        try:
            yield value
        finally:
            value.close()
    else:
        with pools.lease(source, kind, signature, factory) as value:
            yield value


def invalidate(source_id):
    pools = current_database_pools.get()
    if pools is not None:
        pools.invalidate(source_id)
