"""Actual native workers and physical-device admission; estimates are not allocations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from graphmine_agent.analytics import AnalyticsService, WorkflowRequest
from graphmine_agent.analytics_scheduler import MIB, AdmissionError, gpu_inventory
from graphmine_agent.jobs import EventBus
from graphmine_agent.models import FileRole


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem,parameters,available,device,quality",
    [
        ("triangle-counting", {}, True, "gpu", "exact"),
        ("triangle-counting", {}, False, "cpu", "exact"),
        (
            "induced-subgraph",
            {"mode": "induced", "vertices_or_seeds": [0, 1]},
            True,
            "cpu",
            "exact",
        ),
        ("community-detection", {"solution_quality": "exact"}, True, "cpu", "exact"),
        (
            "community-detection",
            {"solution_quality": "heuristic"},
            True,
            "gpu",
            "heuristic",
        ),
        (
            "community-detection",
            {"solution_quality": "heuristic"},
            False,
            "cpu",
            "heuristic",
        ),
    ],
)
async def test_auto_workflow_gpu_priority_and_quality_preserving_fallback(
    settings,
    database,
    graph_store,
    session,
    triangle_graph,
    monkeypatch,
    problem,
    parameters,
    available,
    device,
    quality,
):
    configured = tuple(
        filter(None, os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS", "").split(","))
    )
    if not configured:
        pytest.skip("Configure physical GPU UUIDs for the automatic execution test")
    config = replace(
        settings,
        graph_gpu_uuid=None,
        analytics_gpu_uuids=configured,
        llm_enabled=False,
        job_timeout_seconds=60,
    )
    service = AnalyticsService(config, database, graph_store, EventBus(database))
    if not available:

        async def no_devices():
            return []

        monkeypatch.setattr(service.scheduler, "probe", no_devices)
    uploaded = graph_store.ingest(
        session_id=session.id,
        role=FileRole.graph,
        filename="triangle.json",
        content=triangle_graph,
    )
    service.open()
    try:
        record = await service.create(
            session.id,
            WorkflowRequest(
                mode="normal",
                inputs={"main": {"file_id": uploaded.id}},
                plan={
                    "version": 1,
                    "device": "auto",
                    "steps": [
                        {
                            "id": "answer",
                            "problem": problem,
                            "input": {"input": "main"},
                            "parameters": parameters,
                        }
                    ],
                },
            ),
        )
        await asyncio.gather(*service.tasks.values())
        final = service.get(record["id"])
        assert final["status"] == "completed", final
        result = service.result(record["id"])["steps"]["answer"]["result"]
        assert result["backend"]["device"] == device
        assert result["quality"] == quality
        assert result["complete"]
        if device == "gpu":
            assert (
                result["backend"]["hardware"]["uuid"] == final["allocation"]["gpu_uuid"]
            )
        if problem == "triangle-counting":
            assert result["ports"]["count"]["value"] == 1
        elif problem == "community-detection":
            if device == "gpu":
                assert final["allocation"]["device"] == "gpu"
                assert result["backend"]["id"] in {
                    "gleiden",
                    "parallel-louvain",
                    "parallel-leiden",
                    "parallel-leiden-plus",
                }
        elif problem == "induced-subgraph":
            assert "native CPU" in result["backend"]["selection_reason"]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_physical_gpu1_serial_reservation_and_cancelled_waiter(
    settings, database, graph_store, triangle_graph
):
    configured = os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS", "").split(",")
    inventory = [row for row in await gpu_inventory() if row["uuid"] in configured and row["index"] == 1]
    if len(inventory) != 1:
        pytest.skip("Configure physical GPU 1 for the hardware admission test")
    device = inventory[0]
    config = replace(
        settings,
        graph_gpu_uuid=None,
        analytics_gpu_uuids=tuple(configured),
        llm_enabled=False,
        llm_gpu_uuid=None,
        job_timeout_seconds=60,
    )
    service = AnalyticsService(config, database, graph_store, EventBus(database))
    assert device["free"] - config.analytics_gpu_headroom_bytes > 1024 * MIB
    graph = json.loads(triangle_graph)
    source = graph["vertices"][0]["id"]
    inputs = {"main": {"kind": "graph", "data": graph}}
    plan = {
        "version": 1,
        "device": "gpu",
        "steps": [
            {
                "id": "bfs",
                "problem": "breadth-first-search",
                "input": {"input": "main"},
                "parameters": {"sources": [source]},
            }
        ],
    }
    checked = await service._call(
        {"command": "validate", "plan": plan, "inputs": inputs}
    )
    records = []

    async def run(lease):
        started = time.monotonic()
        result = await service._call(
            {
                "command": "run",
                "plan": checked["plan"],
                "inputs": inputs,
                "expected_hash": checked["workflow_hash"],
            },
            lease=lease,
        )
        native = result["steps"]["bfs"]["result"]
        assert result["status"] == "completed" and result["complete"]
        assert native["backend"]["hardware"]["uuid"] == lease.gpu_uuid
        assert native["backend"]["device"] == "gpu"
        assert sorted(row["distance"] for row in native["result"]["distances"]) == [
            0,
            1,
            1,
        ]
        records.append(
            {
                "allocation": lease.record(),
                "backend": native["backend"],
                "started": started,
                "finished": time.monotonic(),
            }
        )

    async with service.scheduler.reserve("gpu", 128 * MIB, timeout=5) as first:
        assert first.gpu_uuid == device["uuid"]
        await run(first)

        async def waiting():
            async with service.scheduler.reserve("gpu", 1, timeout=30):
                pytest.fail("A second GPU job was admitted while the first held its lease")

        queued = asyncio.create_task(waiting())
        await asyncio.sleep(0.1)
        assert not queued.done()
        queued.cancel()
        await asyncio.gather(queued, return_exceptions=True)
        assert len(service.scheduler.snapshot()) == 1
    assert service.scheduler.snapshot() == []
    async with service.scheduler.reserve("gpu", 128 * MIB, timeout=5) as second:
        assert second.gpu_uuid == first.gpu_uuid
        await run(second)
    assert records[0]["finished"] <= records[1]["started"]

    service.scheduler.settings = replace(
        config, llm_enabled=True, llm_gpu_uuid=device["uuid"], allow_shared_gpu=False
    )
    with pytest.raises(AdmissionError, match="GPU"):
        async with service.scheduler.reserve("gpu", 128 * MIB, timeout=5):
            pytest.fail("Used an excluded physical GPU")
    physical_llm = device
    reservation = physical_llm["total"] * 4 // 5
    service.scheduler.settings = replace(
        config,
        llm_enabled=True,
        llm_gpu_uuid=device["uuid"],
        allow_shared_gpu=True,
        analytics_gpu_uuids=(device["uuid"],),
        analytics_llm_reserve_bytes=reservation,
    )
    with pytest.raises(AdmissionError, match="memory"):
        async with service.scheduler.reserve(
            "gpu", physical_llm["total"] - reservation + 1, timeout=5
        ):
            pytest.fail("Reserved LLM space was admitted to a graph job")
    async with service.scheduler.reserve("gpu", 128 * MIB, timeout=5) as shared:
        assert shared.gpu_uuid == device["uuid"]
        assert shared.llm_reserved_bytes == reservation
        await run(shared)
    assert service.scheduler.snapshot() == []
    output = os.environ.get("GRAPHMINE_HARDWARE_REPORT")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "scope": "Serial actual native workers on physical GPU 1, real physical memory probes, LLM exclusion/reservation and cancelled admission waiter; declared estimates are not actual device allocations",
                    "inventory_before": inventory,
                    "runs": records,
                    "passed": True,
                    "llm_reserved_bytes": reservation,
                    "remaining_allocations": service.scheduler.snapshot(),
                    "test_sha256": hashlib.sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                },
                indent=2,
            )
            + "\n"
        )
