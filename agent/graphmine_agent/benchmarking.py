from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings


class BenchmarkError(RuntimeError):
    """Raised for an invalid benchmark contract or unusable result set."""


def _json_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise BenchmarkError(f"could not read JSON file {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise BenchmarkError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise BenchmarkError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(repository_root: Path, value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else repository_root / path).resolve()


def _graph_features(path: Path) -> dict[str, Any]:
    value = _json_document(path)
    graph = value.get("graph", {})
    vertices = value.get("vertices", [])
    edges = value.get("edges", [])
    if not isinstance(graph, dict) or not isinstance(vertices, list) or not isinstance(
        edges, list
    ):
        raise BenchmarkError(f"benchmark graph is not canonical GraphMine JSON: {path}")
    vertex_count = len(vertices)
    edge_count = len(edges)
    directed = bool(graph.get("directed", False))
    denominator = (
        vertex_count * (vertex_count - 1)
        if directed
        else vertex_count * (vertex_count - 1) / 2
    )
    density = 0.0 if denominator <= 0 else edge_count / denominator
    has_timestamps = any(
        isinstance(edge, dict) and edge.get("timestamp") is not None for edge in edges
    )
    metadata = {
        "vertex_count": vertex_count,
        "edge_count": edge_count,
        "density": density,
        "directed": directed,
        "has_timestamps": has_timestamps,
    }
    return metadata


def _lookup(value: Any, path: str) -> Any:
    current = value
    for component in path.split(".") if path else []:
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, list) and component.isdigit():
            current = current[int(component)]
        else:
            raise BenchmarkError(f"result path does not exist: {path}")
    return current


def _matches_expected(payload: dict[str, Any], expected: dict[str, Any]) -> bool:
    try:
        return all(_lookup(payload, path) == value for path, value in expected.items())
    except BenchmarkError:
        return False


class _GpuMemorySampler:
    def __init__(self, gpu_uuid: str | None):
        self.gpu_uuid = gpu_uuid
        self.peak_mib: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.gpu_uuid:
            return
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> int | None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        return self.peak_mib

    def _sample(self) -> None:
        while not self._stop.is_set():
            try:
                completed = subprocess.run(
                    [
                        "nvidia-smi",
                        f"--id={self.gpu_uuid}",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if completed.returncode == 0:
                    observed = int(completed.stdout.strip().splitlines()[0])
                    self.peak_mib = max(self.peak_mib or 0, observed)
            except (OSError, ValueError, subprocess.SubprocessError, IndexError):
                return
            self._stop.wait(0.05)


def _capabilities(settings: Settings) -> dict[str, Any]:
    completed = subprocess.run(
        [str(settings.graphmine_binary), "list"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=_execution_environment(settings),
        cwd=settings.repository_root,
    )
    if completed.returncode != 0:
        raise BenchmarkError(completed.stderr.strip() or "graphmine list failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BenchmarkError(f"invalid capability JSON: {error}") from error
    if not isinstance(value, dict):
        raise BenchmarkError("capability root must be an object")
    return value


def _execution_environment(settings: Settings) -> dict[str, str]:
    environment = dict(os.environ)
    environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if settings.graph_gpu_uuid:
        environment["CUDA_VISIBLE_DEVICES"] = settings.graph_gpu_uuid
    return environment


def _run_once(
    settings: Settings,
    case: dict[str, Any],
    graph_path: Path,
    backend: str,
    timeout_seconds: int | None,
) -> dict[str, Any]:
    command = [
        str(settings.graphmine_binary),
        "run",
        str(case["problem_id"]),
        "--graph",
        str(graph_path),
        "--backend",
        backend,
        "--device",
        "0",
    ]
    arguments = case.get("arguments", [])
    if not isinstance(arguments, list) or not all(
        isinstance(item, (str, int, float)) for item in arguments
    ):
        raise BenchmarkError(f"case {case['id']} arguments must be scalar values")
    command.extend(str(item) for item in arguments)

    sampler = _GpuMemorySampler(settings.graph_gpu_uuid)
    with tempfile.TemporaryDirectory(prefix="graphmine-benchmark-") as temporary:
        result_path = Path(temporary) / "result.json"
        command.extend(["--output", str(result_path)])
        sampler.start()
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=_execution_environment(settings),
                cwd=settings.repository_root,
            )
            wall_ms = (time.perf_counter() - started) * 1000
            peak_mib = sampler.stop()
        except subprocess.TimeoutExpired as error:
            peak_mib = sampler.stop()
            return {
                "status": "timeout",
                "correct": False,
                "wall_ms": timeout_seconds * 1000.0,
                "peak_gpu_memory_mib": peak_mib,
                "exit_code": None,
                "error": f"timed out after {timeout_seconds} seconds",
                "stdout_tail": (error.stdout or "")[-2000:],
                "stderr_tail": (error.stderr or "")[-2000:],
            }
        if not result_path.is_file():
            return {
                "status": "failed",
                "correct": False,
                "wall_ms": wall_ms,
                "peak_gpu_memory_mib": peak_mib,
                "exit_code": completed.returncode,
                "error": "GraphMine did not produce result JSON",
                "stdout_tail": completed.stdout[-2000:],
                "stderr_tail": completed.stderr[-2000:],
            }
        try:
            payload = _json_document(result_path)
        except BenchmarkError as error:
            return {
                "status": "failed",
                "correct": False,
                "wall_ms": wall_ms,
                "peak_gpu_memory_mib": peak_mib,
                "exit_code": completed.returncode,
                "error": str(error),
                "stdout_tail": completed.stdout[-2000:],
                "stderr_tail": completed.stderr[-2000:],
            }
    expected = case.get("expected", {})
    correct = bool(payload.get("ok")) and _matches_expected(payload, expected)
    serialized_output = json.dumps(
        payload.get("output"), sort_keys=True, separators=(",", ":")
    ).encode()
    return {
        "status": "success" if completed.returncode in {0, 3} else "failed",
        "correct": correct,
        "wall_ms": wall_ms,
        "peak_gpu_memory_mib": peak_mib,
        "exit_code": completed.returncode,
        "backend_ms": payload.get("statistics", {}).get("backend_ms"),
        "end_to_end_ms": payload.get("statistics", {}).get("end_to_end_ms"),
        "output_sha256": hashlib.sha256(serialized_output).hexdigest(),
        "error": None if correct else "result failed the benchmark correctness gate",
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def run_benchmarks(
    settings: Settings,
    manifest_path: Path,
    *,
    warmups: int,
    repetitions: int,
    timeout_seconds: int | None,
) -> dict[str, Any]:
    manifest = _json_document(manifest_path)
    if manifest.get("schema_version") != "1.0.0":
        raise BenchmarkError("unsupported benchmark manifest schema")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BenchmarkError("benchmark manifest requires nonempty cases")
    capabilities = _capabilities(settings)
    compiled_by_problem = {
        str(problem["id"]): {
            str(backend["id"])
            for backend in problem.get("backends", [])
            if backend.get("compiled") and backend.get("validated")
        }
        for problem in capabilities.get("problems", [])
    }
    records: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise BenchmarkError("every benchmark case requires a string id")
        problem_id = str(case.get("problem_id", ""))
        if problem_id not in compiled_by_problem:
            raise BenchmarkError(
                f"case {case['id']} refers to unknown problem {problem_id}"
            )
        graph_path = _resolve_path(settings.repository_root, str(case.get("graph", "")))
        features = _graph_features(graph_path)
        if not isinstance(case.get("expected", {}), dict):
            raise BenchmarkError(f"case {case['id']} expected values must be an object")
        requested = case.get("backends") or sorted(compiled_by_problem[problem_id])
        if not isinstance(requested, list) or not all(
            isinstance(backend, str) and backend for backend in requested
        ):
            raise BenchmarkError(
                f"case {case['id']} backends must be a list of backend IDs"
            )
        unknown = set(requested) - compiled_by_problem[problem_id]
        if unknown:
            raise BenchmarkError(
                f"case {case['id']} requests uncompiled backends: {sorted(unknown)}"
            )
        configured_timeout = case.get("timeout_seconds", timeout_seconds)
        case_timeout = int(configured_timeout) if configured_timeout is not None else None
        if case_timeout is not None and case_timeout < 1:
            raise BenchmarkError(f"case {case['id']} timeout must be positive")
        for backend in requested:
            for _ in range(max(0, warmups)):
                warmup = _run_once(
                    settings, case, graph_path, str(backend), case_timeout
                )
                if not warmup["correct"]:
                    raise BenchmarkError(
                        f"warmup failed correctness for {case['id']} / {backend}: "
                        f"{warmup['error']}"
                    )
            for repetition in range(max(1, repetitions)):
                result = _run_once(
                    settings, case, graph_path, str(backend), case_timeout
                )
                records.append(
                    {
                        "case_id": case["id"],
                        "problem_id": problem_id,
                        "backend_id": str(backend),
                        "repetition": repetition,
                        "graph": str(graph_path),
                        "graph_sha256": _sha256(graph_path),
                        "features": features,
                        **result,
                    }
                )
    correct = sum(item["correct"] for item in records)
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": manifest.get("suite", manifest_path.stem),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": _sha256(manifest_path),
        "binary": str(settings.graphmine_binary),
        "binary_sha256": _sha256(settings.graphmine_binary),
        "graph_gpu_uuid": settings.graph_gpu_uuid,
        "host": platform.node(),
        "platform": platform.platform(),
        "warmups": max(0, warmups),
        "repetitions": max(1, repetitions),
        "correct_records": correct,
        "total_records": len(records),
        "records": records,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
