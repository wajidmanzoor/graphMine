"""Real library API tests plus isolated process-lifecycle fault injection."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import stat
import sys
import textwrap
import time
from dataclasses import replace
from pathlib import Path

import graphmine_agent
import pytest
from fastapi.testclient import TestClient
from graphmine_agent.analytics import AnalyticsError, AnalyticsService
from graphmine_agent.api import create_app
from graphmine_agent.jobs import EventBus

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.fixture(scope="session", autouse=True)
def analytics_application_evidence(request):
    package = Path(graphmine_agent.__file__).parent
    repository = Path(__file__).resolve().parents[2]

    def snapshot():
        paths = list(package.rglob("*.py")) + [
            Path(__file__),
            Path(__file__).with_name("conftest.py"),
        ]
        paths += [Path(path) for path in {item.path for item in request.session.items}]
        paths += [repository / "catalog/python_analytics_coverage.json"]
        return {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        }

    before = snapshot()
    yield
    unchanged = before == snapshot()
    xml = getattr(request.config.option, "xmlpath", None)
    if xml:
        metadata = {
            "scope": "Actual library API workflows, synthetic process/ledger fault injection and authored planning decisions; no browser or LLM accuracy coverage",
            "python": sys.version,
            "gpu_test_devices": os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS"),
            "source_files": before,
            "sources_unchanged_during_run": unchanged,
            "collected_test_count": len(request.session.items),
            "test_modules": sorted({str(item.path) for item in request.session.items}),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("fastapi", "pydantic", "httpx", "pytest", "pytest-asyncio")
            },
        }
        Path(str(xml) + ".metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
    assert unchanged, "Application sources changed during verification"


def plan():
    return {
        "version": 1,
        "device": "cpu",
        "steps": [
            {
                "id": "core",
                "operation": "k-core",
                "input": {"input": "main"},
                "parameters": {"requested_k": 2},
            },
            {
                "id": "sub",
                "operation": "induced-subgraph",
                "input": {"input": "main"},
                "bindings": {"vertices_or_seeds": {"step": "core", "port": "vertices"}},
            },
            {
                "id": "rank",
                "operation": "pagerank",
                "input": {"step": "sub", "port": "graph"},
            },
        ],
    }


def upload(client, graph):
    response = client.post("/api/sessions", headers=AUTH, json={"domain_id": "general"})
    assert response.status_code == 201, response.text
    session = response.json()["id"]
    response = client.post(
        f"/api/sessions/{session}/files",
        headers=AUTH,
        files={"file": ("triangle.json", graph, "application/json")},
        data={"role": "graph", "directed": "false"},
    )
    assert response.status_code == 201, response.text
    return session, response.json()["id"]


def body(file_id, mode="interactive"):
    return {
        "mode": mode,
        "plan": plan(),
        "inputs": {"main": {"file_id": file_id, "kind": "graph"}},
    }


def approve(client, record):
    response = client.post(
        f"/api/workflows/{record['id']}/run",
        headers=AUTH,
        json={
            "workflow_hash": record["validation"]["workflow_hash"],
            "expected_revision": record["revision"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait(client, workflow_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        record = client.get(f"/api/workflows/{workflow_id}", headers=AUTH).json()
        if record["status"] not in {"queued", "running"}:
            return record
        time.sleep(0.025)
    pytest.fail("Workflow did not finish within the test deadline")


@pytest.mark.parametrize("mode", ["normal", "interactive", "expert"])
def test_live_modes_dependent_results_and_pagination(settings, triangle_graph, mode):
    # Requires current committed-source CPU evidence and the analytics venv.
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph, mode)
        )
        assert response.status_code == 201, response.text
        record = response.json()
        if mode != "normal":
            assert record["status"] == (
                "awaiting_review" if mode == "interactive" else "ready"
            )
            assert record["approved_hash"] is None
            assert (
                client.get(
                    f"/api/workflows/{record['id']}/result", headers=AUTH
                ).status_code
                == 409
            )
            approve(client, record)
        final = wait(client, record["id"])
        assert final["status"] == "completed", final
        assert final["complete"]
        result = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()
        assert all(
            row["result"]["backend"]["device"] == "cpu"
            for row in result["steps"].values()
        )
        assert result["steps"]["core"]["result"]["result"]["selected_vertices"] == [
            0,
            1,
            2,
        ]
        rows = result["steps"]["rank"]["result"]["result"]["vertices"]
        assert [row["score"] for row in rows] == pytest.approx([1 / 3] * 3)
        page = client.get(
            f"/api/workflows/{record['id']}/steps/rank/ports/scores?offset=1&limit=1",
            headers=AUTH,
        ).json()
        assert page["total_items"] == 3 and page["complete"] and page["has_more"]
        assert page["items"] == [rows[1]]
        assert (
            client.get(
                f"/api/workflows/{record['id']}/steps/rank/ports/scores?limit=1001",
                headers=AUTH,
            ).status_code
            == 422
        )
        assert (
            client.get(f"/api/sessions/{session}/workflows", headers=AUTH).json()[0][
                "id"
            ]
            == record["id"]
        )


def test_live_review_revision_and_cache_recovery(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph)
        )
        assert response.status_code == 201, response.text
        first = response.json()
        approve(client, first)
        assert wait(client, first["id"])["status"] == "completed"
        revision = {**body(graph), "expected_revision": 1}
        # Identical content is still a new review revision.
        response = client.post(
            f"/api/workflows/{first['id']}/revise", headers=AUTH, json=revision
        )
        assert response.status_code == 200, response.text
        second = response.json()
        assert second["revision"] == 2 and second["approved_hash"] is None
        assert "approved_at" not in second and "finished_at" not in second
        old = client.post(
            f"/api/workflows/{first['id']}/run",
            headers=AUTH,
            json={
                "workflow_hash": first["validation"]["workflow_hash"],
                "expected_revision": 1,
            },
        )
        assert old.status_code == 409
        assert (
            client.post(
                f"/api/workflows/{first['id']}/revise", headers=AUTH, json=revision
            ).status_code
            == 409
        )
        approve(client, second)
        assert all(
            step["reused"] for step in wait(client, first["id"])["steps"].values()
        )
        revision["expected_revision"] = 2
        revision["plan"]["steps"][0]["parameters"]["requested_k"] = 3
        third = client.post(
            f"/api/workflows/{first['id']}/revise", headers=AUTH, json=revision
        ).json()
        approve(client, third)
        final = wait(client, first["id"])
        assert final["status"] == "completed", final
        assert not any(step["reused"] for step in final["steps"].values())
        result = client.get(f"/api/workflows/{first['id']}/result", headers=AUTH).json()
        assert result["steps"]["rank"]["result"]["result"]["vertices"] == []


def test_live_capabilities_authorization_and_input_scope(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/analytics/capabilities").status_code == 401
        caps = client.get("/api/analytics/capabilities", headers=AUTH).json()
        assert caps["operations"] and all(
            card["execution"]["cpu"] for card in caps["operations"]
        ), caps.get("reports")
        session, graph = upload(client, triangle_graph)
        other, _ = upload(client, triangle_graph)
        assert client.post(
            f"/api/sessions/{other}/workflows", headers=AUTH, json=body(graph)
        ).status_code in (400, 422)
        invalid = body(graph)
        invalid["resume"] = {"fake": "result"}
        assert (
            client.post(
                f"/api/sessions/{session}/workflows", headers=AUTH, json=invalid
            ).status_code
            == 422
        )
        invalid = body(graph)
        invalid["plan"]["steps"][1]["bindings"]["vertices_or_seeds"]["port"] = (
            "invented"
        )
        assert (
            client.post(
                f"/api/sessions/{session}/workflows", headers=AUTH, json=invalid
            ).status_code
            == 422
        )


def _service(settings, database, graph_store):
    return AnalyticsService(settings, database, graph_store, EventBus(database))


def test_live_failed_step_recovery_reuses_only_valid_steps(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        request = body(graph, "normal")
        request["plan"]["steps"][0]["budget"] = {"max_output_items": 1}
        request["plan"]["steps"].append(
            {
                "id": "independent",
                "operation": "triangle-counting",
                "input": {"input": "main"},
            }
        )
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = wait(client, response.json()["id"])
        assert record["status"] == "failed"
        assert record["steps"]["rank"]["status"] == "blocked"
        assert record["steps"]["independent"]["status"] == "completed"
        partial = client.get(
            f"/api/workflows/{record['id']}/steps/independent/result", headers=AUTH
        )
        assert partial.status_code == 200, partial.text
        assert partial.json()["result"]["ports"]["count"]["value"] == 1
        assert (
            client.get(
                f"/api/workflows/{record['id']}/steps/rank/result", headers=AUTH
            ).status_code
            == 409
        )
        assert (
            client.get(
                f"/api/workflows/{record['id']}/steps/independent/result"
            ).status_code
            == 401
        )
        request.update(mode="interactive", expected_revision=1)
        request["plan"]["steps"][0]["budget"] = {"max_output_items": 100}
        revised = client.post(
            f"/api/workflows/{record['id']}/revise", headers=AUTH, json=request
        ).json()
        approve(client, revised)
        final = wait(client, record["id"])
        assert final["status"] == "completed", final
        assert final["steps"]["independent"]["reused"]
        assert not final["steps"]["core"]["reused"]


def test_live_evidence_is_rechecked_at_execution(settings, triangle_graph, tmp_path):
    app = create_app(settings)
    with TestClient(app) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph)
        )
        assert response.status_code == 201, response.text
        record = response.json()
        # Move only the worker's evidence root to an empty temporary repository.
        # No real source/report is modified and no verification is bypassed.
        app.state.runtime.analytics.settings = replace(
            settings,
            repository_root=tmp_path,
            analytics_python=settings.repository_root / ".venv-analytics/bin/python",
        )
        approve(client, record)
        final = wait(client, record["id"])
        assert final["status"] == "failed" and "evidence" in final["error"]["message"]
        assert final["steps"] == {}


def test_live_cancel_endpoint(settings, triangle_graph):
    with TestClient(create_app(settings)) as client:
        session, graph = upload(client, triangle_graph)
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=body(graph)
        )
        assert response.status_code == 201, response.text
        record = response.json()
        approve(client, record)
        cancelled = client.delete(f"/api/workflows/{record['id']}", headers=AUTH)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert not cancelled.json()["complete"]


@pytest.mark.parametrize("gpu_index", [0, 1])
def test_live_configured_gpu_workflow(settings, triangle_graph, gpu_index):
    configured = os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS", "").split(",")
    if len(configured) != 2 or not all(configured):
        pytest.skip(
            "Set GRAPHMINE_ANALYTICS_TEST_GPUS to two GPU UUIDs for application GPU checks"
        )
    device = configured[gpu_index]
    selected = replace(
        settings, graph_gpu_uuid=device, llm_gpu_uuid=None, job_timeout_seconds=30
    )
    with TestClient(create_app(selected)) as client:
        session, graph = upload(client, triangle_graph)
        request = body(graph, "normal")
        request["plan"]["device"] = "gpu"
        request["plan"]["steps"][1]["parameters"] = {"mode": "ego", "radius": 0}
        response = client.post(
            f"/api/sessions/{session}/workflows", headers=AUTH, json=request
        )
        assert response.status_code == 201, response.text
        record = wait(client, response.json()["id"])
        assert record["status"] == "completed", record
        result = client.get(
            f"/api/workflows/{record['id']}/result", headers=AUTH
        ).json()
        for step in result["steps"].values():
            backend = step["result"]["backend"]
            assert (
                backend["device"] == "gpu" and backend["cuda_visible_devices"] == device
            )
        assert [
            r["score"] for r in result["steps"]["rank"]["result"]["result"]["vertices"]
        ] == pytest.approx([1 / 3] * 3, abs=1e-8)


def _sleeping_worker(tmp_path):
    script = tmp_path / "sleeping-worker"
    pidfile = tmp_path / "worker-pids.json"
    script.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json, os, pathlib, subprocess, sys, time
        json.load(sys.stdin)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        pathlib.Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), child.pid]))
        time.sleep(60)
        """)
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, pidfile


def _not_running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_process_group_cancellation_and_deadline(
    settings, database, graph_store, tmp_path, cancel
):
    script, pidfile = _sleeping_worker(tmp_path)
    service = _service(
        replace(settings, analytics_python=script, job_timeout_seconds=1),
        database,
        graph_store,
    )
    service.open()
    try:
        task = asyncio.create_task(
            service._call({"command": "run", "plan": {"device": "cpu"}})
        )
        for _ in range(150):
            if pidfile.exists():
                break
            await asyncio.sleep(0.01)
        assert pidfile.exists()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(AnalyticsError, match="deadline"):
                await task
        for _ in range(100):
            if all(_not_running(pid) for pid in json.loads(pidfile.read_text())):
                break
            await asyncio.sleep(0.01)
        assert all(_not_running(pid) for pid in json.loads(pidfile.read_text()))
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_ledger_restart_and_exclusive_ownership(settings, database, graph_store):
    owner = _service(settings, database, graph_store)
    owner.open()
    record = {
        "id": "synthetic-ledger-fixture",
        "session_id": "synthetic",
        "status": "queued",
    }
    owner._save(record)
    competitor = _service(settings, database, graph_store)
    with pytest.raises(RuntimeError, match="already owned"):
        competitor.open()
    await competitor.close()
    assert owner.get(record["id"])["status"] == "queued"
    owner.owner.release()  # simulate an exited process, without graceful shutdown
    restarted = _service(settings, database, graph_store)
    restarted.open()
    assert restarted.get(record["id"])["status"] == "interrupted"
    await restarted.close()


@pytest.mark.asyncio
async def test_cpu_process_cannot_see_configured_gpu(
    settings, database, graph_store, tmp_path
):
    script = tmp_path / "inspect-environment"
    script.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\njson.load(sys.stdin)\nprint(json.dumps({'event':'complete','result':{'cuda':os.getenv('CUDA_VISIBLE_DEVICES')}}))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    service = _service(
        replace(settings, analytics_python=script), database, graph_store
    )
    result = await service._call({"command": "run", "plan": {"device": "cpu"}})
    assert result == {"cuda": ""}


@pytest.mark.asyncio
async def test_missing_worker_does_not_affect_application_start(
    settings, database, graph_store, tmp_path
):
    configured = replace(settings, analytics_python=tmp_path / "missing-python")
    service = _service(configured, database, graph_store)
    with pytest.raises(AnalyticsError, match="environment is unavailable"):
        await service.capabilities()
