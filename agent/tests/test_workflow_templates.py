import json
import time
from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from test_accounts import PASSWORD, login


@pytest.fixture
def recipes(settings, triangle_graph):
    with TestClient(create_app(replace(settings, accounts_enabled=True))) as client:
        runtime = client.app.state.runtime
        for username in ("alice", "bob"):
            runtime.accounts.create_user(username, PASSWORD)
        alice, bob = login(client), login(client, "bob")
        sid = client.post("/api/sessions", headers=alice, json={}).json()["id"]
        file = client.post(
            f"/api/sessions/{sid}/files",
            headers=alice,
            files={"file": ("triangle.json", triangle_graph)},
        ).json()
        record = {
            "id": "original",
            "session_id": sid,
            "revision": 1,
            "status": "completed",
            "input_files": {"main": {"file_id": file["id"], "kind": "graph"}},
            "validation": {
                "workflow_hash": "a" * 64,
                "inputs": {"main": {"kind": "graph", "fingerprint": "input-a"}},
                "plan": {
                    "version": 1,
                    "device": "cpu",
                    "steps": [
                        {
                            "id": "core",
                            "operation": "k-core",
                            "input": {"input": "main"},
                            "parameters": {"requested_k": 1},
                            "bindings": {},
                        }
                    ],
                },
            },
            "steps": {"core": {"status": "completed"}},
        }
        runtime.analytics._save(record)
        result = {
            "steps": {
                "core": {
                    "status": "completed",
                    "result": {
                        "operation": "k-core",
                        "quality": "exact",
                        "complete": True,
                        "ports": {
                            "count": {"type": "scalar", "value": 3, "complete": True}
                        },
                    },
                }
            }
        }
        runtime.analytics._write(
            runtime.analytics._directory(record) / "result.json", result
        )
        yield client, runtime, alice, bob, sid, file, record, result


def save(client, alice):
    response = client.post(
        "/api/workflow-templates",
        headers=alice,
        json={"name": "Core recipe", "workflow_id": "original", "expected_revision": 1},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_template_use_validates_real_native_inputs_and_waits_for_review(recipes):
    client, runtime, alice, _, sid, file, original, _ = recipes
    template = save(client, alice)
    body = {
        "inputs": {"main": {"file_id": file["id"], "kind": "graph"}},
        "parameters": {"core": {"requested_k": 2}},
    }
    response = client.post(
        f"/api/sessions/{sid}/workflow-templates/{template['id']}/use",
        headers=alice,
        json=body,
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "awaiting_review" and record["approved_hash"] is None
    assert record["validation"]["plan"]["steps"][0]["parameters"]["requested_k"] == 2
    assert record["source_template"]["id"] == template["id"]
    assert not runtime.analytics.tasks
    assert runtime.analytics.get("original")["validation"] == original["validation"]
    assert client.get("/api/workflow-templates", headers=alice).json() == [template]
    # The reused recipe actually runs through the verified CPU engine after approval.
    response = client.post(
        f"/api/workflows/{record['id']}/run",
        headers=alice,
        json={
            "workflow_hash": record["validation"]["workflow_hash"],
            "expected_revision": 1,
        },
    )
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        finished = client.get(f"/api/workflows/{record['id']}", headers=alice).json()
        if finished["status"] not in {"queued", "running"}:
            break
        time.sleep(0.05)
    assert finished["status"] == "completed", finished.get("error")


def test_template_access_revision_and_binding_checks(recipes):
    client, runtime, alice, bob, sid, file, _, _ = recipes
    template = save(client, alice)
    assert client.get("/api/workflow-templates", headers=bob).json() == []
    assert (
        client.delete(
            f"/api/workflow-templates/{template['id']}", headers=bob
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/workflow-templates",
            headers=alice,
            json={"name": "stale", "workflow_id": "original", "expected_revision": 2},
        ).status_code
        == 409
    )
    path = f"/api/sessions/{sid}/workflow-templates/{template['id']}/use"
    assert client.post(path, headers=bob, json={"inputs": {}}).status_code == 404
    assert client.post(path, headers=alice, json={"inputs": {}}).status_code == 422
    response = client.post(
        path,
        headers=alice,
        json={
            "inputs": {"main": {"file_id": file["id"], "kind": "graph"}},
            "parameters": {"missing": {"requested_k": 2}},
        },
    )
    assert response.status_code == 422
    assert len(runtime.analytics.list(sid)) == 1


def test_comparison_records_input_differences_exact_values_and_completeness(recipes):
    client, runtime, alice, bob, _, _, original, result = recipes
    second = deepcopy(original)
    second["id"] = "second"
    second["validation"]["inputs"]["main"]["fingerprint"] = "different-input"
    runtime.analytics._save(second)
    result = deepcopy(result)
    result["steps"]["core"]["result"]["ports"]["count"].update(
        value=9007199254740993, complete=False
    )
    runtime.analytics._write(
        runtime.analytics._directory(second) / "result.json", result
    )
    response = client.post(
        "/api/workflows/compare",
        headers=alice,
        json={"workflow_ids": ["original", "second"]},
    )
    assert response.status_code == 200, response.text
    comparison = response.json()
    assert not comparison["same_inputs"]
    output = comparison["runs"][1]["steps"][0]["outputs"]["count"]
    assert output == {"type": "scalar", "value": 9007199254740993, "complete": False}
    assert (
        client.post(
            "/api/workflows/compare",
            headers=bob,
            json={"workflow_ids": ["original", "second"]},
        ).status_code
        == 404
    )
    assert client.get("/api/workflow-history", headers=bob).json() == []
    assert len(client.get("/api/workflow-history", headers=alice).json()) == 2
    assert (
        client.post(
            "/api/workflows/compare",
            headers=alice,
            json={"workflow_ids": ["original", "original"]},
        ).status_code
        == 422
    )


def test_template_survives_source_deletion_and_counts_toward_storage(recipes):
    client, runtime, alice, _, sid, _, _, _ = recipes
    template = save(client, alice)
    user = client.get("/api/auth/me", headers=alice).json()["user"]["id"]
    assert runtime.accounts.storage_usage(user)["templates"] > len(
        json.dumps(template["plan"])
    )
    assert client.delete(f"/api/sessions/{sid}", headers=alice).status_code == 204
    assert client.get("/api/workflow-templates", headers=alice).json() == [template]
    client.delete(f"/api/workflow-templates/{template['id']}", headers=alice)
    assert runtime.accounts.storage_usage(user)["templates"] == 0
