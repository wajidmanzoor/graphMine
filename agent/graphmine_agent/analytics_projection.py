"""Workspace table projection; loading, joins, and construction run in C++/cuDF."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .models import FileRole


class ProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tables: dict[str, str] = Field(min_length=1, max_length=8)
    projection: dict


async def native_request(runtime, value, input_bytes):
    service, settings = runtime.analytics, runtime.settings
    binary = (
        settings.native_runtime_binary
        or settings.repository_root / "library/build/runtime/graphmine-native"
    )
    if not binary.is_file():
        raise AnalyticsError(
            "Table construction needs a libcudf-enabled native executable",
            "native_reader_unavailable",
            503,
        )
    memory = 512 * 1024 * 1024 + input_bytes * 32
    async with service.scheduler.reserve(
        "gpu", memory, timeout=settings.job_timeout_seconds
    ) as lease:
        environment = {**os.environ, "CUDA_VISIBLE_DEVICES": lease.gpu_uuid}
        with tempfile.TemporaryDirectory(prefix="graphmine-projection-") as temporary:
            output, errors = (
                Path(temporary) / "result.json",
                Path(temporary) / "errors.txt",
            )
            with output.open("wb") as stdout, errors.open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(
                    str(binary),
                    "request",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    env=environment,
                    start_new_session=True,
                )
                try:
                    async with asyncio.timeout(min(60, settings.job_timeout_seconds)):
                        await process.communicate(
                            json.dumps(value, allow_nan=False).encode()
                        )
                except TimeoutError as exc:
                    raise AnalyticsError(
                        "Native table construction exceeded its deadline",
                        "resource_limit",
                        504,
                    ) from exc
                finally:
                    await service._stop_process(process)
            if output.stat().st_size > settings.max_result_bytes:
                raise AnalyticsError(
                    "Projection output exceeds the byte budget", "resource_limit"
                )
            try:
                result = json.loads(output.read_bytes())
            except ValueError as exc:
                raise AnalyticsError(
                    "Native table construction returned no valid result",
                    "worker_failure",
                    502,
                ) from exc
            if "error" in result:
                raise AnalyticsError(
                    result["error"]["message"], result["error"]["code"]
                )
            if process.returncode or result.get("complete") is not True:
                raise AnalyticsError(
                    "Native table construction did not complete", "worker_failure", 502
                )
            result["allocation"] = lease.record()
            return result


def source(runtime, session_id, file_id):
    runtime.database.get_session(session_id)
    record = runtime.database.get_file(file_id)
    if record.session_id != session_id:
        raise AnalyticsError("Projection input belongs to another workspace")
    path = Path(record.source_path)
    if path.suffix.lower() != ".csv":
        raise AnalyticsError("Table projections require uploaded CSV files")
    return path


def register_projection_routes(router):
    @router.get("/sessions/{session_id}/tables/{file_id}/schema")
    async def schema(session_id: str, file_id: str, request: Request):
        runtime = request.app.state.runtime
        path = source(runtime, session_id, file_id)
        result = await native_request(
            runtime,
            {"command": "read_csv", "path": str(path), "gpu_device": 0},
            path.stat().st_size,
        )
        table = result.pop("table")
        return {
            **result,
            "columns": table["columns"],
            "row_count": len(table["rows"]),
            "sample": table["rows"][:8],
            "sample_is_excerpt": True,
        }

    @router.post("/sessions/{session_id}/projections", status_code=201)
    async def project(session_id: str, body: ProjectionRequest, request: Request):
        runtime = request.app.state.runtime
        tables = {
            alias: source(runtime, session_id, file_id)
            for alias, file_id in body.tables.items()
        }
        total = sum(path.stat().st_size for path in tables.values())
        if total > runtime.settings.analytics_max_input_bytes:
            raise AnalyticsError(
                "Combined tables exceed the input byte budget", "resource_limit"
            )
        result = await native_request(
            runtime,
            {
                "command": "project_graph",
                "tables": {
                    alias: {"path": str(path)} for alias, path in tables.items()
                },
                "projection": body.projection,
                "gpu_device": 0,
            },
            total,
        )
        record = await run_in_threadpool(
            runtime.graph_store.ingest,
            session_id=session_id,
            role=FileRole.graph,
            filename="projected-network.json",
            content=json.dumps(
                result["graph"], ensure_ascii=False, allow_nan=False
            ).encode(),
        )
        return {
            "file": record.model_dump(
                mode="json", exclude={"source_path", "canonical_path"}
            ),
            "provenance": result["provenance"],
            "complete": result["complete"],
            "allocation": result["allocation"],
        }
