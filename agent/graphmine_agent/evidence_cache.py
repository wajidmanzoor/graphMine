"""Remember evidence-file hashes between library worker processes.

Every worker re-verifies the native evidence before it runs anything, and most
of that time is spent hashing the same unchanged files again. This module is
loaded by path into the worker's own interpreter, ahead of the unchanged
``graphmine.worker``. It lives in the agent rather than the library because the
library's sources are themselves recorded in the verified evidence: editing them
withdraws admission until that evidence is regenerated.

A remembered hash is reused only while the file's device, inode, size,
modification time and change time all match. Any write or replacement changes
the change time, which ordinary users cannot set back, so an edited file is
hashed again. Like the evidence gate itself, this is a reproducibility check,
not a defence against someone who can already write the repository.
"""

from __future__ import annotations

import atexit
import json
import os
import tempfile
from pathlib import Path

# Run by the worker as ``python -c``: load this file by path, install the cache,
# then run the library worker exactly as ``python -m graphmine.worker`` would.
BOOTSTRAP = """\
import importlib.util, os, runpy, sys
if os.environ.get("GRAPHMINE_REPOSITORY_ROOT"):
    sys.path.insert(0, os.path.join(os.environ["GRAPHMINE_REPOSITORY_ROOT"], "python", "graphmine"))
import graphmine.evidence as evidence
spec = importlib.util.spec_from_file_location(
    "graphmine_evidence_cache", os.environ["GRAPHMINE_EVIDENCE_CACHE_MODULE"]
)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)
cache.install(evidence, os.environ["GRAPHMINE_EVIDENCE_HASH_CACHE"])
if os.environ.get("GRAPHMINE_BACKEND_TELEMETRY_ROOT"):
    # This installs admission as well as best-effort logging. A broken safety
    # gate must fail closed; delivery/write errors remain observational.
    sys.path.insert(0, os.environ["GRAPHMINE_BACKEND_TELEMETRY_ROOT"])
    from graphmine_agent.backend_learning.worker import install
    install()
runpy.run_module("graphmine.worker", run_name="__main__", alter_sys=True)
"""


def install(evidence, store):
    """Replace the evidence gate's per-check hasher with one that remembers."""
    store = Path(store)
    try:
        loaded = json.loads(store.read_text())
    except (OSError, ValueError):
        loaded = {}
    saved = loaded if isinstance(loaded, dict) else {}
    changed = []

    class RememberedHashes(evidence._FileHashes):
        def __call__(self, path):
            path = Path(path)
            identity = list(self.identity(path))
            remembered = saved.get(str(path))
            if (
                isinstance(remembered, list)
                and len(remembered) == 6
                and remembered[:5] == identity
                and isinstance(remembered[5], str)
            ):
                self.values[path] = tuple(identity), remembered[5]
                return remembered[5]
            digest = super().__call__(path)
            saved[str(path)] = [*self.values[path][0], digest]
            changed.append(path)
            return digest

    def save():
        if not changed:
            return
        temporary = None
        try:
            store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                "w", dir=store.parent, delete=False, suffix=".tmp"
            ) as handle:
                temporary = Path(handle.name)
                json.dump(saved, handle)
            # Concurrent workers each replace the whole file; the last one wins.
            os.replace(handle.name, store)
            changed.clear()
        except OSError:
            pass  # Only a speed-up: the next worker hashes again.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    evidence._FileHashes = RememberedHashes
    atexit.register(save)
    return RememberedHashes, save
