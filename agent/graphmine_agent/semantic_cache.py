"""Private, account-scoped answer files; never a persisted Ladybug graph.

Hold a process-shared lease for the complete worker lifetime and for clear.
Completed batches are fsynced by the engine before its next provider request.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from .database_job_context import checkpoint
from .errors import AnalyticsError
from .identity import current_principal


def directory(runtime):
    path = runtime.settings.data_root / "semantic-answers"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise AnalyticsError("The answer store must be private to the server account.", "semantic_cache", 503)
    return path


def account_key():
    principal = current_principal.get()
    return hashlib.sha256((principal.user_id if principal else "local").encode()).hexdigest()


@contextmanager
def lease(runtime, *, all_accounts=False, timeout=120):
    root = directory(runtime)
    # All account jobs take the global shared lock. An administrator's clear
    # takes it exclusively, so it cannot delete answers from an active worker.
    paths = [(root / "global.lock", fcntl.LOCK_EX if all_accounts else fcntl.LOCK_SH)]
    if not all_accounts:
        paths.append((root / (account_key() + ".lock"), fcntl.LOCK_EX))
    streams = []
    started = time.monotonic()
    try:
        for path, mode in paths:
            stream = os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+b")
            streams.append(stream)
            while True:
                checkpoint("waiting_for_answer_store")
                try:
                    fcntl.flock(stream, mode | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() - started > timeout:
                        raise AnalyticsError("Saved answers are in use. Retry after active refinements finish.", "semantic_busy", 429)
                    time.sleep(0.1)
        yield root / (account_key() + ".answers")
    finally:
        for stream in reversed(streams):
            stream.close()


def inspect_file(path):
    if not path.exists():
        return 0
    if path.is_symlink():
        raise AnalyticsError("The answer store is invalid.", "semantic_cache", 503)
    # An append-only store may repeat keys after reuse is disabled or entries
    # expire. Count distinct answers, not physical lines or question summaries.
    keys = set()
    with path.open() as stream:
        for line in stream:
            parts = line.rstrip("\n").split("\t", 3)
            if len(parts) == 4 and len(parts[0]) == 32 and parts[1].isdigit():
                try:
                    int(parts[0], 16)
                    json.loads(parts[3])
                except ValueError:
                    continue
                keys.add(parts[0])
    return len(keys)


def summary(runtime):
    root = directory(runtime)
    return sum(inspect_file(path) for path in root.glob("*.answers"))


def clear(runtime):
    with lease(runtime, all_accounts=True, timeout=1):
        count = summary(runtime)
        for path in directory(runtime).glob("*.answers"):
            path.unlink()
    with runtime.database._connect() as db:
        runtime.accounts._audit(db, "semantic.answers.cleared", "semantic", before={"retained_answers": count}, after={"retained_answers": 0})
    return {"cleared_answers": count}
