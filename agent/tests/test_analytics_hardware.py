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
from graphmine_agent.analytics import AnalyticsService
from graphmine_agent.analytics_scheduler import MIB, AdmissionError, gpu_inventory
from graphmine_agent.jobs import EventBus


@pytest.mark.asyncio
async def test_physical_gpu_concurrency_reservation_and_cancelled_waiter(
    settings, database, graph_store, triangle_graph
):
    configured = os.environ.get("GRAPHMINE_ANALYTICS_TEST_GPUS", "").split(",")
    if len(configured) != 2 or not all(configured):
        pytest.skip("Configure two physical GPU UUIDs for the hardware admission test")
    config = replace(
        settings,
        graph_gpu_uuid=None,
        analytics_gpu_uuids=tuple(configured),
        llm_enabled=False,
        llm_gpu_uuid=configured[0],
        job_timeout_seconds=60,
    )
    service = AnalyticsService(config, database, graph_store, EventBus(database))
    inventory = [row for row in await gpu_inventory() if row["uuid"] in configured]
    assert len(inventory) == 2
    available = sorted(
        row["free"] - config.analytics_gpu_headroom_bytes for row in inventory
    )
    assert available[0] > 1024 * MIB, "Hardware check needs 1 GiB free on each GPU"
    # Exercise the admission ledger without allocating tens of GiB: deliberately
    # large declared estimates force placement on distinct physical devices.
    estimates = (available[1] - available[0] // 4, available[0] * 3 // 5)
    graph = json.loads(triangle_graph)
    source = graph["vertices"][0]["id"]
    inputs = {"main": {"kind": "graph", "data": graph}}
    plan = {
        "version": 1,
        "device": "gpu",
        "steps": [
            {
                "id": "bfs",
                "operation": "breadth-first-search",
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

    async with service.scheduler.reserve("gpu", estimates[0], timeout=5) as first:  # noqa: SIM117 - exercise independent concurrent leases
        async with service.scheduler.reserve("gpu", estimates[1], timeout=5) as second:
            assert {first.gpu_uuid, second.gpu_uuid} == set(configured)
            assert len(service.scheduler.snapshot()) == 2
            await asyncio.gather(run(first), run(second))

            async def waiting():
                async with service.scheduler.reserve("gpu", available[0], timeout=30):
                    pytest.fail("An overcommitted job was admitted")

            queued = asyncio.create_task(waiting())
            await asyncio.sleep(0.1)
            assert not queued.done()
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            assert len(service.scheduler.snapshot()) == 2
    assert service.scheduler.snapshot() == []
    assert max(row["started"] for row in records) < min(
        row["finished"] for row in records
    )

    service.scheduler.settings = replace(
        config, llm_enabled=True, allow_shared_gpu=False
    )
    async with service.scheduler.reserve("gpu", 128 * MIB, timeout=5) as exclusive:
        assert exclusive.gpu_uuid == configured[1]
        await run(exclusive)
    physical_llm = next(row for row in inventory if row["uuid"] == configured[0])
    reservation = physical_llm["total"] * 4 // 5
    service.scheduler.settings = replace(
        config,
        llm_enabled=True,
        allow_shared_gpu=True,
        analytics_gpu_uuids=(configured[0],),
        analytics_llm_reserve_bytes=reservation,
    )
    with pytest.raises(AdmissionError, match="memory"):
        async with service.scheduler.reserve(
            "gpu", physical_llm["total"] - reservation + 1, timeout=5
        ):
            pytest.fail("Reserved LLM space was admitted to a graph job")
    async with service.scheduler.reserve("gpu", 128 * MIB, timeout=5) as shared:
        assert shared.gpu_uuid == configured[0]
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
                    "scope": "Two concurrent actual native GPU workers, real physical memory probes, LLM exclusion/reservation and cancelled admission waiter; declared estimates are not actual device allocations",
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
