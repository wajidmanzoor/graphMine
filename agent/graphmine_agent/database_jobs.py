"""Durable database queue; request disconnects never own worker lifetime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from threading import Event
from typing import Literal

from fastapi import Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json
from .database import RecordNotFound
from .database_job_context import current_database_job
from .database_pools import pool_scope
from .database_sources import get_source, validate_cypher
from .datasets import _owner
from .identity import AccountError, Principal, current_principal, identity_scope
from .models import new_id, utc_now
from .query_previews import QueryPreviews

PENDING = ("queued", "running", "cancelling")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")
MAX_OWNER_PENDING = 8
# Finished work exists only in memory while clients collect its result.
RESULT_TTL_SECONDS = 5 * 60
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_RESULTS = 256
# Reserve enough for a bounded request, sampled rows and terminal diagnostics.
MAX_DOCUMENT_BYTES = 768 * 1024
MAX_SAMPLE_BYTES = 256 * 1024
logger = logging.getLogger(__name__)


class WorkStopped(AnalyticsError):
    def __init__(self, interrupted=False):
        self.interrupted = interrupted
        super().__init__("The server stopped before this work completed." if interrupted else "Database work cancelled.",
                         "database_interrupted" if interrupted else "database_cancelled", 409)


class JobControl:
    def __init__(self, service, job):
        self.service, self.job = service, job
        self.cancelled, self.stopped = Event(), Event()
        self.sealed = False
        self.last_update = 0
        self.stage = None

    def checkpoint(self, stage=None, completed=None, total=None):
        if self.sealed:
            return
        if self.stopped.is_set():
            raise WorkStopped(interrupted=True)
        if self.cancelled.is_set():
            raise WorkStopped()
        now = time.monotonic()
        if stage == self.stage and now - self.last_update < 0.25:
            return
        self.last_update, self.stage = now, stage
        def update(job):
            if job["status"] == "cancelling":
                raise WorkStopped()
            if stage:
                job["progress"] = {"stage": stage, "completed": completed, "total": total}
        self.service._change(self.job["id"], update)

    def seal(self, stage):
        self.checkpoint()
        with identity_scope(self.service._principal(self.job["owner_id"])):
            self.service._check_source(self.job)
        def update(job):
            if job["status"] == "cancelling":
                raise WorkStopped()
            job["cancellable"] = False
            job["progress"] = {"stage": stage, "completed": None, "total": None}
        self.service._change(self.job["id"], update)
        self.sealed = True


class DatabaseJobs:
    def __init__(self, runtime):
        self.runtime, self.database = runtime, runtime.database
        self._workers, self._controls = [], {}
        self._ready = asyncio.Event()
        self._stopping = False
        self._loop = None
        self._finished = OrderedDict()

    def _prune_finished(self):
        now = time.monotonic()
        for identifier, entry in list(self._finished.items()):
            if entry[0] <= now:
                del self._finished[identifier]

    def _remember_finished(self, job, receipt):
        self._prune_finished()
        previous = self._finished.pop(job["id"], None)
        expires = previous[0] if previous else time.monotonic() + RESULT_TTL_SECONDS
        document = _json(job).encode()
        self._finished[job["id"]] = (expires, document, receipt, len(document))
        size = sum(entry[3] for entry in self._finished.values())
        while len(self._finished) > MAX_RESULTS or size > MAX_RESULT_BYTES:
            _, removed = self._finished.popitem(last=False)
            size -= removed[3]

    def _row(self, db, identifier, *, owned=True):
        row = db.execute("SELECT document FROM database_jobs WHERE id=?" + (" AND owner_id=?" if owned else ""),
                         (identifier, _owner() or "") if owned else (identifier,)).fetchone()
        if row is not None:
            return json.loads(row[0])
        self._prune_finished()
        entry = self._finished.get(identifier)
        job = json.loads(entry[1]) if entry else None
        if job is None or owned and job["owner_id"] != (_owner() or ""):
            raise RecordNotFound("Database job not found or its temporary result has expired")
        return job

    @staticmethod
    def _save(db, job):
        job["updated_at"] = utc_now().isoformat()
        document = _json(job)
        if len(document.encode()) > MAX_DOCUMENT_BYTES:
            raise AnalyticsError("Database job metadata exceeds its budget.", "resource_limit")
        if job["status"] in TERMINAL:
            db.execute("DELETE FROM database_jobs WHERE id=?", (job["id"],))
        else:
            db.execute("UPDATE database_jobs SET status=?,document=?,reserved_bytes=?,updated_at=? WHERE id=?",
                       (job["status"], document, MAX_DOCUMENT_BYTES, job["updated_at"], job["id"]))

    def _change(self, identifier, update, *, owned=False):
        with self.database._lock:
            with self.database._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                job = self._row(db, identifier, owned=owned)
                row = db.execute("SELECT request_key,request_hash FROM database_jobs WHERE id=?", (identifier,)).fetchone()
                receipt = tuple(row) if row else self._finished[identifier][2]
                update(job)
                self._save(db, job)
            # Publish the memory-only receipt after the persistent deletion commits.
            if job["status"] in TERMINAL:
                self._remember_finished(job, receipt)
        return job

    @staticmethod
    def public(job, *, detail=True):
        result = {key: value for key, value in job.items() if key not in {"owner_id", "source_fingerprint", "result"}}
        if job["kind"] == "sync" and job["status"] == "completed" and job.get("result"):
            keys = {"source_id", "build", "finished_at", "nodes", "relationships", "mapping_hash", "revision", "sync_mode", "source_read_mode", "mapped_content_sha256", "changes", "schema_change"}
            result["synchronization"] = {key: value for key, value in job["result"].items() if key in keys}
        if not detail:
            result.pop("query", None)
        return result

    def get(self, identifier):
        with self.database._lock, self.database._connect() as db:
            return self.public(self._row(db, identifier))

    def list(self, *, source_id=None, kind=None, offset=0, limit=20):
        clauses, values = ["owner_id=?", "status IN ('queued','running','cancelling')"], [_owner() or ""]
        if source_id is not None:
            clauses.append("source_id=?"); values.append(source_id)
        if kind is not None:
            clauses.append("kind=?"); values.append(kind)
        with self.database._connect() as db:
            rows = db.execute("SELECT document FROM database_jobs WHERE " + " AND ".join(clauses)
                              + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?", (*values, limit + 1, offset)).fetchall()
        return {"items": [self.public(json.loads(row[0]), detail=False) for row in rows[:limit]],
                "offset": offset, "has_more": len(rows) > limit}

    def enqueue(self, kind, source_id, query=None, *, request_key=None):
        source = get_source(self.runtime.settings, source_id)
        if kind not in {"query", "sync"}:
            raise ValueError("Unknown database job kind")
        if kind == "sync" and source.sql_type is None:
            raise AnalyticsError("This connection has no SQL source to synchronize. Neo4j queries remain available.", "sql_unavailable", 409)
        if kind == "sync" and not source.entities:
            raise AnalyticsError("Add entity table mappings before synchronizing this connection.", "database_mapping", 409)
        if kind == "query":
            validate_cypher(query.statement)
            if len(_json(query.parameters).encode()) > 256 * 1024:
                raise AnalyticsError("Query parameters exceed the byte limit.", "resource_limit")
        if request_key is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_key):
            raise AnalyticsError("Invalid Idempotency-Key.", "invalid_request")
        body = query.model_dump() if query else None
        request_hash = hashlib.sha256(_json({"kind": kind, "source": source_id, "query": body}).encode()).hexdigest()
        owner, now = _owner() or "", utc_now().isoformat()
        job = {"id": new_id("database_job"), "owner_id": owner, "kind": kind, "source_id": source_id,
               "source_name": source.name, "source_fingerprint": source.fingerprint(), "query": body,
               "status": "queued", "progress": {"stage": "queued", "completed": None, "total": None},
               "cancellable": True, "created_at": now, "updated_at": now, "error": None, "result": None}
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._prune_finished()
            if request_key:
                for entry in self._finished.values():
                    if entry[2][0] == request_key:
                        previous = json.loads(entry[1])
                        if previous["owner_id"] != owner:
                            continue
                        if entry[2][1] != request_hash:
                            raise AnalyticsError("This request key was already used for different work.", "idempotency_conflict", 409)
                        return self.public(previous)
                existing = db.execute("SELECT document,request_hash FROM database_jobs WHERE owner_id=? AND request_key=?", (owner, request_key)).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash:
                        raise AnalyticsError("This request key was already used for different work.", "idempotency_conflict", 409)
                    return self.public(json.loads(existing["document"]))
            pending = db.execute("SELECT count(*),coalesce(sum(owner_id=?),0) FROM database_jobs WHERE status IN ('queued','running','cancelling')", (owner,)).fetchone()
            if pending[0] >= self.runtime.settings.max_pending_jobs or pending[1] >= MAX_OWNER_PENDING:
                raise AnalyticsError("Database job queue is full. Wait for a job to finish or cancel one.", "database_queue_full", 429)
            principal = current_principal.get()
            if principal and MAX_DOCUMENT_BYTES > principal.accounts.upload_remaining(principal.user_id):
                raise AccountError("Your storage allowance has no room for this database job.", "storage_limit")
            document = _json(job)
            if len(document.encode()) > MAX_DOCUMENT_BYTES // 2:
                raise AnalyticsError("Database request exceeds its metadata budget.", "resource_limit")
            db.execute("INSERT INTO database_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (job["id"], owner, source_id, kind, "queued", document, request_key, request_hash, MAX_DOCUMENT_BYTES, now, now))
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._ready.set)
        return self.public(job)

    def cancel(self, identifier):
        def update(job):
            if job["status"] in TERMINAL or job["status"] == "cancelling":
                return
            if not job["cancellable"]:
                raise AnalyticsError("This job is committing its result and can no longer be cancelled.", "database_committing", 409)
            job["status"] = "cancelled" if job["status"] == "queued" else "cancelling"
            job["cancellable"] = False
            if job["status"] == "cancelled":
                job["finished_at"] = utc_now().isoformat()
        job = self._change(identifier, update, owned=True)
        control = self._controls.get(identifier)
        if control and job["status"] == "cancelling":
            control.cancelled.set()
        return self.public(job)

    def retry(self, identifier, *, request_key=None):
        from .database_queries import CypherRequest

        with self.database._lock, self.database._connect() as db:
            job = self._row(db, identifier)
        if job["status"] not in {"failed", "cancelled", "interrupted"}:
            raise AnalyticsError("Only stopped or failed work can be retried.", "database_job_state", 409)
        self._check_source(job)
        return self.enqueue(job["kind"], job["source_id"], CypherRequest.model_validate(job["query"]) if job["query"] else None, request_key=request_key)

    def _check_source(self, job):
        source = get_source(self.runtime.settings, job["source_id"])
        if source.fingerprint() != job["source_fingerprint"]:
            raise AnalyticsError("The connection or mapping changed. Review it and submit new work.", "source_changed", 409)
        return source

    def _principal(self, owner):
        if not owner:
            if self.runtime.settings.accounts_enabled:
                raise AccountError("This job has no account owner.", "account_unavailable", 403)
            return None
        if not self.runtime.settings.accounts_enabled:
            raise AccountError("The job's account is unavailable.", "account_unavailable", 403)
        with self.database._connect() as db:
            row = db.execute("SELECT username,role FROM accounts WHERE id=? AND disabled=0", (owner,)).fetchone()
        if row is None:
            raise AccountError("The job's account is unavailable.", "account_unavailable", 403)
        return Principal(owner, row["username"], self.runtime.accounts, is_admin=row["role"] == "admin")

    def recover(self):
        # Keep queued work, but never replay a write that may have committed.
        # Old completed-job history is no longer retained by this application.
        with self.database._lock:
            recovered = []
            with self.database._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM database_jobs WHERE status IN ('completed','failed','cancelled','interrupted')")
                rows = db.execute("SELECT document,request_key,request_hash FROM database_jobs WHERE status IN ('running','cancelling')").fetchall()
                for row in rows:
                    job = json.loads(row[0])
                    job.update(status="interrupted", cancellable=False, finished_at=utc_now().isoformat(),
                               error={"code": "database_interrupted", "message": "The server restarted during this job. " +
                                      ("The graph may already have been committed. Inspect it before explicitly retrying." if job["kind"] == "sync" else "Retry to create a new query snapshot.")})
                    self._save(db, job)
                    recovered.append((job, (row[1], row[2])))
            for job, receipt in recovered:
                self._remember_finished(job, receipt)

    def _claim(self):
        with self.database._lock, self.database._connect() as db:
            self._prune_finished()
            db.execute("BEGIN IMMEDIATE")
            # Serialize work against each source; refresh cannot overlap its own
            # reads or another refresh, even when submitted by different users.
            row = db.execute("SELECT j.document FROM database_jobs j WHERE j.status='queued' AND NOT EXISTS (SELECT 1 FROM database_jobs a WHERE a.source_id=j.source_id AND a.status IN ('running','cancelling')) ORDER BY j.created_at,j.id LIMIT 1").fetchone()
            if row is None:
                return None
            job = json.loads(row[0]); job.update(status="running", started_at=utc_now().isoformat())
            self._save(db, job)
            return job

    @staticmethod
    def _query_result(response):
        snapshot = response.get("dataset") or response.get("table")
        result = {key: value for key, value in response.items() if key not in {"dataset", "table", "graph", "rows"}}
        result["snapshot_id"] = snapshot["id"] if snapshot else None
        result["graph_metadata"] = {key: value for key, value in response["graph"].items() if key not in {"vertices", "edges"}}
        if snapshot and snapshot["kind"] == "table":
            # Table samples can be reconstructed from the exact typed artifact.
            result["rows"] = []
            return result
        # Large graph row values must not duplicate the full snapshot in the
        # temporary result. The original artifact still retains all graph values.
        rows, size = [], 0
        for row in response["rows"]:
            size += len(_json(row).encode())
            if size > MAX_SAMPLE_BYTES:
                result["rows_truncated"] = True
                result["row_sample_warning"] = "The row sample is limited by bytes; the graph snapshot is complete."
                break
            rows.append(row)
        result["rows"] = rows
        return result

    def result(self, identifier):
        with self.database._lock, self.database._connect() as db:
            job = self._row(db, identifier)
        if job["status"] != "completed":
            raise AnalyticsError("This database job has no completed result.", "database_job_state", 409)
        result = job["result"]
        if job["kind"] == "sync":
            return result
        result = dict(result)
        identifier = result.pop("snapshot_id")
        skipped = result["graph_metadata"].get("preview_skipped", False)
        if identifier and skipped:
            metadata, raw = QueryPreviews(self.runtime).get(identifier), None
        else:
            metadata, raw = QueryPreviews(self.runtime).get(identifier, content=True) if identifier else (None, None)
        graph = {**result.pop("graph_metadata"), "vertices": [], "edges": []}
        result.update(dataset=None, table=None, graph=graph)
        if metadata:
            result["table" if metadata["kind"] == "table" else "dataset"] = metadata
            if skipped:
                return result
            if len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                raise AnalyticsError("The query snapshot failed its integrity check.", "data_integrity", 409)
            value = json.loads(raw)
            if metadata["kind"] == "table":
                result["rows"] = value["rows"][:50]
            else:
                from .query_results import graph_preview

                result["graph"] = graph_preview(value)
        return result

    async def wait(self, identifier):
        """A synchronous client waits on durable work without owning its lifetime."""
        while True:
            job = await run_in_threadpool(self.get, identifier)
            if job["status"] == "completed":
                return {**await run_in_threadpool(self.result, identifier), "job_id": identifier}
            if job["status"] in TERMINAL:
                error = job.get("error") or {}
                details = error.get("details")
                details = details if isinstance(details, dict) else {"cause": details} if details is not None else {}
                raise AnalyticsError(error.get("message", "Synchronization did not complete. Inspect the graph before retrying."),
                                     error.get("code", "database_sync"), error.get("status", 409), details={**details, "job_id": identifier})
            await asyncio.sleep(0.1)

    def _execute(self, job, control):
        token = current_database_job.set(control)
        try:
            with identity_scope(self._principal(job["owner_id"])), pool_scope(self.runtime.database_pools):
                control.checkpoint("connecting")
                source = self._check_source(job)
                if job["kind"] == "query":
                    from .database_queries import CypherRequest, run_query

                    response = run_query(self.runtime, job["source_id"], CypherRequest.model_validate(job["query"]))
                    result = self._query_result(response)
                else:
                    from .database_sync import sync_source

                    result = sync_source(source, self.runtime.settings.analytics_max_input_bytes)
                # Test/custom adapters also pass through the publication boundary.
                if not control.sealed:
                    control.seal("saving")
                def complete(current):
                    current.update(status="completed", result=result, cancellable=False, finished_at=utc_now().isoformat(),
                                   progress={"stage": "completed", "completed": None, "total": None})
                self._change(job["id"], complete)
        except Exception as error:
            if isinstance(error, WorkStopped):
                status = "interrupted" if error.interrupted else "cancelled"
            else:
                status = "failed"
            if isinstance(error, (AnalyticsError, AccountError)):
                detail = {"code": error.code, "message": str(error), "status": error.status, "details": getattr(error, "details", None)}
            elif isinstance(error, RecordNotFound):
                detail = {"code": "source_unavailable", "message": "The source is no longer available to this account.", "status": 404}
            else:
                logger.exception("Database job %s failed", job["id"])
                detail = {"code": "database_job_failed", "message": "Database work failed. Check the connection and job status before retrying.", "status": 502}
            if control.sealed and job["kind"] == "sync":
                status = "interrupted"
                detail = {"code": "database_commit_unknown", "message": "The graph commit could not be confirmed. Inspect the graph before explicitly retrying."}
            self._change(job["id"], lambda current: current.update(status=status, error=detail, cancellable=False, finished_at=utc_now().isoformat()))
        finally:
            current_database_job.reset(token)

    async def _worker(self):
        while not self._stopping:
            job = None
            try:
                job = await run_in_threadpool(self._claim)
                if job:
                    control = JobControl(self, job)
                    self._controls[job["id"]] = control
                    try:
                        async with self.runtime.upload_slots:
                            if self._stopping:
                                control.stopped.set()
                            await run_in_threadpool(self._execute, job, control)
                    finally:
                        self._controls.pop(job["id"], None)
                    continue
            except Exception:
                # Keep the durable queue recoverable after a transient store error.
                logger.exception("Database worker could not process its queue")
                if job:
                    # Execution has ended. Reconcile only this worker's job; a
                    # failed terminal write must not strand the source forever.
                    while not self._stopping:
                        try:
                            def interrupted(current):
                                if current["status"] in PENDING:
                                    current.update(status="interrupted", cancellable=False, finished_at=utc_now().isoformat(),
                                                   error={"code": "database_state_unknown", "message": "The job outcome could not be saved. Inspect the source and saved snapshots before explicitly retrying."})
                            await run_in_threadpool(self._change, job["id"], interrupted)
                            break
                        except Exception:
                            logger.exception("Could not reconcile database job %s", job["id"])
                            await asyncio.sleep(1)
            self._ready.clear()
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=1)
            except TimeoutError:
                pass

    async def start(self):
        if self._workers:
            return
        await run_in_threadpool(self.recover)
        self._stopping = False
        self._loop = asyncio.get_running_loop()
        self._workers = [asyncio.create_task(self._worker(), name=f"database-worker-{i}") for i in range(min(4, self.runtime.settings.max_concurrent_uploads))]

    async def stop(self):
        self._stopping = True
        for control in self._controls.values():
            control.stopped.set()
        self._ready.set()
        if self._workers:
            drain = asyncio.gather(*self._workers, return_exceptions=True)
            cancelled = False
            while True:
                try:
                    await asyncio.shield(drain)
                    break
                except asyncio.CancelledError:
                    cancelled = True
            self._workers = []
            self._loop = None
            if cancelled:
                raise asyncio.CancelledError


def accepted(job):
    return JSONResponse({"job": job}, status_code=202, headers={"Location": f"/api/database-jobs/{job['id']}", "Cache-Control": "no-store"})


def private_response(value):
    return JSONResponse(value, headers={"Cache-Control": "private, no-store"})


def register_database_job_routes(router):
    @router.get("/database-jobs")
    def jobs(request: Request, source_id: str | None = None, kind: Literal["query", "sync"] | None = None, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        return private_response(request.app.state.runtime.database_jobs.list(source_id=source_id, kind=kind, offset=offset, limit=limit))

    @router.get("/database-jobs/{identifier}")
    def get(identifier: str, request: Request):
        return private_response(request.app.state.runtime.database_jobs.get(identifier))

    @router.get("/database-jobs/{identifier}/result")
    async def result(identifier: str, request: Request):
        runtime = request.app.state.runtime
        async with runtime.upload_slots:
            return private_response(await run_in_threadpool(runtime.database_jobs.result, identifier))

    @router.delete("/database-jobs/{identifier}")
    def cancel(identifier: str, request: Request):
        return private_response(request.app.state.runtime.database_jobs.cancel(identifier))

    @router.post("/database-jobs/{identifier}/retry", status_code=202)
    def retry(identifier: str, request: Request):
        return accepted(request.app.state.runtime.database_jobs.retry(identifier, request_key=request.headers.get("Idempotency-Key")))
