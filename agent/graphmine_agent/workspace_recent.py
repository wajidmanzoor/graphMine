"""Small, private summaries for returning to saved workspace activity."""

import json
from typing import Literal

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .datasets import DatasetLibrary, _owner
from .models import SessionRecord
from .query_library import QueryLibrary


class DatasetConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: str = Field(min_length=1, max_length=128)


def recent_work(runtime, section, *, offset=0, limit=4):
    if section == "queries":
        return QueryLibrary(runtime).list(kind="saved", offset=offset, limit=limit)
    if section == "datasets":
        page = DatasetLibrary(runtime).page(offset=offset, limit=limit, latest=True)
        page["items"] = [{**{key: item[key] for key in ("id", "dataset_id", "version", "size_bytes", "name", "kind", "source_complete")},
                          "updated_at": item["created_at"]} for item in page["items"]]
        return page
    with runtime.database._connect() as db:
        # Apply ownership in SQL before sorting or limiting. Never load result
        # artifacts, input blobs, query parameters, or whole workflow documents.
        db.execute("ATTACH DATABASE ? AS analysis", (str(runtime.analytics.path),))
        rows = db.execute(
            "SELECT w.id,w.session_id,json_extract(s.payload,'$.title') AS conversation,"
            "json_extract(w.document,'$.status') AS status,"
            "json_extract(w.document,'$.revision') AS revision,"
            "coalesce(json_extract(w.document,'$.updated_at'),json_extract(w.document,'$.created_at')) AS updated_at,"
            "(SELECT json_group_array(json_extract(value,'$.operation')) "
            "FROM json_each(w.document,'$.validation.plan.steps')) AS operations "
            "FROM analysis.workflows w JOIN sessions s ON s.id=w.session_id "
            "WHERE s.owner_id IS ? AND coalesce(json_extract(s.payload,'$.archived'),0)=0 "
            "ORDER BY CASE WHEN json_extract(w.document,'$.status') IN ('running','queued','awaiting_review') "
            "THEN 0 ELSE 1 END,updated_at DESC,w.id DESC LIMIT ? OFFSET ?",
            (_owner(), limit + 1, offset),
        ).fetchall()
    items = [dict(row) for row in rows[:limit]]
    if section == "analyses":
        for item in items:
            item["operations"] = json.loads(item["operations"])
    return {"items": items, "has_more": len(rows) > limit, "offset": offset, "limit": limit}


def start_dataset_conversation(runtime, identifier, body):
    library = DatasetLibrary(runtime)
    metadata = library.get(identifier)
    runtime.catalog.domain(body.domain_id)
    session = runtime.database.create_session(SessionRecord(domain_id=body.domain_id, title=metadata["name"]))
    try:
        imported = library.import_into(identifier, session.id)
    except Exception:
        from .api import remove_session

        remove_session(runtime, session.id)
        raise
    return {"session": session.model_dump(mode="json"), **imported}


def register_recent_routes(router):
    @router.get("/workspace/recent/{section}")
    def recent(section: Literal["datasets", "queries", "analyses"], request: Request,
               offset: int = Query(0, ge=0, le=100000), limit: int = Query(4, ge=1, le=12)):
        return recent_work(request.app.state.runtime, section, offset=offset, limit=limit)

    @router.post("/datasets/{identifier}/conversation", status_code=201)
    async def start(identifier: str, body: DatasetConversation, request: Request):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Uploads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(start_dataset_conversation, runtime, identifier, body)
