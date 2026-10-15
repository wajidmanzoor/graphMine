"""Read-only, operator-configured SQLite and REST imports into dataset versions."""

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from . import managed_connectors as managed
from .analytics import AnalyticsError, _json
from .csv_ingestion import MAX_CELLS, MAX_ROWS, graph_from_table, read_table
from .database import RecordNotFound
from .datasets import DatasetLibrary
from .identity import AccountError, current_principal
from .models import utc_now


class Connector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=160)
    type: Literal["sqlite", "rest", "neo4j"]
    users: list[str] = Field(min_length=1, max_length=100)
    path: str | None = None
    table: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    format: Literal["json_rows", "graph", "csv"] = "json_rows"
    rows_field: str | None = None
    source_column: str = "source"
    target_column: str = "target"
    directed: bool = False
    complete_response: bool = False
    managed: bool = False
    database: str = "neo4j"
    username: str = "neo4j"
    node_label: str | None = None
    relationship_type: str | None = None


class ImportConnector(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    dataset_id: str | None = None
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def configured(settings):
    if settings.connectors_file is None:
        return []
    try:
        path = settings.connectors_file
        info = path.stat()
        if (
            not path.is_file()
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 1024 * 1024
        ):
            raise ValueError("private configuration required")
        value = json.loads(path.read_text())
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("invalid inventory")
        entries = [Connector.model_validate(row) for row in value]
        if len({entry.id for entry in entries}) != len(entries):
            raise ValueError("duplicate connector")
        return entries
    except (OSError, ValueError) as exc:
        raise AnalyticsError(
            "The connector configuration is unavailable. Ask the administrator to check it.",
            "connector_configuration",
            503,
        ) from exc


def available(runtime):
    user = current_principal.get()
    if user is None:
        return []
    return [
        entry for entry in configured(runtime.settings) if user.username in entry.users
    ] + managed.records(runtime)


def get(runtime, connector_id):
    entry = next(
        (entry for entry in available(runtime) if entry.id == connector_id), None
    )
    if entry is None:
        raise RecordNotFound("Connector not found")
    return entry


def rows_graph(rows, config, limit):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise AnalyticsError(
            "The source must contain between 1 and 100,000 rows.", "connector_input"
        )
    if not all(isinstance(row, dict) for row in rows):
        raise AnalyticsError("Each source row must be a record.", "connector_input")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    if (
        len(columns) > 64
        or len(columns) * len(rows) > MAX_CELLS
        or any(not isinstance(c, str) or not c for c in columns)
    ):
        raise AnalyticsError(
            "The source exceeds the column or cell limit.", "resource_limit"
        )
    raw = _json(rows).encode()
    if len(raw) > limit:
        raise AnalyticsError(
            "The source exceeds the input byte limit.", "resource_limit"
        )
    converted = []
    for row in rows:
        cells = {}
        for column in columns:
            value = row.get(column)
            if value is not None and (
                type(value) not in (str, int, float, bool)
                or isinstance(value, float)
                and not math.isfinite(value)
            ):
                raise AnalyticsError(
                    "Source cells must be finite scalar values.", "connector_input"
                )
            cells[column] = (
                value
                if column in (config.source_column, config.target_column)
                else ""
                if value is None
                else str(value)
            )
        converted.append(cells)
    return {"columns": columns, "rows": converted}, hashlib.sha256(raw).hexdigest()


def sqlite_rows(config, limit):
    if not config.path or not config.table:
        raise ValueError("missing source configuration")
    path = Path(config.path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("source not available")
    started = time.monotonic()
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(limit, 1024 * 1024))
        connection.set_progress_handler(
            lambda: int(time.monotonic() - started > 15), 1000
        )
        connection.execute("BEGIN")
        kind = connection.execute(
            "SELECT type,sql FROM sqlite_schema WHERE name=?", (config.table,)
        ).fetchone()
        if (
            kind is None
            or kind[0] != "table"
            or not kind[1]
            or "VIRTUAL TABLE" in kind[1].upper()
        ):
            raise ValueError("only regular tables can be imported")
        quoted = '"' + config.table.replace('"', '""') + '"'
        query = connection.execute(f"SELECT * FROM {quoted} LIMIT ?", (MAX_ROWS + 1,))
        columns = [column[0] for column in query.description]
        rows, used = [], 0
        if not columns or len(columns) > 64:
            raise AnalyticsError(
                "The source exceeds the column limit.", "resource_limit"
            )
        for record in query:
            row = dict(zip(columns, record, strict=True))
            used += len(_json(row).encode())
            if (
                used > limit
                or len(rows) >= MAX_ROWS
                or (len(rows) + 1) * len(columns) > MAX_CELLS
            ):
                raise AnalyticsError(
                    "The source exceeds the row, cell or byte limit; no partial import was saved.",
                    "resource_limit",
                )
            rows.append(row)
    return rows


def rest_bytes(config, limit, *, settings=None, payload=None):
    parts = urlsplit(config.url or "")
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.fragment
    ):
        raise ValueError("unsupported endpoint configuration")
    data = bytearray()
    started = time.monotonic()
    url, headers, extensions = config.url, dict(config.headers), {}
    if config.managed:
        url, host, server_name = managed.network_target(settings, config.url)
        headers["Host"] = host
        extensions["sni_hostname"] = server_name
    headers["Accept-Encoding"] = "identity"
    headers.setdefault(
        "Accept",
        "text/csv"
        if config.format == "csv" and payload is None
        else "application/json",
    )
    with (
        httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client,
        client.stream(
            "POST" if payload is not None else "GET",
            url,
            headers=headers,
            extensions=extensions,
            **({"json": payload} if payload is not None else {}),
        ) as response,
    ):
        if (
            response.status_code not in ({200, 202} if payload is not None else {200})
            or response.headers.get("content-encoding", "identity") != "identity"
        ):
            raise AnalyticsError(
                "The configured source must return a successful uncompressed response.",
                "connector_upstream",
                502,
            )
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > limit or time.monotonic() - started > 30:
                raise AnalyticsError(
                    "The source exceeds the time or byte limit; no partial import was saved.",
                    "resource_limit",
                )
            data.extend(chunk)
    return bytes(data)


def neo4j_rows(runtime, config, limit):
    # Only this parameterized read query is exposed, never user-provided Cypher.
    # It exports relationships and their endpoints, not isolated database nodes.
    statement = (
        "MATCH (a)-[r]->(b) "
        "WHERE ($label IS NULL OR $label IN labels(a)) "
        "AND ($relationship_type IS NULL OR type(r) = $relationship_type) "
        "RETURN elementId(a) AS source, elementId(b) AS target, "
        "type(r) AS relationship, elementId(r) AS relationship_id "
        "ORDER BY relationship_id LIMIT $limit"
    )
    url = (config.url or "").rstrip("/") + f"/db/{config.database}/query/v2"
    raw = rest_bytes(
        config.model_copy(update={"url": url}),
        limit,
        settings=runtime.settings,
        payload={
            "statement": statement,
            "accessMode": "Read",
            "parameters": {
                "label": config.node_label or None,
                "relationship_type": config.relationship_type or None,
                "limit": MAX_ROWS + 1,
            },
        },
    )
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or value.get("errors")
        or value.get("queryType", "r") != "r"
    ):
        raise AnalyticsError(
            "Neo4j could not complete the relationship read. Check the database and read permissions.",
            "connector_upstream",
            502,
        )
    data = value.get("data", {})
    if not isinstance(data, dict):
        raise TypeError("unexpected Neo4j data")
    fields, values = data.get("fields"), data.get("values")
    expected = ["source", "target", "relationship", "relationship_id"]
    if (
        fields != expected
        or not isinstance(values, list)
        or any(not isinstance(row, list) or len(row) != len(expected) for row in values)
    ):
        raise ValueError("unexpected Neo4j response")
    return [dict(zip(fields, row, strict=True)) for row in values]


def fetch(runtime, config):
    limit = min(
        runtime.settings.analytics_max_input_bytes,
        runtime.settings.account_upload_bytes,
    )
    try:
        typed = True
        if config.type == "sqlite":
            if config.managed:
                _, content = managed.saved(runtime, config.id)
                with managed.sqlite_file(content) as path:
                    rows = sqlite_rows(
                        config.model_copy(update={"path": str(path)}), limit
                    )
            else:
                rows = sqlite_rows(config, limit)
            table, digest = rows_graph(rows, config, limit)
            complete = True
        elif config.type == "neo4j":
            table, digest = rows_graph(
                neo4j_rows(runtime, config, limit), config, limit
            )
            complete = True
        else:
            raw = rest_bytes(config, limit, settings=runtime.settings)
            digest = hashlib.sha256(raw).hexdigest()
            complete = config.complete_response
            if config.format == "csv":
                with tempfile.TemporaryDirectory(
                    prefix="graphmine-connector-"
                ) as temporary:
                    path = Path(temporary) / "source.csv"
                    path.write_bytes(raw)
                    table = read_table(path)
                typed = False
            else:
                value = json.loads(raw)
                if isinstance(value, dict) and (
                    value.get("has_more")
                    or value.get("next")
                    or value.get("next_cursor")
                    or value.get("complete") is False
                ):
                    raise AnalyticsError(
                        "The source reports another page or incomplete output. Configure a complete export endpoint.",
                        "connector_incomplete",
                    )
                if config.format == "graph":
                    runtime.graph_store._validate_graph(value)
                    return value, digest, complete
                rows = (
                    value.get(config.rows_field)
                    if config.rows_field and isinstance(value, dict)
                    else value
                )
                table, _ = rows_graph(rows, config, limit)
        graph = graph_from_table(
            table,
            directed=config.directed,
            source_column=config.source_column,
            target_column=config.target_column,
            name=config.id,
            digest=digest,
            typed_endpoints=typed,
        )
        runtime.graph_store._validate_graph(graph)
        return graph, digest, complete
    except AnalyticsError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        OverflowError,
        sqlite3.Error,
        httpx.HTTPError,
    ) as exc:
        # The exception may contain database paths, endpoints or auth headers.
        raise AnalyticsError(
            "The configured source could not be read as a valid graph. Check its availability, mapping and input limits.",
            "connector_input",
            422,
        ) from exc


def preview(runtime, connector_id):
    config = get(runtime, connector_id)
    graph, digest, complete = fetch(runtime, config)
    if get(runtime, connector_id) != config:
        raise AnalyticsError(
            "The connector configuration changed. Preview again.", "source_changed", 409
        )
    raw = _json(graph).encode()
    if len(raw) > runtime.settings.analytics_max_input_bytes:
        raise AnalyticsError(
            "The graph exceeds the input byte limit.", "resource_limit"
        )
    return {
        "name": config.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": digest,
        "source_complete": complete,
        "source_scope": "matching relationships and their endpoints; isolated nodes are excluded"
        if config.type == "neo4j"
        else "uploaded SQLite snapshot"
        if config.type == "sqlite" and config.managed
        else "configured table"
        if config.type == "sqlite"
        else "one API response",
        "metadata": runtime.graph_store._metadata("preview", graph).model_dump(
            mode="json"
        ),
        "vertices": graph["vertices"][:20],
        "edges": graph["edges"][:20],
    }


def import_source(runtime, connector_id, body):
    config = get(runtime, connector_id)
    graph, digest, complete = fetch(runtime, config)
    if get(runtime, connector_id) != config:
        raise AnalyticsError(
            "The connector configuration changed. Preview again.", "source_changed", 409
        )
    if hashlib.sha256(_json(graph).encode()).hexdigest() != body.expected_sha256:
        raise AnalyticsError(
            "The source changed after preview. Preview it again before importing.",
            "source_changed",
            409,
        )
    return DatasetLibrary(runtime).store(
        graph,
        name=body.name,
        kind="graph",
        complete=complete,
        dataset_id=body.dataset_id,
        source={
            "type": "connector",
            "connector_id": config.id,
            "connector_name": config.name,
            "connector_type": config.type,
            "fetched_at": utc_now().isoformat(),
            "source_sha256": digest,
            "scope": "matching relationships and their endpoints; isolated nodes excluded"
            if config.type == "neo4j"
            else "uploaded SQLite snapshot"
            if config.type == "sqlite" and config.managed
            else "complete configured table"
            if config.type == "sqlite"
            else "single configured API response",
            "mapping": {
                "source_column": config.source_column,
                "target_column": config.target_column,
                "directed": config.directed,
            },
        },
    )


def register_connector_routes(router):
    @router.get("/connectors")
    def list_connectors(request: Request):
        return [
            {
                "id": entry.id,
                "name": entry.name,
                "type": entry.type,
                **({"managed": True} if entry.managed else {}),
            }
            for entry in available(request.app.state.runtime)
        ]

    async def run(request, function, *args):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AccountError("Imports are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(function, runtime, *args)

    @router.post("/connectors", status_code=201)
    async def create_connection(body: managed.ConnectionSettings, request: Request):
        return await run(request, managed.save, body)

    @router.post("/connectors/sqlite", status_code=201)
    async def upload_database(file: UploadFile, request: Request):
        runtime = request.app.state.runtime
        user = managed.principal()
        limit = min(
            runtime.settings.max_upload_bytes,
            runtime.settings.account_upload_bytes,
            user.accounts.upload_remaining(user.user_id),
        )
        if runtime.upload_slots.locked():
            raise AccountError("Imports are busy. Retry shortly.", "busy", 429)
        try:
            async with runtime.upload_slots:
                content = await file.read(limit + 1)
                if len(content) > limit:
                    raise AccountError(
                        "The database exceeds your upload or storage limit.",
                        "request_too_large",
                        413,
                    )
                return await run_in_threadpool(
                    managed.upload_sqlite,
                    runtime,
                    file.filename or "SQLite database",
                    content,
                )
        finally:
            await file.close()

    @router.get("/connectors/{connector_id}")
    def connection_details(connector_id: str, request: Request):
        return managed.detail(request.app.state.runtime, connector_id)

    @router.put("/connectors/{connector_id}")
    async def update_connection(
        connector_id: str, body: managed.ConnectionSettings, request: Request
    ):
        return await run(request, managed.save, body, connector_id)

    @router.delete("/connectors/{connector_id}", status_code=204)
    def delete_connection(connector_id: str, request: Request):
        managed.delete(request.app.state.runtime, connector_id)

    @router.post("/connectors/{connector_id}/preview")
    async def preview_connector(connector_id: str, request: Request):
        return await run(request, preview, connector_id)

    @router.post("/connectors/{connector_id}/import", status_code=201)
    async def import_connector(
        connector_id: str, body: ImportConnector, request: Request
    ):
        return await run(request, import_source, connector_id, body)
