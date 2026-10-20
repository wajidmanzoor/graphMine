"""Cypher result -> immutable dataset -> conversation, with SQL row lineage."""

from __future__ import annotations

import json
import math
from typing import Any

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
from .models import SessionRecord, utc_now


class CypherRequest(Strict):
    statement: str = Field(min_length=1, max_length=20_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=160)
    directed: bool = True


class OpenChat(Strict):
    title: str | None = Field(default=None, max_length=200)


class GraphCollector:
    """Extract actual driver graph values; scalar maps cannot impersonate nodes."""

    def __init__(self, source, byte_limit):
        self.source, self.byte_limit = source, byte_limit
        self.mapping_hash = source.fingerprint()
        self.vertices, self.edges = {}, {}
        self.lineage = {"vertices": {}, "edges": {}}
        self.node_refs, self.edge_refs = {}, {}
        self.node_ids, self.vertex_owners, self.edge_owners = {}, {}, {}
        self.used = 0

    def _identity(self, value, kind):
        props = dict(value)
        identity = props.get("gm_id")
        if type(identity) not in (str, int) or identity == "":
            identity = f"neo4j:{value.element_id}"
        if props.get("gm_source") == self.source.id and props.get("gm_mapping"):
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
            document["type"] = labels[0]
        if value.get("gm_display") is not None:
            document["label"] = str(value["gm_display"])
        self._put(self.vertices, identity, document, value.element_id)
        return identity

    def relationship(self, value):
        self.edge_refs[value.element_id] = value
        identity = self._identity(value, "edges")
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
        weight = value.get("gm_weight", value.get("weight"))
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


def execute_query(source, body, byte_limit):
    validate_cypher(body.statement)
    if len(_json(body.parameters).encode()) > 256 * 1024:
        raise AnalyticsError(
            "Query parameters exceed the byte limit.", "resource_limit"
        )
    byte_limit = min(byte_limit, source.max_bytes)
    collector, sample_records, rows, used = GraphCollector(source, byte_limit), [], 0, 0
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
            for record in response:
                rows += 1
                if rows > source.max_rows:
                    raise AnalyticsError(
                        "Query exceeds the row limit. Add a filter or an explicit LIMIT.",
                        "resource_limit",
                    )
                item = {
                    key: collector.collect(record[key])
                    for key in record.keys()  # noqa: SIM118 - Neo4j records iterate over values.
                }
                used += len(_json(item).encode())
                if used > byte_limit:
                    raise AnalyticsError(
                        "Query exceeds the result byte limit.", "resource_limit"
                    )
                if len(sample_records) < 50:
                    sample_records.append(record)
            response.consume()
            collector.hydrate_endpoints(transaction)
            sample = [
                {key: collector.collect(record[key]) for key in record.keys()}  # noqa: SIM118 - Neo4j records iterate over values.
                for record in sample_records
            ]
            # A read editor has no writes to commit.
            transaction.rollback()
    except AnalyticsError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "") or ""
        if "SyntaxError" in code:
            raise AnalyticsError(
                str(getattr(exc, "message", "Invalid Cypher syntax"))[:1500],
                "cypher_syntax",
            ) from exc
        raise AnalyticsError(
            "Neo4j could not complete the query. Check the connection, schema and query parameters.",
            "database_query",
            502,
        ) from exc
    graph = collector.graph()
    graph["graph"]["directed"] = body.directed
    return graph, collector.lineage, sample, rows


def run_query(runtime, source_id, body):
    source = get_source(runtime.settings, source_id)
    limit = min(
        runtime.settings.analytics_max_input_bytes,
        runtime.settings.account_upload_bytes,
    )
    graph, lineage, sample, rows = execute_query(source, body, limit)
    if source != get_source(runtime.settings, source_id):
        raise AnalyticsError(
            "Source settings changed. Run the query again.", "source_changed", 409
        )
    metadata = None
    if graph["vertices"]:
        metadata = DatasetLibrary(runtime).store(
            graph,
            name=body.name or source.name,
            kind="graph",
            complete=True,
            source={
                "type": "database_query",
                "database_source": {
                    "id": source.id,
                    "name": source.name,
                    "mapping_hash": source.fingerprint(),
                    "revision": source.revision,
                },
                "query": body.statement,
                "parameters": body.parameters,
                "fetched_at": utc_now().isoformat(),
                "lineage": lineage,
                "row_count": rows,
                "scope": "exact returned graph elements and relationship endpoints",
            },
        )
    shown = graph["vertices"][:100]
    keys = {_key(v["id"]) for v in shown}
    edges = [
        e
        for e in graph["edges"]
        if _key(e["source"]) in keys and _key(e["target"]) in keys
    ][:300]
    return {
        "dataset": metadata,
        "row_count": rows,
        "rows": sample,
        "rows_truncated": rows > len(sample),
        "graph": {**graph, "vertices": shown, "edges": edges},
        "vertex_count": len(graph["vertices"]),
        "edge_count": len(graph["edges"]),
        "message": "Graph saved. Open it in chat."
        if metadata
        else "This query returned no graph elements. Return nodes, relationships or paths to analyze a graph.",
    }


def open_chat(runtime, version_id, body):
    library = DatasetLibrary(runtime)
    metadata = library.get(version_id)
    source_id = metadata.get("source", {}).get("database_source", {}).get("id")
    if not source_id:
        raise RecordNotFound("Database query snapshot not found")
    get_source(runtime.settings, source_id)
    session = runtime.database.create_session(
        SessionRecord(domain_id="general", title=body.title or metadata["name"])
    )
    try:
        imported = library.import_into(version_id, session.id)
    except Exception:
        from .api import remove_session

        remove_session(runtime, session.id)
        raise
    return {"session": session.model_dump(mode="json"), **imported}


def register_database_query_routes(router):
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
