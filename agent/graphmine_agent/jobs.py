from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from .database import Database
from .execution import ExecutionError, GraphMineRunner
from .models import (
    ConversationEvent,
    ExecutionPlan,
    JobRecord,
    JobStatus,
    ResultRecord,
    utc_now,
)
from .results import summarize_result, validate_result


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
        event = self.database.add_event(
            ConversationEvent(
                session_id=session_id,
                job_id=job_id,
                type=event_type,
                payload=payload or {},
            )
        )
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
        result_handler: Callable[[ResultRecord, ExecutionPlan], Awaitable[ResultRecord]]
        | None = None,
    ):
        self.database = database
        self.runner = runner
        self.event_bus = event_bus
        self.summary_items = summary_items
        self.result_handler = result_handler
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._active: dict[str, asyncio.Task[None]] = {}

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.database.mark_interrupted_jobs_failed()
        self._worker = asyncio.create_task(self._run_worker(), name="graphmine-worker")
        for job in self.database.list_jobs(statuses={JobStatus.queued}):
            await self._queue.put(job.id)

    async def stop(self) -> None:
        if self._worker is None:
            return
        worker = self._worker
        self._worker = None
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        for task in tuple(self._active.values()):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)

    async def enqueue(self, plan: ExecutionPlan) -> JobRecord:
        job = self.database.save_job(JobRecord(session_id=plan.session_id, plan=plan))
        await self.event_bus.publish(
            plan.session_id,
            "job.queued",
            {"job_id": job.id, "operation_id": plan.operation_id},
            job_id=job.id,
        )
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> JobRecord:
        job = self.database.get_job(job_id)
        if job.status in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
            return job
        task = self._active.get(job_id)
        if task:
            task.cancel()
        cancelled = job.model_copy(
            update={"status": JobStatus.cancelled, "finished_at": utc_now()}
        )
        self.database.save_job(cancelled)
        await self.event_bus.publish(
            job.session_id, "job.cancelled", {"job_id": job.id}, job_id=job.id
        )
        return cancelled

    async def _run_worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if job_id is None:
                    return
                job = self.database.get_job(job_id)
                if job.status != JobStatus.queued:
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
                finally:
                    self._active.pop(job.id, None)
            finally:
                self._queue.task_done()

    async def _execute(self, job: JobRecord) -> None:
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
            payload, command = await self.runner.execute(job.plan, workspace)
            validate_result(self.runner.catalog, job.plan.operation_id, payload)
            if not payload["ok"]:
                error = payload.get("error", {})
                raise ExecutionError(
                    str(error.get("code", "algorithm_failure")),
                    str(error.get("message", "GraphMine algorithm failed")),
                    exit_code=3,
                )
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
            code = (
                error.code if isinstance(error, ExecutionError) else "execution_error"
            )
            failed = running.model_copy(
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
