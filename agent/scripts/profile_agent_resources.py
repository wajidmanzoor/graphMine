"""CPU-only API upload/queue measurements in disposable storage.

No application lifespan, worker, native probe or model call is started. Timed
runs and traced-memory runs are separate because tracemalloc changes latency.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import platform
import resource
import statistics
import tempfile
import time
import tracemalloc
from dataclasses import fields, replace
from pathlib import Path

import graphmine_agent
import httpx
from graphmine_agent.api import build_runtime, create_app
from graphmine_agent.config import Settings
from graphmine_agent.history import HistoryStore
from graphmine_agent.models import ExecutionPlan, SessionRecord, utc_now


def make_inputs(directory, nodes):
    graph = {
        "graph": {
            "id": "resource-fixture",
            "directed": False,
            "allows_self_loops": False,
            "allows_parallel_edges": False,
        },
        "vertices": [{"id": i, "label": f"Record {i}"} for i in range(nodes)],
        "edges": [
            {
                "id": 2 * i + j,
                "source": i,
                "target": (i + step) % nodes,
                "attributes": {"year": 2026, "value": 1.5},
            }
            for i in range(nodes)
            for j, step in enumerate((1, 13))
        ],
    }
    json_path = directory / "records.json"
    with json_path.open("w") as handle:
        json.dump(graph, handle, separators=(",", ":"))
    csv_path, edge_path = directory / "records.csv", directory / "records.txt"
    with csv_path.open("w") as csv_file, edge_path.open("w") as edge_file:
        csv_file.write("id,source,target,year,value\n")
        for edge in graph["edges"]:
            csv_file.write(f"{edge['id']},{edge['source']},{edge['target']},2026,1.5\n")
            edge_file.write(f"{edge['source']} {edge['target']}\n")
    attachment = directory / "attachment.bin"
    with attachment.open("wb") as handle:
        for _ in range(32):
            handle.write(b"x" * 1024 * 1024)
    return [
        (json_path, "graph"),
        (csv_path, "graph"),
        (edge_path, "graph"),
        (attachment, "attachment"),
    ]


async def measure_upload(settings, source, role, *, traced):
    runtime = build_runtime(settings)
    app = create_app(settings)
    app.state.runtime = runtime
    session = runtime.database.create_session(SessionRecord())
    gaps = []
    running = True

    async def heartbeat():
        previous = time.perf_counter()
        while running:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - previous)
            previous = now

    gc.collect()
    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.01)
    gaps.clear()
    if traced:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://cpu-fixture"
        ) as client:
            with source.open("rb") as handle:
                response = await client.post(
                    f"/api/sessions/{session.id}/files",
                    files={"file": (source.name, handle)},
                    data={"role": role},
                )
        elapsed = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1] if traced else None
        if response.status_code != 201:
            raise RuntimeError(response.text)
        record = response.json()
        assert record["sha256"] == HistoryStore.digest(source)
        assert record["size_bytes"] == source.stat().st_size
        await asyncio.sleep(0.01)
        return {
            "seconds": elapsed,
            "python_peak_bytes": peak,
            "maximum_event_loop_gap_seconds": max(gaps, default=0),
            "stored_bytes": record["size_bytes"],
            "metadata": record["metadata"],
        }
    finally:
        if traced:
            tracemalloc.stop()
        running = False
        await task
        await runtime.agent.close()


async def measure_queue(settings):
    # Admission is tested without starting a consumer or executing queued plans.
    if "max_pending_jobs" in {field.name for field in fields(settings)}:
        settings = replace(settings, max_pending_jobs=4)
    runtime = build_runtime(settings)
    session = runtime.database.create_session(SessionRecord())
    plan = ExecutionPlan(
        session_id=session.id,
        graph_id="fixture-no-execution",
        problem_id="maximal_clique_enumeration",
        operation_id="maximal-cliques",
    )
    accepted, rejected = 0, []
    started = time.perf_counter()
    try:
        for _ in range(12):
            try:
                await runtime.jobs.enqueue(plan)
                accepted += 1
            except Exception as error:
                if type(error).__name__ != "QueueCapacityError":
                    raise
                rejected.append(str(error))
        return {
            "attempted": 12,
            "accepted": accepted,
            "rejected": len(rejected),
            "configured_max_pending_jobs": getattr(settings, "max_pending_jobs", None),
            "seconds": time.perf_counter() - started,
            "statistics": runtime.jobs.statistics(),
            "persisted_jobs": len(runtime.database.list_jobs(session.id)),
            "worker_started": False,
        }
    finally:
        await runtime.agent.close()


async def profile(arguments):
    if not 100 <= arguments.nodes <= 100_000 or not 1 <= arguments.repeats <= 5:
        raise ValueError("Use 100..100000 vertices and one to five timed repeats")
    if arguments.output.exists():
        raise FileExistsError(arguments.output)
    root = Path(__file__).resolve().parents[2]
    settings = replace(
        Settings.from_env(root),
        api_token=None,
        llm_enabled=False,
        history_directory=None,
        max_upload_bytes=64 * 1024 * 1024,
    )
    report = {
        "version": "agent-resources-v1",
        "created_at": utc_now().isoformat(),
        "label": arguments.label,
        "nodes": arguments.nodes,
        "edges": 2 * arguments.nodes,
        "timed_repeats": arguments.repeats,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scope": "Synthetic local ASGI uploads including multipart parsing, validation, persistence and history. Separate traced Python allocation peak; no GPU, model, network server, native probe or production-scale throughput measurement. Event-loop gap uses a 5ms heartbeat; RSS is the whole process high-water mark.",
        "source_sha256": {
            name: HistoryStore.digest(Path(graphmine_agent.__file__).parent / name)
            for name in (
                "api.py",
                "graph_store.py",
                "database.py",
                "history.py",
                "jobs.py",
                "execution.py",
                "config.py",
            )
        },
        "profiler_sha256": HistoryStore.digest(Path(__file__)),
        "uploads": [],
        "model_inference": "not_run",
        "native_execution": "not_run",
    }
    with tempfile.TemporaryDirectory(prefix="graphmine-resource-profile-") as temporary:
        directory = Path(temporary)
        fixtures = make_inputs(directory, arguments.nodes)
        for index, (source, role) in enumerate(fixtures):
            samples = []
            for repeat in range(arguments.repeats + 1):
                traced = repeat == arguments.repeats
                sample = await measure_upload(
                    replace(settings, data_root=directory / f"upload-{index}-{repeat}"),
                    source,
                    role,
                    traced=traced,
                )
                if not traced:
                    samples.append(sample)
                else:
                    memory = sample
            report["uploads"].append(
                {
                    "name": source.name,
                    "role": role,
                    "source_bytes": source.stat().st_size,
                    "source_sha256": HistoryStore.digest(source),
                    "timed_runs": samples,
                    "median_seconds": statistics.median(
                        sample["seconds"] for sample in samples
                    ),
                    "maximum_event_loop_gap_seconds": max(
                        sample["maximum_event_loop_gap_seconds"] for sample in samples
                    ),
                    "traced_memory_run": memory,
                }
            )
            print(
                json.dumps(
                    {
                        "finished": source.name,
                        "median_seconds": report["uploads"][-1]["median_seconds"],
                        "python_peak_bytes": memory["python_peak_bytes"],
                    }
                ),
                flush=True,
            )
        report["queue"] = await measure_queue(
            replace(settings, data_root=directory / "queue")
        )
    report["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--nodes", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=3)
    asyncio.run(profile(parser.parse_args()))
