"""MCP and reviewed-example checks against the real authenticated native API."""

import asyncio
import json
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app
from graphmine_agent.mcp import PROTOCOL, Bridge

AUTH = {"Authorization": "Bearer test-secret"}


def upload(client, graph):
    session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
    file = client.post(
        f"/api/sessions/{session}/files",
        headers=AUTH,
        files={"file": ("network.json", graph, "application/json")},
        data={"role": "graph"},
    )
    assert file.status_code == 201, file.text
    return session, file.json()["id"]


def workflow(file, **extra):
    return {
        "mode": "interactive",
        "inputs": {"main": {"file_id": file}},
        "plan": {
            "version": 1,
            "device": "cpu",
            "steps": [
                {
                    "id": "answer",
                    "operation": "triangle-counting",
                    "input": {"input": "main"},
                    "parameters": {},
                }
            ],
        },
        **extra,
    }


def completed(client, session, file, **extra):
    response = client.post(
        f"/api/sessions/{session}/workflows",
        headers=AUTH,
        json=workflow(file, mode="normal", **extra),
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    for _ in range(300):
        record = client.get(f"/api/workflows/{identifier}", headers=AUTH).json()
        if record["status"] in ("completed", "failed", "cancelled"):
            assert record["status"] == "completed", record
            return identifier
        time.sleep(0.02)
    pytest.fail("Workflow did not complete")


def review(client, identifier):
    candidate = client.get(f"/api/workflows/{identifier}/example-review", headers=AUTH)
    assert candidate.status_code == 200, candidate.text
    return {
        key: candidate.json()[key]
        for key in ("expected_revision", "workflow_hash", "result_sha256")
    } | {"question": "Count triangles in this network", "approved": True}


def test_stdio_lifecycle_and_tool_discovery():
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    process = subprocess.run(
        [sys.executable, "-m", "graphmine_agent.mcp"],
        input="\n".join(map(json.dumps, messages)) + "\n",
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(responses) == 2
    assert responses[0]["result"]["protocolVersion"] == PROTOCOL
    definitions = {row["name"]: row for row in responses[1]["result"]["tools"]}
    assert len(definitions) == 14
    assert definitions["approve_workflow"]["inputSchema"]["required"] == [
        "workflow_hash",
        "expected_revision",
        "workflow_id",
    ]
    assert definitions["capabilities"]["annotations"]["readOnlyHint"]


@pytest.mark.asyncio
async def test_mcp_uses_the_same_native_review_and_authentication_boundary(
    settings, triangle_graph
):
    with TestClient(create_app(settings)) as web:
        session, file = upload(web, triangle_graph)

        def transport(request):
            response = web.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(
                response.status_code, content=response.content, headers=response.headers
            )

        async with httpx.AsyncClient(
            base_url="http://testserver",
            transport=httpx.MockTransport(transport),
            headers=AUTH,
        ) as client:
            bridge = Bridge(client)
            bridge.initialized = bridge.ready = True

            async def call(name, arguments):
                reply = await bridge.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    }
                )
                assert "error" not in reply, reply
                return reply["result"]

            caps = await call("capabilities", {})
            assert len(caps["structuredContent"]["operations"]) == 80
            assert not caps["isError"]
            created = await call(
                "create_workflow", {"session_id": session, **workflow(file)}
            )
            assert not created["isError"], created
            record = created["structuredContent"]
            assert record["status"] == "awaiting_review"
            args = {
                "workflow_id": record["id"],
                "workflow_hash": "0" * 64,
                "expected_revision": 1,
            }
            assert (await call("approve_workflow", args))["isError"]
            args["workflow_hash"] = record["validation"]["workflow_hash"]
            assert not (await call("approve_workflow", args))["isError"]
            for _ in range(300):
                saved = (await call("get_workflow", {"workflow_id": record["id"]}))[
                    "structuredContent"
                ]
                if saved["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(0.02)
            assert saved["status"] == "completed", saved
            result = await call("workflow_result", {"workflow_id": record["id"]})
            assert (
                result["structuredContent"]["steps"]["answer"]["result"]["backend"][
                    "id"
                ]
                == "cpp"
            )
            assert (await call("get_workflow", {"workflow_id": "../secrets"}))[
                "isError"
            ]
            bad = workflow(file)
            bad["plan"]["steps"][0]["operation"] = "execute-shell"
            assert (await call("create_workflow", {"session_id": session, **bad}))[
                "isError"
            ]
            client.headers.pop("Authorization")
            assert (await call("capabilities", {}))["isError"]


def test_review_provenance_retrieval_scope_revocation_and_holdout(
    settings, triangle_graph
):
    with TestClient(create_app(settings)) as client:
        session, file = upload(client, triangle_graph)
        identifier = completed(client, session, file)
        body = review(client, identifier)
        examples = client.app.state.runtime.analytics.examples
        assert examples.list(session) == []  # A successful run is never an approval.
        assert (
            client.post(
                f"/api/workflows/{identifier}/example-review",
                headers=AUTH,
                json={**body, "approved": False},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/workflows/{identifier}/example-review",
                headers=AUTH,
                json={**body, "result_sha256": "0" * 64},
            ).status_code
            == 409
        )
        response = client.post(
            f"/api/workflows/{identifier}/example-review", headers=AUTH, json=body
        )
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["provenance"]["result_sha256"] == body["result_sha256"]
        assert len(saved["inputs"]["main"]["file_sha256"]) == 64
        args = (
            session,
            "Count triangles",
            ["triangle-counting"],
            saved["provenance"]["implementation_sha256"],
            ["graph"],
        )
        assert [row["id"] for row in examples.search(*args)] == [saved["id"]]
        assert examples.search(*args, evaluation_id="heldout/new-case") == []
        assert examples.search(*args[:3], "changed-native-core", ["graph"]) == []
        other, _ = upload(client, triangle_graph)
        assert examples.search(other, *args[1:]) == []
        assert (
            client.delete(
                f"/api/sessions/{other}/analytics/examples/{saved['id']}", headers=AUTH
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/sessions/{session}/analytics/examples/{saved['id']}",
                headers=AUTH,
            ).status_code
            == 200
        )
        assert examples.search(*args) == []


def test_evaluation_marker_survives_revision_and_prevents_example_approval(
    settings, triangle_graph
):
    with TestClient(create_app(settings)) as client:
        session, file = upload(client, triangle_graph)
        identifier = completed(
            client, session, file, evaluation_id="heldout/never-train"
        )
        assert (
            client.get(
                f"/api/workflows/{identifier}/example-review", headers=AUTH
            ).status_code
            == 422
        )
        revised = client.post(
            f"/api/workflows/{identifier}/revise",
            headers=AUTH,
            json={**workflow(file), "expected_revision": 1},
        )
        assert revised.status_code == 200, revised.text
        assert revised.json()["evaluation_id"] == "heldout/never-train"
