"""The redesigned chat shares local commands without losing analysis context."""

import io
import json
import zipfile
from uuid import uuid4

import pytest
import test_workflow_templates as template_fixtures
from fastapi.testclient import TestClient
from graphmine_agent.analytics_planning import AnalyticsPlanner
from graphmine_agent.api import create_app
from graphmine_agent.models import ConversationEvent
from test_pilot_feedback import AUTH

recipes = template_fixtures.recipes


def test_commands_target_analytics_and_remain_outside_model_history(
    settings, monkeypatch
):
    async def answer(self, session_id, body):
        return {
            "status": "needs_information",
            "message": "Which team should I examine?",
            "choices": ["Team A"],
        }

    monkeypatch.setattr(AnalyticsPlanner, "_plan", answer)
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        prefix = f"/api/sessions/{session}"
        runtime = client.app.state.runtime
        planned = client.post(
            prefix + "/analytics/plan",
            headers=AUTH,
            json={
                "message": "Find a cohesive team",
                "inputs": {"main": {"file_id": "sample", "kind": "graph"}},
            },
        )
        assert planned.status_code == 200, planned.text
        turn = planned.json()["turn_id"]
        events_before = runtime.database.events(session)

        async def forbidden(*args, **kwargs):
            pytest.fail("A local command invoked a model")

        monkeypatch.setattr(runtime.agent.model, "generate", forbidden)
        monkeypatch.setattr(AnalyticsPlanner, "_plan", forbidden)
        for message in [
            "/",
            "/help",
            r"\status",
            "/unknown",
            "/rate 9",
            "/feedback unclear | explain the team",
            "/correct Team A",
            "/rate 4 useful",
            "/note inspect a second team",
            "/export",
        ]:
            response = client.post(
                prefix + "/chat", headers=AUTH, json={"message": message}
            )
            assert response.status_code == 200, response.text
            assert response.json()["command"] is not None
            assert response.json()["job_id"] is None

        records = client.get(prefix + "/feedback", headers=AUTH).json()
        assert [row["category"] for row in records] == [
            "feedback",
            "correction",
            "rating",
            "note",
        ]
        assert all(row["turn_id"] == turn for row in records)
        for record in records:
            context = record["context"]
            assert [row["message"] for row in context["transcript"][:2]] == [
                "Find a cohesive team",
                "Which team should I examine?",
            ]
            assert context["deployment"]["version"] == settings.deployment_version
            assert context["analysis_events"][0]["payload"]["turn_id"] == turn
            assert not context["automatically_used_for_training"]
        # Both planning's event history and classic chat's model history stay clean.
        assert runtime.database.events(session) == events_before
        assert runtime.database.messages(session) == []
        messages = client.get(prefix + "/workspace", headers=AUTH).json()["messages"]
        assert len(messages) == 22
        assert [row["kind"] for row in messages[:2]] == ["workflow.chat"] * 2
        exported = client.get(prefix + "/feedback/export", headers=AUTH)
        assert len(exported.text.splitlines()) == 4
        with zipfile.ZipFile(
            io.BytesIO(client.get(prefix + "/history/archive", headers=AUTH).content)
        ) as bundle:
            assert json.loads(bundle.read(f"{session}/conversation.json")) == messages
            assert len(json.loads(bundle.read(f"{session}/analytics/events.json"))) == 2


def test_feedback_can_target_an_earlier_answer_but_not_another_session(settings):
    with TestClient(create_app(settings)) as client:
        database = client.app.state.runtime.database
        sessions = [
            client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
            for _ in range(2)
        ]
        turns = [str(uuid4()) for _ in range(3)]
        for session, turn in zip([sessions[0], sessions[0], sessions[1]], turns):
            database.add_event(
                ConversationEvent(
                    session_id=session,
                    type="workflow.chat",
                    payload={"turn_id": turn, "role": "assistant", "message": turn},
                )
            )
        prefix = f"/api/sessions/{sessions[0]}"
        body = {"what_went_wrong": "Review this answer", "turn_id": turns[0]}
        saved = client.post(prefix + "/feedback", headers=AUTH, json=body)
        assert saved.status_code == 201, saved.text
        assert saved.json()["turn_id"] == turns[0]
        body["turn_id"] = turns[2]
        assert (
            client.post(prefix + "/feedback", headers=AUTH, json=body).status_code
            == 422
        )
        # Command replies do not replace the last actual analysis target.
        client.post(prefix + "/chat", headers=AUTH, json={"message": "/help"})
        default = client.post(
            prefix + "/feedback",
            headers=AUTH,
            json={"what_went_wrong": "Latest answer"},
        )
        assert default.json()["turn_id"] == turns[1]
        assert (
            client.post(prefix + "/chat", json={"message": "/help"}).status_code == 401
        )


def test_session_archive_includes_native_artifacts_and_respects_ownership(recipes):
    client, runtime, alice, bob, session, _, record, result = recipes
    session = record["session_id"]
    directory = runtime.analytics._directory(record)
    runtime.analytics._write(directory / "inputs.json", {"main": {"sample": True}})
    private = runtime.settings.data_root / "private-test.txt"
    private.write_text("not part of this session")
    (directory / "outside.txt").symlink_to(private)
    path = f"/api/sessions/{session}/history/archive"
    response = client.get(path, headers=alice)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        prefix = f"{session}/analytics/{record['id']}/revision-1/"
        assert json.loads(bundle.read(prefix + "result.json")) == result
        assert json.loads(bundle.read(prefix + "inputs.json")) == {
            "main": {"sample": True}
        }
        assert prefix + "outside.txt" not in bundle.namelist()
        assert (
            json.loads(bundle.read(f"{session}/analytics/workflows.json"))[0]["id"]
            == record["id"]
        )
    assert client.get(path, headers=bob).status_code == 404
