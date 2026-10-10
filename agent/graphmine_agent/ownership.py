"""Local POSIX ownership shared by workers and offline maintenance tools."""

from __future__ import annotations

import fcntl
from pathlib import Path


class StoreLock:
    def __init__(self, database_path: Path):
        path = database_path.resolve()
        self.path = path.with_name(path.name + ".worker.lock")
        self._handle = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        handle = self.path.open("a", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError(
                "The data store is already owned by another worker or maintenance operation"
            ) from None
        except BaseException:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        # Never unlink a lock file: another process may already hold its inode.

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
