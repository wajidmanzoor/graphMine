"""Training captures outlive conversations and stay with their owner."""

from __future__ import annotations

import functools
import io
import json
import subprocess
import tarfile
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from graphmine_agent.analytics import AnalyticsError, AnalyticsService, InputReference
from graphmine_agent.analytics_answers import build_facts, compose
from graphmine_agent.analytics_planning import AnalyticsPlanner, route_schema
from graphmine_agent.api import create_app
from graphmine_agent.capture import TrainingCapture, deployment_snapshot
from graphmine_agent.jobs import EventBus
from graphmine_agent.models import FileRole
from test_analytics_answers import LABELS, SAVED, TITLES

AUTH = {"Authorization": "Bearer test-secret"}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_records_are_partitioned_by_owner_and_skip_stream_fragments(tmp_path):
    owners = {"s1": {"id": "acct_a", "username": "ana"}}
    capture = TrainingCapture(tmp_path, owner_of=owners.get)
    capture.event("s1", "workflow.chat", {"turn_id": "t1", "role": "user", "message": "Count triangles"})
    capture.event("s1", "workflow.reasoning.delta", {"turn_id": "t1", "text": "fragment"})
    capture.event("s2", "workflow.chat", {"turn_id": "t2", "role": "user", "message": "Unowned"})
    [record] = lines(tmp_path / "users/acct_a/sessions/s1.jsonl")
    assert record["kind"] == "workflow.chat" and record["turn_id"] == "t1"
    assert record["owner"] == {"id": "acct_a", "username": "ana"}
    assert record["data"]["message"] == "Count triangles"
    # Without accounts, captures still have a single local owner.
    assert lines(tmp_path / "users/local/sessions/s2.jsonl")[0]["owner"]["id"] == "local"


def test_capture_failures_never_reach_the_request(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    capture = TrainingCapture(blocked, owner_of=lambda _session: None)
    capture.record("s1", "workflow.chat", {"message": "Still answered"})
    assert capture.statistics()["failure_count"] >= 1


def test_inputs_are_kept_once_per_owner_by_content(
    settings, database, graph_store, session, triangle_graph, tmp_path
):
    database.capture = TrainingCapture(tmp_path / "captures", owner_of=database.session_owner)
    file = graph_store.ingest(
        session_id=session.id, role=FileRole.graph, filename="triangle.json", content=triangle_graph
    )
    analytics = AnalyticsService(settings, database, graph_store, EventBus(database))
    references = {"main": InputReference(file_id=file.id)}
    analytics._inputs(session.id, references)
    analytics._inputs(session.id, references)
    stored = tmp_path / "captures/users/local/datasets" / file.sha256
    assert (stored / "original").read_bytes() == triangle_graph
    assert json.loads((stored / "canonical.json").read_text())["vertices"]
    assert json.loads((stored / "file.json").read_text())["id"] == file.id
    used = [
        record for record in lines(tmp_path / f"captures/users/local/sessions/{session.id}.jsonl")
        if record["kind"] == "dataset.used"
    ]
    assert [record["data"]["sha256"] for record in used] == [file.sha256]


@pytest.mark.asyncio
async def test_planner_calls_keep_the_exact_request_and_raw_response(
    settings, database, graph_store, session, monkeypatch, tmp_path
):
    database.capture = TrainingCapture(tmp_path / "captures", owner_of=database.session_owner)
    events = EventBus(database)
    planner = AnalyticsPlanner(
        replace(settings, llm_enabled=True, llm_base_url="http://planner.test/v1"),
        AnalyticsService(settings, database, graph_store, events),
        events,
    )
    decision = {"intent": "calculate", "operations": ["triangle-counting"], "message": "Count them."}
    replies = [
        httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(decision), "reasoning": "Triangles were asked for.",
        }, "finish_reason": "stop"}]}),
        httpx.Response(500, json={"error": "offline"}),
    ]
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "graphmine_agent.analytics_planning.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(lambda _r: replies.pop(0)), **kwargs),
    )
    planner.conversation.set({"session_id": session.id, "turn_id": "turn_1"})
    schema = route_schema([{"id": "triangle-counting"}])
    assert await planner._generate("route", {"question": "Count triangles"}, schema) == decision
    with pytest.raises(AnalyticsError):
        await planner._generate("route", {"question": "Count triangles"}, schema)
    records = lines(tmp_path / f"captures/users/local/sessions/{session.id}.jsonl")
    calls = [record for record in records if record["kind"] == "model.call"]
    assert [call["data"]["outcome"] for call in calls] == ["ok", "planner_unavailable"]
    ok, failed = (call["data"] for call in calls)
    assert calls[0]["turn_id"] == "turn_1" and ok["stage"] == "route"
    assert [m["role"] for m in ok["request"]["messages"]] == ["system", "user"]
    assert json.loads(ok["request"]["messages"][1]["content"]) == {
        "stage": "route", "question": "Count triangles",
    }
    assert ok["response"]["choices"][0]["message"]["reasoning"] == "Triangles were asked for."
    assert ok["output"] == decision
    # Reviewed edits are checked against the contract the model was held to.
    assert ok["target_schema"] == schema and ok["output_schema"] == schema
    assert failed["output"] is None
    # The live progress events are captured alongside the model calls.
    assert {"workflow.planning", "workflow.reasoning", "workflow.diagnostics"} <= {
        record["kind"] for record in records
    }


@pytest.mark.asyncio
async def test_answer_composition_reports_its_model_call(settings, monkeypatch, tmp_path):
    facts = build_facts(SAVED, TITLES, LABELS)
    content = {"lead": "Here are the tightest groups.", "fact_ids": ["f1"]}
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "graphmine_agent.analytics_answers.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})
        ), **kwargs),
    )
    capture = TrainingCapture(tmp_path, owner_of=lambda _session: None)
    on_call = functools.partial(capture.model_call, "s1", stage="answer", turn_id="t1", workflow_id="w1")
    configured = replace(settings, llm_base_url="http://model.test/v1")
    assert (await compose(configured, "Which groups are tight?", facts, on_call=on_call))["lead"]
    [call] = lines(tmp_path / "users/local/sessions/s1.jsonl")
    assert call["workflow_id"] == "w1" and call["data"]["stage"] == "answer"
    assert json.loads(call["data"]["request"]["messages"][1]["content"])["facts"] == facts
    assert call["data"]["output"] == content and call["data"]["outcome"] == "ok"


def test_feedback_and_questions_outlive_a_deleted_conversation(settings):
    settings = replace(settings, capture_enabled=True)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        client.portal.call(
            runtime.events.publish, session, "workflow.chat",
            {"turn_id": "turn_q", "role": "user", "message": "Who moves the most money?"},
        )
        saved = client.post(
            f"/api/sessions/{session}/feedback", headers=AUTH,
            json={"category": "rating", "rating": 4, "what_went_wrong": "Close, but slow.", "turn_id": "turn_q"},
        )
        assert saved.status_code in {200, 201}, saved.text
        assert client.delete(f"/api/sessions/{session}", headers=AUTH).status_code == 204
        metrics = client.get("/api/metrics", headers=AUTH).json()["capture"]
        assert metrics["status"] == "ok" and metrics["deployment_id"]
        assert not runtime.database.history.session_path(session).exists()
    records = lines(settings.capture_root / f"users/local/sessions/{session}.jsonl")
    kinds = [record["kind"] for record in records]
    assert kinds.index("workflow.chat") < kinds.index("feedback.saved") < kinds.index("session.deleted")
    feedback = next(record for record in records if record["kind"] == "feedback.saved")
    assert feedback["turn_id"] == "turn_q" and feedback["data"]["rating"] == 4
    assert {record["deployment_id"] for record in records} == {runtime.database.capture.deployment_id}
    deployment = settings.capture_root / "deployments" / records[0]["deployment_id"] / "deployment.json"
    assert "test-secret" not in deployment.read_text()


def test_deployment_records_the_commit_and_every_uncommitted_change(settings, tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    git = functools.partial(subprocess.run, cwd=repository, check=True, capture_output=True)
    git(["git", "init", "-q"])
    (repository / "prompt.py").write_text("SYSTEM = 'v1'\n")
    git(["git", "add", "prompt.py"])
    git(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1"])
    (repository / "prompt.py").write_text("SYSTEM = 'v2'\n")
    (repository / "catalog.py").write_text("CARDS = []\n")
    deployment, patch, untracked = deployment_snapshot(replace(settings, repository_root=repository))
    source = deployment["source"]
    assert len(source["commit"]) == 40 and source["dirty"] is True
    assert b"SYSTEM = 'v2'" in patch
    with tarfile.open(fileobj=io.BytesIO(untracked)) as archive:
        assert archive.extractfile("catalog.py").read() == b"CARDS = []\n"
    assert [item["path"] for item in source["untracked"]] == ["catalog.py"]
    assert "test-secret" not in json.dumps(deployment)
