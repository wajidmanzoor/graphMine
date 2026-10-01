from __future__ import annotations

import base64
import time

from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings

AUTH = {"Authorization": "Bearer test-secret"}


def test_domain_upload_chat_gpu_result_and_followup(
    settings: Settings, triangle_graph: bytes
) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/domains").status_code == 401
        domains = client.get("/api/domains", headers=AUTH)
        assert domains.status_code == 200
        assert any(item["id"] == "fraud_detection" for item in domains.json())

        session_response = client.post(
            "/api/sessions",
            headers=AUTH,
            json={"domain_id": "fraud_detection", "title": "Ring study"},
        )
        assert session_response.status_code == 201
        session = session_response.json()

        encoded_token = base64.urlsafe_b64encode(b"test-secret").decode().rstrip("=")
        with client.websocket_connect(
            f"/api/sessions/{session['id']}/events/ws",
            subprotocols=["graphmine", f"graphmine.token.{encoded_token}"],
        ) as websocket:
            assert websocket.accepted_subprotocol == "graphmine"

        upload = client.post(
            f"/api/sessions/{session['id']}/files",
            headers=AUTH,
            files={"file": ("triangle.json", triangle_graph, "application/json")},
            data={"role": "graph", "directed": "false"},
        )
        assert upload.status_code == 201, upload.text
        graph = upload.json()
        assert graph["metadata"]["vertex_count"] == 3
        assert "source_path" not in graph
        assert "canonical_path" not in graph

        chat = client.post(
            f"/api/sessions/{session['id']}/chat",
            headers=AUTH,
            json={
                "message": "Find every maximal clique in this transaction network",
                "graph_id": graph["id"],
                "execute": True,
            },
        )
        assert chat.status_code == 200, chat.text
        job_id = chat.json()["job_id"]
        assert job_id

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert job["status"] == "completed", job

        result = client.get(f"/api/results/{job['result_id']}", headers=AUTH)
        assert result.status_code == 200
        result_body = result.json()
        assert result_body["payload"]["output"]["cliques"] == [[0, 1, 2]]
        assert result_body["interpretation"]["visualizations"]
        assert result_body["interpretation"]["requires_new_execution"] is False
        assert result_body["interpretation"]["evidence"] == [
            {
                "claim": "The computation succeeded.",
                "data_ref": "result.ok",
                "value": True,
            }
        ]

        followup = client.post(
            f"/api/sessions/{session['id']}/chat",
            headers=AUTH,
            json={
                "message": "What does this result mean for the fraud investigation?",
                "result_id": result_body["id"],
            },
        )
        assert followup.status_code == 200
        assert followup.json()["mode"] == "analyst"


def test_static_ui_and_openapi_are_bundled(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "What kind of network are you exploring?" in page.text
        schema = client.get("/openapi.json").json()
        assert "/api/sessions/{session_id}/chat" in schema["paths"]
