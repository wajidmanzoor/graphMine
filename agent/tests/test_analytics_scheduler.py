"""Independent admission ledgers and cancellation checks; no simulated GPU claims."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from graphmine_agent.analytics_scheduler import MIB, AdmissionError, AnalyticsScheduler


async def devices():
    return [
        {"uuid": name, "total": 16 * 1024 * MIB, "free": 14 * 1024 * MIB}
        for name in ("GPU-A", "GPU-B")
    ]


def scheduler(settings, **options):
    config = replace(
        settings,
        graph_gpu_uuid=None,
        llm_gpu_uuid="GPU-A",
        llm_enabled=False,
        analytics_gpu_uuids=("GPU-A", "GPU-B"),
        analytics_gpu_headroom_bytes=0,
        **options,
    )
    return AnalyticsScheduler(
        config, probe=devices, host_memory=lambda: 64 * 1024 * MIB
    )


@pytest.mark.asyncio
async def test_memory_leases_assign_two_devices_without_oversubscription(settings):
    service = scheduler(settings)
    async with service.reserve("gpu", 10 * 1024 * MIB, timeout=1) as first:  # noqa: SIM117 - exercise nested independent leases
        async with service.reserve("gpu", 10 * 1024 * MIB, timeout=1) as second:
            assert {first.gpu_uuid, second.gpu_uuid} == {"GPU-A", "GPU-B"}
            assert len(service.snapshot()) == 2
            with pytest.raises(AdmissionError, match="waiting"):
                async with service.reserve("gpu", 10 * 1024 * MIB, timeout=0.02):
                    pytest.fail("Overcommitted a GPU")
    assert service.snapshot() == []


@pytest.mark.asyncio
async def test_llm_exclusion_and_memory_reservation(settings):
    service = scheduler(settings)
    service.settings = replace(
        service.settings, llm_enabled=True, allow_shared_gpu=False
    )
    async with service.reserve("gpu", 10 * 1024 * MIB, timeout=1) as lease:
        assert lease.gpu_uuid == "GPU-B"
    service.settings = replace(
        service.settings,
        allow_shared_gpu=True,
        analytics_gpu_uuids=("GPU-A",),
        analytics_llm_reserve_bytes=12 * 1024 * MIB,
    )
    with pytest.raises(AdmissionError, match="memory"):
        async with service.reserve("gpu", 5 * 1024 * MIB, timeout=1):
            pytest.fail("Used reserved LLM memory")
    async with service.reserve("gpu", 3 * 1024 * MIB, timeout=1) as lease:
        assert lease.llm_reserved_bytes == 12 * 1024 * MIB
        assert lease.available_bytes_at_admission == 4 * 1024 * MIB


@pytest.mark.asyncio
async def test_cancelled_waiter_and_holder_release_memory(settings):
    service = scheduler(settings)

    async def job(entered):
        async with service.reserve("gpu", 14 * 1024 * MIB, timeout=30):
            entered.set()
            await asyncio.Event().wait()

    first, second = asyncio.Event(), asyncio.Event()
    running = [asyncio.create_task(job(first)), asyncio.create_task(job(second))]
    await first.wait()
    await second.wait()
    waiting = asyncio.create_task(job(asyncio.Event()))
    await asyncio.sleep(0)
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    assert len(service.snapshot()) == 2
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
    assert service.snapshot() == []
    async with service.reserve("gpu", 14 * 1024 * MIB, timeout=1):
        assert len(service.snapshot()) == 1


@pytest.mark.asyncio
async def test_cpu_never_probes_cuda_and_auto_can_use_cpu(settings):
    service = scheduler(settings, analytics_cpu_workers=2)

    async def forbidden():
        raise AssertionError("CPU requested a GPU probe")

    service.probe = forbidden
    async with service.reserve("cpu", 1024 * MIB, timeout=1) as lease:
        assert lease.gpu_uuid is None
        async with service.reserve("cpu", 1024 * MIB, timeout=1):
            assert len(service.snapshot()) == 2

    async def no_gpu():
        return []

    service.probe = no_gpu
    async with service.reserve("auto", 1024 * MIB, timeout=1) as lease:
        assert lease.device == "cpu"
    with pytest.raises(AdmissionError, match="GPU"):
        async with service.reserve("gpu", 1024 * MIB, timeout=1):
            pytest.fail("Silently ran GPU-only work on CPU")
