"""Bounded CPU CSV loading and native construction, with optional cuDF loading."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .csv_ingestion import read_table
from .models import FileRole


class ProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tables: dict[str, str] = Field(min_length=1, max_length=8)
    projection: dict
    device: Literal["cpu", "gpu"] = "cpu"


def write_request(path, value, limit):
    size = 0
    with path.open("wb") as output:
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(
            value
        ):
            raw = chunk.encode()
            size += len(raw)
            if size > limit:
                raise AnalyticsError(
                    "Table construction request exceeds the byte budget",
                    "resource_limit",
                )
            output.write(raw)


async def native_request(runtime, value, input_bytes, *, device="gpu"):
    service, settings = runtime.analytics, runtime.settings
    binary = (
        settings.native_runtime_binary
        or settings.repository_root / "library/build/runtime/graphmine-native"
    )
    if not binary.is_file():
        raise AnalyticsError(
            "Table construction needs the configured native executable",
            "native_reader_unavailable",
            503,
        )
    memory = 512 * 1024 * 1024 + input_bytes * 32
    async with service.scheduler.reserve(
        device, memory, timeout=settings.job_timeout_seconds
    ) as lease:
        environment = {**os.environ, "CUDA_VISIBLE_DEVICES": lease.gpu_uuid or ""}
        with tempfile.TemporaryDirectory(prefix="graphmine-projection-") as temporary:
            output, errors = (
                Path(temporary) / "result.json",
                Path(temporary) / "errors.txt",
            )
            input_path = Path(temporary) / "request.json"
            await run_in_threadpool(
                write_request,
                input_path,
                value,
                settings.analytics_max_input_bytes + settings.max_result_bytes,
            )
            with (
                output.open("wb") as stdout,
                errors.open("wb") as stderr,
                input_path.open("rb") as stdin,
            ):
                process = await asyncio.create_subprocess_exec(
                    str(binary),
                    "request",
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    env=environment,
                    start_new_session=True,
                )
                try:
                    async with asyncio.timeout(min(60, settings.job_timeout_seconds)):
                        await process.communicate()
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
        if path.stat().st_size > runtime.settings.analytics_max_input_bytes:
            raise AnalyticsError(
                "Table exceeds the input byte budget", "resource_limit"
            )
        table = await run_in_threadpool(read_table, path)
        return {
            "complete": True,
            "provenance": {"reader": "python_csv", "device": "cpu"},
            "columns": [
                {"name": name, "type": "string", "nullable": False}
                for name in table["columns"]
            ],
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
        sources = {}
        for alias, path in tables.items():
            sources[alias] = (
                {"data": await run_in_threadpool(read_table, path)}
                if body.device == "cpu"
                else {"path": str(path)}
            )
        result = await native_request(
            runtime,
            {
                "command": "project_graph",
                "tables": sources,
                "projection": body.projection,
                "gpu_device": 0,
            },
            total,
            device=body.device,
        )
        record = await run_in_threadpool(
            runtime.graph_store.ingest,
            session_id=session_id,
            role=FileRole.graph,
            filename="projected-network.json",
            content=json.dumps(
                result["graph"], ensure_ascii=False, allow_nan=False
            ).encode(),
            provenance={
                "projection": result["provenance"],
                "tables": {
                    alias: {
                        "file_id": file_id,
                        "sha256": runtime.database.get_file(file_id).sha256,
                        "reader": "python_csv" if body.device == "cpu" else "libcudf",
                    }
                    for alias, file_id in body.tables.items()
                },
            },
        )
        return {
            "file": record.model_dump(
                mode="json", exclude={"source_path", "canonical_path"}
            ),
            "provenance": result["provenance"],
            "complete": result["complete"],
            "allocation": result["allocation"],
        }
