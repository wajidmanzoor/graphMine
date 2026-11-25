"""Complete typed query tables, owned snapshots, paging and streaming exports."""

import hashlib
import json
import math
import time
from contextlib import contextmanager
from typing import Literal

from fastapi import Query, Request
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json
from .analytics_exports import Budget, Writer, write_csv
from .export_streams import copy_chunks, prepare_download, temporary

FORMAT = "graphmine.table.v1"
MAX_COLUMNS = 256
MAX_ROWS = 100_000


def value_type(value):
    return "null" if value is None else {bool: "boolean", int: "integer", float: "number", str: "string", list: "array", dict: "object"}.get(type(value), "unsupported")


def validate_table(table):
    if not isinstance(table, dict) or table.get("format") != FORMAT or not isinstance(table.get("columns"), list) or not isinstance(table.get("rows"), list):
        raise AnalyticsError("Expected a typed GraphMine table artifact.", "table_format")
    columns, rows = table["columns"], table["rows"]
    if not 1 <= len(columns) <= MAX_COLUMNS or any(not isinstance(name, str) or not name for name in columns) or len(set(columns)) != len(columns):
        raise AnalyticsError("Tables require 1–256 unique, nonempty column names. Use explicit query aliases.", "table_format")
    if len(rows) > MAX_ROWS:
        raise AnalyticsError("Table exceeds the 100,000 row limit.", "resource_limit")
    names = set(columns)
    if any(not isinstance(row, dict) or set(row) != names for row in rows):
        raise AnalyticsError("Each table row must contain exactly its declared columns.", "table_format")
    pending = list(rows)
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise AnalyticsError("Table object keys must be text.", "table_format")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif value is not None and (type(value) not in (str, bool, int, float) or isinstance(value, float) and not math.isfinite(value)):
            raise AnalyticsError("Table cells must contain finite JSON values.", "table_format")
    return table


def summary(table):
    validate_table(table)
    columns = []
    for name in table["columns"]:
        types = {value_type(row[name]) for row in table["rows"]}
        nullable = "null" in types; types.discard("null")
        if types == {"integer", "number"}:
            types = {"number"}
        columns.append({"name": name, "type": next(iter(types)) if len(types) == 1 else "mixed" if types else "unknown", "nullable": nullable})
    return {"columns": columns, "row_count": len(table["rows"])}


def make_table(columns, rows):
    return validate_table({"format": FORMAT, "columns": list(columns), "rows": rows})


def projection_table(table):
    """Native projection applies explicit types to text cells, as for CSV.

    The immutable source retains exact JSON types. Null and empty text both
    become missing projection cells; nested cells become JSON text.
    """
    validate_table(table)
    def cell(value):
        return "" if value is None else value if isinstance(value, str) else _json(value)
    return {"columns": table["columns"], "rows": [{name: cell(row[name]) for name in table["columns"]} for row in table["rows"]]}


def _sort_key(value):
    kind = value_type(value)
    if kind == "boolean":
        return 0, value
    if kind in {"integer", "number"}:
        return 1, value
    if kind == "string":
        return 2, value
    # Objects and lists sort by canonical JSON, never by lossy string coercion.
    return 3, json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


class TableArtifacts:
    def __init__(self, runtime):
        self.runtime = runtime

    def load(self, identifier):
        from .query_previews import QueryPreviews

        metadata, raw = QueryPreviews(self.runtime).get(identifier, content=True)
        if metadata["kind"] != "table":
            raise AnalyticsError("This snapshot is not a table.", "table_kind")
        if len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise AnalyticsError("The saved table failed its integrity check.", "data_integrity", 409)
        return metadata, validate_table(json.loads(raw)), raw

    @contextmanager
    def indexed(self, identifier):
        from .database import RecordNotFound
        from .datasets import _owner
        from .result_index import add_port, open_index, table_index_path

        def source():
            # Read only small metadata and an automatically rotated change token.
            # Content updates invalidate a warm index even if its claimed hash is
            # unchanged; the rebuild verifies the actual bytes before serving it.
            with self.runtime.database._connect() as db:
                row = db.execute("""SELECT json_remove(p.metadata,'$.source'),r.token,p.expires_at
                    FROM query_previews p JOIN preview_blob_revisions r ON r.owner_id=p.owner_id AND r.sha256=p.sha256
                    WHERE p.id=? AND p.owner_id=?""", (identifier, _owner() or "")).fetchone()
                if row is not None:
                    if row[2] <= time.time():
                        raise AnalyticsError("This query preview expired. Run the query again.", "preview_expired", 410)
                else:
                    row = db.execute("SELECT metadata,token FROM dataset_summaries WHERE id=? AND owner_id IS ?", (identifier, _owner())).fetchone()
            if row is None:
                raise RecordNotFound("Dataset version not found")
            metadata = json.loads(row[0])
            if metadata["kind"] != "table":
                raise AnalyticsError("This snapshot is not a table.", "table_kind")
            return metadata, row[1]

        metadata, _ = source()
        def build(db):
            _, table, _ = self.load(identifier)
            add_port(db, "table", {"type": "table", "value": table["rows"]}, sort_key=_sort_key)
            return summary(table)
        def stamp():
            current, token = source()
            return [token, current["sha256"], current["size_bytes"], current["table"]]
        with open_index(table_index_path(self.runtime.database, identifier), stamp, build) as index:
            table_summary = json.loads(index.db.execute("SELECT value FROM meta WHERE key='header'").fetchone()[0])
            metadata, _ = source()
            yield metadata, table_summary, index

    def page(self, identifier, *, offset=0, limit=50, sort=None, direction="asc"):
        with self.indexed(identifier) as (metadata, table_summary, index):
            if sort is not None and sort not in [column["name"] for column in table_summary["columns"]]:
                raise AnalyticsError("Choose a sort column from this table.", "table_sort")
            page = index.page("table", offset, limit, sort=sort, descending=direction == "desc")
            return {**table_summary, "rows": page["items"], "offset": offset, "limit": limit,
                    "has_more": page["has_more"], "sort": sort, "direction": direction,
                    "complete": metadata["source_complete"], "sha256": metadata["sha256"]}

    def _copy_blob(self, identifier, metadata, output):
        from .database import RecordNotFound
        from .datasets import _owner

        with self.runtime.database._connect() as db:
            db.execute("BEGIN")
            table = "query_preview_blobs"
            row = db.execute("""SELECT b.rowid,length(b.content),p.expires_at FROM query_previews p
                JOIN query_preview_blobs b ON b.owner_id=p.owner_id AND b.sha256=p.sha256
                WHERE p.id=? AND p.owner_id=?""", (identifier, _owner() or "")).fetchone()
            if row is None:
                table = "dataset_versions"
                row = db.execute("SELECT rowid,length(content),NULL FROM dataset_versions WHERE id=? AND owner_id IS ?", (identifier, _owner())).fetchone()
            if row is None:
                raise RecordNotFound("Dataset version not found")
            if row[2] is not None and row[2] <= time.time():
                raise AnalyticsError("This query preview expired. Run the query again.", "preview_expired", 410)
            if row[1] != metadata["size_bytes"]:
                raise AnalyticsError("The saved table failed its integrity check.", "data_integrity", 409)
            limit = self.runtime.settings.analytics_max_input_bytes
            writer = Writer(output, Budget(limit))
            with db.blobopen(table, "content", row[0], readonly=True) as blob:
                copy_chunks(blob, writer, limit)
            if writer.digest.hexdigest() != metadata["sha256"]:
                raise AnalyticsError("The saved table failed its integrity check.", "data_integrity", 409)

    def export(self, identifier, format, *, sort=None, direction="asc"):
        output = temporary()
        try:
            with self.indexed(identifier) as (metadata, header, index):
                fields = [column["name"] for column in header["columns"]]
                if format == "csv":
                    if sort is not None and sort not in fields:
                        raise AnalyticsError("Choose a sort column from this table.", "table_sort")
                    limit = self.runtime.settings.analytics_max_input_bytes
                    writer = Writer(output, Budget(None if limit is None else 4 * limit))
                    write_csv(writer, index.rows("table", sort=sort, descending=direction == "desc"), fields, json_booleans=True)
                else:
                    self._copy_blob(identifier, metadata, output)
            return output
        except BaseException:
            output.close(); raise


def register_table_routes(router):
    @router.get("/database-query-snapshots/{identifier}/table")
    async def page(identifier: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                   sort: str | None = Query(None, max_length=20_000), direction: Literal["asc", "desc"] = "asc"):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Table reads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(TableArtifacts(runtime).page, identifier, offset=offset, limit=limit, sort=sort, direction=direction)

    @router.get("/database-query-snapshots/{identifier}/table/{format}")
    async def export(identifier: str, format: Literal["csv", "json"], request: Request,
                     sort: str | None = Query(None, max_length=20_000), direction: Literal["asc", "desc"] = "asc"):
        runtime = request.app.state.runtime
        return await prepare_download(runtime.analytics, TableArtifacts(runtime).export, identifier, format, sort=sort, direction=direction,
                                      filename=f"graphmine-query-table.{format}", media_type="text/csv; charset=utf-8" if format == "csv" else "application/json")
