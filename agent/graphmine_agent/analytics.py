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
from collections import Counter
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
from .database import RecordNotFound
from .evidence_cache import BOOTSTRAP
from .identity import current_principal
from .ownership import StoreLock


class AnalyticsError(ValueError):
    def __init__(self, message, code="invalid_workflow", status=422):
        super().__init__(message)
        self.code, self.status = code, status


class InputReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str
    kind: Literal["graph", "graph_collection", "feature_vectors", "hypergraph"] = (
        "graph"
    )


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["normal", "interactive", "expert"] = "interactive"
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
# Exact searches whose work can grow quickly with graph size.
SEARCH_FAMILIES = {
    "cliques",
    "community",
    "comparison",
    "dense_structures",
    "independent_sets",
    "optimization",
    "partitioning",
    "pattern_mining",
    "topology",
}
LARGE_SEARCH_EDGES = 5000
RESULT_CACHE_ENTRIES = 8
# Longer outputs reach the browser in pages instead of all at once.
SUMMARY_ITEMS = 2000
SLOW_RUN_SECONDS = 120


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

    def __init__(self, settings, database, graph_store, events):
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
        self.answer_tasks = set()
        self.result_cache = {}
        self.edit_lock = asyncio.Lock()
        self.scheduler = AnalyticsScheduler(settings)
        self.capability_cache = None
        self.capability_task = None
        self.closed = False
        self.opened = False
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, document TEXT NOT NULL)"
            )
        from .analytics_examples import ReviewedExamples

        self.examples = ReviewedExamples(self)

    def open(self):
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
        if not self.opened:
            return
        tasks = list(self.tasks.values()) + list(self.answer_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for record in self._all():
            if record["status"] == "queued":
                record.update(status="cancelled", complete=False)
                self._save(record)
        self.owner.release()
        self.opened = False

    def _all(self, session_id=None):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT document FROM workflows"
                + (" WHERE session_id=?" if session_id else ""),
                (session_id,) if session_id else (),
            )
            return [json.loads(row[0]) for row in rows]

    def list(self, session_id):
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
        return record

    def _save(self, record):
        record["updated_at"] = _now()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO workflows VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                (record["id"], record["session_id"], _json(record)),
            )

    def _directory(self, record):
        # Both values are generated by this service, never client paths.
        return self.root / record["id"] / f"revision-{record['revision']}"

    def _write(self, path, value):
        raw = _json(value).encode()
        if len(raw) > self.settings.max_result_bytes:
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
            total += path.stat().st_size
            if total > self.settings.analytics_max_input_bytes:
                raise AnalyticsError(
                    "Combined workflow inputs exceed the byte budget", "resource_limit"
                )
            try:
                data = json.loads(path.read_text())
            except (ValueError, UnicodeError) as exc:
                raise AnalyticsError(
                    "Workflow inputs must be uploaded canonical JSON files"
                ) from exc
            result[alias] = {"kind": reference.kind, "data": data}
        return result

    def _input_provenance(self, references):
        return {
            alias: {"file_id": file.id, "sha256": file.sha256, **file.provenance}
            for alias, reference in references.items()
            for file in [self.database.get_file(reference.file_id)]
        }

    async def _stop_process(self, process):
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()

    async def _call(self, request, *, on_event=None, lease=None):
        python = (
            self.settings.analytics_python
            or self.settings.repository_root / ".venv-analytics/bin/python"
        )
        if not python.is_file():
            raise AnalyticsError(
                "The analytics Python environment is unavailable",
                "backend_unavailable",
                503,
            )
        raw = _json(request).encode()
        if (
            len(raw)
            > self.settings.analytics_max_input_bytes + self.settings.max_result_bytes
        ):
            raise AnalyticsError(
                "Worker request exceeds the byte budget", "resource_limit"
            )
        env = os.environ.copy()
        env.update(
            GRAPHMINE_REPOSITORY_ROOT=str(self.settings.repository_root),
            GRAPHMINE_EVIDENCE_CACHE_MODULE=str(
                Path(__file__).with_name("evidence_cache.py")
            ),
            GRAPHMINE_EVIDENCE_HASH_CACHE=str(
                self.root / "cache" / "evidence-hashes.json"
            ),
            GRAPHMINE_WORKER_INPUT_BYTES=str(
                self.settings.analytics_max_input_bytes + self.settings.max_result_bytes
            ),
            PYTHONUNBUFFERED="1",
        )
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
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
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self.settings.repository_root,
            start_new_session=True,
            limit=self.settings.max_result_bytes + 1,
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
            final, total = None, 0
            while line := await process.stdout.readline():
                total += len(line)
                if total > self.settings.max_result_bytes * 3:
                    raise AnalyticsError(
                        "Worker output exceeded the byte budget", "resource_limit"
                    )
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
                if message.get("event") == "error":
                    error = message["error"]
                    raise AnalyticsError(error["message"], error["code"])
                if message.get("event") == "complete":
                    final = message["result"]
                elif message.get("event") in ("step_started", "step_finished"):
                    if on_event:
                        await on_event(message)
                else:
                    raise AnalyticsError("Unknown worker event", "worker_failure", 502)
            return final

        try:
            tasks = [
                asyncio.create_task(send()),
                asyncio.create_task(diagnostics()),
                asyncio.create_task(receive()),
            ]
            timeout = (
                self.settings.job_timeout_seconds if request["command"] == "run" else 60
            )
            async with asyncio.timeout(timeout):
                _, _, final = await asyncio.gather(*tasks)
                code = await process.wait()
            if code != 0 or final is None:
                raise AnalyticsError(
                    "Analytics worker exited without a completed response",
                    "worker_failure",
                    502,
                )
            return final
        except TimeoutError as exc:
            raise AnalyticsError(
                "Workflow exceeded its execution deadline", "resource_limit"
            ) from exc
        except (BrokenPipeError, ConnectionResetError, ValueError) as exc:
            if isinstance(exc, AnalyticsError):
                raise
            raise AnalyticsError(
                "Analytics worker communication failed", "worker_failure", 502
            ) from exc
        finally:
            for task in tasks:
                task.cancel()
            await self._stop_process(process)
            await asyncio.gather(*tasks, return_exceptions=True)

    def _capability_key(self):
        paths = [
            self.settings.repository_root / "catalog/native_execution_evidence.json",
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
        result["task_families"] = family_catalog(result["operations"])
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
        if body.planning_turn_id and not any(
            event.type == "workflow.chat"
            and event.payload.get("turn_id") == body.planning_turn_id
            and event.payload.get("role") == "assistant"
            and event.payload.get("status") == "ready"
            for event in self.database.events(session_id)
        ):
            raise AnalyticsError("The planning turn is not ready in this workspace")
        inputs = self._inputs(session_id, body.inputs)
        checked = await self._call(
            {"command": "validate", "plan": body.plan, "inputs": inputs}
        )
        record = {
            "id": str(uuid4()),
            "session_id": session_id,
            "revision": 1,
            "mode": body.mode,
            "evaluation_id": body.evaluation_id,
            "planning_turn_id": body.planning_turn_id,
            "status": "awaiting_review" if body.mode == "interactive" else "ready",
            "created_at": _now(),
            "approved_hash": None,
            "input_files": {k: v.model_dump() for k, v in body.inputs.items()},
            "input_provenance": self._input_provenance(body.inputs),
            "validation": checked,
            "steps": {},
        }
        self._write(self._directory(record) / "inputs.json", inputs)
        record["preview"] = await self._preview(record, inputs)
        if body.mode == "normal" and (record["preview"] or {}).get("expensive"):
            # Explain an expensive run and wait for approval, even in Normal mode.
            record["status"] = "awaiting_review"
        self._save(record)
        if body.mode == "normal" and record["status"] == "ready":
            return await self.start(
                record["id"], checked["workflow_hash"], record["revision"]
            )
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
        cards = {card["id"]: card for card in caps["operations"]}
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
                "operation": step["operation"],
                "title": cards.get(step["operation"], {}).get(
                    "title", step["operation"]
                ),
                "quality": cards.get(step["operation"], {}).get("quality"),
                "device": step.get("device"),
                "search": cards.get(step["operation"], {}).get("family")
                in SEARCH_FAMILIES,
            }
            for step in record["validation"]["plan"]["steps"]
        ]
        input_bytes = (self._directory(record) / "inputs.json").stat().st_size
        edges = max((size["edges"] for size in sizes.values()), default=0)
        past = self._past_runtime(record, input_bytes)
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
        operations = sorted(
            s["operation"] for s in record["validation"]["plan"]["steps"]
        )
        seconds = []
        for other in self._all():
            if (
                other["status"] != "completed"
                or not other.get("started_at")
                or not other.get("finished_at")
                or sorted(
                    s.get("operation")
                    for s in other.get("validation", {})
                    .get("plan", {})
                    .get("steps", [])
                )
                != operations
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
            native["admitted_operations"] = 0
        elif cached:
            operations = cached[2]["operations"]
            admitted = sum(1 for c in operations if any(c["execution"].values()))
            native = {
                "status": "ok" if admitted else "unverified",
                "admitted_operations": admitted,
                "operations": len(operations),
            }
        else:
            native = {"status": "checking", "admitted_operations": 0}
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
            inputs = self._inputs(previous["session_id"], body.inputs)
            checked = await self._call(
                {"command": "validate", "plan": body.plan, "inputs": inputs}
            )
            record = {
                **previous,
                "revision": previous["revision"] + 1,
                "mode": body.mode,
                "evaluation_id": previous.get("evaluation_id") or body.evaluation_id,
                "status": "awaiting_review" if body.mode == "interactive" else "ready",
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
            self._write(self._directory(record) / "inputs.json", inputs)
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
            if admission:
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
                    plan, caps["operations"]
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

                result = await self._call(
                    {
                        "command": "run",
                        "plan": record["validation"]["plan"],
                        "inputs": json.loads((directory / "inputs.json").read_text()),
                        "expected_hash": record["approved_hash"],
                        "resume": self._resume(record),
                    },
                    on_event=event,
                    lease=lease,
                )
                if result["workflow_hash"] != record["approved_hash"]:
                    raise AnalyticsError(
                        "Worker result does not match the approved plan",
                        "worker_failure",
                    )
                self._write(directory / "result.json", result)
                record.update(
                    status=result["status"],
                    complete=result["complete"],
                    finished_at=_now(),
                )
        except asyncio.CancelledError:
            record.update(status="cancelled", complete=False, finished_at=_now())
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
                },
            )
            if record["status"] == "completed" and not self.closed:
                # Separate task: answering must not hold the job's slot.
                task = asyncio.create_task(self._answer(record))
                self.answer_tasks.add(task)
                task.add_done_callback(self.answer_tasks.discard)

    def _question(self, record):
        turn = record.get("planning_turn_id")
        for event in self.database.events(record["session_id"]):
            if (
                turn
                and event.type == "workflow.chat"
                and event.payload.get("turn_id") == turn
                and event.payload.get("role") == "user"
            ):
                return event.payload.get("message")
        return None

    def _labels(self, record):
        try:
            inputs = json.loads((self._directory(record) / "inputs.json").read_text())
        except (OSError, ValueError):
            return {}
        labels = {}
        for descriptor in inputs.values():
            data = descriptor.get("data") if isinstance(descriptor, dict) else None
            for vertex in (data or {}).get("vertices", []):
                if isinstance(vertex, dict) and vertex.get("label") is not None:
                    labels[json.dumps(vertex.get("id"), sort_keys=True)] = str(
                        vertex["label"]
                    )
        return labels

    async def _answer(self, record):
        """Publish a chat answer built from the result's facts.

        A model chooses and introduces facts when available; the facts alone are
        the answer otherwise. A finished workflow never fails because of this.
        """
        from .analytics_answers import build_facts, compose, suggested_questions

        try:
            caps = await self.capabilities()
            titles = {card["id"]: card["title"] for card in caps["operations"]}
            saved = self.result(record["id"])
            facts = build_facts(saved, titles, self._labels(record))
            if not facts:
                return
            choice = {"lead": "", "fact_ids": [fact["id"] for fact in facts[:4]]}
            source = "facts"
            question = self._question(record)
            if question and self.settings.llm_enabled:
                try:
                    choice = await compose(self.settings, question, facts)
                    source = "model"
                except Exception as exc:  # noqa: BLE001 - the facts still answer
                    _logger.info("answer composition skipped: %s", exc)
            await self.events.publish(
                record["session_id"],
                "workflow.answer",
                {
                    "workflow_id": record["id"],
                    "revision": record["revision"],
                    "turn_id": record.get("planning_turn_id"),
                    "lead": choice["lead"],
                    "fact_ids": choice["fact_ids"],
                    "facts": facts,
                    "source": source,
                    "suggestions": suggested_questions(saved),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # Never turn a finished workflow into an error.
            _logger.exception("Could not build the chat answer for %s", record["id"])

    async def cancel(self, workflow_id):
        record = self.get(workflow_id)
        task = self.tasks.get(workflow_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            record = self.get(workflow_id)
            # A task cancelled before its coroutine first runs has no finally.
            if record["status"] == "queued":
                record.update(status="cancelled", complete=False)
                self._save(record)
        return record

    def result(self, workflow_id, *, step=None):
        """A caller-owned copy of a saved result."""
        return copy.deepcopy(self._saved(workflow_id, step=step))

    def _saved(self, workflow_id, *, step=None):
        """The shared, cached parse of a saved result; callers must not modify it."""
        record = self.get(workflow_id)
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
        return self._read_result(path)

    def _read_result(self, path):
        """Parse a saved result once; files never change after they are written."""
        info = path.stat()
        key = (str(path), info.st_mtime_ns, info.st_size)
        cached = self.result_cache.pop(key, None)
        if cached is None:
            cached = json.loads(path.read_text())
        self.result_cache[key] = cached  # Most recently used last.
        while len(self.result_cache) > RESULT_CACHE_ENTRIES:
            self.result_cache.pop(next(iter(self.result_cache)))
        return cached

    def result_summary(self, workflow_id, limit=SUMMARY_ITEMS):
        """The result with long outputs cut to their first items; pages hold the rest."""
        saved = self._saved(workflow_id)
        steps = {}
        for name, step in saved.get("steps", {}).items():
            result = step.get("result")
            if not result:
                steps[name] = step
                continue
            ports = {}
            for port_name, port in (result.get("ports") or {}).items():
                value = port.get("value")
                ports[port_name] = (
                    {
                        **port,
                        "value": value[:limit],
                        "value_truncated": True,
                        "total_items": len(value),
                    }
                    if isinstance(value, list) and len(value) > limit
                    else port
                )
                if port.get("type") == "vertex_groups" and isinstance(value, list):
                    sizes, memberships = [], Counter()
                    for row in value:
                        members = {_key(vertex) for vertex in row.get("vertices", [])}
                        sizes.append(len(members))
                        memberships.update(members)
                    ports[port_name] = {
                        **ports[port_name],
                        "group_summary": {
                            "groups": len(value),
                            "unique_members": len(memberships),
                            "shared_members": sum(n > 1 for n in memberships.values()),
                            "smallest": min(sizes, default=0),
                            "largest": max(sizes, default=0),
                        },
                    }
            steps[name] = {**step, "result": {**result, "ports": ports}}
        return {**saved, "steps": steps}

    def group_graph(
        self, workflow_id, step, port, index, *, vertex_limit=2000, edge_limit=10000
    ):
        """One returned group with its connections, read from the full input graph.

        Members come from the saved result, so a group is never limited to what a
        bounded preview happened to include.
        """
        record = self.get(workflow_id)
        saved = self._saved(workflow_id, step=step)
        output = (saved.get("result", {}).get("ports") or {}).get(port)
        if output is None:
            raise RecordNotFound("No such output port")
        groups = output.get("value")
        if output.get("type") != "vertex_groups" or not 0 <= index < len(groups):
            raise AnalyticsError(
                "This output has no group at that position", "invalid_selection"
            )
        members = groups[index].get("vertices", [])
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

    def group_memberships(self, workflow_id, step, port, vertices):
        """Membership counts across all retained groups for a bounded set of IDs."""
        saved = self._saved(workflow_id, step=step)
        output = saved.get("result", {}).get("ports", {}).get(port)
        if output is None:
            raise RecordNotFound("No such output port")
        if output.get("type") != "vertex_groups":
            raise AnalyticsError(
                "Membership counts require a group output", "invalid_selection"
            )
        wanted = {_key(vertex): vertex for vertex in vertices}
        counts = Counter()
        groups = output["value"]
        for group in groups:
            counts.update(
                {_key(vertex) for vertex in group.get("vertices", [])} & wanted.keys()
            )
        return {
            "scope": "retained_groups",
            "total_groups": len(groups),
            "complete": output.get("complete", False),
            "memberships": [
                {"vertex": vertex, "groups": counts[key]}
                for key, vertex in wanted.items()
            ],
        }

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
    ):
        saved = self._saved(workflow_id, step=step)
        value = saved.get("result", {}).get("ports", {}).get(port)
        if value is None:
            raise RecordNotFound("No such output port")
        rows = value["value"] if isinstance(value["value"], list) else [value["value"]]
        total = len(rows)
        positions = list(range(total))
        if min_size is not None or max_size is not None or member is not None:
            if value.get("type") != "vertex_groups":
                raise AnalyticsError(
                    "Group filters require a group output", "invalid_filter"
                )
            if min_size is not None and max_size is not None and min_size > max_size:
                raise AnalyticsError(
                    "Minimum size must not exceed maximum size", "invalid_filter"
                )
            member_key = None
            if member is not None:
                try:
                    entity = json.loads(member)
                except ValueError:
                    entity = member
                if type(entity) not in (int, str):
                    raise AnalyticsError(
                        "A member ID must be an integer or text", "invalid_filter"
                    )
                member_key = _key(entity)
            matches = []
            for i in positions:
                members = {_key(vertex) for vertex in rows[i].get("vertices", [])}
                if (
                    (min_size is None or len(members) >= min_size)
                    and (max_size is None or len(members) <= max_size)
                    and (member_key is None or member_key in members)
                ):
                    matches.append(i)
            positions = matches
        if search:
            positions = [i for i in positions if _matches(rows[i], search)]
        if sort:
            # Rows without the field sort last in either direction.
            present = [
                i
                for i in positions
                if isinstance(rows[i], dict) and rows[i].get(sort) is not None
            ]
            chosen_set = set(present)
            missing = [i for i in positions if i not in chosen_set]
            present.sort(key=lambda i: _sort_key(rows[i][sort]), reverse=descending)
            positions = present + missing
        chosen = positions[offset : offset + limit]
        return {
            **{k: v for k, v in value.items() if k != "value"},
            "offset": offset,
            "limit": limit,
            "total_items": total,
            "matched_items": len(positions),
            "has_more": offset + limit < len(positions),
            "items": [rows[i] for i in chosen],
            "positions": chosen,
        }
