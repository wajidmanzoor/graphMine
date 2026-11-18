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

DEFAULT_DATA_DIR = Path("/data/labdata/wajid/graphmine_data/rlModelData")
DEFAULT_MODEL_DIR = Path("/data/labdata/wajid/graphmine-models/rlModel")
SCHEMA_VERSION = 2
LOG = logging.getLogger(__name__)
SCHEMA = """# Backend run log

Schema history: version 1 added Phase 1 telemetry; version 2 adds Phase 2
feasibility, native limits, memory predictions and preflight rejections.
Readers accept both versions. Rows are immutable and contain aggregate data only.
Corrections append a new run_id with supersedes pointing at the original run_id.
JSONL is authoritative. A per-file flock serializes writers on the same host;
O_APPEND plus fsync makes a successfully acknowledged write durable.

Identity: run_id, workflow_id, step_id, created_at (UTC ISO 8601).
Operation: operation, problem_id, family, parameters (typed scalars, catalog
enums, collection counts; identifiers and free text are redacted).
Selection: requested_device, requested_backend, candidates (id, compiled,
admitted, feasible, infeasible_reason), chosen_backend, reason, policy_version,
model_version, predictions. Phase 1 policy/model/predictions are null.
Hardware: hostname, CPU model/cores/free cores, total/free RAM bytes; all physical
GPUs with index/model/total/free memory bytes/utilisation/process count/driver
and CUDA version; leased_gpu_index. Unavailable measurements are null with a
telemetry warning, never zero. CUDA logical ordinal 0 may be physical GPU 1.
Graph: graph_features, including snapshot_fingerprint and feature_version.
n/m count input vertices/edge instances. Shape (degree, density, Gini, CV,
degeneracy and weak components) uses the simple undirected projection without
self-loops. Logs use log1p; empty graphs have zero-valued shape statistics.
Known bipartite sides use canonical attributes.side; only counts are stored.
Structured inputs have null shape statistics; hyperedges are never expanded.
Outcome: outcome (completed/timeout/oom/unsupported_input/error), error_code,
runtime_seconds (wall time), native_elapsed_seconds, native_compute_seconds, preparation_seconds,
timeout_seconds, censored (a timeout is a lower bound, not a completed run).
Peak memory: peak_memory.gpu_bytes is sampled NVML memory of the worker and its
descendants on the leased GPU; process_rss_bytes is the sampled process-tree RSS.
Sampling can miss brief peaks; peak_memory.sample_interval_seconds records the
interval. Device-wide used memory is not attributed to this run.
Output: output_size (result item count if known, otherwise null).
Other: fallback_chain, is_evaluation, source, implementation_sha256,
prediction_error (null without predictions), telemetry_warnings (fixed codes).
Evaluation/test rows are never training observations. No user identity is stored.

Version 2: policy_version=feasibility-v1. Each candidate also carries device,
limits (maximum input n/m, declared conservatively by native preflight),
native_feasible, predicted_peak_memory_bytes, memory_model_version and
memory_prediction_reason. predictions contains memory estimates and null runtime
predictions until Phase 4. output_estimate is the request's max_output_items
budget, known before execution; actual output_size is never used as an input.
execution_started=false and failure_stage=preflight identify requests rejected
before native execution; they are not completed training observations.
Memory coefficients are nonnegative a+b*n+c*m+d*output_estimate, scoped by
operation, implementation, hardware model, input kind/flags and safe parameters.
At least 20 completed non-evaluation rows and 5 distinct snapshots are required.
The held-out split groups whole snapshots. Fits include a 25% margin, must not
underpredict any held-out peak, and apply only within the training size range.
OOM observations never enter least-squares fitting: for the same context and
snapshot they impose a 1.25x lower bound on the previously available memory.
The workflow scheduler always retains its conservative admission reservation.
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
    for name in ("runs", "benchmarks", "features", "memory_models", "reports"):
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
        # measurements must not raise into the operation's result path.
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


def read_rows(data_dir, *, since=None, operation=None, include_benchmarks=True):
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
                    if not isinstance(row, dict) or row.get("schema_version") not in (1, SCHEMA_VERSION):
                        raise ValueError("Unknown run schema")
                    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                    if (not after or created >= after) and (not operation or row["operation"] == operation):
                        yield row
                except (ValueError, KeyError, TypeError):
                    LOG.warning("backend telemetry: ignored malformed or unsupported row in %s", path.name)
