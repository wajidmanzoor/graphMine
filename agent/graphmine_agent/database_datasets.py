"""Discover the Neo4j graph independently of optional SQL catalog access."""

import re

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .analytics import AnalyticsError
from .benchmark_datasets import DATASETS, describe
from .database import RecordNotFound
from .database_sources import IDENTIFIER, get_source, sql_connection


def default_dataset(source):
    return {
        "id": "default",
        "name": ("Transfers demo" if source.id == "local-transfers" else "Mapped graph") if source.entities else "Neo4j graph",
        "status": "ready", "graph_label": None, "schemas": [],
        "tables": [
            {"name": m.table, "kind": "relationships" if hasattr(m, "source_entity") else "nodes",
             "labels": [m.label], "columns": [{"name": c, "type": ""} for c in m.attributes]}
            for m in source.entities + source.relationships
        ],
        "default_query": ("MATCH p = (a:" + source.entities[0].label + ")-[r"
                          + (":" + source.relationships[0].label if source.relationships else "")
                          + "]->(b)\nRETURN p\nLIMIT 1000") if source.entities
                         else "MATCH p = (a)-[r]->(b)\nRETURN p\nLIMIT 1000",
    }


def _sql_datasets(settings, source):
    result = [default_dataset(source)]
    if source.sql_type == "postgres":
        with sql_connection(source) as db:
            present = db.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='graphmine_catalog' AND table_name='datasets'
                  AND has_table_privilege(quote_ident(table_schema)||'.'||quote_ident(table_name), 'SELECT')
            """).fetchone()
            if present:
                rows = db.execute(
                    "SELECT id,name,schema_name,graph_label,status,manifest FROM graphmine_catalog.datasets ORDER BY (id='default') DESC,name"
                ).fetchall()
                for row in rows:
                    if any(item["id"] == row["id"] for item in result):
                        continue
                    manifest = row["manifest"]
                    entry = {
                        "id": row["id"], "name": row["name"], "status": row["status"],
                        "graph_label": row["graph_label"], "schema_name": row["schema_name"],
                        "schemas": [], "default_query": manifest.get("default_query", ""),
                        "node_count": manifest.get("node_count"),
                        "relationship_count": manifest.get("relationship_count"),
                        "row_count": manifest.get("row_count"),
                        "source_notes": [
                            {k: note[k] for k in ("filename", "note", "incomplete_tail_bytes") if k in note}
                            for note in manifest.get("source_notes", [])
                        ],
                        "tables": [{k: t[k] for k in ("name", "rows", "kind", "labels", "relationship_type", "columns", "key") if k in t}
                                   for t in manifest.get("tables", [])],
                    }
                    if entry["id"] in DATASETS and settings.benchmark_datasets_root:
                        try:
                            published = describe(settings, entry["id"])
                            entry.update(schemas=published["schemas"], source_url=published["source_url"])
                        except RecordNotFound:
                            pass
                    result.append(entry)
            # Show ordinary relational schemas as well, including remote databases.
            known = {r.get("schema_name") for r in result}
            if source.entities:
                known.update(m.schema_name for m in source.entities + source.relationships)
            rows = db.execute("""
                SELECT table_schema,table_name FROM information_schema.tables
                WHERE table_type='BASE TABLE' AND table_schema NOT IN
                    ('pg_catalog','information_schema','graphmine_catalog')
                ORDER BY table_schema,table_name
            """).fetchall()
            schemas = {}
            for row in rows:
                if row["table_schema"] not in known:
                    schemas.setdefault(row["table_schema"], []).append({"name": row["table_name"], "kind": "table"})
            for schema, tables in schemas.items():
                if not re.fullmatch(IDENTIFIER, schema):
                    continue
                result.append({
                    "id": "schema-" + schema, "name": schema, "schema_name": schema,
                    "status": "mapping_needed", "graph_label": None, "tables": tables,
                    "schemas": [], "default_query": "",
                })
    return result


def datasets(settings, source):
    if source.sql_type != "postgres":
        return [default_dataset(source)]
    try:
        return _sql_datasets(settings, source)
    except Exception as error:
        if isinstance(error, AnalyticsError) and error.code == "source_changed":
            raise
        # SQL availability must not remove the independent Neo4j graph.
        return [{**default_dataset(source), "discovery_warning":
                 "SQL dataset discovery is unavailable. You can still query the Neo4j graph; check the SQL connection to browse its catalog."}]

def selected_dataset(settings, source, identifier):
    if identifier == "default":
        return default_dataset(source)
    entries = datasets(settings, source)
    for item in entries:
        if item["id"] == identifier:
            if item["status"] != "ready":
                raise AnalyticsError("This dataset is not ready for graph queries yet.", "dataset_not_ready", 409)
            if item["graph_label"] and not re.fullmatch(IDENTIFIER, item["graph_label"]):
                raise AnalyticsError("The dataset graph label is invalid.", "database_configuration", 503)
            return item
    if any(item.get("discovery_warning") for item in entries):
        raise AnalyticsError("SQL dataset discovery is unavailable. Check the SQL connection, then retry.", "dataset_discovery", 503)
    raise RecordNotFound("Dataset not found in this database connection")


def register_dataset_routes(router):
    @router.get("/database-sources/{source_id}/datasets")
    async def list_datasets(source_id: str, request: Request):
        runtime = request.app.state.runtime
        source = get_source(runtime.settings, source_id)
        if runtime.upload_slots.locked():
            raise AnalyticsError("Database reads are busy. Retry shortly.", "busy", 429)
        async with runtime.upload_slots:
            return await run_in_threadpool(datasets, runtime.settings, source)
