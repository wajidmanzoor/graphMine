from __future__ import annotations

import base64
import stat
import textwrap
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from graphmine_agent.api import create_app
from graphmine_agent.config import Settings

AUTH = {"Authorization": "Bearer test-secret"}


def _slow_binary(path: Path, seconds: int = 30) -> Path:
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json
            from pathlib import Path
            import sys
            import time

            if len(sys.argv) > 1 and sys.argv[1] == "list":
                print(json.dumps({{
                    "operation_count": 13,
                    "library_version": "1.0.0",
                    "validated_backend_count": 26,
                    "compiled_backend_count": 1,
                    "operations": [{{
                        "id": "maximal-cliques",
                        "backends": [{{"id": "rdmce", "compiled": True, "validated": True}}],
                    }}],
                }}))
                raise SystemExit(0)
            if len(sys.argv) > 2 and sys.argv[1] == "run":
                time.sleep({seconds})
                output = Path(sys.argv[sys.argv.index("--output") + 1])
                output.write_text(json.dumps({{
                    "ok": True,
                    "provenance": {{"backend": "rdmce", "test_double": True}},
                    "warnings": [],
                    "output": {{"cliques": [[0, 1, 2]], "returned_count": 1, "complete": True}},
                }}), encoding="utf-8")
                raise SystemExit(0)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _create_structured_job(
    client: TestClient, triangle_graph: bytes
) -> tuple[str, str]:
    session = client.post(
        "/api/sessions", headers=AUTH, json={"domain_id": "general"}
    ).json()
    graph = client.post(
        f"/api/sessions/{session['id']}/files",
        headers=AUTH,
        files={"file": ("triangle.json", triangle_graph, "application/json")},
        data={"role": "graph", "directed": "false"},
    ).json()
    response = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "session_id": session["id"],
            "graph_id": graph["id"],
            "problem_id": "maximal_clique_enumeration",
            "operation_id": "maximal-cliques",
            "backend_id": "rdmce",
        },
    )
    assert response.status_code == 202, response.text
    return session["id"], response.json()["id"]


def _wait_for_status(
    client: TestClient, job_id: str, statuses: set[str], timeout: float = 5
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    job: dict[str, object] = {}
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if job.get("status") in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {statuses}: {job}")


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
        assert result_body["answer"]["groups"][0]["vertices"] == [0, 1, 2]
        evidence = result_body["interpretation"]["evidence"]
        assert evidence[0]["data_ref"] == "answer.facts.0.value"
        assert evidence[0]["value"] == 1
        assert evidence[1]["value"]["internal_connections"] == 3

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

        metrics = client.get("/api/metrics", headers=AUTH)
        assert metrics.status_code == 200
        counters = metrics.json()
        assert counters["version"] == "1.0.0"
        assert counters["database"]["sessions"] == 1
        assert counters["database"]["jobs_by_status"]["completed"] == 1
        assert counters["worker"]["worker_running"] is True


def test_static_ui_and_openapi_are_bundled(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "What kind of network are you exploring?" in page.text
        schema = client.get("/openapi.json").json()
        assert schema["info"]["version"] == "1.0.0"
        assert "/api/sessions/{session_id}/chat" in schema["paths"]
        assert "/api/metrics" in schema["paths"]


def test_websocket_rejects_invalid_token(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        session = client.post(
            "/api/sessions", headers=AUTH, json={"domain_id": "general"}
        ).json()
        encoded = base64.urlsafe_b64encode(b"wrong-secret").decode().rstrip("=")
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                f"/api/sessions/{session['id']}/events/ws",
                subprotocols=["graphmine", f"graphmine.token.{encoded}"],
            ):
                pass
        assert rejected.value.code == 4401


def test_running_job_can_be_cancelled(
    settings: Settings, triangle_graph: bytes, tmp_path: Path
) -> None:
    slow_settings = replace(
        settings,
        graphmine_binary=_slow_binary(tmp_path / "slow-graphmine"),
        job_timeout_seconds=60,
    )
    with TestClient(create_app(slow_settings)) as client:
        _session_id, job_id = _create_structured_job(client, triangle_graph)
        _wait_for_status(client, job_id, {"running"})
        response = client.delete(f"/api/jobs/{job_id}", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert _wait_for_status(client, job_id, {"cancelled"})["status"] == "cancelled"


def test_job_timeout_is_durable_failure(
    settings: Settings, triangle_graph: bytes, tmp_path: Path
) -> None:
    timeout_settings = replace(
        settings,
        graphmine_binary=_slow_binary(tmp_path / "timeout-graphmine"),
        job_timeout_seconds=1,
    )
    with TestClient(create_app(timeout_settings)) as client:
        _session_id, job_id = _create_structured_job(client, triangle_graph)
        job = _wait_for_status(client, job_id, {"failed"})
        assert job["error"] == {
            "code": "timeout",
            "message": "GraphMine exceeded 1 seconds",
        }
