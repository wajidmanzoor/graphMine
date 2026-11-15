"""Private saved queries and bounded history, independent of preview expiration."""

import json
import logging
from typing import Literal

from fastapi import Query, Request
from pydantic import Field

from .analytics import AnalyticsError, _json
from .database import RecordNotFound
from .database_queries import CypherRequest
from .database_sources import Strict, get_source
from .datasets import _owner
from .identity import AccountError, current_principal
from .models import new_id, utc_now

MAX_HISTORY = 200
MAX_SAVED = 250
MAX_DOCUMENT_BYTES = 300 * 1024
logger = logging.getLogger(__name__)


class SaveQuery(Strict):
    source_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    query: CypherRequest
    expected_revision: int | None = Field(default=None, ge=1)


class QueryLibrary:
    def __init__(self, runtime):
        self.runtime, self.database = runtime, runtime.database

    def get(self, identifier, db=None):
        if db is None:
            with self.database._connect() as connection:
                return self.get(identifier, connection)
        row = db.execute("SELECT document FROM query_library WHERE id=? AND owner_id=?", (identifier, _owner() or "")).fetchone()
        if row is None:
            raise RecordNotFound("Query not found")
        return json.loads(row[0])

    def list(self, *, source_id=None, dataset_id=None, kind="saved", offset=0, limit=30):
        clauses, params = ["owner_id=?", "kind=?"], [_owner() or "", kind]
        for column, value in (("source_id", source_id), ("dataset_id", dataset_id)):
            if value is not None:
                clauses.append(column + "=?"); params.append(value)
        with self.database._connect() as db:
            rows = db.execute("SELECT id,source_id,dataset_id,kind,updated_at,"
                              "json_extract(document,'$.name') AS name,"
                              "json_extract(document,'$.revision') AS revision,"
                              "json_extract(document,'$.status') AS status,"
                              "json_extract(document,'$.row_count') AS row_count "
                              "FROM query_library WHERE " + " AND ".join(clauses)
                              + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?", (*params, limit + 1, offset)).fetchall()
        return {"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit, "offset": offset, "limit": limit}

    def _put(self, document, expected_revision=None):
        try:
            raw = _json(document)
        except (TypeError, ValueError, OverflowError) as error:
            raise AnalyticsError("Query parameters must contain finite JSON values.", "cypher_parameters") from error
        if len(raw.encode()) > MAX_DOCUMENT_BYTES:
            raise AnalyticsError("Query and parameter values exceed the 300 KiB storage limit.", "resource_limit")
        owner = _owner() or ""
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            credit = 0
            if expected_revision is not None:
                previous = self.get(document["id"], db)
                if previous["kind"] != "saved" or previous["revision"] != expected_revision:
                    raise AnalyticsError("This saved query changed. Reload it before updating.", "query_changed", 409)
                credit = len(_json(previous).encode())
            elif document["kind"] == "saved":
                if db.execute("SELECT count(*) FROM query_library WHERE owner_id=? AND kind='saved'", (owner,)).fetchone()[0] >= MAX_SAVED:
                    raise AnalyticsError(f"Keep at most {MAX_SAVED} saved queries. Delete an unused query first.", "resource_limit")
            else:
                removed = db.execute("SELECT id,length(CAST(document AS BLOB)) AS size FROM query_library WHERE owner_id=? AND kind='history' ORDER BY updated_at DESC,id DESC LIMIT -1 OFFSET ?", (owner, MAX_HISTORY - 1)).fetchall()
                credit = sum(row["size"] for row in removed)
                db.executemany("DELETE FROM query_library WHERE id=? AND owner_id=?", [(row["id"], owner) for row in removed])
            principal = current_principal.get()
            if principal and len(raw.encode()) > principal.accounts.upload_remaining(principal.user_id) + credit:
                raise AccountError("Your storage allowance is full. Remove unused queries or data to save this query.", "storage_limit")
            db.execute("INSERT INTO query_library VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,source_id=excluded.source_id,dataset_id=excluded.dataset_id,updated_at=excluded.updated_at",
                       (document["id"], owner, document["source_id"], document["dataset_id"], document["kind"], raw, document["updated_at"]))
        return document

    def save(self, body, identifier=None):
        get_source(self.runtime.settings, body.source_id)
        if not body.name.strip():
            raise AnalyticsError("Enter a query name.", "query_name")
        previous = self.get(identifier) if identifier else None
        if previous and body.expected_revision is None:
            raise AnalyticsError("Reload the saved query before updating it.", "query_changed", 409)
        now = utc_now().isoformat()
        document = {"id": identifier or new_id("query"), "kind": "saved", "source_id": body.source_id,
                    "dataset_id": body.query.dataset_id or "default", "name": body.name.strip(),
                    "query": body.query.model_dump(), "revision": previous["revision"] + 1 if previous else 1,
                    "created_at": previous["created_at"] if previous else now, "updated_at": now}
        return self._put(document, body.expected_revision if identifier else None)

    def delete(self, identifier, revision):
        with self.database._lock, self.database._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            document = self.get(identifier, db)
            if document["revision"] != revision:
                raise AnalyticsError("This query changed. Reload it before deleting.", "query_changed", 409)
            db.execute("DELETE FROM query_library WHERE id=? AND owner_id=?", (identifier, _owner() or ""))

    def record(self, source_id, query, *, result=None, error=None, elapsed_ms=0):
        now = utc_now().isoformat()
        snapshot = (result or {}).get("dataset") or (result or {}).get("table") or {}
        document = {"id": new_id("query_run"), "kind": "history", "source_id": source_id,
                    "dataset_id": query.dataset_id or "default", "name": query.name or next(iter(query.statement.strip().splitlines()), "Empty query")[:160],
                    "query": query.model_dump(), "revision": 1, "created_at": now, "updated_at": now,
                    "status": "failed" if error else "completed", "elapsed_ms": elapsed_ms,
                    "error": error, "snapshot_id": snapshot.get("id"), "snapshot_kind": snapshot.get("kind"),
                    "row_count": (result or {}).get("row_count")}
        try:
            return self._put(document)["id"], None
        except (AnalyticsError, AccountError) as exc:
            return None, "Query history was not saved: " + str(exc)
        except Exception:
            # History is ancillary: never turn a successful snapshot into an
            # apparent failed query or conceal the original database error.
            logger.exception("Could not persist query history")
            return None, "Query history is temporarily unavailable. Your query result is still available."


def register_query_library_routes(router):
    @router.get("/query-library")
    def listing(request: Request, source_id: str | None = Query(None, max_length=64), dataset_id: str | None = Query(None, max_length=128),
                kind: Literal["saved", "history"] = "saved", offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        return QueryLibrary(request.app.state.runtime).list(source_id=source_id, dataset_id=dataset_id, kind=kind, offset=offset, limit=limit)

    @router.post("/query-library", status_code=201)
    def save(body: SaveQuery, request: Request):
        return QueryLibrary(request.app.state.runtime).save(body)

    @router.get("/query-library/{identifier}")
    def get(identifier: str, request: Request):
        return QueryLibrary(request.app.state.runtime).get(identifier)

    @router.put("/query-library/{identifier}")
    def update(identifier: str, body: SaveQuery, request: Request):
        return QueryLibrary(request.app.state.runtime).save(body, identifier)

    @router.delete("/query-library/{identifier}", status_code=204)
    def delete(identifier: str, request: Request, revision: int = Query(..., ge=1)):
        QueryLibrary(request.app.state.runtime).delete(identifier, revision)
