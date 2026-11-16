"""Cypher result -> immutable dataset -> conversation, with SQL row lineage."""

from __future__ import annotations

import json
import math
import re
from time import perf_counter
from typing import Any, Literal

from fastapi import Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json, _key
from .database import RecordNotFound
from .database_sources import (
    RelationshipMapping,
    Strict,
    available,
    get_source,
    json_value,
    neo4j_session,
    stable_id,
    validate_cypher,
)
from .datasets import DatasetLibrary
from .benchmark_mappings import resolve_source
from .models import SessionRecord, utc_now
from .query_previews import QueryPreviews
from .database_job_context import begin_commit, checkpoint


class CypherRequest(Strict):
    statement: str = Field(min_length=1, max_length=20_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=160)
    directed: bool = True
    dataset_id: str | None = Field(default=None, max_length=128)
    projection: Literal["elements", "rows"] = "elements"
    weight_property: str | None = Field(default=None, min_length=1, max_length=128)


class OpenChat(Strict):
    title: str | None = Field(default=None, max_length=200)
    domain_id: str = Field(default="general", min_length=1, max_length=128)


class GraphCollector:
    """Extract actual driver graph values; scalar maps cannot impersonate nodes."""

    def __init__(self, source, byte_limit, weight_property=None):
        self.source, self.byte_limit = source, byte_limit
        self.weight_property = weight_property
        self.mapping_hash = source.fingerprint()
        self.vertices, self.edges = {}, {}
        self.lineage = {"vertices": {}, "edges": {}}
        self.node_refs, self.edge_refs = {}, {}
        self.node_ids, self.vertex_owners, self.edge_owners = {}, {}, {}
        self.edge_ids = {}
        self.used = 0

    def _identity(self, value, kind):
        if self.source._catalog.get("registry"):
            # An element ID belongs to one database; no SQL lineage is inferred.
            return f"neo4j:{self.source._catalog['id']}:{value.element_id}"
        props = dict(value)
        identity = props.get("gm_id")
        if type(identity) not in (str, int) or identity == "":
            identity = f"neo4j:{value.element_id}"
        if not self.source._catalog and props.get("gm_source") == self.source.id and props.get("gm_mapping"):
            mapping = self.source.mapping(props["gm_mapping"])
            try:
                keys = json.loads(props["gm_key"])
                if (
                    not isinstance(keys, list)
                    or len(keys) != len(mapping.key)
                    or any(type(x) not in (str, int, float, bool) for x in keys)
                ):
                    raise ValueError
            except (ValueError, TypeError, KeyError) as exc:
                raise AnalyticsError(
                    "A graph element has invalid source lineage.", "database_mapping"
                ) from exc
            if (
                isinstance(mapping, RelationshipMapping) != (kind == "edges")
                or stable_id(self.source, mapping, keys) != identity
            ):
                raise AnalyticsError(
                    "A graph element has inconsistent source identity.",
                    "database_mapping",
                )
            if props.get("gm_mapping_hash") != self.mapping_hash:
                raise AnalyticsError(
                    "Refresh the mapped graph after changing its source configuration.",
                    "source_changed",
                    409,
                )
            self.lineage[kind][_key(identity)] = {"mapping": mapping.id, "keys": keys}
        return identity

    def _put(self, collection, identity, document, element_id):
        key = _key(identity)
        owners = self.vertex_owners if collection is self.vertices else self.edge_owners
        if key in collection:
            if owners[key] != element_id:
                raise AnalyticsError(
                    "Graph elements have conflicting application IDs.",
                    "database_mapping",
                )
            self.used -= len(_json(collection[key]).encode())
        self.used += len(_json(document).encode())
        if (
            self.used > self.byte_limit
            or key not in collection
            and len(self.vertices) + len(self.edges) >= self.source.max_rows
        ):
            raise AnalyticsError(
                "Query graph exceeds the input limit. Narrow the Cypher query.",
                "resource_limit",
            )
        collection[key] = document
        owners[key] = element_id

    def node(self, value):
        previous = self.node_refs.get(value.element_id)
        if not dict(value) and not value.labels and previous is not None:
            value = previous
        self.node_refs[value.element_id] = value
        identity = self._identity(value, "vertices")
        old_id = self.node_ids.get(value.element_id)
        if old_id is not None and old_id != identity:
            old = self.vertices.pop(_key(old_id))
            self.vertex_owners.pop(_key(old_id))
            self.used -= len(_json(old).encode())
        self.node_ids[value.element_id] = identity
        properties = {
            k: json_value(v) for k, v in dict(value).items() if not k.startswith("gm_")
        }
        labels = sorted(value.labels)
        document = {
            "id": identity,
            "attributes": {**properties, "neo4j_labels": labels},
        }
        if labels:
            document["type"] = next((label for label in labels if not label.startswith("GM_")), labels[0])
        if value.get("gm_display") is not None:
            document["label"] = str(value["gm_display"])
        elif any(value.get(key) for key in ("name", "title", "firstName")):
            document["label"] = str(next(value[key] for key in ("name", "title", "firstName") if value.get(key)))
        else:
            for key in ("userId", "user_id", "id"):
                if value.get(key) is not None:
                    document["label"] = f"{document.get('type', 'Node')} {value[key]}"
                    break
        self._put(self.vertices, identity, document, value.element_id)
        return identity

    def relationship(self, value):
        weight = value.get(self.weight_property) if self.weight_property else value.get("gm_weight", value.get("weight"))
        if self.weight_property and (type(weight) not in (int, float) or not math.isfinite(weight)):
            raise AnalyticsError(
                f"Every returned relationship must have a finite numeric '{self.weight_property}' weight. Filter missing values or choose another property.",
                "database_value",
            )
        self.edge_refs[value.element_id] = value
        identity = self._identity(value, "edges")
        old_id = self.edge_ids.get(value.element_id)
        if old_id is not None and old_id != identity:
            old = self.edges.pop(_key(old_id))
            self.edge_owners.pop(_key(old_id))
            self.used -= len(_json(old).encode())
        self.edge_ids[value.element_id] = identity
        properties = {
            k: json_value(v) for k, v in dict(value).items() if not k.startswith("gm_")
        }
        document = {
            "id": identity,
            "source": self.node(value.start_node),
            "target": self.node(value.end_node),
            "type": value.type,
            "attributes": properties,
        }
        if weight is not None:
            if type(weight) not in (int, float) or not math.isfinite(weight):
                raise AnalyticsError(
                    "Relationship weights must be finite numbers.", "database_value"
                )
            document["weight"] = weight
        timestamp = value.get("gm_timestamp")
        if timestamp is not None:
            document["timestamp"] = json_value(timestamp)
        self._put(self.edges, identity, document, value.element_id)
        return identity

    def hydrate_endpoints(self, transaction):
        # RETURN r gives endpoint stubs. Resolve just these nodes within the
        # same transaction, where Neo4j element IDs are valid references.
        missing = [
            key for key, n in self.node_refs.items() if not dict(n) and not n.labels
        ]
        for offset in range(0, len(missing), 500):
            expected = set(missing[offset : offset + 500])
            response = transaction.run(
                "MATCH (n) WHERE elementId(n) IN $ids RETURN n", ids=list(expected)
            )
            for record in response:
                self.node(record["n"])
                expected.discard(record["n"].element_id)
            response.consume()
            if expected:
                raise AnalyticsError(
                    "An endpoint changed during the query. Run the query again.",
                    "source_changed",
                    409,
                )
        # A later record can hydrate a driver object from an earlier record.
        for value in list(self.node_refs.values()):
            self.node(value)
        for value in list(self.edge_refs.values()):
            self.relationship(value)

    def collect(self, value):
        from neo4j.graph import Node, Path, Relationship

        if isinstance(value, Node):
            return {"node": self.node(value)}
        if isinstance(value, Relationship):
            return {"relationship": self.relationship(value)}
        if isinstance(value, Path):
            return {
                "vertices": [self.node(n) for n in value.nodes],
                "edges": [self.relationship(e) for e in value.relationships],
            }
        if isinstance(value, (list, tuple)):
            return [self.collect(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self.collect(v) for k, v in value.items()}
        return json_value(value)

    def graph(self):
        return {
            "graph": {
                "id": self.source.id,
                "directed": True,
                "allows_self_loops": True,
                "allows_parallel_edges": True,
            },
            "vertices": list(self.vertices.values()),
            "edges": list(self.edges.values()),
        }

    def record(self, value, row_number):
        return {key: self.collect(value[key]) for key in value.keys()}


class RowGraphCollector(GraphCollector):
    """Create snapshot edges between real nodes returned as source and target."""

    def record(self, value, row_number):
        from neo4j.graph import Node

        if not {"source", "target"}.issubset(value.keys()):
            raise AnalyticsError(
                "Return nodes as source and target, for example "
                "RETURN a AS source, b AS target, count(*) AS weight.",
                "query_projection",
            )
        if not all(isinstance(value[key], Node) for key in ("source", "target")):
            raise AnalyticsError(
                f"Row {row_number}: source and target must be nodes, not IDs, maps or null. "
                "Return a AS source and b AS target.",
                "query_projection",
            )
        edge_type = value["type"] if "type" in value.keys() else "DERIVED"
        if not isinstance(edge_type, str) or not edge_type.strip():
            raise AnalyticsError(
                f"Row {row_number}: type must be a nonempty string.",
                "query_projection",
            )
        if "weight" in value.keys() and (
            type(value["weight"]) not in (int, float)
            or not math.isfinite(value["weight"])
        ):
            raise AnalyticsError(
                f"Row {row_number}: weight must be a finite number.",
                "query_projection",
            )
        properties = {
            key: json_value(value[key])
            for key in value.keys() if key not in {"source", "target"}
        }
        source, target = (self.node(value[key]) for key in ("source", "target"))
        identity = f"query-edge:{row_number}"
        edge = {
            "id": identity,
            "source": source,
            "target": target,
            "type": edge_type,
            "attributes": properties,
        }
        if "weight" in properties:
            edge["weight"] = properties["weight"]
        # Derived edges have snapshot identity, never a SQL row mapping.
        self._put(self.edges, identity, edge, identity)
        return {"source": {"node": source}, "target": {"node": target}, **properties}


def execute_query(source, body, byte_limit):
    checkpoint("validating")
    validate_cypher(body.statement)
    if body.weight_property and body.projection == "rows":
        raise AnalyticsError("For source/target rows, return the edge weight as the weight column.", "query_projection")
    try:
        parameter_bytes = len(_json(body.parameters).encode())
    except (TypeError, ValueError, OverflowError) as error:
        raise AnalyticsError("Query parameters must contain finite JSON values.", "cypher_parameters") from error
    if parameter_bytes > 256 * 1024:
        raise AnalyticsError(
            "Query parameters exceed the byte limit.", "resource_limit"
        )
    byte_limit = min(byte_limit, source.max_bytes)
    collector_class = RowGraphCollector if body.projection == "rows" else GraphCollector
    collector, sample_records, rows, used = collector_class(source, byte_limit, body.weight_property), [], 0, 0
    scalar_rows = []
    try:
        with (
            neo4j_session(source) as session,
            session.begin_transaction(timeout=source.timeout_seconds) as transaction,
        ):
            explanation = transaction.run(
                "EXPLAIN " + body.statement, body.parameters
            ).consume()
            if explanation.query_type != "r":
                raise AnalyticsError(
                    "This editor accepts read queries only.", "cypher_read_only"
                )
            response = transaction.run(body.statement, body.parameters)
            checkpoint("reading", 0)
            columns = list(response.keys())
            if body.projection == "rows" and not {"source", "target"}.issubset(columns):
                raise AnalyticsError(
                    "Source / target columns mode requires RETURN a AS source, b AS target. "
                    "Return nodes for both columns; weight and type are optional.",
                    "query_projection",
                )
            for record in response:
                rows += 1
                checkpoint("reading", rows)
                if rows > source.max_rows:
                    raise AnalyticsError(
                        "Query exceeds the row limit. Add a filter or an explicit LIMIT.",
                        "resource_limit",
                    )
                item = collector.record(record, rows)
                used += len(_json(item).encode())
                if used > byte_limit:
                    raise AnalyticsError(
                        "Query exceeds the result byte limit.", "resource_limit"
                    )
                if len(sample_records) < 50:
                    sample_records.append((rows, record))
                if collector.vertices or collector.edges:
                    scalar_rows = None
                elif scalar_rows is not None:
                    scalar_rows.append(item)
            response.consume()
            checkpoint("hydrating", rows)
            collector.hydrate_endpoints(transaction)
            sample = [
                collector.record(record, row_number)
                for row_number, record in sample_records
            ]
            # A read editor has no writes to commit.
            transaction.rollback()
    except AnalyticsError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "") or ""
        if "SyntaxError" in code:
            message = str(getattr(exc, "message", "Invalid Cypher syntax"))[:1500]
            position = re.search(r"line (\d+), column (\d+) \(offset: (\d+)\)", message)
            raise AnalyticsError(
                message,
                "cypher_syntax",
                details={key: int(value) for key, value in zip(("line", "column", "offset"), position.groups())} if position else None,
            ) from exc
        if "ParameterMissing" in code:
            raise AnalyticsError(
                "Missing query parameters. Expand Parameters and supply a JSON value "
                "for each $parameter used in the query.",
                "cypher_parameters",
            ) from exc
        raise AnalyticsError(
            "Neo4j could not complete the query. Check the connection, schema and query parameters.",
            "database_query",
            502,
        ) from exc
    graph = collector.graph()
    graph["graph"]["directed"] = body.directed
    table = None
    if scalar_rows is not None and columns:
        from .table_artifacts import make_table

        table = make_table(columns, scalar_rows)
        if len(_json(table).encode()) > byte_limit:
            raise AnalyticsError("Query table exceeds the result byte limit.", "resource_limit")
    return graph, collector.lineage, sample, rows, table


def run_query(runtime, source_id, body):
    from .query_library import QueryLibrary

    # Do not retain attempts against connections the current owner cannot see.
    get_source(runtime.settings, source_id)
    library, started = QueryLibrary(runtime), perf_counter()
    try:
        result = _run_query(runtime, source_id, body)
    except AnalyticsError as error:
        library.record(source_id, body, error={"code": error.code, "message": str(error)}, elapsed_ms=round((perf_counter() - started) * 1000))
        raise
    identifier, warning = library.record(source_id, body, result=result, elapsed_ms=result["elapsed_ms"])
    result.update(history_id=identifier, history_warning=warning)
    return result


def _run_query(runtime, source_id, body):
    started = perf_counter()
    source = get_source(runtime.settings, source_id)
    dataset = None
    if body.dataset_id or source._catalog.get("registry"):
        from .database_datasets import selected_dataset

        dataset = selected_dataset(runtime.settings, source, body.dataset_id or source._catalog["id"])
        source = resolve_source(runtime.settings, source, dataset["id"])
    limit = min(
        runtime.settings.analytics_max_input_bytes,
        runtime.settings.account_upload_bytes,
    )
    graph, lineage, sample, rows, table = execute_query(source, body, limit)
    checkpoint("validating", rows)
    if source.fingerprint() != resolve_source(runtime.settings, get_source(runtime.settings, source_id), body.dataset_id).fingerprint():
        raise AnalyticsError(
            "Source settings changed. Run the query again.", "source_changed", 409
        )
    metadata = table_metadata = None
    provenance = {
        "type": "database_query",
        "database_dataset": {key: dataset[key] for key in ("id", "name", "registry", "workload_url", "load_finished_at", "load_seconds", "script_hashes")
                             if key in dataset} if dataset else None,
        "database_source": {"id": source.id, "name": source.name, "mapping_hash": source.fingerprint(), "revision": source.revision,
                            "capabilities": source.capabilities()},
        "query": body.statement, "parameters": body.parameters, "projection": body.projection,
        "weight_property": body.weight_property, "fetched_at": utc_now().isoformat(), "lineage": lineage, "row_count": rows,
        "scope": "exact returned table rows" if table is not None else "one derived edge per returned source/target row" if body.projection == "rows" else "exact returned graph elements and relationship endpoints",
    }
    name = body.name or (dataset["name"] if dataset else source.name)
    begin_commit("saving")
    if graph["vertices"]:
        metadata = QueryPreviews(runtime).store(
            graph,
            name=name,
            kind="graph",
            complete=True,
            source=provenance,
        )
    elif table is not None:
        table_metadata = QueryPreviews(runtime).store(table, name=name, kind="table", complete=True, source=provenance)
    shown = graph["vertices"][:100]
    keys = {_key(v["id"]) for v in shown}
    edges = [
        e
        for e in graph["edges"]
        if _key(e["source"]) in keys and _key(e["target"]) in keys
    ][:300]
    return {
        "dataset": metadata,
        "table": table_metadata,
        "row_count": rows,
        "rows": sample,
        "rows_truncated": rows > len(sample),
        "graph": {**graph, "vertices": shown, "edges": edges},
        "vertex_count": len(graph["vertices"]),
        "edge_count": len(graph["edges"]),
        "elapsed_ms": round((perf_counter() - started) * 1000),
        "message": "Graph preview ready. Save it or use it in chat within 24 hours."
        if metadata
        else (
            (f"{rows:,} rows saved in a temporary table. Browse, export, save, or map its columns for analysis." if rows else "No rows matched. The empty table retains the query's column names for inspection and export.")
            if table_metadata else
            "No rows matched. Check the selected connection, labels, filters and parameter values."
        ),
    }


def open_chat(runtime, version_id, body):
    library = DatasetLibrary(runtime)
    metadata = QueryPreviews(runtime).get(version_id)
    source_id = metadata.get("source", {}).get("database_source", {}).get("id")
    if not source_id:
        raise RecordNotFound("Database query snapshot not found")
    get_source(runtime.settings, source_id)
    runtime.catalog.domain(body.domain_id)
    session = runtime.database.create_session(
        SessionRecord(domain_id=body.domain_id, title=body.title or metadata["name"])
    )
    try:
        imported = library.import_into(version_id, session.id)
    except Exception:
        from .api import remove_session

        remove_session(runtime, session.id)
        raise
    return {"session": session.model_dump(mode="json"), **imported}


def register_database_query_routes(router):
    from .database_connections import register_connection_routes
    from .benchmark_datasets import register_benchmark_routes
    from .database_datasets import register_dataset_routes
    from .graph_builder import register_builder_routes
    from .query_library import register_query_library_routes
    from .table_artifacts import register_table_routes

    register_connection_routes(router)
    register_benchmark_routes(router)
    register_dataset_routes(router)
    register_builder_routes(router)
    register_query_library_routes(router)
    register_table_routes(router)
    @router.get("/database-sources")
    def sources(request: Request):
        return [
            source.public() for source in available(request.app.state.runtime.settings)
        ]

    @router.get("/database-sources/{source_id}")
    def source_schema(source_id: str, request: Request):
        return get_source(request.app.state.runtime.settings, source_id).public()

    @router.post("/database-sources/{source_id}/queries", status_code=201)
    async def query(source_id: str, body: CypherRequest, request: Request):
        runtime = request.app.state.runtime
        if "respond-async" in request.headers.get("Prefer", "").lower():
            from .database_jobs import accepted

            job = await run_in_threadpool(runtime.database_jobs.enqueue, "query", source_id, body, request_key=request.headers.get("Idempotency-Key"))
            return accepted(job)
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database reads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(run_query, runtime, source_id, body)

    @router.post("/database-query-snapshots/{version_id}/chat", status_code=201)
    async def chat(version_id: str, body: OpenChat, request: Request):
        runtime = request.app.state.runtime
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database reads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(open_chat, runtime, version_id, body)

    @router.post("/database-query-snapshots/{version_id}/save")
    async def save_preview(version_id: str, request: Request):
        return await run_in_threadpool(QueryPreviews(request.app.state.runtime).promote, version_id)

    @router.delete("/database-query-snapshots/{version_id}", status_code=204)
    async def discard_preview(version_id: str, request: Request):
        await run_in_threadpool(QueryPreviews(request.app.state.runtime).discard, version_id)
