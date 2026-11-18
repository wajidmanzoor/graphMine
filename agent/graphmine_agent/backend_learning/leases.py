"""A shared physical-GPU-1 lease for application and offline workers."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path


class GPULock:
    def __init__(self, fd):
        self.fd = fd

    @classmethod
    def acquire(cls, data_dir=None):
        # A process lease is runtime state, not a training artifact. Use one
        # per-account location regardless of the configured data destination.
        directory = Path("/run/user") / str(os.getuid())
        fd = os.open(directory / "graphmine-gpu-1.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        except BaseException:
            os.close(fd)
            raise
        return cls(fd)

    def close(self):
        if self.fd is not None:
            # close, rather than LOCK_UN: a surviving child keeps the inherited
            # open-file-description locked until its native work has stopped.
            os.close(self.fd)
            self.fd = None
