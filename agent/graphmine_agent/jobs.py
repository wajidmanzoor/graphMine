from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import contextmanager, suppress
from typing import Any

from .database import Database
from .execution import ExecutionError, GraphMineRunner
from .identity import AccountError, current_principal, identity_scope
from .models import (
    ConversationEvent,
    ExecutionPlan,
    JobRecord,
    JobStatus,
    ResultRecord,
    utc_now,
)
from .ownership import StoreLock
from .results import summarize_result, validate_result

_logger = logging.getLogger(__name__)


@contextmanager
def _measure_stage(timings, name):
    started = time.monotonic()
    try:
        yield
    finally:
        timings["stages_seconds"][name] = time.monotonic() - started


class EventBus:
    def __init__(self, database: Database):
        self.database = database
        self._subscribers: dict[str, set[asyncio.Queue[ConversationEvent]]] = (
            defaultdict(set)
        )

    async def publish(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        job_id: str | None = None,
    ) -> ConversationEvent:
        event = ConversationEvent(
            session_id=session_id,
            job_id=job_id,
            type=event_type,
            payload=payload or {},
        )
        try:
            event = self.database.add_event(event)
        except (sqlite3.Error, OSError) as error:
            # Job state is authoritative. A failed notification must not turn
            # committed admission/completion into a false error or repeat work.
            self.database.history.record_failure("event.publish", error)
            return event
        for queue in tuple(self._subscribers.get(session_id, set())):
            with suppress(asyncio.QueueFull):
                queue.put_nowait(event)
        return event

    def subscribe(self, session_id: str) -> asyncio.Queue[ConversationEvent]:
        queue: asyncio.Queue[ConversationEvent] = asyncio.Queue(maxsize=256)
        self._subscribers[session_id].add(queue)
        return queue

    def unsubscribe(
        self, session_id: str, queue: asyncio.Queue[ConversationEvent]
    ) -> None:
        self._subscribers[session_id].discard(queue)
        if not self._subscribers[session_id]:
            self._subscribers.pop(session_id, None)


class JobManager:
    """Serial GraphMine worker for the dedicated compute GPU."""

    def __init__(
        self,
        database: Database,
        runner: GraphMineRunner,
        event_bus: EventBus,
        *,
        summary_items: int,
        max_pending_jobs: int = 64,
        accounts=None,
        result_handler: Callable[[ResultRecord, ExecutionPlan], Awaitable[ResultRecord]]
        | None = None,
    ):
        self.database = database
        self.runner = runner
        self.event_bus = event_bus
        self.summary_items = summary_items
        if max_pending_jobs < 1:
            raise ValueError("max_pending_jobs must be positive")
        self.max_pending_jobs = max_pending_jobs
        self.result_handler = result_handler
        self.accounts = accounts
        self._quota_jobs = {}
        # SQLite owns the pending backlog. This event is only a wakeup signal,
        # so canceled jobs and pre-existing backlogs consume no in-memory queue.
        self._ready = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._active: dict[str, asyncio.Task[None]] = {}
        self._ownership = StoreLock(database.path)
        self._fatal_error: dict[str, str] | None = None

    def statistics(self) -> dict[str, Any]:
        active_ids = sorted(self._active)
        try:
            counts = self.database.pending_job_counts()
            if current_principal.get():
                visible = {job.id for job in self.database.list_jobs()}
                active_ids = [
                    identifier for identifier in active_ids if identifier in visible
                ]
        except (sqlite3.Error, OSError):
            return {
                "worker_running": self._worker is not None and not self._worker.done(),
                "error": {
                    "code": "storage_unavailable",
                    "message": "Cannot read durable job state",
                },
                "queue_depth": None,
                "pending_count": None,
                "available_slots": 0,
                "max_pending_jobs": self.max_pending_jobs,
                "active_count": len(self._active),
                "active_job_ids": [] if current_principal.get() else active_ids,
            }
        return {
            "queue_depth": counts["queued"],
            "pending_count": sum(counts.values()),
            "max_pending_jobs": self.max_pending_jobs,
            "available_slots": max(0, self.max_pending_jobs - sum(counts.values())),
            "active_count": len(self._active),
            "active_job_ids": active_ids,
            "worker_running": self._worker is not None and not self._worker.done(),
            "error": self._fatal_error,
        }

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._ownership.acquire()
        try:
            # Account admission leases are recovered at startup. Do not resume
            # an old queue outside those per-user and shared admission slots.
            self.database.mark_interrupted_jobs_failed(
                include_queued=self.accounts is not None
            )
            self._fatal_error = None
            self._ready.set()
            self._worker = asyncio.create_task(
                self._run_worker(), name="graphmine-worker"
            )
        except BaseException:
            self._ownership.release()
            raise

    async def stop(self) -> None:
        # Keep ownership until every subprocess/task has actually exited, even
        # when lifespan shutdown itself is cancelled more than once.
        drain = asyncio.create_task(self._drain())
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(drain)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    if drain.done():
                        drain.result()
                        break
        finally:
            self._worker = None
            self._ownership.release()
            if cancelled:
                raise asyncio.CancelledError

    async def _drain(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        for task in tuple(self._active.values()):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)

    async def enqueue(
        self,
        plan: ExecutionPlan,
        *,
        analysis_id: str | None = None,
        step_index: int = 0,
        step_count: int = 1,
    ) -> JobRecord:
        jobs = await self._admit(
            [
                JobRecord(
                    session_id=plan.session_id,
                    plan=plan,
                    turn_id=self.database.history.turn_id(),
                    analysis_id=analysis_id,
                    step_index=step_index,
                    step_count=step_count,
                )
            ]
        )
        return jobs[0]

    async def enqueue_many(
        self, plans: list[ExecutionPlan], *, analysis_id: str
    ) -> list[JobRecord]:
        if not plans or len({plan.session_id for plan in plans}) != 1:
            raise ValueError("An analysis must contain plans from one session")
        return await self._admit(
            [
                JobRecord(
                    session_id=plan.session_id,
                    plan=plan,
                    turn_id=self.database.history.turn_id(),
                    analysis_id=analysis_id,
                    step_index=index,
                    step_count=len(plans),
                )
                for index, plan in enumerate(plans)
            ]
        )

    async def _admit(self, jobs: list[JobRecord]) -> list[JobRecord]:
        if self._fatal_error or (self._worker is not None and self._worker.done()):
            raise ExecutionError(
                "worker_unavailable",
                "The worker stopped after a storage failure. Repair storage and restart the API before submitting more work.",
            )
        principal = current_principal.get()
        admission = (
            self.accounts.admit_jobs(principal.user_id, len(jobs))
            if self.accounts and principal
            else None
        )
        if self.accounts and principal is None:
            raise AccountError(
                "A job requires an account owner.", "account_required", 401
            )
        try:
            self.database.admit_jobs(jobs, max_pending=self.max_pending_jobs)
        except BaseException:
            if admission:
                self.accounts.abort_admission(admission)
            raise
        if admission:
            self._quota_jobs.update({job.id: admission for job in jobs})
        self._ready.set()
        for job in jobs:
            await self.event_bus.publish(
                job.session_id,
                "job.queued",
                {"job_id": job.id, "operation_id": job.plan.operation_id},
                job_id=job.id,
            )
        return jobs

    async def cancel(self, job_id: str) -> JobRecord:
        job = self.database.get_job(job_id)
        if job.status in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
            return job
        task = self._active.get(job_id)
        if task:
            task.cancel()
        else:
            self._finish_admission(job_id)
        cancelled = job.model_copy(
            update={"status": JobStatus.cancelled, "finished_at": utc_now()}
        )
        self.database.save_job(cancelled)
        await self.event_bus.publish(
            job.session_id, "job.cancelled", {"job_id": job.id}, job_id=job.id
        )
        return cancelled

    async def _run_worker(self) -> None:
        try:
            await self._work_loop()
        except Exception as error:
            # Do not retry a job when its durable state cannot be trusted.
            self._fatal_error = {
                "code": "worker_storage_error",
                "message": f"Worker stopped after {type(error).__name__}; repair storage and restart",
            }
            _logger.exception("GraphMine worker stopped; queued work is preserved")

    async def _work_loop(self) -> None:
        while True:
            await self._ready.wait()
            job = self.database.next_queued_job()
            if job is None:
                # No await between the durable lookup and clearing the event:
                # admission on this event loop cannot lose its wakeup signal.
                self._ready.clear()
                continue
            task = asyncio.create_task(self._execute(job), name=f"job-{job.id}")
            self._active[job.id] = task
            try:
                await task
            except asyncio.CancelledError:
                if asyncio.current_task() and asyncio.current_task().cancelling():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
            except Exception as error:  # noqa: BLE001
                # Includes failures before the execution try block and during
                # finalization. Preserve completed jobs and stored result IDs.
                await self._fail_job(job, error)
            finally:
                self._active.pop(job.id, None)

    async def _execute(self, job: JobRecord) -> None:
        if self.accounts is None:
            return await self._execute_unlimited(job)
        try:
            principal = self.accounts.session_principal(job.session_id)
            with identity_scope(principal):
                async with self.accounts.execution_slot(
                    principal.user_id, self._quota_jobs.get(job.id)
                ):
                    await self._execute_unlimited(job)
        except AccountError as error:
            await self._fail_job(job, error)
        finally:
            self._finish_admission(job.id)

    def _finish_admission(self, job_id):
        admission = self._quota_jobs.pop(job_id, None)
        if admission and admission not in self._quota_jobs.values():
            self.accounts.release(admission)

    async def _execute_unlimited(self, job: JobRecord) -> None:
        history = self.database.history
        workspace = self.runner.settings.workspaces_root / job.id
        started = time.monotonic()
        active_started_at = utc_now()
        timings = {
            "version": "job-timings-v1",
            "job_id": job.id,
            "operation_id": job.plan.operation_id,
            "queued_at": job.created_at.isoformat(),
            "active_started_at": active_started_at.isoformat(),
            "queue_wait_seconds": max(
                0, (active_started_at - job.created_at).total_seconds()
            ),
            "stages_seconds": {},
            "scope": "Wall times. Execution includes input preparation, subprocess wait and result loading; interpretation includes computed answers, views and optional narration. Final timing persistence and workspace archival are excluded. Queue wait is a nonnegative wall-clock timestamp difference.",
        }
        with history.scope(
            job.session_id, "execution", job.plan, turn_id=job.turn_id, job_id=job.id
        ):
            try:
                await self._execute_job(job, timings)
            finally:
                timings["total_active_seconds"] = time.monotonic() - started
                timings["status"] = self.database.get_job(job.id).status.value
                with history.best_effort("job.timings"):
                    history.write(workspace / "timings.json", timings)
                history.record(job.session_id, "job.timings", timings)
                history.capture_workspace(job.session_id, job.id, workspace)

    async def _execute_job(self, job: JobRecord, timings) -> None:
        running = job.model_copy(
            update={"status": JobStatus.running, "started_at": utc_now()}
        )
        self.database.save_job(running)
        await self.event_bus.publish(
            job.session_id,
            "job.running",
            {"job_id": job.id, "operation_id": job.plan.operation_id},
            job_id=job.id,
        )
        workspace = self.runner.settings.workspaces_root / job.id
        try:
            if job.analysis_id and job.step_index:
                earlier = [
                    item
                    for item in self.database.list_jobs(job.session_id)
                    if item.analysis_id == job.analysis_id
                    and item.step_index < job.step_index
                ]
                if len(earlier) != job.step_index or any(
                    item.status != JobStatus.completed for item in earlier
                ):
                    raise ExecutionError(
                        "supporting_analysis_incomplete",
                        "A supporting analysis failed or was cancelled; the remaining workflow was not executed.",
                    )
            inputs = [job.plan.graph_id] + [
                identifier
                for values in job.plan.auxiliary_inputs.values()
                for identifier in values
            ]
            history = self.database.history
            history.snapshot(
                job.session_id,
                f"jobs/{job.id}/inputs.json",
                {
                    "plan": job.plan,
                    "files": [
                        self.database.get_file(identifier) for identifier in inputs
                    ],
                    "history_files": [
                        f"files/{identifier}/metadata.json" for identifier in inputs
                    ],
                    "capabilities": self.runner.capabilities,
                    "timeout_seconds": self.runner.settings.job_timeout_seconds,
                    "max_result_bytes": self.runner.settings.max_result_bytes,
                },
            )
            with _measure_stage(timings, "execution"):
                payload, command = await self.runner.execute(job.plan, workspace)
            with _measure_stage(timings, "result_validation"):
                validate_result(self.runner.catalog, job.plan.operation_id, payload)
                if not payload["ok"]:
                    error = payload.get("error", {})
                    raise ExecutionError(
                        str(error.get("code", "algorithm_failure")),
                        str(error.get("message", "GraphMine algorithm failed")),
                        exit_code=3,
                    )
            with _measure_stage(timings, "result_storage"):
                result = self.database.save_result(
                    ResultRecord(
                        job_id=job.id,
                        session_id=job.session_id,
                        operation_id=job.plan.operation_id,
                        payload=payload,
                        summary=summarize_result(payload, self.summary_items),
                    )
                )
            if self.result_handler is not None:
                interpreting = running.model_copy(
                    update={
                        "status": JobStatus.interpreting,
                        "command": command,
                        "result_id": result.id,
                    }
                )
                self.database.save_job(interpreting)
                await self.event_bus.publish(
                    job.session_id,
                    "job.interpreting",
                    {"job_id": job.id, "result_id": result.id},
                    job_id=job.id,
                )
                with _measure_stage(timings, "interpretation_and_presentation"):
                    result = await self.result_handler(result, job.plan)
            completed = running.model_copy(
                update={
                    "status": JobStatus.completed,
                    "command": command,
                    "result_id": result.id,
                    "finished_at": utc_now(),
                }
            )
            self.database.save_job(completed)
            await self.event_bus.publish(
                job.session_id,
                "job.completed",
                {"job_id": job.id, "result_id": result.id},
                job_id=job.id,
            )
        except asyncio.CancelledError:
            current = self.database.get_job(job.id)
            if current.status != JobStatus.cancelled:
                self.database.save_job(
                    current.model_copy(
                        update={"status": JobStatus.cancelled, "finished_at": utc_now()}
                    )
                )
            raise
        # A background worker must convert every unexpected implementation or
        # persistence failure into a durable terminal job state.
        except Exception as error:  # noqa: BLE001
            await self._fail_job(job, error)

    async def _fail_job(self, job: JobRecord, error: Exception) -> None:
        current = self.database.get_job(job.id)
        if current.status in {
            JobStatus.completed,
            JobStatus.failed,
        }:
            return
        if current.status == JobStatus.cancelled and not (
            isinstance(error, AccountError) and error.code == "job_time_limit"
        ):
            return
        code = getattr(error, "code", "execution_error")
        failed = current.model_copy(
            update={
                "status": JobStatus.failed,
                "finished_at": utc_now(),
                "error": {"code": code, "message": str(error)},
            }
        )
        self.database.save_job(failed)
        await self.event_bus.publish(
            job.session_id,
            "job.failed",
            {"job_id": job.id, "error": failed.error},
            job_id=job.id,
        )
