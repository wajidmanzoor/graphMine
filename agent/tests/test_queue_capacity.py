"""Durable admission bounds, atomic analysis batches, cancellation and restart."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import pytest
from graphmine_agent.api import build_runtime, create_app
from graphmine_agent.database import Database, QueueCapacityError
from graphmine_agent.models import (
    ExecutionPlan,
    FileRole,
    JobRecord,
    JobStatus,
    PlanningOutcome,
    RouteDecision,
    SessionRecord,
)


def setup_runtime(settings, triangle_graph, *, limit=3):
    configured = replace(settings, api_token=None, max_pending_jobs=limit)
    runtime = build_runtime(configured)
    session = runtime.database.create_session(SessionRecord())
    graph = runtime.graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="triangle.json",
        content=triangle_graph,
    )
    plan = ExecutionPlan(
        session_id=session.id,
        graph_id=graph.id,
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
    )
    return runtime, plan


async def test_rejected_batch_creates_no_partial_jobs_and_cancel_frees_capacity(
    settings, triangle_graph
):
    runtime, plan = setup_runtime(settings, triangle_graph)
    try:
        first = await runtime.jobs.enqueue(plan)
        second = await runtime.jobs.enqueue(plan)
        with pytest.raises(QueueCapacityError) as error:
            await runtime.jobs.enqueue_many([plan, plan], analysis_id="does-not-fit")
        assert error.value.pending == 2 and error.value.requested == 2
        assert [job.id for job in runtime.database.list_jobs(plan.session_id)] == [
            first.id,
            second.id,
        ]
        await runtime.jobs.cancel(first.id)
        batch = await runtime.jobs.enqueue_many([plan, plan], analysis_id="fits-now")
        assert [job.step_index for job in batch] == [0, 1]
        assert all(
            job.step_count == 2 and job.analysis_id == "fits-now" for job in batch
        )
        stats = runtime.jobs.statistics()
        assert (
            stats["queue_depth"]
            == stats["pending_count"]
            == stats["max_pending_jobs"]
            == 3
        )
        assert stats["available_slots"] == 0
    finally:
        await runtime.agent.close()


@pytest.mark.parametrize(
    "status", [JobStatus.queued, JobStatus.running, JobStatus.interpreting]
)
async def test_all_pending_states_count_toward_admission(
    settings, triangle_graph, status
):
    runtime, plan = setup_runtime(settings, triangle_graph, limit=1)
    try:
        runtime.database.save_job(
            JobRecord(session_id=plan.session_id, plan=plan, status=status)
        )
        with pytest.raises(QueueCapacityError):
            await runtime.jobs.enqueue(plan)
        assert len(runtime.database.list_jobs()) == 1
        assert runtime.jobs.statistics()["pending_count"] == 1
    finally:
        await runtime.agent.close()


def test_competing_connections_cannot_over_admit_a_batch(database, session):
    other = Database(database.path)
    plan = ExecutionPlan(
        session_id=session.id,
        graph_id="unused",
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
    )
    barrier = threading.Barrier(2)

    def admit(store):
        jobs = [JobRecord(session_id=session.id, plan=plan) for _ in range(3)]
        barrier.wait(timeout=3)
        try:
            store.admit_jobs(jobs, max_pending=4)
            return "accepted"
        except QueueCapacityError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, [database, other]))
    assert sorted(results) == ["accepted", "rejected"]
    assert len(database.list_jobs()) == 3


def test_database_error_rolls_back_the_entire_batch(database, session):
    plan = ExecutionPlan(
        session_id=session.id,
        graph_id="unused",
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
    )
    valid = JobRecord(session_id=session.id, plan=plan)
    invalid = JobRecord(session_id="missing-session", plan=plan)
    with pytest.raises(sqlite3.IntegrityError):
        database.admit_jobs([valid, invalid], max_pending=4)
    assert database.list_jobs() == []
    assert database.pending_job_counts() == {
        "queued": 0,
        "running": 0,
        "interpreting": 0,
    }


async def wait_for_status(database, ids, status=JobStatus.completed):
    async def wait():
        while True:
            jobs = [database.get_job(identifier) for identifier in ids]
            if all(job.status == status for job in jobs):
                return
            for job in jobs:
                if (
                    job.status
                    in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}
                    and job.status != status
                ):
                    raise AssertionError(
                        f"Unexpected terminal job: {job.status}, {job.error}"
                    )
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), 3)


async def test_restart_drains_accepted_backlog_above_new_limit_and_wakes_again(
    settings, triangle_graph
):
    runtime, plan = setup_runtime(settings, triangle_graph, limit=2)
    jobs = [
        runtime.database.save_job(JobRecord(session_id=plan.session_id, plan=plan))
        for _ in range(6)
    ]
    interrupted = runtime.database.save_job(
        JobRecord(session_id=plan.session_id, plan=plan, status=JobStatus.running)
    )
    await runtime.jobs.cancel(jobs[1].id)
    executed = []

    async def execute(plan, workspace):
        executed.append(workspace.name)
        await asyncio.sleep(0.001)
        return {
            "ok": True,
            "provenance": {"test_double": True},
            "warnings": [],
            "output": {"cliques": [[0, 1, 2]], "returned_count": 1, "complete": True},
        }, ["cpu-fixture"]

    runtime.runner.execute = execute
    runtime.jobs.result_handler = None
    try:
        await runtime.jobs.start()
        with pytest.raises(QueueCapacityError):
            await runtime.jobs.enqueue(plan)
        expected = [job.id for job in jobs if job.id != jobs[1].id]
        await wait_for_status(runtime.database, expected)
        assert executed == expected
        assert (
            runtime.database.get_job(interrupted.id).error["code"] == "server_restarted"
        )
        assert runtime.database.get_job(jobs[1].id).status == JobStatus.cancelled
        await asyncio.sleep(0.01)
        later = await runtime.jobs.enqueue(plan)
        await wait_for_status(runtime.database, [later.id])
        assert executed == [*expected, later.id]
        assert runtime.jobs.statistics()["pending_count"] == 0
    finally:
        await runtime.jobs.stop()
        await runtime.agent.close()


async def test_api_rejects_whole_supporting_analysis_with_retry_response(
    settings, triangle_graph, monkeypatch
):
    runtime, plan = setup_runtime(settings, triangle_graph, limit=1)
    app = create_app(runtime.settings)
    app.state.runtime = runtime

    async def ready(*args, **kwargs):
        return PlanningOutcome(
            status="ready",
            message="Authored two-step fixture",
            plan=plan,
            plans=[plan, plan],
            decision=RouteDecision(
                problem_id=plan.problem_id,
                operation_id=plan.operation_id,
                supported=True,
                confidence=1,
                explanation="CPU admission fixture",
            ),
        )

    monkeypatch.setattr(runtime.agent, "plan", ready)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://cpu-fixture"
        ) as client:
            response = await client.post(
                f"/api/sessions/{plan.session_id}/chat",
                json={
                    "message": "Run both analyses",
                    "graph_id": plan.graph_id,
                    "execute": True,
                },
            )
            assert response.status_code == 429, response.text
            assert response.headers["retry-after"] == "5"
            assert response.json()["error"]["code"] == "job_queue_full"
            assert response.json()["error"]["details"] == {
                "limit": 1,
                "pending": 0,
                "requested": 2,
            }
            assert runtime.database.list_jobs() == []
            accepted = await client.post("/api/jobs", json=plan.model_dump(mode="json"))
            assert accepted.status_code == 202, accepted.text
            rejected = await client.post("/api/jobs", json=plan.model_dump(mode="json"))
            assert rejected.status_code == 429
            assert len(runtime.database.list_jobs()) == 1
    finally:
        await runtime.agent.close()


def test_pending_limit_setting_must_be_positive(settings):
    with pytest.raises(ValueError, match="MAX_PENDING_JOBS"):
        replace(settings, max_pending_jobs=0)
