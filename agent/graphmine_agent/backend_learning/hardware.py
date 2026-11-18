"""Read-only host/NVML measurements; no CUDA context or device scheduling."""

from __future__ import annotations

import ctypes as C
import ctypes.util
import os
import socket
import threading
from pathlib import Path


class _Memory(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ("total", "free", "used")]


class _Utilization(C.Structure):
    _fields_ = [("gpu", C.c_uint), ("memory", C.c_uint)]


class _Process(C.Structure):
    _fields_ = [("pid", C.c_uint), ("usedGpuMemory", C.c_ulonglong),
                ("gpuInstanceId", C.c_uint), ("computeInstanceId", C.c_uint)]


class NVML:
    def __init__(self):
        name = ctypes.util.find_library("nvidia-ml")
        if not name:
            raise OSError("NVML is unavailable")
        self.lib = C.CDLL(name)
        self._check(self.lib.nvmlInit_v2())
        self.closed = False

    @staticmethod
    def _check(status):
        if status:
            raise OSError(f"NVML status {status}")

    def _string(self, function, *args):
        output = C.create_string_buffer(128)
        self._check(getattr(self.lib, function)(*args, output, C.c_uint(len(output))))
        return output.value.decode(errors="replace")

    def handle(self, index):
        result = C.c_void_p()
        self._check(self.lib.nvmlDeviceGetHandleByIndex_v2(C.c_uint(index), C.byref(result)))
        return result

    def processes(self, handle):
        processes = {}
        for kind in ("Compute", "Graphics"):
            function = getattr(self.lib, f"nvmlDeviceGet{kind}RunningProcesses_v3")
            count = C.c_uint()
            status = function(handle, C.byref(count), None)
            if status not in (0, 7):  # NVML_ERROR_INSUFFICIENT_SIZE
                self._check(status)
            for _ in range(3):
                count.value = max(16, count.value * 2)
                rows = (_Process * count.value)()
                status = function(handle, C.byref(count), rows)
                if status != 7:
                    break
            self._check(status)
            for row in rows[:count.value]:
                value = row.usedGpuMemory
                if value == (1 << 64) - 1:
                    value = None
                previous = processes.get(row.pid)
                processes[row.pid] = max(previous or 0, value) if value is not None else previous
        return processes

    def snapshot(self, pids=()):
        count, cuda = C.c_uint(), C.c_int()
        self._check(self.lib.nvmlDeviceGetCount_v2(C.byref(count)))
        self._check(self.lib.nvmlSystemGetCudaDriverVersion(C.byref(cuda)))
        driver = self._string("nvmlSystemGetDriverVersion")
        result = []
        for index in range(count.value):
            handle, memory, utilization = self.handle(index), _Memory(), _Utilization()
            self._check(self.lib.nvmlDeviceGetMemoryInfo(handle, C.byref(memory)))
            self._check(self.lib.nvmlDeviceGetUtilizationRates(handle, C.byref(utilization)))
            try:
                processes = self.processes(handle)
                other = len(set(processes) - set(pids))
            except OSError:
                other = None
            result.append(dict(index=index, uuid=self._string("nvmlDeviceGetUUID", handle),
                               model=self._string("nvmlDeviceGetName", handle),
                               total_memory_bytes=memory.total, free_memory_bytes=memory.free,
                               utilization_percent=utilization.gpu, other_processes=other,
                               driver_version=driver, cuda_version=cuda.value))
        return result

    def close(self):
        if not self.closed:
            self.lib.nvmlShutdown()
            self.closed = True


def process_tree(pid):
    seen, pending = set(), [pid]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            for path in Path(f"/proc/{current}/task").glob("*/children"):
                try:
                    pending.extend(int(item) for item in path.read_text().split())
                except (OSError, ValueError):
                    pass
        except OSError:
            pass
    return seen


def process_rss(pid):
    rss, observed = 0, False
    for child in process_tree(pid):
        try:
            rss += int(Path(f"/proc/{child}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
            observed = True
        except (OSError, ValueError, IndexError):
            pass
    return rss if observed else None


def merge_peaks(first, second):
    result = {**first, **second}
    for name in ("gpu_bytes", "process_rss_bytes"):
        values = [item[name] for item in (first, second) if item.get(name) is not None]
        result[name] = max(values) if values else None
    return result


def hardware_snapshot(*, leased_gpu_uuid=None, pid=None):
    result = dict(hostname=socket.gethostname(), cpu_model=None,
                  total_cores=os.cpu_count(), free_cores=None,
                  total_ram_bytes=None, free_ram_bytes=None,
                  gpus=[], leased_gpu_index=None, warnings=[])
    try:
        result["free_cores"] = max(0.0, (os.cpu_count() or 1) - os.getloadavg()[0])
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                result["cpu_model"] = line.split(":", 1)[1].strip()
                break
        memory = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
                  for line in Path("/proc/meminfo").read_text().splitlines()}
        result.update(total_ram_bytes=memory["MemTotal"], free_ram_bytes=memory["MemAvailable"])
        try:
            limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
            if limit != "max":
                used = int(Path("/sys/fs/cgroup/memory.current").read_text())
                result["total_ram_bytes"] = min(int(limit), result["total_ram_bytes"])
                result["free_ram_bytes"] = min(max(0, int(limit) - used), result["free_ram_bytes"])
        except OSError:
            pass
    except (OSError, ValueError, KeyError):
        result["warnings"].append("host_metrics_unavailable")
    nvml = None
    try:
        nvml = NVML()
        result["gpus"] = nvml.snapshot(process_tree(pid or os.getpid()))
        for gpu in result["gpus"]:
            if gpu["uuid"] == leased_gpu_uuid:
                result["leased_gpu_index"] = gpu["index"]
    except (OSError, AttributeError):
        result["warnings"].append("nvml_unavailable")
    finally:
        if nvml:
            nvml.close()
    return result


class PeakSampler:
    def __init__(self, pid, gpu_index=None, *, interval=0.1):
        self.pid, self.gpu_index, self.interval = pid, gpu_index, interval
        self.rss, self.gpu = None, None
        self.warnings = []
        self.stop_event = threading.Event()
        self.nvml = None
        try:
            if gpu_index is not None:
                self.nvml = NVML()
        except (OSError, AttributeError):
            self.warnings.append("gpu_peak_unavailable")
        self.sample()
        self.thread = threading.Thread(target=self._loop, name="backend-memory-sampler", daemon=True)
        self.thread.start()

    def sample(self):
        pids = process_tree(self.pid)
        rss, observed = 0, False
        for pid in pids:
            try:
                pages = int(Path(f"/proc/{pid}/statm").read_text().split()[1])
                rss += pages * os.sysconf("SC_PAGE_SIZE")
                observed = True
            except (OSError, ValueError, IndexError):
                pass
        if observed:
            self.rss = max(self.rss or 0, rss)
        if self.nvml:
            try:
                processes = self.nvml.processes(self.nvml.handle(self.gpu_index))
                sizes = [memory for pid, memory in processes.items() if pid in pids]
                if all(size is not None for size in sizes):
                    self.gpu = max(self.gpu or 0, sum(sizes))
            except (OSError, AttributeError):
                if "gpu_peak_sample_failed" not in self.warnings:
                    self.warnings.append("gpu_peak_sample_failed")

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            self.sample()

    def finish(self):
        self.stop_event.set()
        self.thread.join(timeout=1)
        self.sample()
        if self.nvml:
            self.nvml.close()
        return dict(gpu_bytes=self.gpu, process_rss_bytes=self.rss,
                    sample_interval_seconds=self.interval)
