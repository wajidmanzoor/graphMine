"""Actual API → native cuDF projection → native CPU workflow on each GPU."""

import os
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from graphmine_agent.api import create_app

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.mark.parametrize("gpu_index", [0, 1])
def test_native_table_join_builds_a_scoped_reusable_input(settings, gpu_index):
    devices = os.environ["GRAPHMINE_ANALYTICS_TEST_GPUS"].split(",")
    settings = replace(
        settings,
        graph_gpu_uuid=devices[gpu_index],
        llm_gpu_uuid=None,
        job_timeout_seconds=30,
    )
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]

        def upload(name, content):
            r = client.post(
                f"/api/sessions/{session}/files",
                headers=AUTH,
                data={"role": "attachment"},
                files={"file": (name, content, "text/csv")},
            )
            assert r.status_code == 201, r.text
            return r.json()["id"]

        events = upload(
            "events.csv",
            "from,to,amount,time\n001,002,4,10\n001,002,5,10\n002,003,7,20\n",
        )
        accounts = upload("accounts.csv", "id,branch\n001,east\n002,west\n003,north\n")
        schema = client.get(
            f"/api/sessions/{session}/tables/{events}/schema", headers=AUTH
        )
        assert schema.status_code == 200, schema.text
        assert schema.json()["row_count"] == 3
        spec = {
            "version": 1,
            "id": "transfers",
            "task": "max_flow",
            "edge_table": "events",
            "joins": [
                {
                    "table": "accounts",
                    "alias": "sender",
                    "left": "events.from",
                    "right": "id",
                    "kind": "required",
                    "cardinality": "many_to_one",
                }
            ],
            "source": {
                "field": "events.from",
                "type": "string",
                "attributes": {"branch": {"field": "sender.branch", "type": "string"}},
            },
            "target": {"field": "events.to", "type": "string"},
            "directed": True,
            "weight": {
                "field": "events.amount",
                "type": "integer",
                "meaning": "capacity",
            },
            "timestamp": {"field": "events.time", "type": "integer"},
            "time_window": {"start": 10, "end": 20},
            "duplicates": "sum",
        }
        body = {"tables": {"events": events, "accounts": accounts}, "projection": spec}
        r = client.post(f"/api/sessions/{session}/projections", headers=AUTH, json=body)
        assert r.status_code == 201, r.text
        result = r.json()
        assert result["provenance"]["edge_count"] == 1
        assert result["provenance"]["outside_time_window"] == 1
        assert result["allocation"]["gpu_uuid"] == devices[gpu_index]
        assert client.app.state.runtime.analytics.scheduler.snapshot() == []
        file_id = result["file"]["id"]
        r = client.post(
            f"/api/sessions/{session}/workflows",
            headers=AUTH,
            json={
                "mode": "normal",
                "inputs": {"main": {"file_id": file_id}},
                "plan": {
                    "version": 1,
                    "device": "cpu",
                    "steps": [
                        {
                            "id": "flow",
                            "operation": "max-flow-min-cut",
                            "input": {"input": "main"},
                            "parameters": {
                                "source": "001",
                                "sink": "002",
                                "capacity_mode": "edge_weight",
                            },
                        }
                    ],
                },
            },
        )
        assert r.status_code == 201, r.text
        identifier = r.json()["id"]
        for _ in range(400):
            saved = client.get(f"/api/workflows/{identifier}", headers=AUTH).json()
            if saved["status"] in ("completed", "failed"):
                break
            time.sleep(0.02)
        assert saved["status"] == "completed", saved
        calculated = client.get(
            f"/api/workflows/{identifier}/result", headers=AUTH
        ).json()["steps"]["flow"]["result"]
        assert calculated["backend"]["id"] == "cpp"
        assert calculated["result"]["flow_value"] == 9
        other = client.post("/api/sessions", headers=AUTH, json={}).json()["id"]
        assert (
            client.post(
                f"/api/sessions/{other}/projections", headers=AUTH, json=body
            ).status_code
            == 422
        )
