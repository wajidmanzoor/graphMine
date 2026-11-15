"""Reconcile a complete SQL snapshot with its managed Neo4j records atomically."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from datetime import UTC, datetime

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError, _json
from .config import Settings
from .database_job_context import begin_commit, checkpoint
from .database_sources import (
    configured,
    json_value,
    neo4j_session,
    read_rows,
    sql_connection,
    stable_id,
)


def properties(source, mapping, row, build, mapping_hash):
    keys = [row[k] for k in mapping.key]
    values = {
        name: json_value(row.get(name))
        for name in (
            mapping.graph_attributes
            if mapping.graph_attributes is not None
            else mapping.attributes
        )
    }
    # Neo4j properties do not accept nested maps; preserve their JSON text.
    values = {
        k: _json(v) if isinstance(v, (dict, list)) else v for k, v in values.items()
    }
    values.update(
        gm_source=source.id,
        gm_mapping=mapping.id,
        gm_key=_json(json_value(keys)),
        gm_id=stable_id(source, mapping, keys),
        gm_build=build,
        gm_mapping_hash=mapping_hash,
    )
    if mapping.display:
        values["gm_display"] = str(row.get(mapping.display, ""))
    values["gm_label"] = mapping.label
    values["gm_fields"] = sorted([*values, "gm_fields"])
    return values


def mapped_records(source, db, build, *, relationship=None, selected=None):
    mapping_hash = source.fingerprint()
    entities = {m.id: m for m in source.entities}
    node_rows, edge_rows = {}, {}
    if relationship is None:
        used, count = 0, 0
        for mappings, output in (
            (source.entities, node_rows),
            (source.relationships, edge_rows),
        ):
            for m in mappings:
                checkpoint("reading_tables", count)
                rows = read_rows(db, source, m, fields=m.graph_attributes, validate_schema=True)
                count += len(rows)
                used += len(_json(json_value(rows)).encode())
                if count > source.max_rows or used > source.max_bytes:
                    raise AnalyticsError(
                        "Mapped graph exceeds the source read budget.", "resource_limit"
                    )
                output[m.id] = rows
                checkpoint("reading_tables", count)
    else:
        m = relationship
        groups = []
        for alias, columns in (
            (m.source_entity, m.source_columns),
            (m.target_entity, m.target_columns),
        ):
            keys = [r["keys"] for r in selected if r["mapping"] == alias]
            if keys:
                groups.append((columns, keys))
        found = {}
        used = 0
        for columns, keys in groups:
            for offset in range(0, len(keys), 100):
                for row in read_rows(
                    db,
                    source,
                    m,
                    where_keys=[(columns, keys[offset : offset + 100])],
                    fields=m.graph_attributes,
                ):
                    key = _json(json_value([row[c] for c in m.key]))
                    if key not in found:
                        found[key] = row
                        used += len(_json(json_value(row)).encode())
                    if len(found) > source.max_rows or used > source.max_bytes:
                        raise AnalyticsError(
                            "Relationship expansion exceeds the source read budget.",
                            "resource_limit",
                        )
        edge_rows[m.id] = list(found.values())
        for alias, columns in (
            (m.source_entity, m.source_columns),
            (m.target_entity, m.target_columns),
        ):
            keys = list(
                {
                    _json(json_value([r[c] for c in columns])): [r[c] for c in columns]
                    for r in edge_rows[m.id]
                }.values()
            )
            existing = {
                _json(json_value([r[c] for c in entities[alias].key])): r
                for r in node_rows.get(alias, [])
            }
            # Bound bind variables and SQL expression depth for selections.
            for offset in range(0, len(keys), 100):
                for row in read_rows(
                    db,
                    source,
                    entities[alias],
                    keys=keys[offset : offset + 100],
                    fields=entities[alias].graph_attributes,
                ):
                    existing[
                        _json(json_value([row[c] for c in entities[alias].key]))
                    ] = row
            node_rows[alias] = list(existing.values())
    nodes, edges, node_ids = [], [], set()
    for alias, rows in node_rows.items():
        mapping = entities[alias]
        for row in rows:
            props = properties(source, mapping, row, build, mapping_hash)
            if props["gm_id"] in node_ids:
                raise AnalyticsError("Entity keys are not unique.", "database_mapping")
            node_ids.add(props["gm_id"])
            nodes.append(
                {"mapping": alias, "label": mapping.label, "properties": props}
            )
    seen_edges = set()
    for alias, rows in edge_rows.items():
        mapping = source.mapping(alias)
        for row in rows:
            props = properties(source, mapping, row, build, mapping_hash)
            if props["gm_id"] in seen_edges:
                raise AnalyticsError(
                    "Relationship keys are not unique.", "database_mapping"
                )
            seen_edges.add(props["gm_id"])
            start = stable_id(
                source,
                entities[mapping.source_entity],
                [row[k] for k in mapping.source_columns],
            )
            end = stable_id(
                source,
                entities[mapping.target_entity],
                [row[k] for k in mapping.target_columns],
            )
            if start not in node_ids or end not in node_ids:
                raise AnalyticsError(
                    "A relationship references a missing entity.", "database_mapping"
                )
            if mapping.weight and row.get(mapping.weight) is not None:
                value = float(row[mapping.weight])
                if not math.isfinite(value):
                    raise AnalyticsError("Weights must be finite.", "database_mapping")
                props["gm_weight"] = value
            if mapping.timestamp and row.get(mapping.timestamp) is not None:
                props["gm_timestamp"] = json_value(row[mapping.timestamp])
            edges.append(
                {
                    "mapping": alias,
                    "type": mapping.label,
                    "source": start,
                    "target": end,
                    "properties": props,
                }
            )
    if (
        len(nodes) + len(edges) > source.max_rows
        or len(_json({"nodes": nodes, "edges": edges}).encode()) > source.max_bytes
    ):
        raise AnalyticsError(
            "Mapped graph exceeds the source row budget.", "resource_limit"
        )
    return nodes, edges


def reconcile_records(source, nodes, edges, byte_limit):
    from .database_reconciliation import apply_changes, change_summary, plan_changes, prepare_constraints, read_state

    with neo4j_session(source, write=True) as session:
        prepare_constraints(session, source)
        with session.begin_transaction(timeout=source.timeout_seconds) as tx:
            checkpoint("comparing", 0)
            old_nodes, old_edges = read_state(tx, source, byte_limit)
            changes = plan_changes(source, nodes, edges, old_nodes, old_edges)
            summary = change_summary(source, changes, old_nodes, old_edges)
            apply_changes(tx, source, changes)
            begin_commit()
            tx.commit()
            return summary


def sync_source(source, byte_limit=64 * 1024 * 1024):
    if source.sql_type is None:
        raise AnalyticsError("This connection has no SQL source to synchronize.", "sql_unavailable", 409)
    if not source.entities:
        raise AnalyticsError("Add entity table mappings before synchronizing this connection.", "database_mapping", 409)
    checkpoint("reading_tables", 0)
    build = datetime.now(UTC).isoformat()
    try:
        with sql_connection(source) as db:
            nodes, edges = mapped_records(source, db, build)
    except Exception as error:
        if (isinstance(error, sqlite3.OperationalError) and str(error).startswith(("no such table:", "no such column:"))) or getattr(error, "sqlstate", None) in {"42703", "42P01"}:
            raise AnalyticsError("A mapped SQL table or column is missing. Update the mapping before retrying; the graph was not changed.", "database_schema", 409) from error
        raise
    byte_limit = min(byte_limit, source.max_bytes)
    if len(_json({"nodes": nodes, "edges": edges}).encode()) > byte_limit:
        raise AnalyticsError("Import exceeds the byte budget.", "resource_limit")
    checksum = hashlib.sha256()
    for kind, rows in (("node", nodes), ("relationship", edges)):
        for row in sorted(rows, key=lambda item: item["properties"]["gm_id"]):
            checksum.update(_json({"kind": kind, **row, "properties": {key: value for key, value in row["properties"].items() if key != "gm_build"}}).encode() + b"\n")
    summary = reconcile_records(source, nodes, edges, byte_limit)
    return {
        "source_id": source.id,
        "build": build,
        "nodes": len(nodes),
        "relationships": len(edges),
        "mapping_hash": source.fingerprint(),
        "revision": source.revision,
        "sync_mode": "incremental",
        "source_read_mode": "complete_snapshot",
        "mapped_content_sha256": checksum.hexdigest(),
        "finished_at": datetime.now(UTC).isoformat(),
        **summary,
    }


def register_database_sync_routes(router):
    @router.post("/database-sources/{source_id}/sync")
    async def sync(source_id: str, request: Request):
        runtime = request.app.state.runtime
        from .database_jobs import accepted, private_response

        job = await run_in_threadpool(runtime.database_jobs.enqueue, "sync", source_id, request_key=request.headers.get("Idempotency-Key"))
        if "respond-async" in request.headers.get("Prefer", "").lower():
            return accepted(job)
        return private_response(await runtime.database_jobs.wait(job["id"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_id")
    args = parser.parse_args()
    source = next(
        (s for s in configured(Settings.from_env()) if s.id == args.source_id), None
    )
    if source is None:
        parser.error("Unknown database source")
    print(json.dumps(sync_source(source)))


if __name__ == "__main__":
    main()
