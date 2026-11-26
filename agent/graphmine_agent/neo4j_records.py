"""Neo4j provenance classification and administrator-only record counts."""

import json
from pathlib import Path
import sqlite3

BACKENDS = {"local", "iu-remote"}


def backend_id(document):
    if not isinstance(document, (dict, list)):
        return None
    if isinstance(document, list):
        values = {backend_id(value) for value in document} - {None}
    else:
        tag = document.get("backend_id")
        if isinstance(tag, str) and tag in BACKENDS:
            return tag
        # These are metadata/provenance containers, never uploaded graph rows.
        values = {backend_id(document.get(key)) for key in (
            "source", "parent", "provenance", "database_source", "file_snapshot", "input_provenance", "inputs")}
        if "input_provenance" in document and isinstance(document["input_provenance"], dict):
            values.update(backend_id(value) for value in document["input_provenance"].values())
        if document.get("database_source") is not None:
            values.add("local") if not (values - {None}) else None
        values.discard(None)
        if not values and (document.get("type") in {"neo4j", "database_query", "database_sync"}
                           or document.get("connector_type") == "neo4j"
                           or document.get("kind") in {"database_query", "database_sync"}):
            return "local"
    # A shared workspace never combines local and remote inputs. Historical
    # untagged Neo4j provenance belongs to local; uploads return None.
    return next(iter(values)) if len(values) == 1 else None


def derived_backend(document, files):
    """Workflow/job provenance may retain file identifiers rather than sources."""
    direct = backend_id(document)
    if direct:
        return direct
    def referenced(value):
        if isinstance(value, dict):
            found = {files.get(value.get("file_id"))}
            for key, item in value.items():
                if key != "file_id":
                    found.update(referenced(item))
            return found - {None}
        if isinstance(value, list):
            return {tag for item in value for tag in referenced(item)}
        return set()
    values = referenced(document)
    return next(iter(values)) if len(values) == 1 else None


def counts(runtime):
    from .database_sources import configured
    from .neo4j_backend import source_backend_id
    from .neo4j_registry import sources

    kinds = ("connections", "curated_datasets", "snapshots", "saved_queries", "files", "workflows", "results")
    result = {name: dict.fromkeys(kinds, 0) for name in sorted(BACKENDS)}
    def add(kind, document, *, default=None):
        tag = backend_id(document) or default
        if tag:
            result[tag][kind] += 1
    for source in configured(runtime.settings):
        add("connections", {}, default=source_backend_id(source))
    for source in sources(runtime.settings):
        tag = source_backend_id(source)
        add("connections", {}, default=tag)
        add("curated_datasets", {}, default=tag)
    for path in (Path(runtime.settings.data_root) / "database-connections").glob("*/*.json"):
        value = json.loads(path.read_text())
        add("connections", value.get("source", {}), default="local")
    with runtime.database._connect() as db:
        files = {row[0]: backend_id(json.loads(row[1])) for row in db.execute("SELECT id,payload FROM files")}
        for table, column, kind in (("dataset_versions", "metadata", "snapshots"),
                                    ("query_previews", "metadata", "snapshots"),
                                    ("files", "payload", "files"), ("results", "payload", "results"),
                                    ("user_connectors", "document", "connections")):
            for row in db.execute(f"SELECT {column} FROM {table}"):
                add(kind, json.loads(row[0]))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_library'").fetchone():
            columns = {row[1] for row in db.execute("PRAGMA table_info(query_library)")}
            if "backend_id" in columns:
                for row in db.execute("SELECT backend_id,count(*) FROM query_library GROUP BY backend_id"):
                    result[row[0] or "local"]["saved_queries"] += row[1]
            else:
                result["local"]["saved_queries"] = db.execute("SELECT count(*) FROM query_library").fetchone()[0]
    with sqlite3.connect(runtime.analytics.path) as db:
        for row in db.execute("SELECT document FROM workflows"):
            value = json.loads(row[0])
            tag = derived_backend(value, files)
            add("workflows", value, default=tag)
            if value.get("status") == "completed":
                add("results", value, default=tag)
    return result
