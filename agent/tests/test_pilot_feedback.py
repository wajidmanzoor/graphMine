import io
import json
import zipfile
from dataclasses import replace

from fastapi.testclient import TestClient
from graphmine_agent.api import create_app

AUTH = {"Authorization": "Bearer test-secret"}


def test_reasoning_endpoint_returns_only_recorded_local_model_output(settings):
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        history = client.app.state.runtime.database.history
        with history.scope(session, "chat", {"message": "A planning request"}):
            history.current(
                "llm.request",
                {
                    "call_id": "llm_test",
                    "request": {
                        "model": "local-qwen",
                        "messages": [
                            {
                                "role": "system",
                                "content": "INPUT_PROMPT_NOT_FOR_DISPLAY",
                            }
                        ],
                        "response_format": {"json_schema": {"name": "PlanDraft"}},
                    },
                },
            )
            history.current(
                "llm.response",
                {
                    "call_id": "llm_test",
                    "body": json.dumps(
                        {
                            "model": "local-qwen",
                            "choices": [
                                {
                                    "message": {
                                        "reasoning": "Recorded Qwen reasoning <script>text</script>",
                                        "content": "{}",
                                    }
                                }
                            ],
                        }
                    ),
                },
            )
        response = client.get(f"/api/sessions/{session}/reasoning", headers=AUTH)
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert (
            response.json()[0]["reasoning"]
            == "Recorded Qwen reasoning <script>text</script>"
        )
        assert response.json()[0]["source"] == "local_model_response"
        assert response.json()[0]["verified_computation"] is False
        assert "INPUT_PROMPT_NOT_FOR_DISPLAY" not in response.text
        assert client.get(f"/api/sessions/{session}/reasoning").status_code == 401


def test_pre_history_messages_remain_visible_and_are_included_in_feedback(settings):
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        database = client.app.state.runtime.database
        database.add_message(session, "user", {"message": "An older question"})
        database.add_message(session, "assistant", {"message": "An older answer"})
        client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"message": "A new question"},
        )
        client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"message": "/feedback Keep the earlier context"},
        )
        workspace = client.get(
            f"/api/sessions/{session}/workspace", headers=AUTH
        ).json()
        assert [row["message"] for row in workspace["messages"][:3]] == [
            "An older question",
            "An older answer",
            "A new question",
        ]
        record = client.get(f"/api/sessions/{session}/feedback", headers=AUTH).json()[0]
        assert record["context"]["transcript"][0]["message"] == "An older question"
        exported = client.get(f"/api/sessions/{session}/history/archive", headers=AUTH)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            conversation = json.loads(archive.read(f"{session}/conversation.json"))
        assert conversation[0]["message"] == "An older question"


def test_local_commands_snapshot_the_conversation_without_model_calls(settings):
    settings = replace(
        settings, deployment_version="pilot-test", llm_route_model="business-test"
    )
    with TestClient(create_app(settings)) as client:
        session = client.post(
            "/api/sessions",
            headers=AUTH,
            json={"title": "Usability session", "participant_id": "tester-17"},
        ).json()["id"]
        target = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={"message": "Which teams should work together?"},
        ).json()["turn_id"]
        runtime = client.app.state.runtime
        before = runtime.database.messages(session)

        async def forbidden(**kwargs):
            raise AssertionError("Local commands must never invoke a model")

        runtime.agent.model.generate = forbidden
        for message in [
            r"\feedback I need a clearer upload example",
            "/correct Show an example CSV",
            "/rate 4 Helpful starting point",
            "/note Testing with a staffing manager",
        ]:
            response = client.post(
                f"/api/sessions/{session}/chat", headers=AUTH, json={"message": message}
            )
            assert response.status_code == 200
            assert response.json()["feedback_id"]
        for message in ["/help", r"\status", "/export", "/unknown-command", "/rate 9"]:
            response = client.post(
                f"/api/sessions/{session}/chat", headers=AUTH, json={"message": message}
            )
            assert response.status_code == 200
            assert response.json()["command"] and not response.json()["job_id"]
        assert runtime.database.messages(session) == before
        records = client.get(f"/api/sessions/{session}/feedback", headers=AUTH).json()
        assert [row["category"] for row in records] == [
            "feedback",
            "correction",
            "rating",
            "note",
        ]
        for record in records:
            assert record["turn_id"] == target
            assert record["context"]["session"]["participant_id"] == "tester-17"
            assert record["context"]["deployment"]["version"] == "pilot-test"
            assert (
                record["context"]["transcript"][0]["message"]
                == "Which teams should work together?"
            )
            assert record["context"]["automatically_used_for_training"] is False
        export = client.get(f"/api/sessions/{session}/feedback/export", headers=AUTH)
        rows = [json.loads(line) for line in export.text.splitlines()]
        assert len(rows) == 4 and all(
            row["review_status"] == "unreviewed" for row in rows
        )
        assert rows[2]["annotation"]["rating"] == 4
        workspace = client.get(
            f"/api/sessions/{session}/workspace", headers=AUTH
        ).json()
        assert workspace["feedback_count"] == 4
        assert len(workspace["messages"]) == 20
        assert not any("llm.request" in row["kind"] for row in workspace["messages"])
        assert client.get(f"/api/sessions/{session}/workspace").status_code == 401
        assert client.get(f"/api/sessions/{session}/feedback/export").status_code == 401


def test_public_activity_is_parsed_stage_evidence_and_survives_resume(
    settings, triangle_graph
):
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        graph = client.post(
            f"/api/sessions/{session}/files",
            headers=AUTH,
            files={"file": ("teams.json", triangle_graph, "application/json")},
        ).json()["id"]
        response = client.post(
            f"/api/sessions/{session}/chat",
            headers=AUTH,
            json={
                "message": "Find every maximal clique",
                "graph_id": graph,
                "execute": False,
            },
        )
        assert response.status_code == 200
        saved = client.get(f"/api/sessions/{session}/workspace", headers=AUTH).json()
        activity = [
            event for event in saved["events"] if event["type"] == "analysis.activity"
        ]
        assert activity and all(
            event["payload"]["turn_id"] == response.json()["turn_id"]
            for event in activity
        )
        assert {event["payload"]["status"] for event in activity} == {
            "running",
            "completed",
        }
        assert all(
            set(event["payload"])
            <= {
                "activity_id",
                "turn_id",
                "stage",
                "status",
                "message",
                "elapsed_seconds",
            }
            for event in activity
        )
        assert saved["files"][0]["id"] == graph and len(saved["messages"]) == 2
        for invalid in [
            {"category": "rating"},
            {"category": "correction"},
            {"rating": True},
        ]:
            assert (
                client.post(
                    f"/api/sessions/{session}/feedback",
                    headers=AUTH,
                    json={"what_went_wrong": "Needs work", **invalid},
                ).status_code
                == 422
            )
