"""Durable, reviewed workflows over the verified C++/CUDA analytics library."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import os
import re
import shutil
import signal
import sqlite3
import time
from contextlib import closing, nullcontext, suppress
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .analytics_scheduler import (
    AnalyticsScheduler,
    estimate_memory,
    execution_admission,
)
from .analytics_modes import AnalysisMode, saved_mode
from .database import RecordNotFound
from .calculation_limits import minimum_limit, response_lines
from .errors import AnalyticsError  # Re-export for existing integrations.
from .evidence_cache import BOOTSTRAP
from .identity import current_principal
from .ownership import StoreLock
from .query_results import is_database_query


class InputReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str
    kind: Literal["graph", "graph_collection", "feature_vectors", "hypergraph"] = (
        "graph"
    )


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: AnalysisMode = "expert"
    plan: dict[str, Any]
    inputs: dict[str, InputReference]
    evaluation_id: str | None = Field(default=None, min_length=1, max_length=200)
    planning_turn_id: str | None = Field(default=None, min_length=1, max_length=64)


class WorkflowRevision(WorkflowRequest):
    expected_revision: int = Field(ge=1)


class WorkflowApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_hash: str = Field(min_length=64, max_length=64)
    expected_revision: int = Field(ge=1)


class GroupMembershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    vertices: list[int | str] = Field(min_length=1, max_length=500)


_logger = logging.getLogger(__name__)

# Displayed capabilities may lag evidence edits by this long; execution always
# re-verifies evidence before admitting a workflow.
CAPABILITY_CACHE_SECONDS = 300
# Preserve the existing large-search warning for these problems. Cost advice
# is independent of the families used to organize the catalog.
SEARCH_PROBLEMS = {
    "balanced-partitioning",
    "butterfly-counting",
    "densest-k-subgraph",
    "densest-subgraph",
    "frequent-subgraphs",
    "graph-edit-distance",
    "graphlet-counting",
    "group-steiner-tree",
    "hypergraph-partitioning",
    "k-cliques",
    "maximal-biclique-counting",
    "maximal-bicliques",
    "maximal-cliques",
    "maximal-independent-set",
    "maximum-clique",
    "maximum-common-subgraph",
    "maximum-independent-set",
    "minimum-vertex-cover",
    "motif-counting",
    "network-alignment",
    "overlapping-communities",
    "persistent-homology",
    "quasi-cliques",
    "signed-balance",
    "single-graph-frequent-subgraphs",
    "subgraph-isomorphism",
    "temporal-motifs",
}
LARGE_SEARCH_EDGES = 5000
# Longer outputs reach the browser in pages instead of all at once.
SUMMARY_ITEMS = 2000
SLOW_RUN_SECONDS = 120
# Saving usually follows planning within seconds; manual review takes longer.
VALIDATION_CACHE_SECONDS = 900
VALIDATION_CACHE_ENTRIES = 64


def _now():
    return datetime.now(timezone.utc).isoformat()


def _seconds(start, end):
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _percentiles(values):
    if not values:
        return None
    values = sorted(values)

    def pick(q):  # Nearest-rank percentile.
        return round(values[max(0, math.ceil(q * len(values)) - 1)], 2)

    return {"count": len(values), "p50": pick(0.5), "p95": pick(0.95)}


def _matches(row, search):
    """Same rules as the results table: "field:value" is exact, text is a substring."""
    scoped = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*):(.*)", search.strip(), re.DOTALL)
    if scoped:
        try:
            expected = json.loads(scoped.group(2).strip())
        except ValueError:
            expected = scoped.group(2).strip()
        return (
            isinstance(row, dict)
            and scoped.group(1) in row
            and _key(row[scoped.group(1)]) == _key(expected)
        )
    return search.strip().casefold() in json.dumps(row, ensure_ascii=False).casefold()


def _sort_key(value):
    return (
        (0, value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else (1, _key(value))
    )


def _key(value):
    return json.dumps(value, sort_keys=True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class AnalyticsService:
    """One owned ledger; execution stays outside the ASGI process.

    Memory leases permit concurrent workers and preserve configured LLM space.
    """

    def __init__(self, settings, database, graph_store, events, *, llm_power=None):
        from .llm_power import get_registry
        self.llm_power = llm_power or get_registry(settings)
        self._owns_power = llm_power is None and not self.llm_power.shared
        self.settings, self.database, self.graph_store, self.events = (
            settings,
            database,
            graph_store,
            events,
        )
        self.root = settings.data_root / "analytics"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "workflows.sqlite3"
        self.owner = StoreLock(self.path)
        self.tasks = {}
        self.admissions = {}
        self.admin_cancelled = set()
        self.answer_tasks = set()
        # Questions being planned, by (session, turn), so a person can stop one.
        self.planning_tasks = {}
        self.planning_cancelled = set()
        # Worker validations reused between planning and saving the same plan.
        self.validations = {}
        from .result_cache import ResultCache

        self.result_cache = ResultCache(settings.analytics_result_cache_bytes)
        self.export_slots = asyncio.Semaphore(settings.analytics_max_exports)
        self.edit_lock = asyncio.Lock()
        self.scheduler = AnalyticsScheduler(settings)
        self.capability_cache = None
        self.capability_task = None
        self.closed = False
        self.opened = False
        self.run_log = None
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, document TEXT NOT NULL)"
            )
            from .workflow_index import initialize

            initialize(db)
        from .analytics_examples import ReviewedExamples

        self.examples = ReviewedExamples(self)

    def open(self):
        self._open_run_log()
        self.owner.acquire()
        self.opened = True
        for record in self._all():
            if record["status"] in ("queued", "running"):
                record.update(
                    status="interrupted",
                    error={
                        "code": "service_restarted",
                        "message": "Execution was interrupted; successful saved steps can be reused after review",
                    },
                )
                for step in record.get("steps", {}).values():
                    if step.get("status") == "running":
                        step["status"] = "interrupted"
                self._save(record)

    async def close(self):
        self.closed = True
        self.result_cache.clear()
        if not self.opened:
            if self._owns_power:
                await self.llm_power.close()
            if self.run_log is not None:
                await asyncio.to_thread(self.run_log.close)
            return
        tasks = list(self.tasks.values()) + list(self.answer_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._owns_power:
            await self.llm_power.close()
        for record in self._all():
            if record["status"] == "queued":
                record.update(status="cancelled", complete=False)
                self._save(record)
        self.owner.release()
        self.opened = False
        self.result_cache.clear()
        if self.run_log is not None:
            await asyncio.to_thread(self.run_log.close)

    def _open_run_log(self):
        if self.run_log is None:
            from .backend_learning.storage import RunLog, prepare_directories

            prepare_directories(self.settings.backend_data_dir, self.settings.backend_model_dir,
                                self.settings.repository_root)
            self.run_log = RunLog(self.settings.backend_data_dir)

    def _all(self, session_id=None):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT document FROM workflows"
                + (" WHERE session_id=?" if session_id else ""),
                (session_id,) if session_id else (),
            )
            return [saved_mode(json.loads(row[0])) for row in rows]

    def list(self, session_id, *, summary=False):
        if summary:
            from .workflow_index import summaries

            return summaries(self, session_id)
        self.database.get_session(session_id)
        return self._all(session_id)

    def get(self, workflow_id):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT document FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"Workflow {workflow_id} not found")
        record = json.loads(row[0])
        self.database.get_session(record["session_id"])
        return saved_mode(record)

    def _save(self, record):
        record["updated_at"] = _now()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO workflows VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                (record["id"], record["session_id"], _json(record)),
            )
        if self.database.capture:
            self.database.capture.workflow(record)

    def _directory(self, record):
        # Both values are generated by this service, never client paths.
        return self.root / record["id"] / f"revision-{record['revision']}"

    def _write(self, path, value, *, input_snapshot=False):
        raw = _json(value).encode()
        if not input_snapshot and self.settings.max_result_bytes is not None and len(raw) > self.settings.max_result_bytes:
            raise AnalyticsError(
                "Workflow artifact exceeds the byte budget", "resource_limit"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)

    def _inputs(self, session_id, references):
        self.database.get_session(session_id)
        result, total = {}, 0
        for alias, reference in references.items():
            path = self.graph_store.execution_path(reference.file_id, session_id)
            record = self.database.get_file(reference.file_id)
            if not (reference.kind == "graph" and is_database_query(record.provenance.get("source"))):
                total += path.stat().st_size
            if self.settings.analytics_max_input_bytes is not None and total > self.settings.analytics_max_input_bytes:
                raise AnalyticsError(
                    "Combined workflow inputs exceed the byte budget", "resource_limit"
                )
            try:
                data = json.loads(path.read_text())
            except (ValueError, UnicodeError) as exc:
                raise AnalyticsError(
                    "Workflow inputs must be uploaded canonical JSON files"
                ) from exc
            if self.database.capture:
                self.database.capture.dataset(
                    session_id, self.database.get_file(reference.file_id), path
                )
            result[alias] = {"kind": reference.kind, "data": data}
        return result

    async def load_inputs(self, session_id, references):
        """``_inputs`` off the event loop: large graphs take seconds to parse."""
        return await asyncio.to_thread(self._inputs, session_id, references)

    def _validation_key(self, session_id, references, plan):
        files = {
            alias: [ref.kind, ref.file_id, self.database.get_file(ref.file_id).sha256]
            for alias, ref in references.items()
        }
        return _json([session_id, files, plan, repr(self._capability_key())])

    async def validate(self, session_id, references, plan, inputs):
        """Worker validation, reused for an identical plan on unchanged inputs.

        Planning validates a plan and saving it validates the same plan again;
        both use the same files and native implementation, so the second check
        would only repeat the first.
        """
        key = await asyncio.to_thread(self._validation_key, session_id, references, plan)
        now = time.monotonic()
        cached = self.validations.get(key)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])
        checked = await self._call({"command": "validate", "plan": plan, "inputs": inputs})
        # The browser saves the normalized plan this returns. Validating that
        # plan gives this identical result, so it is remembered under both.
        keys = {key, await asyncio.to_thread(
            self._validation_key, session_id, references, checked["plan"]
        )}
        self.validations = {k: v for k, v in self.validations.items() if v[0] > now}
        while len(self.validations) > VALIDATION_CACHE_ENTRIES - len(keys):
            self.validations.pop(next(iter(self.validations)))
        for name in keys:
            self.validations[name] = (now + VALIDATION_CACHE_SECONDS, copy.deepcopy(checked))
        return checked

    def _input_provenance(self, references):
        return {
            alias: {
                **file.provenance,
                "file_id": file.id,
                "sha256": file.sha256,
                "file_snapshot": {
                    "name": file.original_name,
                    "kind": reference.kind,
                    "created_at": file.created_at.isoformat(),
                    "size_bytes": file.size_bytes,
                    "graph": {
                        key: value
                        for key, value in (
                            file.metadata.model_dump() if isinstance(file.metadata, BaseModel)
                            else file.metadata or {}
                        ).items()
                        if key in {"vertex_count", "edge_count", "directed"}
                    },
                },
            }
            for alias, reference in references.items()
            for file in [self.database.get_file(reference.file_id)]
        }

    async def _stop_process(self, process):
        try:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            if process.returncode is None:
                await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            pass
        finally:
            # A native child can outlive the Python leader. Every attempt stays
            # in this group; clean it before releasing the shared GPU lease.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def _call(self, request, *, on_event=None, lease=None):
        from .backend_learning.hardware import PeakSampler, merge_peaks
        from .backend_learning.worker import outcome_for

        request = dict(request)
        telemetry = request.pop("telemetry", {})
        native_runs = {}
        terminal_runs = set()
        step_deadline = None
        terminal_error = None
        timed_out = False
        if request.get("command") == "run":
            self._open_run_log()
        python = (
            self.settings.analytics_python
            or self.settings.native_repository_root / ".venv-analytics/bin/python"
        )
        if not python.is_file():
            raise AnalyticsError(
                "The analytics Python environment is unavailable",
                "backend_unavailable",
                503,
            )
        # Requests carry whole input graphs; serializing them can take seconds.
        raw = await asyncio.to_thread(lambda: _json(request).encode())
        # Inputs have already passed ownership/size validation in _inputs.
        # Database query graphs are complete inputs with no fixed byte ceiling.
        # Give the worker an exact, finite read budget for this trusted request.
        worker_input_bytes = len(raw)
        env = os.environ.copy()
        env.update(
            GRAPHMINE_REPOSITORY_ROOT=str(self.settings.native_repository_root),
            GRAPHMINE_EVIDENCE_CACHE_MODULE=str(
                Path(__file__).with_name("evidence_cache.py")
            ),
            GRAPHMINE_EVIDENCE_HASH_CACHE=str(
                self.root / "cache" / "evidence-hashes.json"
            ),
            GRAPHMINE_WORKER_INPUT_BYTES=str(worker_input_bytes),
            PYTHONUNBUFFERED="1",
        )
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        if request["command"] == "run":
            env.update(
                GRAPHMINE_BACKEND_TELEMETRY_ROOT=str(Path(__file__).resolve().parents[1]),
                GRAPHMINE_BACKEND_DATA_DIR=str(self.settings.backend_data_dir),
                GRAPHMINE_GPU_LEASE_FDS=",".join(str(fd) for fd in self.scheduler.worker_fds(lease)),
                GRAPHMINE_BACKEND_RUN_CONTEXT=_json({
                    **telemetry, "job_timeout_seconds": self.settings.job_timeout_seconds,
                    "leased_gpu_uuid": lease.gpu_uuid if lease else self.settings.graph_gpu_uuid,
                    "backend_memory_safety": self.settings.backend_memory_safety,
                    "backend_model_dir": str(self.settings.backend_model_dir),
                    "backend_selection": self.settings.backend_selection,
                    "backend_require_rollout_evidence": self.settings.backend_require_rollout_evidence,
                    "backend_exploration_enabled": self.settings.backend_exploration_enabled,
                    "backend_exploration_budget": self.settings.backend_exploration_budget,
                    "backend_temperature": self.settings.backend_temperature,
                    "backend_exploration_floor": self.settings.backend_exploration_floor,
                    "backend_default_timeout_seconds": self.settings.backend_default_timeout_seconds,
                    "max_result_bytes": self.settings.max_result_bytes,
                    "execution_isolated": True,
                }),
            )
        native_library = self.settings.native_runtime_library
        if native_library is None and not env.get("GRAPHMINE_NATIVE_LIBRARY"):
            binary = self.settings.native_runtime_binary
            if binary is not None:
                native_library = binary.with_name("libgraphmine_runtime.so")
        if native_library is not None:
            env["GRAPHMINE_NATIVE_LIBRARY"] = str(native_library)
        policy = request.get("plan", {}).get("device", "auto")
        gpu = lease.gpu_uuid if lease is not None else self.settings.graph_gpu_uuid
        if request["command"] != "run" or policy == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        else:
            if policy == "gpu" and not gpu:
                raise AnalyticsError(
                    "GPU execution requires a configured graph GPU",
                    "backend_unavailable",
                    503,
                )
            env["CUDA_VISIBLE_DEVICES"] = gpu or ""
        process = await asyncio.create_subprocess_exec(
            str(python),
            "-c",
            BOOTSTRAP,
            pass_fds=self.scheduler.worker_fds(lease),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self.settings.native_repository_root,
            start_new_session=True,
            # Aggregate telemetry has a separate allowance; enabling logging
            # must not consume the user's native result byte budget.
            limit=256 * 1024,
        )
        tasks = []
        errors = bytearray()

        async def send():
            process.stdin.write(raw)
            await process.stdin.drain()
            process.stdin.close()

        async def diagnostics():
            while data := await process.stderr.read(65536):
                if len(errors) < 8192:
                    errors.extend(data[: 8192 - len(errors)])

        async def receive():
            nonlocal step_deadline
            final, total = None, 0
            byte_limit = self.settings.max_result_bytes
            line_limit = max(byte_limit + 1, 256 * 1024) if byte_limit is not None else None
            async for line in response_lines(process.stdout, line_limit):
                try:
                    message = json.loads(line)
                except ValueError as exc:
                    raise AnalyticsError(
                        "Invalid worker response", "worker_failure", 502
                    ) from exc
                if final is not None:
                    raise AnalyticsError(
                        "Worker emitted data after completion", "worker_failure", 502
                    )
                if message.get("event") == "telemetry_warning":
                    _logger.warning("Backend worker telemetry warning: %s", message.get("code"))
                    continue
                if message.get("event") == "native_started":
                    row = message["record"]
                    if row["run_id"] in native_runs or row["run_id"] in terminal_runs:
                        raise AnalyticsError("Duplicate native attempt identity", "worker_failure", 502)
                    sampler = None
                    try:
                        sampler = PeakSampler(process.pid, row["hardware"]["leased_gpu_index"])
                    except Exception:
                        row["telemetry_warnings"].append("peak_sampler_unavailable")
                    native_runs[row["run_id"]] = row, time.monotonic(), sampler
                    continue
                if message.get("event") == "native_finished":
                    row = message["record"]
                    if row["run_id"] in terminal_runs:
                        raise AnalyticsError("Duplicate native terminal row", "worker_failure", 502)
                    terminal_runs.add(row["run_id"])
                    previous = native_runs.pop(row["run_id"], None)
                    if previous:
                        sampler = previous[2]
                        if sampler is not None:
                            try:
                                row["peak_memory"] = merge_peaks(row["peak_memory"], sampler.finish())
                                row["telemetry_warnings"].extend(sampler.warnings)
                            except Exception:
                                row["telemetry_warnings"].append("peak_sampler_failed")
                    # Preflight failures have a terminal row without a start.
                    # They must remain visible even when no native kernel ran.
                    self.run_log.submit(row)
                    continue
                total += len(line)
                if byte_limit is not None and (len(line) > byte_limit + 1 or total > byte_limit * 3):
                    raise AnalyticsError(
                        "Worker output exceeded the byte budget", "resource_limit"
                    )
                if message.get("event") == "error":
                    error = message["error"]
                    raise AnalyticsError(error["message"], error["code"])
                if message.get("event") == "complete":
                    final = message["result"]
                elif message.get("event") in ("step_started", "step_finished"):
                    if message["event"] == "step_started":
                        step = next(s for s in request["plan"]["steps"] if s["id"] == message["step"])
                        limit = minimum_limit(self.settings.job_timeout_seconds,
                                              step.get("budget", {}).get("timeout_seconds"))
                        step_deadline = time.monotonic() + limit if limit is not None else None
                    else:
                        step_deadline = None
                    if on_event:
                        await on_event(message)
                else:
                    raise AnalyticsError("Unknown worker event", "worker_failure", 502)
            return final

        async def deadlines():
            while not tasks[2].done():
                if step_deadline is not None and time.monotonic() >= step_deadline:
                    raise TimeoutError("Native step exceeded its total execution deadline")
                await asyncio.sleep(0.05)

        try:
            tasks = [
                asyncio.create_task(send()),
                asyncio.create_task(diagnostics()),
                asyncio.create_task(receive()),
                asyncio.create_task(deadlines()),
            ]
            async with asyncio.timeout(self.settings.job_timeout_seconds):
                _, _, final, _ = await asyncio.gather(*tasks)
                code = await process.wait()
            if code != 0 or final is None:
                raise AnalyticsError(
                    "Analytics worker exited without a completed response",
                    "worker_failure",
                    502,
                )
            return final
        except TimeoutError as exc:
            timed_out = True
            terminal_error = exc
            raise AnalyticsError(
                "Workflow exceeded its execution deadline", "resource_limit"
            ) from exc
        except (BrokenPipeError, ConnectionResetError, ValueError) as exc:
            terminal_error = exc
            if isinstance(exc, AnalyticsError):
                raise
            raise AnalyticsError(
                "Analytics worker communication failed", "worker_failure", 502
            ) from exc
        except BaseException as exc:
            terminal_error = exc
            raise
        finally:
            for task in tasks:
                task.cancel()
            await self._stop_process(process)
            await asyncio.gather(*tasks, return_exceptions=True)
            if b"backend telemetry:" in errors:
                _logger.warning("Backend worker telemetry warning: diagnostics_reported_failure")
            for row, started, sampler in native_runs.values():
                outcome, code = outcome_for(terminal_error or RuntimeError("worker_interrupted"), timed_out=timed_out)
                row.update(outcome=outcome, error_code=code, censored=outcome == "timeout",
                           runtime_seconds=time.monotonic() - started)
                row["fallback_chain"] = [*row.get("fallback_chain", []), dict(run_id=row["run_id"],
                    backend=row.get("chosen_backend"), outcome=outcome, runtime_seconds=row["runtime_seconds"])]
                if sampler is not None:
                    try:
                        row["peak_memory"] = merge_peaks(row["peak_memory"], sampler.finish())
                        row["telemetry_warnings"].extend(sampler.warnings)
                    except Exception:
                        row["telemetry_warnings"].append("peak_sampler_failed")
                self.run_log.submit(row)

    def _capability_key(self):
        paths = [
            self.settings.native_repository_root / "catalog/native_execution_evidence.json",
            self.settings.native_runtime_library,
            self.settings.native_runtime_binary,
            os.environ.get("GRAPHMINE_NATIVE_LIBRARY"),
        ]
        key = []
        for path in paths:
            try:
                info = Path(path).stat() if path else None
            except OSError:
                info = None
            key.append(info and (str(path), info.st_mtime_ns, info.st_size))
        return tuple(key)

    async def _load_capabilities(self, key):
        from .analytics_planning import family_catalog

        result = await self._call({"command": "capabilities"})
        result["task_families"] = family_catalog(result["problems"])
        self.capability_cache = (
            key,
            time.monotonic() + CAPABILITY_CACHE_SECONDS,
            result,
        )
        return result

    async def _native_capabilities(self, refresh=False):
        """One shared verification serves every viewer until evidence changes."""
        key = self._capability_key()
        cached = self.capability_cache
        if not refresh and cached and cached[0] == key and time.monotonic() < cached[1]:
            return cached[2]
        if self.capability_task is None or self.capability_task.done():
            self.capability_task = asyncio.create_task(self._load_capabilities(key))
        # A disconnected viewer must not cancel the verification others await.
        return await asyncio.shield(self.capability_task)

    async def capabilities(self, refresh=False):
        result = copy.deepcopy(await self._native_capabilities(refresh))
        from .analytics_eligibility import attach_requirements
        attach_requirements(result["problems"], self.settings.repository_root)
        from .result_views import profile
        from .view_contracts import catalog_roles
        from ._families import TOPICS
        from .analytics_options import quality_guarantees
        for problem in result["problems"]:
            problem["quality_guarantees"] = quality_guarantees(problem)
            problem["visualization"] = profile(problem["id"])
            problem["visualization"]["field_roles"] = catalog_roles(problem["id"], problem.get("output_ports", {}))
            topic = TOPICS.get(problem.get("topic_id"), {})
            problem["topic_title"] = topic.get("title", problem.get("topic_id"))
        result["application_limits"] = {
            "input_bytes": self.settings.analytics_max_input_bytes,
            "result_bytes": self.settings.max_result_bytes,
            "run_timeout_seconds": self.settings.job_timeout_seconds,
            "memory_admission": "Estimated separately for each validated workflow; execution waits for available capacity.",
        }
        result["question_planner_enabled"] = self.settings.llm_enabled
        devices = self.scheduler.eligible(await self.scheduler.probe())
        result["device_configuration"] = {
            "cpu": True,
            "gpu_configured": bool(
                self.settings.graph_gpu_uuid or self.settings.analytics_gpu_uuids
            ),
            "gpu_available": bool(devices),
            "active_allocations": self.scheduler.snapshot(),
        }
        return result

    async def create(self, session_id, body):
        async with self.edit_lock:
            record = await self._create(session_id, body)
        if body.mode == "normal" and record["status"] == "ready":
            return await self.start(record["id"], record["validation"]["workflow_hash"], record["revision"])
        return record

    async def _create(self, session_id, body):
        if body.planning_turn_id and not self.database.chat_turn_exists(
            session_id, body.planning_turn_id, role="assistant", status="ready"
        ):
            raise AnalyticsError("The planning turn is not ready in this workspace")
        inputs = await self.load_inputs(session_id, body.inputs)
        checked = await self.validate(session_id, body.inputs, body.plan, inputs)
        record = {
            "id": str(uuid4()),
            "session_id": session_id,
            "revision": 1,
            "mode": body.mode,
            "evaluation_id": body.evaluation_id,
            "planning_turn_id": body.planning_turn_id,
            "status": "ready",
            "created_at": _now(),
            "approved_hash": None,
            "input_files": {k: v.model_dump() for k, v in body.inputs.items()},
            "input_provenance": self._input_provenance(body.inputs),
            "validation": checked,
            "steps": {},
        }
        await asyncio.to_thread(self._write, self._directory(record) / "inputs.json", inputs, input_snapshot=True)
        record["preview"] = await self._preview(record, inputs)
        if body.mode == "normal" and (record["preview"] or {}).get("expensive"):
            # Explain an expensive run and wait for approval, even in Normal mode.
            record["status"] = "awaiting_review"
        self._save(record)
        return record

    async def _preview(self, record, inputs):
        """What will run, its guarantees, the input size and likely cost.

        Only an explanation: a validated plan still runs if this cannot be built.
        """
        try:
            return await self._build_preview(record, inputs)
        except Exception:
            _logger.exception("Could not explain workflow %s", record["id"])
            return None

    async def _build_preview(self, record, inputs):
        caps = await self.capabilities()
        cards = {card["id"]: card for card in caps["problems"]}
        sizes = {
            alias: {
                "vertices": len(descriptor["data"].get("vertices", [])),
                "edges": len(descriptor["data"].get("edges", [])),
            }
            for alias, descriptor in inputs.items()
            if isinstance(descriptor.get("data"), dict)
        }
        steps = [
            {
                "id": step["id"],
                "problem": step["problem"],
                "title": cards.get(step["problem"], {}).get(
                    "title", step["problem"]
                ),
                "quality": cards.get(step["problem"], {}).get("quality"),
                "device": step.get("device"),
                "search": step["problem"] in cards
                and step["problem"] in SEARCH_PROBLEMS,
            }
            for step in record["validation"]["plan"]["steps"]
        ]
        input_bytes = (self._directory(record) / "inputs.json").stat().st_size
        edges = max((size["edges"] for size in sizes.values()), default=0)
        # Reads every saved workflow, so it must not hold the event loop.
        past = await asyncio.to_thread(self._past_runtime, record, input_bytes)
        reasons = []
        if edges > LARGE_SEARCH_EDGES and any(step["search"] for step in steps):
            reasons.append(
                f"It runs an exact search on {edges:,} connections. This kind of "
                "search can take a long time, or stop at its search limit, on large graphs."
            )
        if past and past["median_seconds"] > SLOW_RUN_SECONDS:
            reasons.append(
                f"Similar runs on this server took about "
                f"{max(1, round(past['median_seconds'] / 60))} minutes."
            )
        return {
            "steps": steps,
            "inputs": sizes,
            "memory_bytes": estimate_memory(record["validation"]["plan"], input_bytes),
            "past_runs": past,
            "expensive": bool(reasons),
            "reasons": reasons,
        }

    def _past_runtime(self, record, input_bytes):
        """Median time of completed runs with the same steps and similar input size."""
        problems = sorted(
            s["problem"] for s in record["validation"]["plan"]["steps"]
        )
        seconds = []
        for other in self._all():
            if (
                other["status"] != "completed"
                or not other.get("started_at")
                or not other.get("finished_at")
                or sorted(
                    s.get("problem")
                    for s in other.get("validation", {})
                    .get("plan", {})
                    .get("steps", [])
                )
                != problems
            ):
                continue
            try:
                size = (self._directory(other) / "inputs.json").stat().st_size
            except OSError:
                continue
            if input_bytes / 2 <= size <= input_bytes * 2:
                seconds.append(
                    (
                        datetime.fromisoformat(other["finished_at"])
                        - datetime.fromisoformat(other["started_at"])
                    ).total_seconds()
                )
        if not seconds:
            return None
        seconds.sort()
        return {"count": len(seconds), "median_seconds": seconds[len(seconds) // 2]}

    def active_inputs(self, session_id):
        """Uploaded files that queued or running workflows still read."""
        return {
            reference["file_id"]
            for record in self._all(session_id)
            if record["status"] in ("queued", "running")
            for reference in record.get("input_files", {}).values()
        }

    def delete_session(self, session_id):
        """Remove a conversation's workflows, results and reviewed examples."""
        records = self._all(session_id)
        if any(record["status"] in ("queued", "running") for record in records):
            raise AnalyticsError(
                "Cancel the running analysis before deleting this conversation.",
                "state_conflict",
                409,
            )
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM workflows WHERE session_id=?", (session_id,))
            db.execute(
                "DELETE FROM reviewed_examples WHERE session_id=?", (session_id,)
            )
        for record in records:
            shutil.rmtree(self.root / record["id"], ignore_errors=True)

    async def health(self):
        """Is the engine people use able to run work, and is work failing?"""
        # Health answers at once: it reads the shared verification and only
        # starts a refresh in the background, never waiting for a worker.
        cached, task = self.capability_cache, self.capability_task
        if (not cached or time.monotonic() >= cached[1]) and (
            task is None or task.done()
        ):
            refresh = asyncio.create_task(
                self._load_capabilities(self._capability_key())
            )
            refresh.add_done_callback(lambda done: done.cancelled() or done.exception())
            self.capability_task = refresh
        if (
            task is not None
            and task.done()
            and not task.cancelled()
            and task.exception()
        ):
            native = {"status": "error", "error": str(task.exception())[:300]}
            native["admitted_problems"] = 0
        elif cached:
            problems = cached[2]["problems"]
            admitted = sum(1 for c in problems if any(c["execution"].values()))
            native = {
                "status": "ok" if admitted else "unverified",
                "admitted_problems": admitted,
                "problems": len(problems),
                "implementation_sha256": cached[2].get("implementation_sha256"),
            }
        else:
            native = {"status": "checking", "admitted_problems": 0}
        now = datetime.now(UTC)
        since = (now - timedelta(days=1)).isoformat()
        records = self._all()
        finished = [r for r in records if (r.get("finished_at") or "") >= since]
        failed = [r for r in finished if r["status"] == "failed"]
        queued = [r.get("approved_at") for r in records if r["status"] == "queued"]
        oldest = min((at for at in queued if at), default=None)
        return {
            "native": native,
            "scheduler": {"active_allocations": self.scheduler.snapshot()},
            "workflows": {
                "running": sum(r["status"] == "running" for r in records),
                "queued": len(queued),
                "oldest_queued_seconds": round(
                    (now - datetime.fromisoformat(oldest)).total_seconds()
                )
                if oldest
                else None,
                "finished_24h": len(finished),
                "failed_24h": len(failed),
                "recent_failures": [
                    {
                        "code": (r.get("error") or {}).get("code"),
                        "at": r.get("finished_at"),
                    }
                    for r in failed[-5:]
                ],
            },
        }

    def metrics(self, diagnostics):
        """Planning and execution timings over the last day, from saved records."""
        stages, outcomes = {}, {}
        for report in diagnostics:
            if isinstance(report.get("seconds"), (int, float)):
                stages.setdefault(report.get("stage"), []).append(report["seconds"])
            outcome = report.get("outcome", "unknown")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        queue, run, failed, finished = [], [], 0, 0
        for record in self._all():
            if (record.get("finished_at") or "") < since:
                continue
            finished += 1
            failed += record["status"] == "failed"
            approved, started = record.get("approved_at"), record.get("started_at")
            if approved and started:
                queue.append(_seconds(approved, started))
            if started:
                run.append(_seconds(started, record["finished_at"]))
        return {
            "planning_seconds": {stage: _percentiles(v) for stage, v in stages.items()},
            "planning_outcomes": outcomes,
            "queue_seconds": _percentiles(queue),
            "run_seconds": _percentiles(run),
            "workflows_finished_24h": finished,
            "failure_rate_24h": round(failed / finished, 3) if finished else None,
            "reserved_memory_bytes": sum(
                lease["reserved_bytes"] for lease in self.scheduler.snapshot()
            ),
        }

    def queue_position(self, record):
        """Place in line across all users; reveals only a count."""
        if record["status"] != "queued":
            return None
        mine = record.get("approved_at") or ""
        return 1 + sum(
            other["status"] in ("queued", "running")
            and (other.get("approved_at") or "") < mine
            for other in self._all()
        )

    async def revise(self, workflow_id, body):
        async with self.edit_lock:
            previous = self.get(workflow_id)
            if previous["revision"] != body.expected_revision or previous["status"] in (
                "queued",
                "running",
            ):
                raise AnalyticsError(
                    "The workflow changed or is running; reload it before editing",
                    "revision_conflict",
                    409,
                )
            inputs = await self.load_inputs(previous["session_id"], body.inputs)
            checked = await self.validate(
                previous["session_id"], body.inputs, body.plan, inputs
            )
            record = {
                **previous,
                "revision": previous["revision"] + 1,
                "mode": body.mode,
                "evaluation_id": previous.get("evaluation_id") or body.evaluation_id,
                "status": "ready",
                "approved_hash": None,
                "input_files": {k: v.model_dump() for k, v in body.inputs.items()},
                "input_provenance": self._input_provenance(body.inputs),
                "validation": checked,
                "steps": {},
            }
            record.pop("error", None)
            record.pop("complete", None)
            for field in ("approved_at", "started_at", "finished_at"):
                record.pop(field, None)
            await asyncio.to_thread(
                self._write, self._directory(record) / "inputs.json", inputs, input_snapshot=True
            )
            record["preview"] = await self._preview(record, inputs)
            self._save(record)
        if body.mode == "normal":
            return await self.start(
                workflow_id, checked["workflow_hash"], record["revision"]
            )
        return record

    async def start(self, workflow_id, expected_hash, expected_revision):
        async with self.edit_lock:
            record = self.get(workflow_id)
            if self.closed or record["status"] in ("queued", "running"):
                raise AnalyticsError(
                    "Workflow execution is unavailable or already pending",
                    "state_conflict",
                    409,
                )
            if (
                expected_hash != record["validation"]["workflow_hash"]
                or expected_revision != record["revision"]
            ):
                raise AnalyticsError(
                    "Approval refers to a different plan or input revision",
                    "approval_required",
                    409,
                )
            if len(self.tasks) >= self.settings.max_pending_jobs:
                raise AnalyticsError("Workflow queue is full", "queue_full", 429)
            principal = current_principal.get()
            admission = (
                principal.accounts.admit_jobs(principal.user_id) if principal else None
            )
            record.update(
                status="queued",
                approved_hash=expected_hash,
                approved_at=_now(),
                complete=False,
                steps={},
            )
            record.pop("started_at", None)
            record.pop("finished_at", None)
            record.pop("error", None)
            try:
                self._save(record)
                task = asyncio.create_task(self._execute(workflow_id, admission))
            except BaseException:
                if admission:
                    principal.accounts.abort_admission(admission)
                raise
            self.admin_cancelled.discard(workflow_id)
            if admission:
                self.admissions[workflow_id] = admission
                task.add_done_callback(lambda _done: self.admissions.pop(workflow_id, None))
                task.add_done_callback(
                    lambda _done: principal.accounts.release(admission)
                )
            self.tasks[workflow_id] = task
            task.add_done_callback(
                lambda done: (
                    self.tasks.pop(workflow_id, None)
                    if self.tasks.get(workflow_id) is done
                    else None
                )
            )
            return record

    def _resume(self, record):
        cache = {}
        for revision in range(1, record["revision"] + 1):
            directory = self.root / record["id"] / f"revision-{revision}"
            for path in sorted(directory.glob("step-*.json")):
                try:
                    saved = json.loads(path.read_text())
                except (OSError, ValueError):
                    continue  # Corrupt cache entries are recomputed, never trusted.
                if isinstance(saved, dict) and saved.get("status") == "completed":
                    cache[path.stem[5:]] = saved
        return cache

    async def _execute(self, workflow_id, admission=None):
        record = self.get(workflow_id)
        directory = self._directory(record)
        try:
            plan = record["validation"]["plan"]
            policy, allowed_gpu_uuids = "cpu", set()
            if any(step["device"] != "cpu" for step in plan["steps"]):
                caps = await self._call({"command": "capabilities"})
                policy, allowed_gpu_uuids = execution_admission(
                    plan, caps["problems"]
                )
            memory = estimate_memory(plan, (directory / "inputs.json").stat().st_size)
            principal = current_principal.get()
            limit = (
                principal.accounts.execution_slot(principal.user_id, admission)
                if principal
                else nullcontext()
            )
            async with (
                limit,
                self.scheduler.reserve(
                    policy,
                    memory,
                    timeout=self.settings.job_timeout_seconds,
                    allowed_gpu_uuids=allowed_gpu_uuids,
                ) as lease,
            ):
                (directory / "result.json").unlink(missing_ok=True)
                record.update(
                    status="running",
                    started_at=_now(),
                    steps={},
                    allocation=lease.record(),
                )
                self._save(record)

                async def event(message):
                    step = message["step"]
                    if step not in {
                        s["id"] for s in record["validation"]["plan"]["steps"]
                    }:
                        raise AnalyticsError(
                            "Worker returned an unknown step", "worker_failure"
                        )
                    if message["event"] == "step_finished":
                        saved = message["record"]
                        self._write(directory / f"step-{step}.json", saved)
                        from .view_data import saved_view_manifest
                        try:
                            manifest = await asyncio.to_thread(saved_view_manifest, self, record, step, saved)
                            if manifest is not None:
                                await asyncio.to_thread(self._write, directory / f"step-{step}.views.json", manifest)
                        except Exception:
                            _logger.exception("Could not persist display profile for completed step %s", step)
                        summary = {k: v for k, v in saved.items() if k != "result"}
                        if "result" in saved:
                            summary.update(
                                complete=saved["result"]["complete"],
                                quality=saved["result"]["quality"],
                                backend=saved["result"]["backend"],
                            )
                        record["steps"][step] = summary
                    else:
                        record["steps"][step] = {"status": "running"}
                    self._save(record)
                    await self.events.publish(
                        record["session_id"],
                        "workflow.step",
                        {
                            "workflow_id": workflow_id,
                            "revision": record["revision"],
                            "step": step,
                            **record["steps"][step],
                        },
                    )

                inputs = await asyncio.to_thread(
                    lambda: json.loads((directory / "inputs.json").read_text())
                )
                result = await self._call(
                    {
                        "command": "run",
                        "plan": record["validation"]["plan"],
                        "inputs": inputs,
                        "expected_hash": record["approved_hash"],
                        "resume": self._resume(record),
                        "telemetry": {"workflow_id": workflow_id,
                                      "is_evaluation": bool(record.get("evaluation_id"))},
                    },
                    on_event=event,
                    lease=lease,
                )
                if result["workflow_hash"] != record["approved_hash"]:
                    raise AnalyticsError(
                        "Worker result does not match the approved plan",
                        "worker_failure",
                    )
                await asyncio.to_thread(self._write, directory / "result.json", result)
                record.update(
                    status=result["status"],
                    complete=result["complete"],
                    finished_at=_now(),
                )
        except asyncio.CancelledError:
            record.update(status="cancelled", complete=False, finished_at=_now())
            if workflow_id in self.admin_cancelled:
                record["error"] = {"code": "admin_cancelled", "message": "Cancelled by an administrator"}
        except Exception as exc:  # noqa: BLE001 - persist terminal failures from isolated jobs
            record.update(
                status="failed",
                complete=False,
                finished_at=_now(),
                error={
                    "code": getattr(exc, "code", "workflow_failure"),
                    "message": str(exc),
                },
            )
        finally:
            for step in record["steps"].values():
                if step["status"] == "running":
                    step["status"] = (
                        "cancelled"
                        if record["status"] == "cancelled"
                        else "interrupted"
                    )
            self._save(record)
            await self.events.publish(
                record["session_id"],
                "workflow.finished",
                {
                    "workflow_id": workflow_id,
                    "revision": record["revision"],
                    "status": record["status"],
                    "complete": record.get("complete", False),
                    "error_code": (record.get("error") or {}).get("code"),
                    "error": record.get("error"),
                    **self._admin_event_metadata(record),
                    "duration_ms": ((datetime.fromisoformat(record["finished_at"]) - datetime.fromisoformat(record["started_at"])).total_seconds() * 1000
                                    if record.get("finished_at") and record.get("started_at") else None),
                },
            )
            if record["status"] == "completed" and not self.closed:
                # Separate task: answering must not hold the job's slot.
                task = asyncio.create_task(self._answer(record))
                self.answer_tasks.add(task)
                task.add_done_callback(self.answer_tasks.discard)

    def _question(self, record):
        turn = record.get("planning_turn_id")
        if not turn:
            return None
        for event in self.database.events(record["session_id"], types=("workflow.chat",)):
            if (
                event.payload.get("turn_id") == turn
                and event.payload.get("role") == "user"
            ):
                return event.payload.get("message")
        return None

    def _labels(self, record):
        from .graph_context import display_name
        try:
            inputs = json.loads((self._directory(record) / "inputs.json").read_text())
        except (OSError, ValueError):
            return {}
        labels = {}
        for descriptor in inputs.values():
            data = descriptor.get("data") if isinstance(descriptor, dict) else None
            for vertex in (data or {}).get("vertices", []):
                if isinstance(vertex, dict) and "id" in vertex:
                    labels[json.dumps(vertex.get("id"), sort_keys=True)] = str(
                        display_name(vertex)
                    )
        return labels

    def _answer_input_context(self, record, saved):
        from .analytics_answers import bipartite_input_context
        try:
            inputs = json.loads((self._directory(record) / "inputs.json").read_text())
        except (OSError, ValueError):
            return {}
        return bipartite_input_context(saved, record.get("validation", {}).get("plan", {}), inputs)

    async def _answer(self, record):
        """Publish a chat answer built from the result's facts.

        The facts are published as soon as they are computed. When a model is
        available it then chooses and introduces them, and a second answer event
        replaces the first. A finished workflow never fails because of this.
        """
        from .analytics_answers import (
            build_facts,
            compose,
            default_fact_ids,
            suggested_questions,
            writer_observers,
        )
        from .answer_grounding import Evidence, fact_sources

        try:
            caps = await self.capabilities()
            titles = {card["id"]: card["title"] for card in caps["problems"]}
            saved = await asyncio.to_thread(self.result, record["id"], expected_revision=record['revision'])
            capture = self.database.capture
            if capture:
                await asyncio.to_thread(
                    capture.result, record["session_id"], record["id"],
                    record["revision"], saved,
                )
            labels = await asyncio.to_thread(self._labels, record)
            input_context = await asyncio.to_thread(self._answer_input_context, record, saved)
            facts = build_facts(saved, titles, labels, input_context)
            if not facts:
                return
            turn_id = record.get('planning_turn_id') or f"workflow:{record['id']}:{record['revision']}"
            evidence = Evidence(turn_id).record('build_facts', fact_sources(facts, workflow_id=record['id'], revision=record['revision']))
            await self.events.publish(record['session_id'], 'workflow.evidence',
                {'turn_id': turn_id, 'tool': 'build_facts', 'sources': list(evidence.sources.values())})
            question = self._question(record)
            # A single scalar result already has a complete, grounded answer.
            completed = [step["result"] for step in saved.get("steps", {}).values() if step.get("status") == "completed" and step.get("result")]
            scalar_answer = len(completed) == 1 and any(port.get("type") == "scalar" for port in completed[0].get("ports", {}).values()) and all(port.get("type") == "scalar" or not port.get("value") for port in completed[0].get("ports", {}).values())
            composing = bool(question and self.settings.llm_enabled and not scalar_answer)
            answer = {
                "workflow_id": record["id"],
                "revision": record["revision"],
                "turn_id": record.get("planning_turn_id"),
                "lead": "",
                "fact_ids": default_fact_ids(facts),
                "facts": facts,
                "source": "facts",
                "suggestions": suggested_questions(saved, facts),
                # The browser shows that an introduction is still being written.
                "pending": composing,
                **evidence.facts(default_fact_ids(facts)),
                'sources': evidence.public_sources(default_fact_ids(facts)),
                'grounding': {'checked': True, 'fallback': False, 'attempts': 0},
            }
            assert not evidence.check(answer, turn_id=turn_id, data_answer=True)
            await self.events.publish(record["session_id"], "workflow.answer", answer)
            if not composing:
                return
            try:
                choice = await compose(
                    self.settings, question, facts, evidence=evidence, wake=False,
                    **writer_observers(self.settings, self.events, self.database, record['session_id'], turn_id,
                                       power=self.llm_power, workflow_id=record['id'], revision=record['revision']),
                )
                if not evidence.check(choice, turn_id=turn_id, data_answer=True):
                    answer.update(choice)
                    answer['sources'] = evidence.public_sources(row['id'] for row in answer['citations'])
            except Exception as exc:  # noqa: BLE001 - the facts still answer
                if getattr(exc, "code", None) == "admin_cancelled":
                    answer["notice"] = "Cancelled by an administrator"
                _logger.info("answer composition skipped: %s", exc)
            answer["pending"] = False
            await self.events.publish(record["session_id"], "workflow.answer", answer)
        except asyncio.CancelledError:
            raise
        except Exception:  # Never turn a finished workflow into an error.
            _logger.exception("Could not build the chat answer for %s", record["id"])

    @staticmethod
    def _admin_event_metadata(record):
        return {"problems": list(dict.fromkeys(step["problem"] for step in record.get("validation", {}).get("plan", {}).get("steps", []))),
                "datasets": list(dict.fromkeys(value.get("file_snapshot", {}).get("name", "Unknown input") for value in record.get("input_provenance", {}).values()))}

    async def cancel(self, workflow_id, *, admin=False):
        record = self.get(workflow_id)
        task = self.tasks.get(workflow_id)
        if task:
            if admin:
                self.admin_cancelled.add(workflow_id)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            record = self.get(workflow_id)
            # A task cancelled before its coroutine first runs has no finally.
            if record["status"] == "queued":
                record.update(status="cancelled", complete=False, finished_at=_now())
                if admin:
                    record["error"] = {"code": "admin_cancelled", "message": "Cancelled by an administrator"}
                self._save(record)
                await self.events.publish(record["session_id"], "workflow.finished", {
                    "workflow_id": workflow_id, "revision": record["revision"], "status": "cancelled",
                    "complete": False, "error_code": "admin_cancelled" if admin else None,
                    "error": record.get("error"), **self._admin_event_metadata(record)})
            self.admin_cancelled.discard(workflow_id)
        return record

    def result(self, workflow_id, *, step=None, expected_revision=None):
        """A caller-owned copy of a saved result."""
        return copy.deepcopy(self._saved(workflow_id, step=step, expected_revision=expected_revision))

    def _saved(self, workflow_id, *, step=None, expected_revision=None):
        """The shared, cached parse of a saved result; callers must not modify it."""
        return self._read_result(self._result_path(workflow_id, step=step, expected_revision=expected_revision))

    def _result_path(self, workflow_id, *, step=None, expected_revision=None):
        record = self.get(workflow_id)
        if expected_revision is not None and record["revision"] != expected_revision:
            raise AnalyticsError("This analysis revision changed. Reopen the analysis to load its current result.", "revision_conflict", 409)
        from .admin_data import touch
        touch(self.database, "workflow", workflow_id)
        if step is not None and step not in {
            s["id"] for s in record["validation"]["plan"]["steps"]
        }:
            raise RecordNotFound("Unknown workflow step")
        if step is None and record["status"] not in ("completed", "failed"):
            raise AnalyticsError(
                "The workflow has no completed result", "result_unavailable", 409
            )
        if (
            step is not None
            and record["steps"].get(step, {}).get("status") != "completed"
        ):
            raise AnalyticsError(
                "This step has no completed result in the current execution",
                "result_unavailable",
                409,
            )
        path = self._directory(record) / (
            f"step-{step}.json" if step else "result.json"
        )
        if not path.is_file():
            raise RecordNotFound("No saved result for this workflow revision")
        return path

    def _indexed(self, workflow_id, *, step=None, expected_revision=None):
        from .result_index import build_workflow, file_stamp, open_index

        path = self._result_path(workflow_id, step=step, expected_revision=expected_revision)
        def stamp():
            current = self._result_path(workflow_id, step=step, expected_revision=expected_revision)
            if current != path:
                raise AnalyticsError("This analysis revision changed. Reopen its results.", "revision_conflict", 409)
            return file_stamp(path)
        def build(db):
            with path.open("rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                if self.settings.max_result_bytes is not None and size > self.settings.max_result_bytes:
                    raise AnalyticsError("Workflow artifact exceeds the byte budget", "resource_limit")
                raw = handle.read(size + 1)
            if len(raw) != size:
                raise AnalyticsError("The result changed while it was being read.", "revision_conflict", 409)
            try:
                saved = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise AnalyticsError("The saved result could not be read.", "data_integrity", 409) from exc
            return build_workflow(db, saved)
        return open_index(path.with_suffix(".rows.sqlite3"), stamp, build)

    def _read_result(self, path):
        """Share immutable parses only while their byte budget permits."""
        return self.result_cache.read(path, self.settings.max_result_bytes)

    def result_summary(self, workflow_id, limit=SUMMARY_ITEMS, *, expected_revision=None):
        """Read a bounded summary from the saved artifact's row index."""
        with self._indexed(workflow_id, expected_revision=expected_revision) as index:
            return index.summary(limit)

    def group_graph(
        self, workflow_id, step, port, index, *, vertex_limit=2000, edge_limit=10000, expected_revision=None
    ):
        """One returned group with its connections, read from the full input graph.

        Members come from the saved result, so a group is never limited to what a
        bounded preview happened to include.
        """
        record = self.get(workflow_id)
        if expected_revision is not None and record["revision"] != expected_revision:
            raise AnalyticsError("This analysis revision changed. Reopen its results.", "revision_conflict", 409)
        with self._indexed(workflow_id, step=step, expected_revision=record["revision"]) as indexed:
            output, total, _ = indexed.metadata(_json(["", port]))
            if output.get("type") != "vertex_groups" or not 0 <= index < total:
                raise AnalyticsError("This output has no group at that position", "invalid_selection")
            members = indexed.page(_json(["", port]), index, 1)["items"][0].get("vertices", [])
        plan = record["validation"]["plan"]
        steps, current, alias = {s["id"]: s for s in plan["steps"]}, step, None
        for _ in range(len(steps)):  # Derived graphs keep their input's vertex IDs.
            source = steps.get(current, {}).get("input", {})
            if "input" in source:
                alias = source["input"]
                break
            current = source.get("step")
        inputs = json.loads((self._directory(record) / "inputs.json").read_text())
        graph = (inputs.get(alias) or {}).get("data")
        if not isinstance(graph, dict) or not isinstance(graph.get("vertices"), list):
            raise AnalyticsError(
                "The group's input graph is not available", "result_unavailable", 409
            )
        wanted = {_key(vertex) for vertex in members}
        vertices = [v for v in graph["vertices"] if _key(v.get("id")) in wanted]
        shown = {_key(v["id"]) for v in vertices[:vertex_limit]}
        edges = [
            edge
            for edge in graph.get("edges", [])
            if _key(edge.get("source")) in shown and _key(edge.get("target")) in shown
        ]
        return {
            "graph": graph.get("graph", {}),
            "vertex_count": len(members),
            "edge_count": len(edges),
            "vertices": vertices[:vertex_limit],
            "edges": edges[:edge_limit],
            "vertices_truncated": len(vertices) > vertex_limit,
            "edges_truncated": len(edges) > edge_limit,
            "group": {"step": step, "port": port, "index": index},
        }

    def group_memberships(self, workflow_id, step, port, vertices, *, expected_revision=None):
        """Membership counts across all retained groups for a bounded set of IDs."""
        with self._indexed(workflow_id, step=step, expected_revision=expected_revision) as index:
            return index.memberships(_json(["", port]), vertices)

    def port_page(
        self,
        workflow_id,
        step,
        port,
        offset,
        limit,
        search=None,
        sort=None,
        descending=False,
        min_size=None,
        max_size=None,
        member=None,
        expected_revision=None,
    ):
        with self._indexed(workflow_id, step=step, expected_revision=expected_revision) as index:
            return index.page(_json(["", port]), offset, limit, search=search, sort=sort,
                              descending=descending, min_size=min_size, max_size=max_size, member=member)
