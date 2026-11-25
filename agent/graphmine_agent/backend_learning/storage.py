"""Append-only JSONL storage. A dedicated thread owns slow writes and fsync."""

from __future__ import annotations

import atexit
import fcntl
import json
import logging
import os
import queue
import re
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_DATA_DIR = Path.home() / ".local/state/graphmine/backend-runs"
DEFAULT_MODEL_DIR = Path.home() / ".local/state/graphmine/backend-models"
SCHEMA_VERSION = 5
LOG = logging.getLogger(__name__)
SCHEMA = """# Shared backend policy run log (schema 5)

Rows are append-only, aggregate-only JSONL; supersedes identifies corrections.
Identity: run_id, decision_id, attempt_index, workflow_id, step_id, created_at,
problem (the executable ID), topic_id (documentation only), implementation_sha256.
Context: graph_features including snapshot_fingerprint, hardware (one-minute
load estimate, logical cores, RAM, physical GPU 1 utilization and VRAM), safe
parameters (catalog enums/scalars and collection counts), execution_isolated.
Decision: eligible_backends after native preflight and conservative memory
admission, chosen_backend, probabilities, selection_probability, model_version,
context_features in the artifact feature_schema order, selection_mode, reason.
The probability belongs to the actual choice after all constraints and budget
checks. Explicit choices and single-backend decisions have probability one.
Shadow proposal fields are separate and never become behavior propensities.
Outcome: runtime_seconds, outcome, timeout_seconds, native timing fields,
peak_memory, fallback_chain, execution_started, telemetry_warnings.
Cost: cost_scale_seconds and failure_cost are empirical benchmark controls, not
runtime predictions. Retraining uses clipped inverse propensity cost offline.
Benchmark: comparison_id, paired_eligible_backends, pair_context, load_regime,
backend order/repetition, benchmark_attempt_key; all timings remain authoritative.
Versions 1-4 are readable for inspection; legacy operation keys normalize to
problem on read. Shared model fitting requires current implementation provenance.
No auxiliary memory or runtime models are maintained. No graph identities or
parameters enter learned features. Safe parameters remain in logs for benchmark
pairing, feasibility and execution controls. Evaluation rows never train models.
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def atomic_json(path, value):
    """Publish derived metadata, never authoritative run rows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid4().hex)
    try:
        with temporary.open("x") as handle:
            handle.write(_json(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_directories(data_dir, model_dir, repository_root):
    """Startup validation deliberately fails before any work is accepted."""
    root = Path(repository_root).resolve()
    for label, location in (("backend_data_dir", data_dir), ("backend_model_dir", model_dir)):
        path = Path(location).expanduser().resolve()
        if (path == root or root in path.parents or path == Path("/tmp") or Path("/tmp") in path.parents
                or any((parent / ".git").exists() for parent in (path, *path.parents))):
            raise ValueError(f"{label} must be outside the repository and /tmp: {path}")
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            probe = path / (".write-check-" + uuid4().hex)
            fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, b"writable\n")
                os.fsync(fd)
            finally:
                os.close(fd)
                probe.unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError(f"{label} is not writable: {path} ({exc.strerror})") from exc
    path = Path(data_dir)
    for name in ("runs", "benchmarks", "features", "reports"):
        (path / name).mkdir(exist_ok=True, mode=0o700)
    schema = path / "SCHEMA.md"
    try:
        with schema.open("x") as handle:
            handle.write(SCHEMA)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if schema.read_text() != SCHEMA:
            temporary = schema.with_name("SCHEMA.md." + uuid4().hex)
            try:
                with temporary.open("x") as handle:
                    handle.write(SCHEMA)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, schema)
            finally:
                temporary.unlink(missing_ok=True)


def append_row(path, row):
    """Never replace rows, including after a concurrent write or a failed fsync."""
    raw = (_json(row) + "\n").encode()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                raise OSError("No progress appending backend telemetry")
            offset += count
        os.fsync(fd)
    finally:
        os.close(fd)


class RunLog:
    def __init__(self, data_dir, *, destination=None, warning=None, max_pending=4096):
        self.data_dir = Path(data_dir)
        self.destination = Path(destination) if destination else None
        if self.destination and not self.destination.resolve().is_relative_to(self.data_dir.resolve()):
            raise ValueError("Run log destination must be beneath backend_data_dir")
        self.warning = warning
        self.warnings = []
        self.pending = queue.Queue(maxsize=max_pending)
        self.closed = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._write_loop, name="backend-run-log", daemon=True)
        self.thread.start()
        atexit.register(self.close)

    def _warn(self, code):
        self.warnings.append(code)
        del self.warnings[:-100]
        LOG.warning("backend telemetry: %s", code)
        if self.warning:
            try:
                self.warning(code)
            except Exception:
                LOG.warning("backend telemetry warning callback failed")

    def submit(self, row):
        # Snapshot/serialization is done outside the filesystem writer. Bad
        # measurements must not raise into the problem's result path.
        try:
            frozen = json.loads(_json(row))
            with self.lock:
                if self.closed:
                    raise RuntimeError("Run logger closed")
                self.pending.put_nowait(frozen)
            return True
        except Exception:
            self._warn("log_enqueue_failed")
            return False

    def _write_loop(self):
        while True:
            row = self.pending.get()
            try:
                if row is None:
                    return
                date = datetime.fromisoformat(row["created_at"]).astimezone(timezone.utc)
                host = re.sub(r"[^A-Za-z0-9_.-]", "_", socket.gethostname())
                path = self.destination or self.data_dir / "runs" / date.strftime("%Y/%m/%d") / f"runs-{host}.jsonl"
                append_row(path, row)
                features = row.get("graph_features") or {}
                fingerprint = features.get("snapshot_fingerprint", "")
                if re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                    path = self.data_dir / "features" / (fingerprint + ".json")
                    # Atomic cache publication; concurrent identical snapshots
                    # can harmlessly replace this derived, nonauthoritative file.
                    temporary = path.with_name(path.name + "." + uuid4().hex)
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        with temporary.open("x") as handle:
                            handle.write(_json(features) + "\n")
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, path)
                    finally:
                        temporary.unlink(missing_ok=True)
            except Exception:
                # Do not retry an uncertain append: it may already be durable.
                self._warn("log_write_failed")
            finally:
                self.pending.task_done()

    def flush(self):
        """Explicit CLI/test/shutdown barrier; never called by native execution."""
        self.pending.join()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.pending.put(None)
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            self._warn("log_shutdown_timeout")


def read_rows(data_dir, *, since=None, problem=None, include_benchmarks=True):
    root = Path(data_dir)
    paths = sorted((root / "runs").glob("*/*/*/runs-*.jsonl"))
    if include_benchmarks:
        paths += sorted((root / "benchmarks").glob("*/runs.jsonl"))
    after = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    if after and after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    for path in paths:
        with path.open() as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or row.get("schema_version") not in (1, 2, 3, 4, SCHEMA_VERSION):
                        raise ValueError("Unknown run schema")
                    if "operation" in row:
                        row["problem"] = row.pop("operation")
                    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                    if (not after or created >= after) and (not problem or row["problem"] == problem):
                        yield row
                except (ValueError, KeyError, TypeError):
                    LOG.warning("backend telemetry: ignored malformed or unsupported row in %s", path.name)
