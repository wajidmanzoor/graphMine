"""Fault injection against disposable CPU stores; no model or native work."""

from __future__ import annotations

import asyncio
import gc
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from graphmine_agent.api import create_app
from graphmine_agent.execution import ExecutionError
from graphmine_agent.models import FileRole, JobRecord, JobStatus
from test_queue_capacity import setup_runtime, wait_for_status


def no_space(*args, **kwargs):
    raise OSError(28, "Injected history disk full")


async def test_history_failure_preserves_accepted_upload(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    try:
        monkeypatch.setattr(runtime.database.history, "write", no_space)
        record = runtime.graph_store.ingest(
            session_id=plan.session_id,
            role=FileRole.graph,
            filename="accepted.json",
            content=triangle_graph,
        )
        assert runtime.database.get_file(record.id) == record
        assert Path(record.source_path).read_bytes() == triangle_graph
        assert Path(record.canonical_path).is_file()
        assert runtime.database.history.statistics()["status"] == "degraded"
    finally:
        await runtime.agent.close()


async def test_history_failure_does_not_make_admission_ambiguous(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    try:
        monkeypatch.setattr(runtime.database.history, "write", no_space)
        jobs = await runtime.jobs.enqueue_many([plan, plan], analysis_id="accepted")
        assert [job.id for job in runtime.database.list_jobs()] == [
            job.id for job in jobs
        ]
        assert runtime.jobs._ready.is_set()
    finally:
        await runtime.agent.close()


async def test_archive_failure_cannot_stop_worker(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    runtime.runner.probe()
    runtime.jobs.result_handler = None
    try:
        monkeypatch.setattr("graphmine_agent.history.shutil.copyfile", no_space)
        jobs = await runtime.jobs.enqueue_many(
            [plan, plan], analysis_id="archive-failure"
        )
        await runtime.jobs.start()
        await wait_for_status(runtime.database, [job.id for job in jobs])
        await asyncio.sleep(0.02)
        assert runtime.jobs.statistics()["worker_running"]
        assert runtime.database.history.statistics()["failure_count"] >= 2
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()


async def test_failed_start_closes_model_resources(settings, monkeypatch):
    from graphmine_agent import api

    runtime = api.build_runtime(settings)
    close = AsyncMock(wraps=runtime.agent.close)
    monkeypatch.setattr(runtime.agent, "close", close)
    monkeypatch.setattr(api, "build_runtime", lambda configured: runtime)
    monkeypatch.setattr(runtime.runner, "probe", no_space)
    app = create_app(settings)
    with pytest.raises(OSError, match="Injected"):
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must fail")
    close.assert_awaited_once()


def test_connections_close_without_waiting_for_garbage_collection(database, session):
    # Connection context managers commit/rollback but do not themselves close.
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        before = len(list(Path("/proc/self/fd").iterdir()))
        for _ in range(40):
            database.get_session(session.id)
        after = len(list(Path("/proc/self/fd").iterdir()))
        assert after <= before + 2
    finally:
        if enabled:
            gc.enable()
        gc.collect()


async def test_second_worker_cannot_mark_first_workers_job_interrupted(
    settings, triangle_graph
):
    from graphmine_agent.api import build_runtime

    first, plan = setup_runtime(settings, triangle_graph)
    second = build_runtime(first.settings)
    try:
        await first.jobs.start()
        running = first.database.save_job(
            JobRecord(
                session_id=plan.session_id,
                plan=plan,
                status=JobStatus.running,
            )
        )
        with pytest.raises(RuntimeError, match="already owned"):
            await second.jobs.start()
        assert first.database.get_job(running.id).status == JobStatus.running
        await first.jobs.stop()
        await second.jobs.start()
        assert second.database.get_job(running.id).error["code"] == "server_restarted"
    finally:
        await first.jobs.stop()
        await second.jobs.stop()
        await first.agent.close()
        await second.agent.close()


async def test_event_failure_keeps_accepted_job_and_reports_gap(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    try:

        def fail(*args):
            raise sqlite3.OperationalError("injected event write failure")

        monkeypatch.setattr(runtime.database, "add_event", fail)
        job = await runtime.jobs.enqueue(plan)
        assert runtime.database.get_job(job.id).status == JobStatus.queued
        assert runtime.database.history.statistics()["status"] == "degraded"
    finally:
        await runtime.agent.close()


async def test_session_update_failure_rolls_back_admission_and_upload(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    try:
        before = runtime.database.list_files(plan.session_id)
        monkeypatch.setattr(runtime.database, "_touch_session", no_space)
        with pytest.raises(OSError):
            await runtime.jobs.enqueue_many([plan, plan], analysis_id="rollback")
        assert runtime.database.list_jobs() == []
        with pytest.raises(OSError):
            runtime.graph_store.ingest(
                session_id=plan.session_id,
                role=FileRole.graph,
                filename="rollback.json",
                content=triangle_graph,
            )
        assert runtime.database.list_files(plan.session_id) == before
        assert not list(settings.data_root.rglob("rollback.json"))
    finally:
        await runtime.agent.close()


async def test_unrecoverable_database_error_stops_admission_without_reexecution(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    original = runtime.database.save_job

    async def execute(plan, workspace):
        calls.append(workspace.name)
        entered.set()
        await release.wait()
        raise ExecutionError("fixture_failure", "injected execution failure")

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("injected durable state failure")

    runtime.runner.execute = execute
    try:
        jobs = await runtime.jobs.enqueue_many([plan, plan], analysis_id="preserve")
        await runtime.jobs.start()
        await asyncio.wait_for(entered.wait(), 3)
        monkeypatch.setattr(runtime.database, "save_job", fail)
        release.set()
        await asyncio.wait_for(asyncio.shield(runtime.jobs._worker), 3)
        assert calls == [jobs[0].id]
        assert runtime.jobs.statistics()["error"]["code"] == "worker_storage_error"
        with pytest.raises(ExecutionError, match="worker stopped"):
            await runtime.jobs.enqueue(plan)
        assert runtime.database.get_job(jobs[1].id).status == JobStatus.queued
        # Repair/restart fails the interrupted job without repeating it. Its
        # dependent step fails explicitly rather than running with missing input.
        await runtime.jobs.stop()
        monkeypatch.setattr(runtime.database, "save_job", original)
        await runtime.jobs.start()
        await wait_for_status(
            runtime.database, [job.id for job in jobs], JobStatus.failed
        )
        assert calls == [jobs[0].id]
    finally:
        release.set()
        await runtime.jobs.stop()
        await runtime.agent.close()


async def test_isolated_failure_before_running_state_does_not_kill_worker(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    runtime.runner.probe()
    runtime.jobs.result_handler = None
    original = runtime.database.save_job
    first_id = None

    def fail_once(job):
        if job.id == first_id and job.status == JobStatus.running:
            raise sqlite3.OperationalError("injected single state-write failure")
        return original(job)

    try:
        first = await runtime.jobs.enqueue(plan)
        first_id = first.id
        second = await runtime.jobs.enqueue(plan)
        monkeypatch.setattr(runtime.database, "save_job", fail_once)
        await runtime.jobs.start()
        await wait_for_status(runtime.database, [first.id], JobStatus.failed)
        await wait_for_status(runtime.database, [second.id])
        assert runtime.jobs.statistics()["worker_running"]
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()


async def test_cancelled_shutdown_retains_ownership_until_child_exits(
    settings, triangle_graph
):
    from graphmine_agent.ownership import StoreLock

    runtime, plan = setup_runtime(settings, triangle_graph)
    entered, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def execute(plan, workspace):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            draining.set()
            await release.wait()

    runtime.runner.execute = execute
    try:
        job = await runtime.jobs.enqueue(plan)
        await runtime.jobs.start()
        await asyncio.wait_for(entered.wait(), 3)
        stopping = asyncio.create_task(runtime.jobs.stop())
        await asyncio.wait_for(draining.wait(), 3)
        for _ in range(2):
            stopping.cancel()
            await asyncio.sleep(0)
            with (
                pytest.raises(RuntimeError, match="already owned"),
                StoreLock(settings.database_path),
            ):
                pytest.fail("Ownership released before active child exited")
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stopping, 3)
        assert runtime.database.get_job(job.id).status == JobStatus.cancelled
        with StoreLock(settings.database_path):
            pass
    finally:
        release.set()
        await runtime.jobs.stop()
        await runtime.agent.close()


async def test_history_and_report_io_failures_preserve_completed_result(
    settings, triangle_graph, monkeypatch
):
    import httpx

    runtime, plan = setup_runtime(settings, triangle_graph)
    runtime.runner.probe()
    app = create_app(runtime.settings)
    app.state.runtime = runtime
    try:
        monkeypatch.setattr(runtime.database.history, "write", no_space)
        monkeypatch.setattr(runtime.database.history, "text_snapshot", no_space)
        job = await runtime.jobs.enqueue(plan)
        await runtime.jobs.start()
        await wait_for_status(runtime.database, [job.id])
        stored = runtime.database.get_result(runtime.database.get_job(job.id).result_id)
        assert stored.answer and stored.interpretation
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            health = (await client.get("/api/health")).json()
            assert health["status"] == "degraded"
            assert health["worker"]["worker_running"]
            assert health["history"]["failure_count"] > 0
            assert "Injected" not in str(health)
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()
