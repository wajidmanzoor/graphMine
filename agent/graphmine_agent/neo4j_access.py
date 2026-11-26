"""Cross-process admission and session draining for a backend switch."""

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import os
from pathlib import Path
import time

from .errors import AnalyticsError

_held = ContextVar("neo4j_access_roots", default=frozenset())


def busy():
    return AnalyticsError("The database backend is switching. Retry when it finishes.", "database_switching", 409)


@contextmanager
def _file(settings, name):
    root = Path(settings.data_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def admission(settings, *, switching=False):
    with _file(settings, "neo4j_admission.lock") as fd:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if switching else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise busy() from None
        yield


@contextmanager
def session(settings):
    """Hold a read lease from endpoint resolution through session closure."""
    root = str(Path(settings.data_root).absolute())
    if root in _held.get():
        yield
        return
    with _file(settings, "neo4j_sessions.lock") as fd:
        with admission(settings):
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        token = _held.set(_held.get() | {root})
        try:
            yield
        finally:
            _held.reset(token)


@contextmanager
def drained(settings, *, timeout=120):
    """Call after closing admission and cancelling/waiting for database jobs."""
    with _file(settings, "neo4j_sessions.lock") as fd:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise AnalyticsError("Active database sessions did not finish in time. The backend was not changed.",
                                         "database_sessions_busy", 409) from None
                time.sleep(.05)
        yield


def switching(settings):
    try:
        with admission(settings):
            return False
    except AnalyticsError:
        return True
