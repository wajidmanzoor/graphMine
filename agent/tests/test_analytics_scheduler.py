"""Independent admission ledgers and cancellation checks; no simulated GPU claims."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from graphmine_agent.analytics_scheduler import (
    MIB,
    AdmissionError,
    AnalyticsScheduler,
    execution_admission,
)


async def devices():
    return [
        {"index": index, "uuid": name, "total": 16 * 1024 * MIB, "free": 14 * 1024 * MIB}
        for index, name in enumerate(("GPU-A", "GPU-B"))
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
async def test_only_physical_gpu1_is_leased_and_runs_are_serial(settings):
    service = scheduler(settings)
    async with service.reserve("gpu", 10 * 1024 * MIB, timeout=1) as first:  # noqa: SIM117 - exercise nested independent leases
        assert first.gpu_uuid == "GPU-B"
        assert len(service.snapshot()) == 1
        with pytest.raises(AdmissionError, match="waiting"):
            async with service.reserve("gpu", 1, timeout=0.02):
                pytest.fail("Started a concurrent GPU job despite the serial policy")
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
        analytics_gpu_uuids=("GPU-B",),
        llm_gpu_uuid="GPU-B",
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

    first = asyncio.Event()
    running = [asyncio.create_task(job(first))]
    await first.wait()
    waiting = asyncio.create_task(job(asyncio.Event()))
    await asyncio.sleep(0)
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    assert len(service.snapshot()) == 1
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
    assert service.snapshot() == []
    async with service.reserve("gpu", 14 * 1024 * MIB, timeout=1):
        assert len(service.snapshot()) == 1


@pytest.mark.asyncio
async def test_gpu0_and_unknown_indices_are_never_permitted(settings):
    service = scheduler(settings)
    service.settings = replace(service.settings, analytics_gpu_uuids=("GPU-A",))
    with pytest.raises(AdmissionError, match="GPU"):
        async with service.reserve("gpu", 1, timeout=1):
            pytest.fail("Scheduled on GPU 0")
    service.settings = replace(service.settings, analytics_gpu_uuids=())
    assert service.eligible([{"uuid": "GPU-unknown", "total": 10, "free": 10}]) == []
    async with service.reserve("auto", 1, timeout=1, allowed_gpu_uuids={"GPU-A"}) as lease:
        assert lease.device == "cpu"


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


def test_workflow_admission_uses_verified_backends_and_explicit_devices():
    cards = [
        {
            "id": problem,
            "execution": {"cpu": cpu, "gpu": bool(devices)},
            "backends": [
                {"device": "gpu", "verified": True, "verified_devices": devices},
                {
                    "device": "gpu",
                    "verified": False,
                    "verified_devices": ["unverified"],
                },
            ],
        }
        for problem, devices, cpu in (
            ("count", ["GPU-A", "GPU-B"], True),
            ("rank", ["GPU-B"], True),
            ("lookup", [], True),
            ("gpu-only", ["GPU-B"], False),
        )
    ]

    def plan(*steps):
        return {
            "device": "auto",
            "steps": [{"problem": op, "device": device} for op, device in steps],
        }

    assert execution_admission(plan(("count", "auto")), cards) == (
        "auto",
        {"GPU-A", "GPU-B"},
    )
    assert execution_admission(plan(("count", "cpu"), ("lookup", "auto")), cards) == (
        "cpu",
        set(),
    )
    assert execution_admission(plan(("count", "gpu"), ("rank", "gpu")), cards) == (
        "gpu",
        {"GPU-B"},
    )
    assert execution_admission(
        plan(("count", "auto"), ("gpu-only", "auto")), cards
    ) == ("gpu", {"GPU-B"})
    assert execution_admission(plan(("lookup", "gpu")), cards) == ("gpu", set())


@pytest.mark.asyncio
async def test_auto_prefers_verified_gpu_and_falls_back_when_unavailable(settings):
    service = scheduler(settings)
    async with service.reserve(
        "auto", 1024 * MIB, timeout=1, allowed_gpu_uuids={"GPU-B"}
    ) as lease:
        assert lease.device == "gpu" and lease.gpu_uuid == "GPU-B"
    for allowed in (set(), {"GPU-unavailable"}):
        async with service.reserve(
            "auto", 1024 * MIB, timeout=1, allowed_gpu_uuids=allowed
        ) as lease:
            assert lease.device == "cpu"
    async with service.reserve("auto", 15 * 1024 * MIB, timeout=1) as lease:
        assert lease.device == "cpu"  # Neither GPU has enough free memory.
    with pytest.raises(AdmissionError, match="GPU"):
        async with service.reserve(
            "gpu", 1024 * MIB, timeout=1, allowed_gpu_uuids=set()
        ):
            pytest.fail("Explicit GPU execution must not fall back to CPU")
