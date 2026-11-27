"""Owned snapshot refinement; publication uses the existing preview lifecycle."""

import copy
import hashlib
from importlib import metadata as package_metadata
import json
from time import perf_counter
from typing import Any, Literal

from fastapi import Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .database_job_context import begin_commit, checkpoint
from .database_sources import Strict, get_source
from .errors import AnalyticsError
from .models import utc_now
from .query_previews import QueryPreviews
from .query_results import graph_preview, is_database_query
from .semantic_engine import engine_lock
from .semantic_loader import encoded, key, schema
from .semantic_worker import MAX_BYTES, run_worker


class SemanticRequest(Strict):
    base_version_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=20_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    model: str = Field(default="qwen", pattern=r"^[a-z][a-z0-9_]{0,31}$")
    call_limit: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)
    reuse_answers: bool = False
    projection: Literal["elements", "rows"] = "elements"
    directed: bool | None = None
    weight_property: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=160)


def base_snapshot(runtime, identifier, *, content=False):
    value = QueryPreviews(runtime).get(identifier, content=content)
    metadata, raw = value if content else (value, None)
    if metadata["kind"] != "graph" or not metadata.get("source_complete") or not is_database_query(metadata.get("source")):
        raise AnalyticsError("Choose a complete graph snapshot from a database query.", "semantic_input", 422)
    source_id = metadata.get("source", {}).get("database_source", {}).get("id")
    if not source_id:
        raise AnalyticsError("This graph has no retained database-source identity.", "semantic_input", 422)
    get_source(runtime.settings, source_id)  # access check only; never opens Neo4j
    if content:
        if len(raw) > MAX_BYTES:
            raise AnalyticsError("The snapshot exceeds the semantic worker's 64 MiB input budget.", "resource_limit")
        if len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise AnalyticsError("The base snapshot failed its integrity check.", "data_integrity", 409)
    return (metadata, raw) if content else metadata


def prepare_request(runtime, body):
    metadata = base_snapshot(runtime, body.base_version_id)
    try:
        size = len(encoded(body.parameters).encode())
    except (ValueError, TypeError):
        raise AnalyticsError("Semantic parameters must be finite JSON values.", "semantic_parameters") from None
    if size > 256 * 1024:
        raise AnalyticsError("Semantic parameters exceed the byte budget.", "resource_limit")
    if body.projection == "rows" and body.weight_property:
        raise AnalyticsError("Row projection takes its weight from the column returned AS weight.", "query_projection")
    from .semantic_policy import execution_policy
    execution_policy(runtime, body.model_dump())
    lock = engine_lock()
    try:
        version = package_metadata.version(lock["distribution"])
    except package_metadata.PackageNotFoundError:
        raise AnalyticsError("Install the source-built agent semantic extra before refining snapshots.", "semantic_unavailable", 503) from None
    if version != lock["version"]:
        raise AnalyticsError("Reinstall the pinned semantic engine for this GraphMine release.", "semantic_incompatible", 503)
    return metadata


def snapshot_schema(runtime, identifier):
    from .admin_settings import load
    from .semantic_policy import allowed
    metadata, raw = base_snapshot(runtime, identifier, content=True)
    settings = load(runtime.settings, runtime.database)
    return {"base_version_id": identifier, "sha256": metadata["sha256"], "schema": schema(json.loads(raw)),
            "capabilities": {"plain_queries": True, "mock_queries": settings.semantic_mode == "mock" and allowed(settings), "live_queries": False,
                             "answer_reuse": False, "query_wide_call_limit": False, "call_estimate": False,
                             "judgments": False, "max_input_bytes": MAX_BYTES, "max_output_bytes": MAX_BYTES,
                             "timeout_seconds": settings.semantic_timeout_seconds, "max_mock_calls_per_expression": settings.semantic_max_calls,
                             "default_call_limit": settings.semantic_default_call_limit, "max_concurrent_requests": settings.semantic_max_concurrent_requests,
                             "blockers": engine_lock()["live_blockers"] + engine_lock()["integration_blockers"]}}


def run_query(runtime, body):
    from .semantic_policy import slot
    started = perf_counter()
    base, raw = base_snapshot(runtime, body.base_version_id, content=True)
    checkpoint("loading")
    with slot(runtime, body.model_dump()) as policy:
        output = run_worker(json.loads(raw), {**body.model_dump(), "call_limit": policy["call_limit"]},
                            execution=policy, timeout=policy["timeout_seconds"])
    checkpoint("validating", output["row_count"])
    graph = output["value"] if output["kind"] == "graph" else {
        "graph": {"id": "semantic-table", "directed": True, "allows_self_loops": True, "allows_parallel_edges": True}, "vertices": [], "edges": []}
    ancestry = base["source"]
    old_lineage = ancestry.get("lineage") or {}
    lineage = {"vertices": {key(v["id"]): copy.deepcopy(old_lineage.get("vertices", {}).get(key(v["id"]))) for v in graph["vertices"]
                            if key(v["id"]) in old_lineage.get("vertices", {})},
               "edges": {key(e["id"]): copy.deepcopy(old_lineage.get("edges", {}).get(key(e["id"]))) for e in graph["edges"]
                         if body.projection == "elements" and key(e["id"]) in old_lineage.get("edges", {})}}
    duration = round((perf_counter() - started) * 1000)
    source = {
        "type": "semantic_query", "backend_id": base.get("backend_id"),
        "database_source": copy.deepcopy(ancestry["database_source"]),
        "database_dataset": copy.deepcopy(ancestry.get("database_dataset")),
        "parent": {"version_id": base["id"], "dataset_id": base["dataset_id"], "sha256": base["sha256"], "source": copy.deepcopy(ancestry)},
        "base_version_id": base["id"], "base_sha256": base["sha256"],
        "query": body.statement, "parameters": body.parameters, "projection": body.projection,
        "weight_property": body.weight_property, "lineage": lineage,
        "steps": output["steps"], "engine": output["engine"], "schema": output["schema"],
        "settings": output["effective_settings"], "requested_call_limit": body.call_limit,
        "usage": output["usage"], "column_types": output["column_types"], "row_count": output["row_count"],
        "model_dependent_input": bool(ancestry.get("model_dependent_input")),
        "simulation": bool(output["steps"]) or bool(ancestry.get("simulation")),
        "completion_state": "completed", "duration_ms": duration, "fetched_at": utc_now().isoformat(),
        "scope": "mock semantic refinement" if output["steps"] else "structural refinement of a saved snapshot",
    }
    # The complete graph/table is validated before cancellation is sealed.
    if output["kind"] == "graph":
        runtime.graph_store._validate_graph(output["value"])
    else:
        from .table_artifacts import validate_table
        validate_table(output["value"])
    begin_commit("saving")
    snapshot = QueryPreviews(runtime).store(output["value"], name=body.name or base["name"] + " refinement",
                                            kind=output["kind"], source=source, complete=True)
    preview = graph_preview(graph)
    return {"dataset": snapshot if output["kind"] == "graph" else None, "table": snapshot if output["kind"] == "table" else None,
            "graph": preview, "rows": output["rows"], "row_count": output["row_count"], "rows_truncated": output["rows_truncated"],
            "vertex_count": len(graph["vertices"]), "edge_count": len(graph["edges"]), "usage": output["usage"], "elapsed_ms": duration,
            "message": "Mock refinement ready; its judgments are simulated." if output["steps"] else "Snapshot refinement ready."}


def register_semantic_routes(router):
    @router.get("/database-query-snapshots/{identifier}/semantic-schema")
    async def get_schema(identifier: str, request: Request):
        from .database_jobs import private_response
        runtime = request.app.state.runtime
        async with runtime.upload_slots:
            return private_response(await run_in_threadpool(snapshot_schema, runtime, identifier))

    @router.post("/semantic-queries", status_code=202)
    async def enqueue(body: SemanticRequest, request: Request):
        from .database_jobs import accepted
        runtime = request.app.state.runtime
        metadata = await run_in_threadpool(prepare_request, runtime, body)
        job = await run_in_threadpool(runtime.database_jobs.enqueue, "semantic", metadata["source"]["database_source"]["id"], body,
                                     request_key=request.headers.get("Idempotency-Key"))
        return accepted(job)
