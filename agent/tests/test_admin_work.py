"""Phase-three acceptance: measured aggregates, private metadata and cancellation."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from graphmine_agent import admin_events, admin_jobs, admin_model_calls
from graphmine_agent.identity import AccountError, Principal, identity_scope
from graphmine_agent.models import ConversationEvent, ExecutionPlan, SessionRecord
from test_accounts import PASSWORD
from test_admin_console import console


def make_workflow(runtime, principal, identifier="admin-cancel-work"):
    with identity_scope(principal):
        session = runtime.database.create_session(SessionRecord(domain_id="general", title="PRIVATE CONVERSATION"))
    record = {"id": identifier, "session_id": session.id, "revision": 1, "status": "draft", "mode": "expert", "steps": {},
              "created_at": datetime.now(timezone.utc).isoformat(), "private_question": "PRIVATE QUESTION",
              "validation": {"workflow_hash": "test-hash", "plan": {"device": "cpu", "steps": [{"id": "core", "operation": "k-core", "device": "cpu", "parameters": {"k": 2}}]}},
              "input_provenance": {"graph": {"file_snapshot": {"name": "triangle.json", "graph": {"vertex_count": 3, "edge_count": 3}}, "private_input": "PRIVATE CONTENT"}}}
    runtime.analytics._save(record)
    runtime.analytics._write(runtime.analytics._directory(record) / "inputs.json", {})
    return record


@pytest.mark.parametrize("before_start", [True, False])
def test_cancel_workflow_refunds_once_and_notifies_owner(console, monkeypatch, before_start):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    _, principal = accounts.login("member", PASSWORD, "local")
    record = make_workflow(runtime, principal)
    started = asyncio.Event()

    async def hang(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.analytics, "_call", hang)

    async def start():
        with identity_scope(principal):
            await runtime.analytics.start(record["id"], "test-hash", 1)
        if before_start:
            with identity_scope(Principal(accounts.user("owner")["id"], "owner", accounts, is_admin=True)):
                return await admin_jobs.cancel(runtime, "workflow", record["id"])
        await asyncio.wait_for(started.wait(), 3)

    result = client.portal.call(start)
    if not before_start:
        # Owners can be disabled while their existing work is still running.
        accounts.disable("member")
        response = client.post(f"/api/admin/jobs/workflow/{record['id']}/cancel", headers=admin)
        assert response.status_code == 200, response.text
        result = response.json()
    assert result["daily_job_refunded"]
    with accounts.database._connect() as db:
        assert db.execute("SELECT jobs FROM quota_buckets WHERE scope=?", (principal.user_id,)).fetchone()[0] == 0
        assert db.execute("SELECT jobs FROM quota_buckets WHERE scope='server'").fetchone()[0] == 0
        row = db.execute('SELECT actor,"before","after" FROM admin_activity WHERE action=\'calculation.cancelled\'').fetchone()
        assert row[0] == "owner" and json.loads(row[2])["daily_job_refunded"]
        assert json.loads(row[1])["status"] in {"queued", "running"}
        event = db.execute("SELECT payload FROM conversation_events WHERE session_id=? AND type='workflow.finished'", (record["session_id"],)).fetchone()
        assert json.loads(event[0])["error"]["message"] == "Cancelled by an administrator"
        assert db.execute("SELECT count(*) FROM events WHERE type='calculation'").fetchone()[0] == 1
    response = client.post(f"/api/admin/jobs/workflow/{record['id']}/cancel", headers=admin)
    assert response.status_code == 409
    detail = client.get(f"/api/admin/jobs/workflow/{record['id']}", headers=admin)
    assert detail.json()["status"] == "cancelled"
    assert detail.json()["inputs"][0]["vertex_count"] == 3
    assert "PRIVATE" not in detail.text
    assert client.get("/api/admin/jobs?view=finished", headers=admin).json()["calculations"][0]["id"] == record["id"]


def test_model_call_cancel_tracks_wait_positions_and_never_copies_prompt(console):
    client, accounts, admin, _ = console
    _, principal = accounts.login("member", PASSWORD, "local")
    tasks, entered = [], []

    async def launch():
        async def call(index):
            with identity_scope(principal):
                async with admin_model_calls.observe({"messages": [{"content": "PRIVATE PROMPT"}], "response_format": {"json_schema": {"name": "AnalyticsRoute"}}}):
                    if index == 0:
                        admin_model_calls.running("test-lease", accounts.clock())
                        admin_model_calls.usage({"total_tokens": 19})
                    entered.append(index)
                    await asyncio.Event().wait()
        tasks.extend(asyncio.create_task(call(i)) for i in range(3))
        while len(entered) < 3:
            await asyncio.sleep(0)

    client.portal.call(launch)
    response = client.get("/api/admin/jobs", headers=admin)
    calls = response.json()["model_calls"]
    assert "PRIVATE" not in response.text
    assert [r["position"] for r in calls] == [None, 1, 2]
    assert calls[0]["tokens"] == 19 and calls[1]["tokens"] is None
    assert calls[0]["stage"] == "route"
    cancelled = client.post(f"/api/admin/model-calls/{calls[1]['id']}/cancel", headers=admin)
    assert cancelled.status_code == 200, cancelled.text

    async def finish():
        with pytest.raises(AccountError, match="Cancelled by an administrator"):
            await tasks[1]
        for task in (tasks[0], tasks[2]):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    client.portal.call(finish)
    assert accounts.model_calls == {}
    with accounts.database._connect() as db:
        audit = db.execute('SELECT actor,"before","after" FROM admin_activity WHERE action=\'model_call.cancelled\'').fetchone()
        assert audit[0] == "owner" and json.loads(audit[1])["status"] == "waiting"
        assert json.loads(audit[2])["status"] == "cancel_requested"


def test_usage_measured_totals_percentiles_comparison_cache_and_missing_values(console):
    client, accounts, admin, _ = console
    user = accounts.user("member")["id"]
    now = accounts.clock()
    for ms in (100, 300):
        admin_events.record(accounts.database, "question", "Question completed", user_id=user, duration_ms=ms, ts=now - 10,
                            details={"tokens": 50, "reasoning_tokens": 20, "stage_ms": {"route": ms}, "private": "PRIVATE TEXT"})
    admin_events.record(accounts.database, "question", "Question completed", user_id=user, duration_ms=400, ts=now - 7 * 86400 - 10, details={"tokens": 30})
    admin_events.record(accounts.database, "calculation", "Calculation failed", user_id=user, outcome="failed", duration_ms=250,
                        details={"datasets": ["triangle.json"], "operations": ["k-core"]})
    admin_events.record(accounts.database, "error", "Calculation failure", user_id=user, outcome="worker_failure", details={"code": "worker_failure"})
    response = client.get("/api/admin/usage?days=7", headers=admin)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "PRIVATE" not in response.text
    assert data["summary"]["questions"] == 2 and data["previous"]["questions"] == 1
    assert data["summary"]["tokens"] == 100 and data["summary"]["reasoning_share"] == .4
    assert data["summary"]["answer_median_ms"] == 200 and data["summary"]["answer_p95_ms"] == 290
    assert data["summary"]["error_rate"] == pytest.approx(1 / 3)  # error row does not double count
    assert data["datasets"] == [{"dataset": "triangle.json", "count": 1}]
    assert data["routing_corrections"] is None
    admin_events.record(accounts.database, "question", "Older format", user_id=user)
    assert client.get("/api/admin/usage?days=7", headers=admin).json() == data
    accounts.clock = lambda: now + 61
    refreshed = client.get("/api/admin/usage?days=7", headers=admin).json()
    assert refreshed["summary"]["tokens"] is None and refreshed["summary"]["tokens_recorded"] == 100
    assert refreshed["tokens_by_user"][0]["missing"] == 1
    assert "questions,3,1" in client.get("/api/admin/usage/export?days=7", headers=admin).text
    assert client.get("/api/admin/usage?days=8", headers=admin).status_code == 422


def test_empty_usage_does_not_fabricate_timings_or_errors(console):
    client, _, admin, _ = console
    data = client.get("/api/admin/usage?days=14", headers=admin).json()
    assert data["summary"]["answer_median_ms"] is None
    assert data["summary"]["error_rate"] is None
    assert data["time_breakdown"] == [] and data["errors"] == []
    assert len(data["daily"]) == 14


def test_cancel_waiting_legacy_batch_refunds_only_cancelled_jobs(console):
    client, accounts, admin, _ = console
    runtime = client.app.state.runtime
    _, principal = accounts.login("member", PASSWORD, "local")
    with identity_scope(principal):
        session = runtime.database.create_session(SessionRecord(domain_id="general"))
    held = accounts.acquire(principal.user_id, "execution", 4)

    async def enqueue():
        with identity_scope(principal):
            plan = ExecutionPlan(session_id=session.id, graph_id="unused-test-input", problem_id="maximal_clique_enumeration", operation_id="maximal-cliques")
            jobs = await runtime.jobs.enqueue_many([plan, plan], analysis_id="admin-refund-batch")
        for _ in range(100):
            if accounts.waiting.get("execution"):
                return [j.id for j in jobs]
            await asyncio.sleep(.01)
        raise AssertionError("The real queue did not start waiting")

    identifiers = client.portal.call(enqueue)
    for index, identifier in enumerate(identifiers):
        response = client.post(f"/api/admin/jobs/job/{identifier}/cancel", headers=admin)
        assert response.status_code == 200, response.text
        with accounts.database._connect() as db:
            assert db.execute("SELECT jobs FROM quota_buckets WHERE scope=?", (principal.user_id,)).fetchone()[0] == 1 - index
            assert db.execute("SELECT jobs FROM quota_buckets WHERE scope='server'").fetchone()[0] == 1 - index
    accounts.release(held)
    assert runtime.jobs.admin_refunded == set()


def test_partial_provider_usage_is_not_presented_as_complete(console):
    _, accounts, _, _ = console
    _, principal = accounts.login("member", PASSWORD, "local")
    with identity_scope(principal):
        session = accounts.database.create_session(SessionRecord(domain_id="general"))
        for payload in ({"stage": "family", "seconds": .1, "usage": {"total_tokens": 12, "completion_tokens_details": {"reasoning_tokens": 3}}},
                        {"stage": "route", "seconds": .2, "usage": None}):
            accounts.database.add_event(ConversationEvent(session_id=session.id, type="workflow.diagnostics", payload={"turn_id": "partial-turn", **payload}))
        accounts.database.add_event(ConversationEvent(session_id=session.id, type="workflow.chat", payload={"role": "assistant", "turn_id": "partial-turn", "message": "Private answer"}))
    with accounts.database._connect() as db:
        details = json.loads(db.execute("SELECT details_json FROM events WHERE type='question'").fetchone()[0])
    assert details["tokens"] is None and details["reasoning_tokens"] is None
    assert details["tokens_recorded"] == 12


async def test_cancelled_explanation_propagates_instead_of_silently_falling_back(settings, monkeypatch):
    from dataclasses import replace
    from graphmine_agent.analytics_answers import build_facts, compose
    from test_analytics_answers import SAVED, TITLES, LABELS

    async def cancelled(*args, **kwargs):
        raise AccountError("Cancelled by an administrator", "admin_cancelled", 409)

    monkeypatch.setattr("graphmine_agent.accounts.model_post", cancelled)
    with pytest.raises(AccountError, match="Cancelled by an administrator"):
        await compose(replace(settings, llm_enabled=True), "Explain", build_facts(SAVED, TITLES, LABELS))
