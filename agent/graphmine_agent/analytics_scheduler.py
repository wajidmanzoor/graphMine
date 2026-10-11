"""Memory admission and cancellable leases for isolated native workers."""

from __future__ import annotations

import asyncio
import csv
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

MIB = 1024 * 1024


class AdmissionError(ValueError):
    def __init__(self, message, code="resource_limit"):
        super().__init__(message)
        self.code = code


async def gpu_inventory():
    """Query physical UUIDs, so CUDA visibility remapping cannot swap devices."""
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=uuid,memory.total,memory.free",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        raw, _ = await asyncio.wait_for(process.communicate(), 5)
        if process.returncode:
            return []
        return [
            {
                "uuid": row[0].strip(),
                "total": int(row[1]) * MIB,
                "free": int(row[2]) * MIB,
            }
            for row in csv.reader(raw.decode().splitlines())
        ]
    except (OSError, ValueError, TimeoutError):
        return []
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


def cpu_available():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        values[name] = int(value.split()[0]) * 1024
    available = values["MemAvailable"]
    # Honor a container's memory ceiling rather than the host's free memory.
    try:
        maximum = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if maximum != "max":
            used = int(Path("/sys/fs/cgroup/memory.current").read_text())
            available = min(available, max(0, int(maximum) - used))
    except OSError:
        pass
    return available


def estimate_memory(plan, input_bytes):
    """Conservative admission estimate, not a guarantee about vendor allocation.

    Includes canonical/property records, CSR copies, an allocator workspace and
    bounded output. Actual allocation failures remain explicit worker failures.
    """
    output = max(
        (
            step.get("budget", {}).get("max_output_items", 100000)
            for step in plan["steps"]
        ),
        default=100000,
    )
    return 512 * MIB + input_bytes * 32 + output * 64


@dataclass(frozen=True)
class Lease:
    id: str
    device: str
    gpu_uuid: str | None
    reserved_bytes: int
    available_bytes_at_admission: int
    llm_reserved_bytes: int = 0
    estimate_version: str = "native-workspace-v1"

    def record(self):
        return asdict(self)


class AnalyticsScheduler:
    def __init__(self, settings, *, probe=gpu_inventory, host_memory=cpu_available):
        self.settings, self.probe, self.host_memory = settings, probe, host_memory
        self.condition = asyncio.Condition()
        self.leases = {}

    def eligible(self, devices):
        configured = set(self.settings.analytics_gpu_uuids)
        if self.settings.graph_gpu_uuid:
            configured.add(self.settings.graph_gpu_uuid)
        result = []
        for device in devices:
            if configured and device["uuid"] not in configured:
                continue
            llm = (
                self.settings.llm_enabled
                and device["uuid"] == self.settings.llm_gpu_uuid
            )
            if llm and not self.settings.allow_shared_gpu:
                continue
            reserve = self.settings.analytics_llm_reserve_bytes if llm else 0
            if llm and not reserve:
                reserve = int(device["total"] * 0.80)
            result.append({**device, "llm_reserve": reserve})
        return result

    def snapshot(self):
        return [lease.record() for lease in self.leases.values()]

    @asynccontextmanager
    async def reserve(self, policy, requested, *, timeout):
        if policy not in {"cpu", "gpu", "auto"} or requested <= 0:
            raise AdmissionError("Invalid resource request", "invalid_input")
        lease = None
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while lease is None:
                devices = self.eligible(await self.probe()) if policy != "cpu" else []
                if policy == "gpu" and not devices:
                    raise AdmissionError(
                        "No configured GPU is available outside the LLM reservation",
                        "backend_unavailable",
                    )
                async with self.condition:
                    ranked = []
                    for device in devices:
                        reserved = sum(
                            item.reserved_bytes
                            for item in self.leases.values()
                            if item.gpu_uuid == device["uuid"]
                        )
                        capacity = min(
                            device["free"],
                            max(0, device["total"] - device["llm_reserve"]),
                        )
                        available = (
                            capacity
                            - reserved
                            - self.settings.analytics_gpu_headroom_bytes
                        )
                        ranked.append((available, device))
                    # Prefer the device with more admitted space; UUID breaks ties.
                    ranked.sort(key=lambda item: (-item[0], item[1]["uuid"]))
                    if ranked and ranked[0][0] >= requested:
                        available, device = ranked[0]
                        lease = Lease(
                            str(uuid4()),
                            "gpu",
                            device["uuid"],
                            requested,
                            available,
                            device["llm_reserve"],
                        )
                    elif policy == "gpu" and requested > max(
                        device["total"]
                        - device["llm_reserve"]
                        - self.settings.analytics_gpu_headroom_bytes
                        for device in devices
                    ):
                        raise AdmissionError(
                            "This workflow exceeds every permitted GPU's memory admission limit"
                        )
                    elif policy != "gpu":
                        cpu = [
                            item
                            for item in self.leases.values()
                            if item.device == "cpu"
                        ]
                        available = self.host_memory() - sum(
                            item.reserved_bytes for item in cpu
                        )
                        if (
                            len(cpu) < self.settings.analytics_cpu_workers
                            and requested <= available
                        ):
                            lease = Lease(
                                str(uuid4()), "cpu", None, requested, available
                            )
                    if lease is not None:
                        self.leases[lease.id] = lease
                        break
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise AdmissionError(
                            "Timed out waiting for an admitted execution slot"
                        )
                    try:
                        await asyncio.wait_for(self.condition.wait(), min(1, remaining))
                    except TimeoutError:
                        pass
            yield lease
        finally:
            if lease is not None:
                async with self.condition:
                    self.leases.pop(lease.id, None)
                    self.condition.notify_all()
